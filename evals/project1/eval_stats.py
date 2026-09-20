# -*- coding: utf-8 -*-
"""
项目一评测统计脚本（对应 14_评测脚手架 的统计脚本）
================================================
读取 run_eval.py 产出的 results.jsonl，输出：
  - 总条数、各题型数量
  - 准确率 = correct / (correct + wrong + hallucinated)
  - 拒答正确率 = refuse_correct / (refuse_correct + refuse_wrong)
  - 幻觉条数（单独列出，≥3 须在复盘文档逐条归因）
  - 达标判定（拒答率≥70% 且 条数≥20）

运行：
    python eval_stats.py
    python eval_stats.py --out summary.txt   # 同时落盘摘要
"""
import os
import sys
import json
import argparse
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results.jsonl")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="", help="把摘要同时写到该文件")
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(RESULTS, encoding="utf-8")]
    c = Counter(r["result"] for r in rows)
    type_c = Counter(r["type"] for r in rows)

    answered = c["correct"] + c["wrong"] + c["hallucinated"]
    acc = c["correct"] / answered if answered else 0.0
    refuse_total = c["refuse_correct"] + c["refuse_wrong"]
    refuse_rate = c["refuse_correct"] / refuse_total if refuse_total else 0.0
    passed = (refuse_rate >= 0.7) and (len(rows) >= 20)

    lines = []
    lines.append("=" * 56)
    lines.append("项目一 课程知识问答智能体（RAG）· 评测统计摘要")
    lines.append("=" * 56)
    lines.append(f"总条数            : {len(rows)}")
    lines.append(f"题型分布          : " + ", ".join(f"{t}={n}" for t, n in type_c.items()))
    lines.append("-" * 56)
    lines.append(f"准确率            : {acc:.1%}  (correct={c['correct']}, wrong={c['wrong']}, hallucinated={c['hallucinated']})")
    lines.append(f"拒答正确率        : {refuse_rate:.1%}  (拒对={c['refuse_correct']}, 拒错={c['refuse_wrong']})")
    lines.append(f"幻觉条数          : {c['hallucinated']}  （≥3 须复盘逐条归因）")
    lines.append("-" * 56)
    lines.append(f"逐条判定明细      :")
    for r in rows:
        tag = {"correct": "正确", "wrong": "错误", "hallucinated": "幻觉",
               "refuse_correct": "拒对", "refuse_wrong": "拒错"}[r["result"]]
        lines.append(f"  {r['id']} [{r['type']:11s}] {tag:4s} sim={r['top_score']:.3f}  {r['question']}")
    lines.append("-" * 56)
    lines.append(f"达标判定          : {'PASS ✅' if passed else 'FAIL ❌'}")
    lines.append(f"  （硬性条件：拒答率≥70% 且 评测集≥20 条）")
    lines.append("=" * 56)

    text = "\n".join(lines)
    print(text)
    if args.out:
        with open(os.path.join(HERE, args.out), "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"[eval_stats] 摘要已落盘 -> {args.out}")


if __name__ == "__main__":
    main()
