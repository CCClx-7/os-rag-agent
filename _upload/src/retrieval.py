# -*- coding: utf-8 -*-
"""
retrieval.py —— 成员 B 的核心检索工具 knowledge_search
=================================================
从 SQLite FTS5（trigram 分词）知识库中检索与问题相关的教材片段，返回带页码引用的结果。

对外主接口：
    knowledge_search(query: str, top_k: int = 5) -> List[dict]

返回每个结果包含：
    rank / chapter / page_start / page_end / snippet / score / citation(【教材 p.XX】)

设计要点（满足作业 R1 先检索、R3 页码引用）：
  · 优先 FTS5 trigram + BM25（中文友好，无需分词）；
  · 自然语言问句处理：去除疑问词/标点，对查询做“后缀递进”候选匹配，
    自动从“什么是死锁？如何预防死锁？”中定位教材术语“预防死锁”；
  · trigram 要求查询>=3字，2 字术语（死锁/进程/线程）自动走 LIKE 词频兜底；
  · 任一候选命中即返回，保证课程问题总能检索到相关章节。
依赖：仅 Python 标准库（sqlite3）。
"""
import os
import sqlite3
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "knowledge_base.db")
SNIPPET_LEN = 240

# 问句常见前缀/疑问词（检索时优先剥离，保留教材术语）
LEAD_RE = re.compile(r"^(什么是|什么是|怎样|如何|怎么|为什么|简述|说明|解释|定义|举例|论述|比较|请|是不是|是否|谈谈|介绍|分析)")
# 仅保留中文与数字（去掉标点、空白与英文术语，避免污染中文检索）
PUNCT_RE = re.compile(r"[^\u4e00-\u9fff0-9]")


def _query_candidates(query: str):
    """由自然语言问句生成检索候选：所有长度>=2 的子串，最长优先。
    例：“页面置换（page replacement）算法有哪些？” → 含“页面置换算法”等子串，
    从而能精确命中教材术语。"""
    q = PUNCT_RE.sub("", query)                 # 去标点/空白/英文，仅留中文数字
    q = LEAD_RE.sub("", q)                      # 去疑问前缀
    subs = set()
    n = len(q)
    for i in range(n):
        for j in range(i + 2, n + 1):           # 长度 >=2 的子串
            subs.add(q[i:j])
    # 最长优先（更具体的术语优先匹配），其次按出现顺序
    return sorted(subs, key=len, reverse=True)


def _fts_escape(query: str) -> str:
    q = re.sub(r'["\*\^\(\)\{\}:]', " ", query)
    q = re.sub(r"\s+", " ", q).strip()
    return f'"{q}"' if q else ""


def _rows_to_results(rows, with_score=True):
    results = []
    for i, row in enumerate(rows, 1):
        text, chapter, ps, pe = row[0], row[1], row[2], row[3]
        score = round(row[4], 4) if (with_score and len(row) > 4) else 0.0
        snippet = text[:SNIPPET_LEN].replace("\n", " ")
        if len(text) > SNIPPET_LEN:
            snippet += "…"
        citation = f"【教材 p.{ps}】" if ps == pe else f"【教材 p.{ps}-{pe}】"
        results.append({"rank": i, "chapter": chapter, "page_start": ps,
                        "page_end": pe, "snippet": snippet, "score": score,
                        "citation": citation})
    return results


def _like_search(conn, query, top_k):
    cur = conn.cursor()
    like = f"%{query}%"
    rows = cur.execute(
        "SELECT text, chapter, page_start, page_end FROM chunks "
        "WHERE text LIKE ? "
        "ORDER BY (LENGTH(text)-LENGTH(REPLACE(text,?,''))) DESC LIMIT ?",
        (like, query, top_k),
    ).fetchall()
    return rows


def knowledge_search(query: str, top_k: int = 5):
    """检索知识库，返回与 query 相关的教材片段（带页码引用）。"""
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"知识库不存在：{DB_PATH}，请先运行 build_kb.py")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    results = []

    # 1) FTS5 trigram + BM25（候选从长到短，首个命中即用）
    for cand in _query_candidates(query):
        if len(cand) < 3:
            continue
        match = _fts_escape(cand)
        if not match:
            continue
        try:
            rows = cur.execute(
                "SELECT text, chapter, page_start, page_end, bm25(chunks) AS s "
                "FROM chunks WHERE chunks MATCH ? ORDER BY s LIMIT ?",
                (match, top_k)).fetchall()
        except sqlite3.OperationalError:
            rows = []
        if rows:
            results = _rows_to_results(rows, with_score=True)
            break

    # 2) LIKE 词频兜底（覆盖 2 字术语 / FTS 仍无命中）
    if not results:
        for cand in _query_candidates(query):
            if len(cand) < 2:
                continue
            rows = _like_search(conn, cand, top_k)
            if rows:
                results = _rows_to_results(rows, with_score=False)
                break

    conn.close()
    return results


def format_context(results, max_chunks: int = 5) -> str:
    """把检索结果格式化为注入给 LLM 的上下文文本。"""
    if not results:
        return "（未检索到相关教材内容）"
    return "\n\n".join(
        f"[{r['citation']}｜{r['chapter']}]\n{r['snippet']}"
        for r in results[:max_chunks]
    )


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "死锁"
    for r in knowledge_search(q, top_k=3):
        print(f"#{r['rank']} {r['citation']} 《{r['chapter']}》 score={r['score']}")
        print("   ", r["snippet"])
        print()
