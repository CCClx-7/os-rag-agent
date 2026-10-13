# -*- coding: utf-8 -*-
"""
qa_system.py —— 成员 B（智能体配置）+ 拓展挑战（可视化界面 / 多轮对话）
==================================================================
一个“先检索、后回答”的 RAG 智能体，仅基于《计算机操作系统（第4版）》知识库作答。

关键设计（满足作业强制要求）：
  · R1 先检索：检索步骤在【代码层】强制完成——先 knowledge_search 再生成回答，
    不依赖模型是否“自觉”调用工具，从根本上保证检索先于回答。
  · R2 只用教材 / R3 页码引用 / R4 简单中文+术语 / R5 诚实标注 / R6 版权保护：
    由 prompts/system_prompt.txt 约束，并在无 Key 退化模式下由代码保证。

技术栈（方案 C）：纯 Python + SQLite FTS5 + 直连 OpenAI 兼容 LLM API（DeepSeek / OpenAI 等）。

拓展挑战 1 · 可视化界面：run_cli() 提供命令行交互式问答（带检索过程展示、颜色分隔）。
拓展挑战 2 · 多轮对话：维护对话历史，自动识别“它/该/上述”等指代并扩展检索查询。

运行：
  python qa_system.py            # 进入 CLI 交互
  python qa_system.py "什么是死锁"   # 单轮问答（用于测试/管道）
环境变量 / 配置（agent_config.json）：
  OS_QA_API_KEY   你的 LLM API Key（不设置则使用“检索合成”退化模式，仍可演示 RAG）
  OS_QA_BASE_URL  API base，默认 https://api.deepseek.com/v1
  OS_QA_MODEL     模型名，默认 deepseek-chat
"""
import os
import re
import sys
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROMPT_PATH = ROOT / "prompts" / "system_prompt.txt"
CFG_PATH = ROOT / "agent_config.json"

# 指代词：多轮对话中用于判断是否需要结合上文扩展查询
ANAPHORA = ["它", "它们", "该", "这个", "这些", "前者", "后者", "上述", "其", "本章", "本节"]


