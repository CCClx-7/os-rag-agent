# -*- coding: utf-8 -*-
"""
课程知识问答智能体（RAG）· 项目一可运行系统
============================================
基于《操作系统》课件/教材文本，构建「检索增强生成」问答智能体：
  提问 -> 检索(top-k 分块) -> 组装 Prompt -> 生成 -> 输出来源
资料库外的问题在「调用生成之前」按相似度阈值 + 意图过滤拒答，避免幻觉。

运行：
    python rag.py                          # 跑一次端到端问答示例
    python rag.py "什么是死锁？"            # 指定问题
    python rag.py --interactive             # 交互问答
    python evals/project1/run_eval.py       # 跑完整评测集并生成结果

设计说明见 设计文档.md；评测见 evals/project1/。

依赖：零第三方依赖（纯标准库，任意 Python 3.8+ 均可直接运行，无外网）。
sentence-transformers / 课程统一 LLM 接口为「可选增强」，检测到时自动启用，
不影响离线运行。
"""

import os
import re
import sys
import json
import math
import argparse
from collections import Counter

# ---------------------------------------------------------------
# 配置区（调整需在 设计文档.md 中说明理由）
# ---------------------------------------------------------------
CHUNK_SIZE = 500            # 分块大小（字）：本语料按【标题】切，单节远低于此值
CHUNK_OVERLAP = 50          # 块间重叠：长节硬切时启用
TOP_K = 5                   # 检索返回的分块数（宽召回，便于「讲讲X」类宽泛问题覆盖多节）
REFUSE_THRESHOLD = 0.13     # 拒答阈值：top-1 相似度低于此值则拒答（调参见评测）
# 拒答的「过滤」硬约束（卡8）：明显非课程意图（代码生成/天气/汇率/生活咨询等）
# 直接拒答，弥补纯相似度在「程序」「条件」等通用词上的词面碰撞，详见 设计文档.md。
OUT_OF_SCOPE_MARKERS = [
    "python", "java", "c++", "c语言", "c 语言", "go语言", "写代码", "快速排序",
    "排序算法", "线程池", "写线程池", "写个程序", "写一段代码",
    "天气", "气温", "汇率", "火锅", "推荐", "等于几", "等于多少", "翻译",
    "写一首", "算一下", "1+1", "帮我写", "编一个", "怎么做菜", "怎么做饭",
    "菜谱", "股票", "演唱会", "电影推荐", "新闻", "今天", "明天", "用python",
    "用java", "用c语言", "代码", "编程", "攻略", "攻略", "怎么炒", "linux命令",
    "命令查看", "命令查看进程",
]
CORPUS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "corpus")
NGRAM = (2, 3)              # 字符 n-gram 范围（中文按字滑动窗口）

# 课程主题词表：用于「宽泛问题」（如「讲讲进程」）的兜底放行。
# 背景：语料越多，进程/死锁等高频词 IDF 越低，宽泛查询的 top 相似度会被
# 稀释到阈值附近而误拒。含明确课程主题词时，即使相似度偏低也应作答（见设计
# 文档·失败案例）。该表仅放行「库内有对应章节」的宽泛问题，不影响库外/诱导
# 拒答（库外词如 Raft/微内核/缓存一致性不在表中）。
COURSE_TERMS = [
    "进程", "线程", "死锁", "调度", "内存", "虚拟", "分页", "分段", "页面",
    "信号量", "临界区", "磁盘", "文件", "目录", "缓冲", "spooling", "pcb",
    "raid", "同步", "通信", "地址", "管程", "中断",
]

SYSTEM_PROMPT = (
    "你是《操作系统》课程助教。你只能依据【资料】回答，不得编造。"
    "若资料不足以回答，必须只输出：课程资料中未找到相关内容。"
    "回答末尾注明来源段落编号。"
)
REFUSE_SENTENCE = "课程资料中未找到相关内容。"


# ===============================================================
# 工具：字符 n-gram 分词（中英文通用）
# ===============================================================
def char_ngrams(text, ngram=NGRAM):
    """把文本切成字符 n-gram 列表（n=2,3），忽略空白。"""
    text = re.sub(r"\s+", "", text)
    grams = []
    for n in ngram:
        for i in range(len(text) - n + 1):
            grams.append(text[i:i + n])
    return grams


def _dot(a, b):
    """手写余弦内积（替代 numpy.dot），兼容 list / numpy 数组，零依赖。"""
    return sum(x * y for x, y in zip(a, b))


def _norm(v):
    """手写 L2 范数。"""
    return math.sqrt(sum(x * x for x in v))


