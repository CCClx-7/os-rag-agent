# 项目一：课程知识问答智能体（RAG）

基于《操作系统》课件与教材文本搭建的**检索增强生成（RAG）**课程问答智能体。
学生提问课程相关问题，系统基于课程资料作答并**标注来源段落**；资料库中没有依据的问题，系统**明确拒答，不编造**。

> 对应课程资料：`10_项目一任务书`、`02_三项目Rubric评分表`、`11_RAG概念卡_8张`、`12_最小RAG骨架`、`13_样例语料与标准分块`、`14_评测脚手架`、`15_外部资料精选清单`。

---

## 一、环境要求

- **任意 Python ≥ 3.8，零第三方依赖**（纯标准库，无需 numpy，无外网即可运行）
- 可选增强（检测到自动启用，不影响离线运行）：
  - `sentence-transformers`：提供语义向量，替代 TF-IDF n-gram
  - 设置环境变量 `OPENAI_API_KEY`（及可选 `OPENAI_BASE_URL`）：启用真实 LLM 流畅生成，检索与拒答逻辑不变

> 无需 `pip install`。如果运行报 `No module named 'numpy'`，说明用的是系统 Python——
> 本项目已不依赖 numpy，请直接用下面的命令即可，不要去给系统 Python 装包。

---

## 二、一键运行（可复现）

```bash
python rag.py                         # 跑一次端到端问答示例
python rag.py "什么是死锁？"          # 指定问题
python rag.py --interactive           # 交互问答（输入 exit 退出）
```

首次运行会加载 `corpus/` 下全部语料并构建索引，输出形如：
`已加载 39 个分块，来源：['os_ch1.txt', ...]`。

---

## 三、评测（达标验证）

评测集 ≥ 20 条，含逐条结果与统计摘要，全部位于 `evals/project1/`：

```bash
python evals/project1/run_eval.py     # 对 30 条问题跑系统，生成 results.jsonl
python evals/project1/eval_stats.py   # 汇总指标，输出 summary.txt
```

**当前结果（详见 `evals/project1/summary.txt`）**

| 指标 | 结果 | 硬性达标线 |
|------|------|-----------|
| 准确率 correct/(correct+wrong+hallucinated) | **100.0%** | ≥ 70% |
| 拒答正确率 refuse_correct/(refuse_correct+refuse_wrong) | **100.0%** | ≥ 70%（硬性条件） |
| 评测集条数 | **30** | ≥ 20（硬性条件） |
| 幻觉条数 | 0 | ≥3 须复盘 |
| 达标判定 | **PASS** | — |

> 题型配比：in_scope 18 / out_of_scope 6 / adversarial 3 / vague 3，均满足 `14_评测脚手架` 的占比要求。

---

## 四、目录结构

```
project1/
├── rag.py                  # 可运行系统：分块→Embedding→检索→拒答→生成
├── requirements.txt        # 依赖
├── README.md               # 本文件（一键复现）
├── 设计文档.md             # 分块策略/Prompt/拒答机制/失败案例/迭代方向
├── corpus/                 # 课程知识库（《操作系统》6 章，【标题】分段）
│   ├── os_ch1.txt          # 进程与线程
│   ├── os_ch2.txt          # CPU 调度与死锁
│   ├── os_ch3.txt          # 内存管理
│   ├── os_ch4.txt          # 文件与 I/O
│   ├── os_ch5.txt          # 进程同步与通信
│   └── os_ch6.txt          # 磁盘调度与 RAID
└── evals/project1/
    ├── eval_set.jsonl      # 评测集（30 条，含题型/expected）
    ├── run_eval.py         # 评测运行脚本（生成 results.jsonl）
    ├── results.jsonl       # 逐条结果与判定
    ├── eval_stats.py       # 统计脚本（生成 summary.txt）
    └── summary.txt         # 统计摘要
```

---

## 五、设计要点速览

- **RAG 五步流程**：提问 → 检索(top-k) → 组装 Prompt → 生成 → 输出来源。
- **离线 Embedding**：字符 n-gram + IDF 稠密向量（纯标准库实现，无 numpy 依赖）；语义向量可选。
- **拒答三件套（硬约束）**：①意图过滤（代码/天气/汇率/生活咨询等）②相似度阈值（top-1 < 0.13 且无课程主题词则拒答）③评测集验证拒答率——均放在「调用生成之前」，比 Prompt 软约束可靠。
- **零幻觉基线**：默认用「抽取式」合成（从检索段落挑选相关句子），不生成资料外内容；真实 LLM 为可选增强。
- 详见 `设计文档.md`。

---

## 六、外部资料与来源说明

按 `15_外部资料精选清单` / `自学方法指南`：本项目核心实现由本组完成，概念与命名参考以下公开资料（已在 `设计文档.md` 引用，未直接复制代码）：

- Lewis et al., 2020, *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks* (arXiv:2005.11401) — RAG 原始论文。
- LangChain 官方文档 (python.langchain.com/docs) — RAG 组件命名与流程对照。
- Chroma 文档 (docs.trychroma.com) — 向量库最小可用集概念。
- Prompt Engineering Guide (promptingguide.ai) — 检索结果组织进 Prompt 的写法。
- `11_RAG概念卡_8张`、`12_最小RAG骨架`、`13_样例语料与标准分块`、`14_评测脚手架` — 课程脚手架。

> 注：本环境无外网，系统以 TF-IDF + 抽取式合成为离线基线；上述语义/LLM 能力为可选插件，检测到时自动启用。