def load_prompt_template() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def load_config() -> dict:
    cfg = {
        "api_key": os.environ.get("OS_QA_API_KEY", ""),
        "base_url": os.environ.get("OS_QA_BASE_URL", "https://api.deepseek.com/v1"),
        "model": os.environ.get("OS_QA_MODEL", "deepseek-chat"),
    }
    if CFG_PATH.exists():
        try:
            cfg.update(json.loads(CFG_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    return cfg


class QAEngine:
    def __init__(self):
        self.prompt_template = load_prompt_template()
        self.cfg = load_config()
        self.history = []  # 多轮对话历史: [{"role","content","citations"}]

    # ---- 多轮对话：指代消解，扩展检索查询 ----
    def expand_query(self, question: str) -> str:
        has_anaphora = any(w in question for w in ANAPHORA)
        if has_anaphora and self.history:
            # 用上一轮用户问题为当前指代提供实体，提升检索命中
            last_user = next((h["content"] for h in reversed(self.history)
                              if h["role"] == "user"), "")
            if last_user:
                return f"{last_user} {question}"
        return question

    # ---- 检索（R1）----
    def retrieve(self, question: str, top_k: int = 5):
        from retrieval import knowledge_search, format_context
        expanded = self.expand_query(question)
        results = knowledge_search(expanded, top_k=top_k)
        context = format_context(results)
        return expanded, results, context

    # ---- 调用 LLM（OpenAI 兼容）----
    def call_llm(self, system_prompt: str, user_message: str) -> str:
        cfg = self.cfg
        if not cfg.get("api_key"):
            return ""  # 无 Key，交由退化模式处理
        url = cfg["base_url"].rstrip("/") + "/chat/completions"
        messages = [{"role": "system", "content": system_prompt}]
        # 注入多轮历史（保证 LLM 能理解指代）
        for h in self.history:
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": user_message})
        payload = {"model": cfg["model"], "messages": messages, "temperature": 0.2,
                   "stream": False}
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {cfg['api_key']}",
                     "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            return f"[LLM 调用失败：{e}]"

    # ---- 无 Key 退化模式：检索合成答案（仍满足 R3/R5/R6）----
    def _best_chunk(self, results, query: str):
        """在检索结果中挑选与问题最相关、OCR 噪声最少的块。
        query 应为“扩展后的查询”（含多轮先行词），以便正确打分。"""
        # 把查询中文拆成所有 >=2 字子串（按长度加权），让“进程同步”等术语真正参与打分
        subkw = set()
        for run in re.findall(r"[\u4e00-\u9fff]+", query):
            for i in range(len(run)):
                for j in range(i + 2, len(run) + 1):
                    subkw.add(run[i:j])
        compare = any(w in query for w in ["区别", "不同", "比较"])
        best, best_score = results[0], -1
        for r in results:
            s = r["snippet"]
            kw_score = sum(s.count(k) * len(k) for k in subkw)   # 长词权重更高
            if compare and ("区别" in s or "不同" in s):
                kw_score += 4
            cjk_ratio = len(re.findall(r"[\u4e00-\u9fff]", s)) / max(1, len(s))
            score = kw_score + cjk_ratio * 0.5
            if score > best_score:
                best_score, best = score, r
        return best

    def compose_answer(self, results, query: str) -> str:
        if not results:
            return ("未检索到相关教材内容。本助手仅基于《计算机操作系统（第4版）》"
                    "作答，该问题在已检索的教材片段中未覆盖，无法提供确定答案"
                    "（依据 R5 诚实标注，不编造）。")
        top = self._best_chunk(results, query)
        # 转述片段前若干句，丢弃低中文比的 OCR 噪声句，避免连续超过 3 句原文（R6）
        sentences = [s for s in re.split(r"(?<=[。！？])", top["snippet"]) if s.strip()]
        kept = []
        for s in sentences:
            if len(kept) >= 3:
                break
            cjk_ratio = len(re.findall(r"[\u4e00-\u9fff]", s)) / max(1, len(s))
            if cjk_ratio < 0.35:   # 多为图注/公式 OCR 残片，跳过
                continue
            kept.append(s)
        summary = "".join(kept[:3]).strip()
        summary = re.sub(r"\s+", "", summary)
        if not summary:
            summary = top["snippet"][:80].strip()
        return (f"根据教材{top['citation']}《{top['chapter']}》的讲解：{summary}。"
                f"（注：当前为无 API Key 的检索合成模式，仅作 RAG 管线演示；"
                f"配置 OS_QA_API_KEY 后将由大模型生成更完整的回答。）")

    # ---- 一次完整问答（RAG 编排）----
    def ask(self, question: str, verbose: bool = True) -> dict:
        expanded, results, context = self.retrieve(question)
        system_prompt = self.prompt_template.replace("{retrieved_context}", context)
        if verbose:
            print(f"\n🔍 【检索】knowledge_search(\"{expanded}\") → 命中 {len(results)} 条")
            for r in results[:3]:
                print(f"   {r['citation']} 《{r['chapter']}》 {r['snippet'][:60]}…")
        answer = self.call_llm(system_prompt, question)
        used_llm = bool(answer)
        if not used_llm:
            answer = self.compose_answer(results, expanded)
        # 记录历史（多轮）
        self.history.append({"role": "user", "content": question})
        self.history.append({"role": "assistant", "content": answer,
                             "citations": [r["citation"] for r in results]})
        return {"query": expanded, "retrieved": results, "answer": answer,
                "used_llm": used_llm}

    # ---- 拓展挑战 1：命令行可视化交互界面 ----
    def run_cli(self):
        print("=" * 60)
        print("  操作系统教材智能问答系统（RAG · 方案 C）")
        print("  输入问题开始问答；命令：/clear 清空历史  /search 仅检索  /quit 退出")
        print("=" * 60)
        while True:
            try:
                q = input("\n你 > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n再见！")
                break
            if not q:
                continue
            if q in ("/quit", "/exit"):
                print("再见！")
                break
            if q == "/clear":
                self.history.clear()
                print("（对话历史已清空）")
                continue
            if q.startswith("/search "):
                from retrieval import knowledge_search
                for r in knowledge_search(q[8:].strip(), top_k=5):
                    print(f"  {r['citation']} 《{r['chapter']}》 {r['snippet'][:80]}…")
                continue
            res = self.ask(q)
            print("\n🤖 助手：")
            print(res["answer"])
            mode = "LLM 生成" if res["used_llm"] else "检索合成(无Key退化)"
            print(f"\n  └─ 模式：{mode} ｜ 检索命中：{len(res['retrieved'])} 条")


def main():
    eng = QAEngine()
    if len(sys.argv) > 1:
        q = " ".join(sys.argv[1:])
        res = eng.ask(q)
        print("\n🤖 助手：")
        print(res["answer"])
    else:
        eng.run_cli()


if __name__ == "__main__":
    main()