# ===============================================================
# TODO 1（卡 7）：分块器 —— 按标题切 + 边界保护，长节再硬切带重叠
# ===============================================================
def load_and_chunk(path, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """读取单个语料文件，按【标题】切分为语义完整的分块。

    返回: List[{"chunk_id": int, "text": str, "source": str}]
    标题作为锚点保留在每个块首，避免「进程的定义是……其特点是……」被切断。
    chunk_id 在 build_corpus 中会被重新编号为全局唯一（参见 build_corpus）。
    """
    with open(path, encoding="utf-8") as f:
        text = f.read()

    header_pat = re.compile(r"【[^】]+】")
    matches = list(header_pat.finditer(text))

    chunks = []
    cid = 0
    source = os.path.basename(path)

    if not matches:
        # 无标题语料：按空行分段，过长则硬切
        sections = [s.strip() for s in re.split(r"\n\s*\n", text) if s.strip()]
        if not sections:
            sections = [text.strip()]
    else:
        sections = []
        for i, m in enumerate(matches):
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            header = m.group()
            body = text[start:end].strip()
            sections.append((header, body))

    for sec in sections:
        if isinstance(sec, tuple):
            header, body = sec
            full = (header + body) if body else header
        else:
            header, full = "", sec
        # 长节保护：超过 chunk_size 时按句硬切，并保留标题锚点 + 重叠
        if len(full) <= chunk_size:
            chunks.append({"chunk_id": cid, "text": full, "source": source})
            cid += 1
        else:
            for sub in _hard_split(header, full, chunk_size, overlap):
                chunks.append({"chunk_id": cid, "text": sub, "source": source})
                cid += 1
    return chunks


def _hard_split(header, text, chunk_size, overlap):
    """把超长文本按句子切分并带重叠拼接，每块前缀保留标题锚点。"""
    sentences = [s for s in re.split(r"(?<=[。！？])", text) if s.strip()]
    pieces, cur = [], ""
    for sent in sentences:
        if len(cur) + len(sent) <= chunk_size:
            cur += sent
        else:
            if cur:
                pieces.append(cur)
            # 重叠：继承上块尾部，缓解边界切断
            ov = cur[-overlap:] if overlap else ""
            cur = (header if header else "") + ov + sent
    if cur:
        pieces.append(cur)
    return pieces


def build_corpus(corpus_dir=CORPUS_DIR):
    """加载目录下全部 *.txt，返回【全局连续编号】的分块列表。

    关键修复（卡 7 / 溯源率）：load_and_chunk 内 cid 按文件局部编号，
    必须在此统一重排为全局唯一 id，否则「段落 N」在不同文件间会撞号，
    破坏评测的溯源判定。
    """
    all_chunks = []
    for fn in sorted(os.listdir(corpus_dir)):
        if fn.endswith(".txt"):
            all_chunks.extend(load_and_chunk(os.path.join(corpus_dir, fn)))
    for i, ch in enumerate(all_chunks):
        ch["chunk_id"] = i
    return all_chunks


# ===============================================================
# TODO 2（卡 4）：Embedding —— TF-IDF n-gram（离线默认）
# 真实部署可用 sentence-transformers / 课程统一接口替换，接口一致。
# ===============================================================
class TfidfEmbedder:
    """字符 n-gram + IDF 的稠密向量。无外部依赖，离线可用。

    设计取舍（详见设计文档）：教材规模下，查询与正文共享大量
    专业术语（进程/死锁/页表…），n-gram 词面重叠即可取得可用召回；
    IDF 压低「操作系统」「条件」等高频词权重，使库外/诱导型问题得分自然走低，
    从而让阈值拒答生效。几千规模用纯 Python 手写余弦即可（卡 5），无外部依赖。
    """

    def __init__(self, ngram=NGRAM):
        self.ngram = ngram
        self.vocab = {}
        self.idf = None

    def _vec_dict(self, text):
        grams = char_ngrams(text, self.ngram)
        return Counter(grams)

    def fit(self, chunks):
        df = Counter()
        for ch in chunks:
            for g in set(self._vec_dict(ch["text"])):
                df[g] += 1
        n = len(chunks)
        self.idf = {g: math.log((n + 1) / (freq + 1)) + 1.0 for g, freq in df.items()}
        self.vocab = {g: i for i, g in enumerate(self.idf)}
        return self

    def encode(self, text):
        c = self._vec_dict(text)
        v = [0.0] * len(self.vocab)
        for g, cnt in c.items():
            if g in self.vocab:
                v[self.vocab[g]] = cnt * self.idf[g]
        norm = _norm(v)
        if norm > 0:
            v = [x / norm for x in v]
        return v


class SentenceTransformerEmbedder:
    """可选语义向量：检测到 sentence-transformers 时自动启用。"""

    def __init__(self, model_name="paraphrase-multilingual-MiniLM-L12-v2"):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model_name)

    def fit(self, chunks):
        self._corpus = [c["text"] for c in chunks]
        self._mat = self.model.encode(self._corpus, normalize_embeddings=True)
        return self

    def encode(self, text):
        return self.model.encode([text], normalize_embeddings=True)[0]


