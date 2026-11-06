#!/usr/bin/env python3
"""结构化题目 JSON + 答案 JSON → Markdown 笔记。

两种风格（style）：

- `classic`（默认）：题目用 `##`，答案/解析是普通段落，题型分组用加粗行。
  这是历史行为，保持不变，别破坏已有用法。
- `exam`：按 `references/note-format.md` 的「先做题、后对答案」范本排版——
  `######` 题号 + 全选项换行 + 引用块包住解析与答案 + `***` 分隔。
  需要扩展的答案字段（concept / derivation / option_notes），详见该文档第 8 节。

答案文件可选；没有答案时渲染成待填。键是题号（字符串）。
紧凑格式 `{"1": "B"}` 与扩展格式 `{"1": {"answer": "B", ...}}` 都认。
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


def _render_classic(
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
                # 两种答案格式都认：紧凑格式 {"1": "B"} / {"5": ["A","C"]}，
                # 以及带解析的 {"1": {"answer": "B", "explain": "..."}}。
                if isinstance(a, str):
                    ans, exp = a.strip(), ""
                elif isinstance(a, list):
                    ans, exp = " ｜ ".join(str(x) for x in a), ""
                elif isinstance(a, dict):
                    raw_ans = a.get("answer") or ""
                    if isinstance(raw_ans, list):
                        raw_ans = " ｜ ".join(str(x) for x in raw_ans)
                    ans = str(raw_ans).strip()
                    exp = str(a.get("explain") or "").strip()
                else:
                    ans, exp = str(a).strip(), ""
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


# ---------------------------------------------------------------- exam 风格
# 依据 references/note-format.md：题干+全选项在前，解析与答案收进引用块。

JUDGE_WORDS = {"对", "错", "正确", "错误", "true", "false", "√", "×"}


def _answer_parts(a):
    """把任意形态的答案值拆成 (answer, concept, derivation, option_notes, explain)。"""
    if a is None:
        return "", "", "", {}, ""
    if isinstance(a, str):
        return a.strip(), "", "", {}, ""
    if isinstance(a, list):
        return " ｜ ".join(str(x) for x in a), "", "", {}, ""
    if isinstance(a, dict):
        raw = a.get("answer") or ""
        if isinstance(raw, list):
            raw = " ｜ ".join(str(x) for x in raw)
        return (
            str(raw).strip(),
            str(a.get("concept") or "").strip(),
            str(a.get("derivation") or "").strip(),
            a.get("option_notes") or {},
            str(a.get("explain") or "").strip(),
        )
    return str(a).strip(), "", "", {}, ""


def _exam_question(q: dict, a, include_placeholder: bool) -> list[str]:
    no = q["no"]
    qtype = (q.get("type") or "").strip() or "题目"
    stem = (q.get("stem") or "").strip()
    opts = {k: (v or "").strip() for k, v in (q.get("options") or {}).items()}
    ans, concept, derivation, option_notes, explain = _answer_parts(a)

    out = [f"###### {no}. （{qtype}）{stem}", ""]

    # 简答/操作/案例：没有选项，不套遮挡，直接给完整推导
    if not opts:
        if derivation or concept or explain:
            out += [f"**【解析】** {' '.join(x for x in (concept, derivation, explain) if x)}", ""]
        if ans:
            out += [f"**【正确答案】** {ans}", ""]
        elif include_placeholder:
            out += ["**【正确答案】** *(待填)*", ""]
        return out

    for letter in sorted(opts):
        out.append(f"{letter}. {opts[letter]}  ")   # 行尾两空格 = Markdown 硬换行
    out.append("")

    is_judge = all(v.lower() in JUDGE_WORDS for v in opts.values())
    ans_up = ans.upper().replace("｜", "").replace(" ", "")
    correct = {L for L in opts if L in ans_up} or {L for L, T in opts.items() if T == ans}

    out.append("> **解析**：")
    if concept:
        out.append(f"> * **考点**：{concept}")
    if derivation:
        out.append(f"> * **推导**：{derivation}")
    if option_notes:
        for letter in sorted(opts):
            note = str(option_notes.get(letter, "")).strip()
            label = (f"判「{opts[letter]}」" if is_judge else f"{letter}. {opts[letter]}")
            line = f"> * {label}：{note}"
            if letter in correct:
                line = f"> * **{label}**：{note}"
            out.append(line)
    elif explain:
        out.append(f"> * **说明**：{explain}")
    out.append(">")
    if ans:
        out.append(f"> **答案**：**{ans}**")
    elif include_placeholder:
        out.append("> **答案**：*(待填)*")
    return out


def _render_exam(
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

    lines: list[str] = ["---", f"title: {title}"]
    if course:
        lines.append(f"course: {course}")
    lines += ["type: 作业", "platform: 超星学习通", f"total: {total_part} / {score_part}"]
    if window:
        lines.append(f"window: {window}")
    lines += ["---", "", f"# {head}（{total_part} / {score_part}）", ""]

    desc = [f"题量 **{declared or total}**", f"满分 **{_fmt_score(score)}**"]
    if window:
        desc.append(f"作答时间 **{window}**")
    lines += ["> " + " ｜ ".join(desc), ""]
    lines += ["> 题目块按「先做题、后对答案」排版：解析与答案收在引用块里；格式依据 `references/note-format.md`。", ""]

    for sec in sections:
        idx = sec.get("index") or ""
        name = sec.get("name") or ""
        cnt = sec.get("count") or len(sec["questions"])
        sc = _fmt_score(sec.get("score"))
        lines += [f"### {idx}、{name}（{cnt} 题，{sc} 分）", ""]
        for q in sec["questions"]:
            a = answers.get(str(q["no"])) or answers.get(q["no"])
            lines += _exam_question(q, a, include_answer_placeholder)
            lines += ["", "***", ""]

    return "\n".join(lines).rstrip() + "\n"


def render(
    data: dict,
    answers: dict | None = None,
    course: str | None = None,
    include_answer_placeholder: bool = False,
    style: str = "classic",
) -> str:
    """按 style 分发。默认 classic 保持历史输出不变。"""
    if style == "exam":
        return _render_exam(data, answers, course, include_answer_placeholder)
    if style != "classic":
        raise ValueError(f"未知 style: {style}（只支持 classic / exam）")
    return _render_classic(data, answers, course, include_answer_placeholder)


def main(argv=None):
    ap = argparse.ArgumentParser(description="题目 JSON → Markdown 笔记")
    ap.add_argument("json", help="parse 出来的结构化 JSON")
    ap.add_argument("-a", "--answers", help="答案 JSON（可选）")
    ap.add_argument("-c", "--course", help="课程名，写进 frontmatter 和标题")
    ap.add_argument("-o", "--out", help="输出 Markdown 路径")
    ap.add_argument("--placeholder", action="store_true", help="没有答案时留占位行")
    ap.add_argument("--style", choices=["classic", "exam"], default="classic",
                    help="classic（默认，历史格式）/ exam（先做题后对答案，见 references/note-format.md）")
    a = ap.parse_args(argv)

    data = json.loads(Path(a.json).read_text(encoding="utf-8"))
    answers = json.loads(Path(a.answers).read_text(encoding="utf-8")) if a.answers else None

    md = render(data, answers, a.course, a.placeholder, a.style)
    if a.out:
        Path(a.out).write_text(md, encoding="utf-8")
        print(f"[ok] {a.out} · {len(md)} 字符", file=sys.stderr)
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
