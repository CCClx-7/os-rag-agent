# -*- coding: utf-8 -*-
"""
项目一评测运行脚本（eval_stats.py 的数据生产者）
================================================
读取 eval_set.jsonl，对每条问题调用 rag.RAG.query，生成 results.jsonl：
    {"id","question","type","expected","answer","refused","sources","top_score","result","note"}
并实时打印每条答案与自动判定，供人工复核。

运行：
    python run_eval.py            # 生成 results.jsonl 并打印摘要
    python run_eval.py --print     # 同时逐条打印答案文本（长）
"""
import os
import sys
import json
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT1 = os.path.dirname(os.path.dirname(HERE))   # .../project1（脚本位于 evals/project1/ 下两级）
sys.path.insert(0, PROJECT1)

import rag

EVAL_SET = os.path.join(HERE, "eval_set.jsonl")
RESULTS = os.path.join(HERE, "results.jsonl")


def auto_label(item, r):
    """按题型 + 是否拒答 给出初步判定，最终以人工复核为准。"""
    t = item["type"]
    refused = r["refused"]
    if t in ("out_of_scope", "adversarial"):
        return "refuse_correct" if refused else "refuse_wrong"
    # in_scope / vague
    return "refuse_wrong" if refused else "correct"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", action="store_true", help="逐条打印答案文本")
    args = ap.parse_args()

    chunks = rag.build_corpus(rag.CORPUS_DIR)
    print(f"[eval] 加载 {len(chunks)} 个分块")
    R = rag.RAG(chunks)

    rows = []
    with open(EVAL_SET, encoding="utf-8") as f:
        items = [json.loads(l) for l in f if l.strip()]

    for it in items:
        r = R.query(it["question"])
        result = auto_label(it, r)
        row = {
            "id": it["id"],
            "question": it["question"],
            "type": it["type"],
            "expected": it["expected"],
            "answer": r["answer"],
            "refused": r["refused"],
            "sources": r["sources"],
            "top_score": r["top_score"],
            "result": result,
            "note": "",
        }
        rows.append(row)
        flag = "拒答" if r["refused"] else "作答"
        print(f"[{it['id']}] {it['type']:12s} {flag} sim={r['top_score']:.3f} -> {result}")
        if args.print:
            print("    答:", r["answer"][:200].replace("\n", " "))

    with open(RESULTS, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"\n[eval] 已写出 {len(rows)} 条结果 -> {RESULTS}")


if __name__ == "__main__":
    main()