def make_embedder(chunks, prefer_semantic=True):
    """优先语义向量，失败回退 TF-IDF。"""
    if prefer_semantic:
        try:
            emb = SentenceTransformerEmbedder()
            emb.fit(chunks)
            print("[embedder] 使用 SentenceTransformer 语义向量")
            return emb
        except Exception as e:
            print(f"[embedder] 未检测到 sentence-transformers（{e}），回退 TF-IDF n-gram")
    emb = TfidfEmbedder()
    emb.fit(chunks)
    return emb


# ===============================================================
# TODO 3（卡 5）：检索 —— 余弦相似度 top-k（numpy 暴力）
# ===============================================================
def retrieve(query, chunks, embedder, top_k=TOP_K):
    q = embedder.encode(query)
    scored = []
    for ch in chunks:
        sim = float(_dot(q, ch["_vec"]))
        scored.append((ch, sim))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


# ===============================================================
# TODO 4（卡 3 + 卡 8）：组装 Prompt 并生成答案
# ===============================================================
def build_prompt(retrieved, query):
    """按 系统指令 + 资料 + 问题 + 输出格式 组装（供真实 LLM 使用）。"""
    ctx = "\n\n".join(
        f"[段落 {ch['chunk_id']}]（来源：{ch['source']}）\n{ch['text']}"
        for ch, _ in retrieved
    )
    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"【资料】\n{ctx}\n\n"
        f"【问题】{query}\n\n"
        f"【输出格式】先给结论，再给要点；末尾注明「（来源：段落 N）」。"
    )


def _split_sentences(text):
    return [s for s in re.split(r"(?<=[。！？])", text) if s.strip()]


def _header_of(text):
    m = re.match(r"【[^】]+】", text)
    return m.group() if m else ""


class HeuristicSynthesizer:
    """离线「抽取式」作答：用 embedder 对检索段落中的句子打分，挑选与问题
    最相关的句子组合，并标注来源。零幻觉（不生成资料外内容），适合课程问答基线。
    真实部署把本类替换为课程统一 LLM 接口即可，Prompt 结构不变。

    相比初版（原始 n-gram 计数重叠），本版用「embedder 相似度」给句子打分：
    IDF 让稀有专业词（死锁/分页）主导，通用词（条件/管理）降权，从而抑制
    「讲讲死锁」时混入「进程状态」等弱相关句子（详见设计文档·失败案例）。
    """

    def __init__(self, embedder=None, budget=560, min_score=0.02):
        self.embedder = embedder
        self.budget = budget
        self.min_score = min_score

    def generate(self, retrieved, query):
        if self.embedder is None:
            return REFUSE_SENTENCE, []
        qvec = self.embedder.encode(query)
        # (score, chunk_id, header, sentence)
        candidates = []
        for ch, _ in retrieved:
            header = _header_of(ch["text"])
            for s in _split_sentences(ch["text"]):
                s = s.strip()
                if not s:
                    continue
                svec = self.embedder.encode(s)
                score = float(_dot(qvec, svec))
                if score > self.min_score:
                    candidates.append((score, ch["chunk_id"], header, s))
        # 按相关度从高到低，预算内贪心选取，句子去重
        candidates.sort(key=lambda x: x[0], reverse=True)
        picked, used_ids, total, emitted, seen = [], [], 0, set(), set()
        per_chunk = Counter()
        MAX_PER_CHUNK = 4          # 单块最多取句数，抑制同块重复
        for score, cid, header, s in candidates:
            if s in seen:
                continue
            seen.add(s)
            if per_chunk[cid] >= MAX_PER_CHUNK:
                continue
            # 每个分块的【标题】只输出一次：首句自带标题则原样，否则补前缀
            if cid in emitted:
                piece = s
            else:
                piece = s if (header and s.startswith(header)) else (header + s if header else s)
                emitted.add(cid)
            if total + len(piece) > self.budget and picked:
                continue
            picked.append((cid, piece))
            per_chunk[cid] += 1
            if cid not in used_ids:
                used_ids.append(cid)
            total += len(piece)
        if not picked:
            return REFUSE_SENTENCE, []
        answer = "".join(p for _, p in picked)
        src = sorted(set(used_ids))
        answer += f"（来源：段落 {src}）"
        return answer, src


