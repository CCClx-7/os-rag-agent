# -*- coding: utf-8 -*-
"""
build_kb.py —— 成员 A（知识库构建）
=================================================
《计算机操作系统（第4版）》知识库构建脚本。

说明：本教材 PDF 为“图片型”（由 ABBYY FineReader 生成，仅含页面图像、无文本层），
无法用常规 PDF 文本提取得到文字，因此采用 OCR（Tesseract 5.4 + chi_sim 中文包）
逐页识别，再构建检索库。OCR 结果缓存到 docs/pages_ocr.jsonl，重复运行直接复用，
避免重复耗时识别。

功能（对照作业 Phase 1 要求）：
  1. PDF 提取：PyMuPDF 渲染页面 + Tesseract OCR，按页提取全文，保留每页页码元数据。
  2. 章节检测：利用 PDF 书签/目录（TOC）识别章节边界（>=3 章）。
  3. 语义分块：按章节滑动窗口分块，目标 800~1200 token（中文约 1300~1900 字），
     块间重叠（overlap），每块记录 text / page_start / page_end / chapter。
  4. 检索建库：构建 SQLite FTS5（trigram 分词器，适合中文）全文检索库。
  5. 验证：输出块数统计、章节覆盖率、检索测试样例。

用法：
  python build_kb.py            # 首次 OCR 全本并建库（较慢）
  python build_kb.py --use-cache# 直接复用 docs/pages_ocr.jsonl 重建库（快）
依赖：pymupdf（pip install pymupdf）；Tesseract 5.4 + chi_sim（见 README 安装说明）。
产物：../knowledge_base.db 与 ../docs/pages_ocr.jsonl
"""
import os
import re
import sqlite3
import json
import subprocess
import sys

import pymupdf

# ----------------------------------------------------------------------------
# 路径配置
# ----------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PDF_PATH = r"F:/华农珠/大四上/专业素质/计算机操作系统（第4版）.pdf"
DB_PATH = os.path.join(ROOT, "knowledge_base.db")
OCR_CACHE = os.path.join(ROOT, "docs", "pages_ocr.jsonl")
# Tesseract 便携版（随项目附带，免安装）：tools/tesseract_raw/tesseract.exe
TESS_EXE = os.path.join(ROOT, "tools", "tesseract_raw", "tesseract.exe")

# ----------------------------------------------------------------------------
# 分块参数
# ----------------------------------------------------------------------------
TARGET_CHARS = 1600     # 目标块大小（中文约 1000~1100 token）
OVERLAP_CHARS = 220      # 块间重叠，保证上下文连续
MIN_CHARS = 400         # 过短块直接并入前文，避免噪声

CHAPTER_RE = re.compile(r"^第[一二三四五六七八九十百零\d]+章")


def clean_ocr_text(text):
    """清理 chi_sim OCR 在汉字之间插入的空格（保留拉丁词周围的空格）。"""
    # 去掉两个汉字之间的空白
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    # 压缩多余空行
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


OCR_DPI = 260  # 识别分辨率：260 在清晰度与速度间取得平衡


def ocr_page_bytes(png_bytes, tess_exe):
    """把 PNG 字节管道送入 tesseract，返回识别文本。"""
    proc = subprocess.run(
        [tess_exe, "stdin", "stdout", "-l", "chi_sim", "--psm", "3"],
        input=png_bytes, capture_output=True, timeout=120,
    )
    return proc.stdout.decode("utf-8", errors="ignore")


# ---- 多进程并行 OCR 所需的工作进程状态 ----
_MP_DOC = None
_MP_TESS = None


def _mp_init(pdf_path, tess_exe):
    global _MP_DOC, _MP_TESS
    import pymupdf
    _MP_DOC = pymupdf.open(pdf_path)
    _MP_TESS = tess_exe


def _mp_worker(page_index):
    global _MP_DOC, _MP_TESS
    pix = _MP_DOC[page_index].get_pixmap(dpi=OCR_DPI)
    try:
        raw = ocr_page_bytes(pix.tobytes("png"), _MP_TESS)
    except Exception as e:
        raw = ""
    return page_index + 1, clean_ocr_text(raw)


