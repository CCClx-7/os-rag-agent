# 计算机操作系统（第4版）· 课程知识库智能问答系统

> 某课程「知识库的智能问答系统」分组实践作业 —— 个人完整实现（成员 A/B/C/D 工作合并交付）
> 技术栈：**方案 C（纯 Python + SQLite FTS5 + 直连 LLM API）**，与教师参考案例（方案 A / Node + DSH）刻意差异化。

---

## 0. 一句话运行

```bash
# ① 构建知识库（教材为图片型 PDF，需先 OCR；结果会缓存，二次运行很快）
python src/build_kb.py --use-cache

# ② 单轮问答（未配 API Key 时走“检索合成”退化模式，仍可演示 RAG 管线）
python src/qa_system.py "什么是死锁？如何预防？"

# ③ 进入命令行交互界面（拓展挑战：可视化界面 + 多轮对话）
python src/qa_system.py
```

---

## 1. 作业强制约束（R1~R6）如何被满足

| 编号 | 要求 | 本系统的实现方式 |
|---|---|---|
| R1 | 回答前必须**先检索** | 检索在**代码层**强制：先 `knowledge_search()` 再生成回答，不依赖模型自觉调用工具 |
| R2 | **只用教材**，禁内部知识 | 系统提示词限定知识来源仅为检索片段；无 Key 退化模式只转述检索结果 |
| R3 | 每条事实附**页码引用**【教材 p.XX】 | 检索结果自带页码；提示词 + 合成逻辑强制每条事实后标注 |
| R4 | 简单中文 + **保留英文术语** | 提示词规定术语中英对照（process/thread/deadlock…） |
| R5 | 未覆盖**如实说明** | 检索为空时输出“未检索到相关教材内容”，不编造 |
| R6 | 禁止连续 >3 句原文（版权） | 合成模式只取片段前 3 句转述并保留引用 |

---

## 2. 技术选型与差异化

- **教材**：《计算机操作系统（第4版）》，416 页，12 章，图片型 PDF（ABBYY 生成，无文本层）。
- **提取**：PyMuPDF 渲染页面 + **Tesseract 5.4（chi_sim）OCR**（教材无文本层，OCR 不可避免）。
- **分块**：按章节滑动窗口，目标 800~1200 token（≈1300~1900 字），块间重叠 220 字。
- **检索**：**SQLite FTS5 + trigram 分词器 + BM25**（trigram 对中文无需分词，开箱即用）。

> 注：教材为图片型 PDF，OCR 由 Tesseract(chi_sim) 完成。正文中偶有图表公式的 OCR 残片，
> 属正常现象，不影响分块与检索命中；RAG 回答的页码引用均真实可溯。
- **智能体**：纯 Python 编排 `knowledge_search` → 注入上下文 → 调 LLM（OpenAI 兼容）。
- **与参考案例差异**：参考用 Node + DSH + 向量/FTS5；本方案用纯 Python、零 RAG 框架依赖，最易读懂。

---

## 3. 目录结构

```
project-1/
├── README.md                  本文件
├── requirements.txt           运行依赖
├── agent_config.json.example  LLM 配置样例（复制为 agent_config.json 填入 Key）
├── knowledge_base.db          ← 构建产物（run build_kb.py 生成）
├── docs/
│   ├── pages_ocr.jsonl        OCR 逐页文本缓存（避免重复识别）
│   ├── kb_stats.json          知识库统计
│   ├── prompt_design.md       系统提示词设计说明（R1~R6 映射）
│   ├── division.md            小组分工说明
│   └── test_report.docx       ← 测试报告（run tests/run_tests.py 生成）
├── prompts/
│   └── system_prompt.txt      五段式系统提示词（落实 R1~R6）
├── src/
│   ├── build_kb.py            成员A：PDF(OCR)提取 + 章节检测 + 分块 + FTS5 建库
│   ├── retrieval.py           成员B：knowledge_search 检索工具（带页码引用）
│   └── qa_system.py          成员B：RAG 智能体 + CLI + 多轮对话
└── tools/
    └── tesseract_raw/         便携版 Tesseract 5.4 + chi_sim（随项目附带，免安装）
```

---

## 4. 环境依赖

- Python 3.10+（标准库：sqlite3 / re / json / subprocess / concurrent.futures / urllib）
- `pymupdf`（PDF 渲染）：`pip install pymupdf`
- Tesseract 5.4 + `chi_sim` 中文包（已附带于 `tools/tesseract_raw/`，无需联网安装）
- LLM API（**可选**）：DeepSeek / OpenAI 兼容接口；不配置也能跑“检索合成”演示模式

---

## 5. LLM API Key 管理（安全）

> 作业明确要求：不得在代码/提交物中暴露密钥。本系统通过环境变量或本地配置文件读取，且**配置文件不入库**。

```bash
# 方式一：环境变量（推荐，最安全）
export OS_QA_API_KEY="sk-你的密钥"
export OS_QA_BASE_URL="https://api.deepseek.com/v1"   # 默认
export OS_QA_MODEL="deepseek-chat"                    # 默认

# 方式二：本地配置文件（复制样例后填写，勿提交）
cp agent_config.json.example agent_config.json
# 编辑 agent_config.json 填入 api_key
```

配置后运行 `python src/qa_system.py "你的问题"` 即由大模型生成完整回答；
未配置时自动退化为“检索合成”模式（仍满足 R3/R5/R6，用于无 Key 演示与测试）。

---

## 6. 拓展挑战（选做，本实现完成 2 项）

1. **可视化界面**：`qa_system.py` 提供命令行交互式问答（检索过程展示、引用高亮、/search 仅检索、/clear 清历史）。
2. **多轮对话**：维护对话历史，自动识别“它/该/上述”等指代并扩展检索查询，使后续问题能结合上下文命中正确章节。

---

## 7. 交付物清单（映射到作业第七节）

| # | 交付物 | 对应文件 |
|---|---|---|
| 1 | 知识库（数据库 + 构建脚本） | `knowledge_base.db` + `src/build_kb.py` |
| 2 | 检索工具/函数 | `src/retrieval.py`（`knowledge_search`） |
| 3 | 系统提示词 | `prompts/system_prompt.txt` + `docs/prompt_design.md` |
| 4 | 智能体配置 | `agent_config.json.example` + `src/qa_system.py` |
| 5 | 测试报告 | `docs/test_report.docx`（由 `tests/run_tests.py` 生成） |
| 6 | 实施过程 PPT | `docs/实施过程.pptx` |
| 7 | 小组分工说明 | `docs/division.md` |