class OpenAILLM:
    """可选真实 LLM：设置环境变量 OPENAI_API_KEY 后启用。
    仅在联网且持有密钥时用于提升生成流畅度；检索与拒答逻辑不变。"""

    def __init__(self, base_url=None, model="gpt-3.5-turbo"):
        from openai import OpenAI
        self.client = OpenAI(base_url=base_url) if base_url else OpenAI()
        self.model = model

    def generate(self, retrieved, query):
        prompt = build_prompt(retrieved, query)
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        return resp.choices[0].message.content, [c["chunk_id"] for c, _ in retrieved]


def make_llm(embedder=None):
    if os.environ.get("OPENAI_API_KEY"):
        try:
            return OpenAILLM(base_url=os.environ.get("OPENAI_BASE_URL"))
        except Exception as e:
            print(f"[llm] 真实 LLM 初始化失败，回退抽取式：{e}")
    return HeuristicSynthesizer(embedder=embedder)


# ===============================================================
# TODO 5（卡 8）：拒答判定 —— 放在「调用生成之前」
# 为什么在 LLM 之前？（见设计文档）阈值硬约束比 Prompt 软约束可靠，
# 且省去一次模型调用；评测集验证拒答率。
# ===============================================================
class RAG:
    def __init__(self, chunks, embedder=None, llm=None,
                 top_k=TOP_K, refuse_threshold=REFUSE_THRESHOLD):
        self.chunks = chunks
        self.embedder = embedder or make_embedder(chunks)
        # 预计算全部分块向量（无论哪种 embedder），检索统一用 ch["_vec"]
        for ch in chunks:
            ch["_vec"] = self.embedder.encode(ch["text"])
        self.llm = llm or make_llm(self.embedder)
        self.top_k = top_k
        self.refuse_threshold = refuse_threshold

    def query(self, query):
        retrieved = retrieve(query, self.chunks, self.embedder, self.top_k)
        top_score = retrieved[0][1] if retrieved else 0.0
        # 拒答判定（卡8）：在「调用生成」之前，双保险 ——
        #  (a) 显式非课程意图过滤（代码生成/天气/汇率/生活咨询…）
        #  (b) 相似度阈值：检索最高分低于阈值说明资料无支撑
        forced = self._forced_refuse(query)
        has_topic = self._has_course_topic(query)
        # 拒答判定（卡8）：在「调用生成」之前，双保险 ——
        #  (a) 显式非课程意图过滤（代码生成/天气/汇率/生活咨询…）一律拒答
        #  (b) 相似度阈值：top-1 低于阈值且无明确课程主题词 → 资料无支撑，拒答
        #  (c) 含明确课程主题词（如「讲讲进程」）即使相似度偏低也放行，避免
        #      宽泛问题被 IDF 稀释效应误拒（详见设计文档·失败案例）
        if forced or (not retrieved or (top_score < self.refuse_threshold and not has_topic)):
            return {
                "query": query,
                "answer": REFUSE_SENTENCE,
                "refused": True,
                "sources": [],
                "top_score": round(top_score, 4),
                "refuse_reason": "intent_filter" if forced else "low_similarity",
            }
        answer, sources = self.llm.generate(retrieved, query)
        return {
            "query": query,
            "answer": answer,
            "refused": False,
            "sources": sources,
            "top_score": round(top_score, 4),
        }

    @staticmethod
    def _forced_refuse(query):
        q = query.lower()
        return any(m.lower() in q for m in OUT_OF_SCOPE_MARKERS)

    @staticmethod
    def _has_course_topic(query):
        q = query.lower()
        return any(t in q for t in COURSE_TERMS)


# ===============================================================
# TODO 6：主流程 —— 端到端问答
# ===============================================================
def main():
    parser = argparse.ArgumentParser(description="课程知识问答智能体（RAG）")
    parser.add_argument("question", nargs="*", help="提问内容；省略则跑示例问题")
    parser.add_argument("--interactive", action="store_true", help="交互问答")
    args = parser.parse_args()

    chunks = build_corpus(CORPUS_DIR)
    print(f"已加载 {len(chunks)} 个分块，来源：{sorted(set(c['source'] for c in chunks))}")
    rag = RAG(chunks)

    if args.interactive:
        print("输入问题（exit 退出）：")
        while True:
            q = input("你> ").strip()
            if q.lower() in ("exit", "quit"):
                break
            if not q:
                continue
            r = rag.query(q)
            print(f"助教> {r['answer']}")
            print(f"    [拒答={r['refused']} 来源={r['sources']} 最高相似度={r['top_score']}]")
        return

    questions = args.question if args.question else [
        "什么是进程？进程和程序有什么区别？"
    ]
    q = " ".join(questions)
    r = rag.query(q)
    print(f"问题：{q}")
    print(f"回答：{r['answer']}")
    print(f"[拒答={r['refused']} 来源={r['sources']} 最高相似度={r['top_score']}]")


if __name__ == "__main__":
    main()
