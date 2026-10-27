#!/usr/bin/env python3
"""结构化题目 JSON + 答案 JSON → Markdown 笔记。

设计约定：
- 题目原文用 `##`，大纲里展开一级就是全部题目
- 答案、解析是标题下的普通段落，不占标题层级
- 题型分组用加粗行，不进大纲

答案文件是可选的。没有答案时渲染成待填，方便先抓题后补答。

答案文件格式：
    {
      "1":  {"answer": "B", "explain": "…"},
      "11": {"answer": "命令 / 参数", "explain": "…"}
    }
键是题号（字符串），answer 和 explain 都可以省略。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TYPE_ORDER = ["单选题", "多选题", "填空题", "判断题", "简答题", "操作题", "案例", "论述题"]


def _fmt_score(x) -> str:
    if x is None:
        return "—"
    return str(int(x)) if float(x).is_integer() else str(x)


def _render_options(q: dict) -> list[str]:
    opts = q.get("options") or {}
    if not opts:
        return []
    out = []
    for letter in sorted(opts):
        out.append(f"- {letter}. {opts[letter]}")
    return out


def render(
    data: dict,
    answers: dict | None = None,
    course: str | None = None,
    include_answer_placeholder: bool = False,
) -> str:
    answers = answers or {}
    meta = data.get("meta") or {}
    sections = data.get("sections") or []

    total = data.get("parsed_total") or sum(len(s["questions"]) for s in sections)
    declared = meta.get("total_questions")
    score = meta.get("total_score")
    window = meta.get("window")

    title = data.get("title") or "作业"
    head = f"{course} · {title}" if course else title

    total_part = f"{declared} 题" if declared else f"{total} 题"
    score_part = f"{_fmt_score(score)} 分" if score else "— 分"

    lines: list[str] = []
    lines.append("---")
    lines.append(f"title: {title}")
    if course:
        lines.append(f"course: {course}")
    lines.append("type: 作业")
    lines.append("platform: 超星学习通")
    lines.append(f"total: {total_part} / {score_part}")
    if window:
        lines.append(f"window: {window}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {head}（{total_part} / {score_part}）")
    lines.append("")
    desc = [f"题量 **{declared or total}**", f"满分 **{_fmt_score(score)}**"]
    if window:
        desc.append(f"作答时间 **{window}**")
    lines.append("> " + " ｜ ".join(desc))
    struct = " ｜ ".join(
        f"{s['name']} {s['count'] or len(s['questions'])} 题 {_fmt_score(s['score'])} 分"
        for s in sections
    )
    if struct:
        lines.append(f"> 结构：{struct}")
    lines.append("")

    for sec in sections:
        idx = sec.get("index") or ""
        name = sec.get("name") or ""
        cnt = sec.get("count") or len(sec["questions"])
        sc = _fmt_score(sec.get("score"))
        lines.append("---")
        lines.append("")
        lines.append(f"**{idx}、{name}（{cnt} 题，{sc} 分）**")
        lines.append("")
        lines.append("---")
        lines.append("")

        for q in sec["questions"]:
            no = q["no"]
            qtype = q.get("type") or name
            stem = (q.get("stem") or "").strip()
            lines.append(f"## {no}. ({qtype}) {stem}")
            lines.append("")

            opts = _render_options(q)
            if opts:
                lines.extend(opts)
                lines.append("")

            if q.get("blank_count"):
                blanks = q["blank_count"]
                lines.append(f"*（共 {blanks} 空）*")
                lines.append("")

            a = answers.get(str(no)) or answers.get(no)
            if a:
                ans = (a.get("answer") or "").strip()
                exp = (a.get("explain") or "").strip()
                if ans:
                    lines.append(f"**答案：{ans}**")
                    lines.append("")
                if exp:
                    lines.append(f"**解析：** {exp}")
                    lines.append("")
            elif include_answer_placeholder:
                lines.append("**答案：** *(待填)*")
                lines.append("")

            # 题与题之间加分隔线，和手写笔记的排版一致
            if q is not sec["questions"][-1]:
                lines.append("---")
                lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="题目 JSON → Markdown 笔记")
    ap.add_argument("json", help="parse 出来的结构化 JSON")
    ap.add_argument("-a", "--answers", help="答案 JSON（可选）")
    ap.add_argument("-c", "--course", help="课程名，写进 frontmatter 和标题")
    ap.add_argument("-o", "--out", help="输出 Markdown 路径")
    ap.add_argument("--placeholder", action="store_true", help="没有答案时留占位行")
    a = ap.parse_args(argv)

    data = json.loads(Path(a.json).read_text(encoding="utf-8"))
    answers = json.loads(Path(a.answers).read_text(encoding="utf-8")) if a.answers else None

    md = render(data, answers, a.course, a.placeholder)
    if a.out:
        Path(a.out).write_text(md, encoding="utf-8")
        print(f"[ok] {a.out} · {len(md)} 字符", file=sys.stderr)
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