def extract_pages(doc, force=False):
    """逐页 OCR 提取（多进程并行）；结果缓存到 OCR_CACHE。
    返回 [(page_no(1-based), text), ...]"""
    if (not force) and os.path.exists(OCR_CACHE):
        print(f"    [复用缓存] 读取 {OCR_CACHE}")
        rows = []
        with open(OCR_CACHE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                rows.append((obj["page"], obj["text"]))
        if len(rows) == doc.page_count:
            return rows
        print(f"    [缓存页数不符 {len(rows)}!={doc.page_count}]，重新 OCR")
    if not os.path.exists(TESS_EXE):
        sys.exit(f"[错误] 未找到 Tesseract：{TESS_EXE}\n请先按 README 安装 Tesseract 5.4 + chi_sim。")
    import concurrent.futures as cf
    nproc = max(1, min(8, (os.cpu_count() or 4)))
    print(f"    [OCR] 并行识别 {doc.page_count} 页（{nproc} 进程，dpi={OCR_DPI}）...")
    rows = [None] * doc.page_count
    done = 0
    with cf.ProcessPoolExecutor(max_workers=nproc,
                                 initializer=_mp_init,
                                 initargs=(PDF_PATH, TESS_EXE)) as ex:
        futs = {ex.submit(_mp_worker, i): i for i in range(doc.page_count)}
        with open(OCR_CACHE, "w", encoding="utf-8") as out:
            for fut in cf.as_completed(futs):
                page, text = fut.result()
                rows[page - 1] = (page, text)
                out.write(json.dumps({"page": page, "text": text}, ensure_ascii=False) + "\n")
                out.flush()
                done += 1
                if done % 40 == 0:
                    print(f"       已 OCR {done}/{doc.page_count} 页")
    print(f"    [OCR] 完成，缓存写入 {OCR_CACHE}")
    return rows


def build_chapters(doc, page_count):
    """基于 TOC 构建章节区间列表 [(chapter_title, start_page, end_page), ...]"""
    toc = doc.get_toc()
    bounds = []
    for lvl, title, page in toc:
        if lvl == 1 and CHAPTER_RE.search(title.strip()):
            bounds.append((title.strip(), page))  # page 为 1-based
    bounds.sort(key=lambda x: x[1])
    if not bounds:
        for pno, txt in extract_pages(doc):
            m = re.search(r"第[一二三四五六七八九十百零\d]+章[^\n]{0,30}", txt[:200])
            if m:
                bounds.append((m.group(0), pno))
        bounds.sort(key=lambda x: x[1])
    chapters = []
    for idx, (title, start) in enumerate(bounds):
        end = bounds[idx + 1][1] - 1 if idx + 1 < len(bounds) else page_count
        chapters.append((title, start, end))
    return chapters


def chunk_chapter(chapter_title, pages):
    chunks = []
    buf_text = ""
    buf_start = pages[0][0]
    buf_end = pages[0][0]
    for pno, txt in pages:
        buf_text += txt + "\n"
        buf_end = pno
        while len(buf_text) >= TARGET_CHARS:
            chunk = buf_text[:TARGET_CHARS]
            chunks.append({"text": chunk.strip(), "chapter": chapter_title,
                           "page_start": buf_start, "page_end": buf_end})
            buf_text = buf_text[TARGET_CHARS - OVERLAP_CHARS:]
            buf_start = buf_end
    if buf_text.strip() and len(buf_text.strip()) >= MIN_CHARS:
        chunks.append({"text": buf_text.strip(), "chapter": chapter_title,
                       "page_start": buf_start, "page_end": buf_end})
    return chunks


def build_db(chunks, chapters):
    # 注：沙箱环境拦截 os.remove，故用「存在则 DROP 表」方式覆盖重建，避免删除操作。
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS chunks")
    cur.execute("DROP TABLE IF EXISTS chapters")
    cur.execute("DROP TABLE IF EXISTS meta")
    cur.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    cur.execute("""CREATE TABLE chapters (id INTEGER PRIMARY KEY, title TEXT,
                   start_page INTEGER, end_page INTEGER)""")
    cur.execute("""CREATE VIRTUAL TABLE chunks USING fts5(
                   text, chapter, page_start UNINDEXED, page_end UNINDEXED,
                   tokenize='trigram')""")
    for cid, (title, s, e) in enumerate(chapters, 1):
        cur.execute("INSERT INTO chapters(title,start_page,end_page) VALUES(?,?,?)", (title, s, e))
    for c in chunks:
        cur.execute("INSERT INTO chunks(text,chapter,page_start,page_end) VALUES(?,?,?,?)",
                    (c["text"], c["chapter"], c["page_start"], c["page_end"]))
    cur.execute("INSERT INTO meta(key,value) VALUES('chunk_count',?)", (str(len(chunks)),))
    cur.execute("INSERT INTO meta(key,value) VALUES('chapter_count',?)", (str(len(chapters)),))
    cur.execute("INSERT INTO meta(key,value) VALUES('source_pdf',?)", (os.path.basename(PDF_PATH),))
    conn.commit()
    conn.close()


def verify(conn, chapters):
    cur = conn.cursor()
    chunk_count = cur.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    covered = cur.execute("SELECT COUNT(DISTINCT chapter) FROM chunks").fetchone()[0]
    print(f"  [验证] 文本块总数：{chunk_count}")
    print(f"  [验证] 章节覆盖：{covered}/{len(chapters)} 章有内容块")
    from retrieval import knowledge_search
    tests = ["死锁", "页面置换算法", "进程同步", "虚拟存储器", "磁盘调度",
             "操作系统接口", "什么是死锁？如何预防死锁？"]
    print("  [验证] 检索抽样（knowledge_search，trigram+BM25+词频兜底）：")
    for q in tests:
        rows = knowledge_search(q, top_k=2)
        hits = [f"{r['citation']}{r['chapter'][:6]}" for r in rows]
        print(f"    · {q!r} -> {hits if hits else '无命中'}")


def main():
    force = "--force" in sys.argv
    use_cache = "--use-cache" in sys.argv
    print("== 成员A：知识库构建 ==")
    print(f"[1] 打开教材：{os.path.basename(PDF_PATH)}")
    doc = pymupdf.open(PDF_PATH)
    page_count = doc.page_count
    print(f"    页数：{page_count}")

    print("[3] 基于目录检测章节边界...")
    chapters = build_chapters(doc, page_count)
    print(f"    检测到章节数：{len(chapters)}")
    for t, s, e in chapters:
        print(f"      - {t}  (p{s}~p{e})")

    print("[2] 逐页 OCR 提取文本（保留页码元数据）...")
    if use_cache and os.path.exists(OCR_CACHE):
        pages = extract_pages(doc, force=False)
    else:
        pages = extract_pages(doc, force=force)
    nonempty = sum(1 for _, t in pages if t.strip())
    print(f"    非空页：{nonempty}/{page_count}")

    print("[4] 按章节语义分块（滑动窗口 + 重叠）...")
    page_map = {pno: txt for pno, txt in pages}
    all_chunks = []
    for title, s, e in chapters:
        chap_pages = [(pno, page_map[pno]) for pno in range(s, e + 1) if pno in page_map]
        if not chap_pages:
            continue
        all_chunks.extend(chunk_chapter(title, chap_pages))
    print(f"    生成文本块：{len(all_chunks)}")

    print("[5] 构建 SQLite FTS5 检索库...")
    build_db(all_chunks, chapters)
    conn = sqlite3.connect(DB_PATH)
    verify(conn, chapters)
    conn.close()
    print(f"[完成] 知识库已写入：{DB_PATH}")
    with open(os.path.join(ROOT, "docs", "kb_stats.json"), "w", encoding="utf-8") as f:
        json.dump({"page_count": page_count, "chapter_count": len(chapters),
                   "chunk_count": len(all_chunks),
                   "chapters": [{"title": t, "start": s, "end": e} for t, s, e in chapters]},
                  f, ensure_ascii=False, indent=2)
    print("[完成] 统计已写入 docs/kb_stats.json")


if __name__ == "__main__":
    main()
