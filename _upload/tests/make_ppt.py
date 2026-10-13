# -*- coding: utf-8 -*-
"""
make_ppt.py —— 成员 D（汇报展示）实施过程 PPT 生成
=================================================
生成 docs/实施过程.pptx（15~20 页），面向同学讲解技术选型与实施过程。
运行：python tests/make_ppt.py
依赖：python-pptx
"""
import os
import json
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATS = os.path.join(ROOT, "docs", "kb_stats.json")
OUT = os.path.join(ROOT, "docs", "实施过程.pptx")

# 配色（深色主题友好）
C_TITLE = RGBColor(0x1F, 0x4E, 0x79)
C_ACCENT = RGBColor(0xC0, 0x39, 0x2B)
C_BODY = RGBColor(0x22, 0x22, 0x22)
C_LIGHT = RGBColor(0xF2, 0xF4, 0xF7)


def load_stats():
    if os.path.exists(STATS):
        try:
            return json.load(open(STATS, encoding="utf-8"))
        except Exception:
            pass
    return {"page_count": 416, "chapter_count": 12, "chunk_count": "—"}


def add_title_slide(prs, title, subtitle):
    s = prs.slides.add_slide(prs.slide_layouts[0])
    s.shapes.title.text = title
    tf = s.placeholders[1].text_frame
    tf.text = subtitle
    return s


def add_bullets(prs, title, bullets, notes=None):
    s = prs.slides.add_slide(prs.slide_layouts[1])
    s.shapes.title.text = title
    tf = s.placeholders[1].text_frame
    tf.word_wrap = True
    for i, b in enumerate(bullets):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        if isinstance(b, tuple):
            p.text = b[0]
            p.level = b[1] if len(b) > 1 else 0
        else:
            p.text = b
        p.space_after = Pt(6)
    if notes:
        s.notes_slide.notes_text_frame.text = notes
    return s


def add_flow(prs, title, steps):
    """用文本框+箭头画横向流程（检索先于回答）。"""
    s = prs.slides.add_slide(prs.slide_layouts[6])  # 空白
    box = s.shapes.add_textbox(Inches(0.5), Inches(0.3), Inches(9), Inches(0.8))
    box.text_frame.text = title
    box.text_frame.paragraphs[0].font.size = Pt(28)
    box.text_frame.paragraphs[0].font.bold = True
    box.text_frame.paragraphs[0].font.color.rgb = C_TITLE
    n = len(steps)
    left = Inches(0.4)
    top = Inches(2.2)
    w = Inches(1.7)
    h = Inches(1.3)
    gap = Inches(0.35)
    for i, st in enumerate(steps):
        tb = s.shapes.add_textbox(left + i * (w + gap), top, w, h)
        tf = tb.text_frame
        tf.word_wrap = True
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        p = tf.paragraphs[0]
        p.text = st
        p.alignment = PP_ALIGN.CENTER
        p.font.size = Pt(14)
        p.font.color.rgb = C_BODY
        # 简单底色
        tb.fill.solid()
        tb.fill.fore_color.rgb = C_LIGHT
        if i < n - 1:
            ar = s.shapes.add_textbox(left + w + i * (w + gap) + Inches(0.02), top + Inches(0.45), gap, Inches(0.4))
            ar.text_frame.text = "→"
            ar.text_frame.paragraphs[0].font.size = Pt(24)
            ar.text_frame.paragraphs[0].font.color.rgb = C_ACCENT
            ar.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER
    return s


def main():
    stats = load_stats()
    prs = Presentation()
    prs.slide_width = Inches(10)
    prs.slide_height = Inches(5.63)

    # 1 封面
    add_title_slide(prs, "计算机操作系统（第4版）· 课程知识库智能问答系统",
                    "专业素养培养 · 分组实践作业\n技术栈：方案 C（纯 Python + SQLite FTS5 + 直连 LLM API）")

    # 2 作业背景与 RAG
    add_bullets(prs, "一、作业背景：什么是 RAG 问答",
                ["RAG = Retrieval-Augmented Generation（检索增强生成）",
                 "核心思想：先“检索”教材相关内容，再“生成”回答，而非依赖模型记忆",
                 "价值：有效避免大语言模型的“幻觉”，答案可溯源到教材页码",
                 "本作业要求：选一门课程教材 → 建本地知识库 → 配只基于教材问答、带页码引用的系统"])

    # 3 强制约束 R1-R6
    add_bullets(prs, "二、强制行为约束（R1~R6，与技术栈无关）",
                ["R1 回答前必须先检索知识库",
                 "R2 只能使用检索到的教材内容，禁止模型内部知识",
                 "R3 每个事实陈述附页码引用【教材 p.XX】",
                 "R4 简单中文解释，关键术语保留英文（process / thread / deadlock）",
                 "R5 未覆盖内容必须如实说明，不编造",
                 "R6 禁止输出连续 >3 句原文（版权保护）"])

    # 4 技术选型
    add_bullets(prs, "三、技术选型：为什么选方案 C",
                ["方案 A（参考案例）：Node + DSH 框架 + FTS5 —— 中，生态重",
                 "方案 B：ChromaDB/FAISS + LangChain —— 中高，需 ML 基础",
                 ("方案 C（本实现）：SQLite FTS5 + 纯 Python + 直连 LLM API —— 低中",
                  0),
                 "方案 D：Dify/FastGPT 低代码 —— 低，黑盒",
                 "选 C 的理由：零 RAG 框架依赖、最易读懂、与参考案例差异化、利于演示 RAG 原理"])

    # 5 教材与知识库概览
    add_bullets(prs, "四、知识库概览（教材：《计算机操作系统（第4版）》）",
                [f"教材页数：{stats.get('page_count')} 页（图片型 PDF，无文本层 → 需 OCR）",
                 f"章节数：{stats.get('chapter_count')} 章（基于 PDF 目录自动检测）",
                 f"文本块数：{stats.get('chunk_count')} 块（滑动窗口 + 重叠分块）",
                 "检索：SQLite FTS5 + trigram 分词 + BM25（对中文无需分词，开箱即用）"])

    # 6 Phase1 构建流程
    add_flow(prs, "五、Phase 1 知识库构建流程（成员 A）",
             ["PDF/OCR\n提取每页", "目录检测\n章节边界", "滑动窗口\n语义分块", "FTS5\n建库", "验证\n覆盖率"])

    # 7 分块策略
    add_bullets(prs, "六、分块策略（成员 A）",
                ["按章节分组，章节内用滑动窗口",
                 "目标块大小：800~1200 token（≈1300~1900 中文字）",
                 "块间重叠 220 字，保证上下文连续、减少边界信息丢失",
                 "每块记录：text / page_start / page_end / chapter（四类元数据齐全）",
                 "OCR 逐页识别并缓存（docs/pages_ocr.jsonl），避免重复识别"])

    # 8 Phase2 智能体配置
    add_bullets(prs, "七、Phase 2 智能体配置（成员 B）",
                ["检索工具 knowledge_search(query)：返回带页码的教材片段",
                 "系统提示词：五段式，落实 R1~R6（见 prompts/system_prompt.txt）",
                 "RAG 编排：代码层先检索后回答，不依赖模型自觉调用工具",
                 "LLM：OpenAI 兼容 API（DeepSeek 等），无 Key 时退化“检索合成”"])

    # 9 系统提示词五段
    add_bullets(prs, "八、系统提示词五段结构（成员 B）",
                ["① RAG 工作流：先检索后回答（R1）",
                 "② 知识边界：只用教材（R2）",
                 "③ 引用规范：每条事实附【教材 p.XX】（R3）",
                 "④ 语言风格：简单中文 + 保留英文术语（R4）",
                 "⑤ 版权与诚实：禁 >3 句原文 + 未覆盖如实说（R5/R6）"])

    # 10 RAG 工作流（检索先于回答）
    add_flow(prs, "九、RAG 工作流：检索先于回答（R1 双保险）",
             ["用户提问", "knowledge_search\n强制先检索", "注入上下文\n+页码", "LLM 生成\n/合成", "带引用回答"])

    # 11 拓展挑战1 可视化界面
    add_bullets(prs, "十、拓展挑战 ①：可视化界面（CLI）",
                ["命令行交互式问答，零前端依赖、零额外包",
                 "实时展示检索过程：命中条数 + 引用 + 章节",
                 "命令：/search 仅检索、/clear 清空历史、/quit 退出",
                 "价值：无需搭服务器即可课堂演示完整 RAG 行为"])

    # 12 拓展挑战2 多轮对话
    add_bullets(prs, "十一、拓展挑战 ②：多轮对话（指代消解）",
                ["维护对话历史，理解上下文中的“它 / 该 / 上述”等指代",
                 "检测到指代时，用上一轮问题扩展检索查询，提升命中准确率",
                 "历史同时注入给 LLM，使其能正确解析指代",
                 "示例：先问“进程同步”，再问“它有哪些经典问题？”→ 命中正确章节"])

    # 13 测试验证
    add_bullets(prs, "十二、测试验证（成员 C）",
                ["≥3 个问答案例逐条验证 R1~R6（见 docs/test_report.docx）",
                 "覆盖：死锁预防、页面置换、进程 vs 线程（教材内）",
                 "超纲问题（Kafka 配置）→ 验证 R5 诚实拒答",
                 "多轮指代案例 → 验证拓展挑战“多轮对话”",
                 "结论：R1/R3/R5/R6 硬性约束全部满足"])

    # 14 交付物
    add_bullets(prs, "十三、交付物清单",
                ["① 知识库：knowledge_base.db + build_kb.py",
                 "② 检索工具：retrieval.py（knowledge_search）",
                 "③ 系统提示词：system_prompt.txt + prompt_design.md",
                 "④ 智能体配置：agent_config.json.example + qa_system.py",
                 "⑤ 测试报告：docs/test_report.docx",
                 "⑥ 实施过程 PPT：本文件",
                 "⑦ 小组分工说明：docs/division.md"])

    # 15 分工
    add_bullets(prs, "十四、小组分工（成员 A~D）",
                ["成员 A · 知识库构建：PDF(OCR)提取、章节检测、语义分块、FTS5 建库、验证",
                 "成员 B · 智能体配置：knowledge_search、系统提示词设计、RAG 编排",
                 "成员 C · 测试验证：冒烟测试、R1~R6 合规验证、测试报告",
                 "成员 D · 汇报展示：PPT 制作、文档整理（含本 PPT 与分工说明）"])

    # 16 总结
    add_bullets(prs, "十五、总结",
                ["纯 Python 实现 RAG 问答，零重型框架、与参考案例差异化",
                 "代码层强制“先检索后回答”，R1~R6 可逐条验证",
                 "完成 2 项拓展挑战：可视化界面 + 多轮对话",
                 "可演进：换教材只需重跑 build_kb；可平滑接入向量/混合检索"],
                notes="Thanks / Q&A")

    prs.save(OUT)
    try:
        npages = len(prs.slides._sldIdLst)
    except Exception:
        npages = sum(1 for _ in prs.slides)
    print(f"[完成] PPT 已生成：{OUT}（{npages} 页）")


if __name__ == "__main__":
    main()
