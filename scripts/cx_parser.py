#!/usr/bin/env python3
"""超星作业页文本 → 结构化题目。

不依赖 HTML 结构（超星改版频繁），只吃纯文本。
容错原则：拿不准的宁可留在 stem 里，也不要丢。

输入形态（`cxwork fetch` 出来的 .txt，或 Ctrl+A/C 复制出来的文本）：
    暂时保存提交作业
    作业一
    题量: 27 满分: 100 作答时间:10-26 19:10至10-29 19:10
    一. 单选题（共10题，37分）
    1. (单选题) 题干……
    A
    Ctrl+Alt+F1

    B
    Ctrl+Alt+T

输出：dict，见 parse_work_text 的 docstring。
"""
from __future__ import annotations

import json
import re
from typing import Any

# 题型标题行：一. 单选题（共10题，37分） / 二、填空题（37分） / 三. 简答题（共5题，18.5分）
RE_SECTION = re.compile(
    r"^\s*(?P<idx>[一二三四五六七八九十]+)\s*[.、]\s*"
    r"(?P<name>[^\s（(]{2,8}?)"
    r"[（(]\s*(?:共\s*)?(?P<count>\d+)\s*题\s*[，,、]?\s*(?P<score>[\d.]+)\s*分\s*[）)]"
)

# 题型标题（省略题数时）：一. 单选题（37分）
RE_SECTION_NOCNT = re.compile(
    r"^\s*(?P<idx>[一二三四五六七八九十]+)\s*[.、]\s*"
    r"(?P<name>[^\s（(]{2,8}?)"
    r"[（(]\s*(?P<score>[\d.]+)\s*分\s*[）)]"
)

# 题号行：1. (单选题) 题干……
RE_QUESTION = re.compile(
    r"^\s*(?P<no>\d{1,3})\s*[.．、]\s*"
    r"[（(]\s*(?P<type>[^）)]{1,10})\s*[）)]\s*"
    r"(?P<stem>.*)$"
)

# 选项字母独占一行
RE_OPTION_LETTER = re.compile(r"^\s*(?P<letter>[A-Z])\s*$")

# 选项字母 + 内容在同一行：A. xxx / A、xxx
RE_OPTION_INLINE = re.compile(r"^\s*(?P<letter>[A-Z])\s*[.．、]\s*(?P<text>.+)$")

# 填空占位：第1空
RE_BLANK = re.compile(r"^\s*第\s*(?P<n>\d+)\s*空\s*$")

# 元信息行：题量: 27 满分: 100 作答时间:10-26 19:10至10-29 19:10
RE_META = re.compile(
    r"题量\s*[:：]\s*(?P<qty>\d+).*?满分\s*[:：]\s*(?P<score>[\d.]+)"
    r"(?:.*?作答时间\s*[:：]\s*(?P<win>.+))?"
)

# 尾部的答题卡（"一. 单选题（37分）\n12345678910"），要整段丢弃
RE_CARD_DIGITS = re.compile(r"^\s*\d{5,}\s*$")

# 页面装饰性文字，不算题干
NOISE_LINES = {"暂时保存", "提交", "作业", "暂时保存提交作业"}


def _clean_stem(lines: list[str]) -> str:
    """把题干的多行拼起来，去掉装饰行和空行。"""
    keep = []
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if s in NOISE_LINES:
            continue
        keep.append(s)
    return " ".join(keep).strip()


def _is_section(line: str) -> re.Match | None:
    return RE_SECTION.match(line) or RE_SECTION_NOCNT.match(line)


def parse_work_text(text: str) -> dict[str, Any]:
    """解析一份作业页文本。

    返回：
    {
      "title": "作业一",
      "meta": {"total_questions": 27, "total_score": 100.0, "window": "..."},
      "sections": [
         {"index":"一", "name":"单选题", "count":10, "score":37.0,
          "questions":[{"no":1,"type":"单选题","stem":"...","options":{"A":"..."},"blank_count":0}]}
      ],
      "warnings": ["..."]
    }
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    result: dict[str, Any] = {
        "title": "",
        "meta": {"total_questions": None, "total_score": None, "window": None},
        "sections": [],
        "warnings": [],
    }

    # ---- 元信息
    for ln in lines[:15]:
        m = RE_META.search(ln)
        if m:
            result["meta"]["total_questions"] = int(m.group("qty"))
            result["meta"]["total_score"] = float(m.group("score"))
            if m.group("win"):
                result["meta"]["window"] = m.group("win").strip()
            break

    # ---- 标题：第一段里既不是元信息也不是题型标题的非空行
    for ln in lines[:15]:
        s = ln.strip()
        if not s or RE_META.search(s) or _is_section(s):
            continue
        if s in NOISE_LINES:
            continue
        if re.match(r"^\d{4}-\d{2}-\d{2}", s):  # 日期
            continue
        result["title"] = s
        break

    # ---- 切块
    cur_section: dict | None = None
    cur_q: dict | None = None
    state = "idle"  # idle | stem | options | blanks
    last_option: str | None = None
    pending_card = False  # 进入答题卡区域，丢弃后续

    def flush_question():
        nonlocal cur_q, state, last_option
        if cur_q is None:
            return
        cur_q["stem"] = _clean_stem(cur_q["stem_lines"])
        del cur_q["stem_lines"]
        if cur_q["blank_count"] == 0 and cur_q.get("_blank_seen"):
            cur_q["blank_count"] = cur_q["_blank_seen"]
        cur_q.pop("_blank_seen", None)
        if cur_section is not None:
            cur_section["questions"].append(cur_q)
        cur_q = None
        state = "idle"
        last_option = None

    meta_total = result["meta"]["total_questions"]

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            continue

        # 已经解析够标注的题数 → 后面全是答题卡和按钮，整段丢弃。
        # 这比"识别答题卡长什么样"可靠得多，因为超星答题卡里的题型标题
        # （"一. 单选题（37分）"）和正文长得几乎一样，靠形态分不出来。
        if meta_total:
            so_far = sum(len(s["questions"]) for s in result["sections"])
            if so_far >= meta_total:
                break

        # 兜底：页面没给总题数时，靠"纯数字串"识别答题卡入口
        if RE_CARD_DIGITS.match(line):
            flush_question()
            pending_card = True
            continue
        if pending_card:
            continue

        # 题型标题
        m = _is_section(line)
        if m:
            d = m.groupdict()
            name = (d.get("name") or "").strip()
            # 答题卡区的题型标题不带「共N题」，只带分值；而且必然和正文重名。
            # 命中就说明正文结束了，后面整段丢弃。
            if not d.get("count") and any(s["name"] == name for s in result["sections"]):
                flush_question()
                break
            flush_question()
            cur_section = {
                "index": d.get("idx"),
                "name": name,
                "count": int(d["count"]) if d.get("count") else None,
                "score": float(d["score"]) if d.get("score") else None,
                "questions": [],
            }
            result["sections"].append(cur_section)
            state = "idle"
            continue

        # 题号行
        mq = RE_QUESTION.match(line)
        if mq:
            flush_question()
            cur_q = {
                "no": int(mq.group("no")),
                "type": mq.group("type").strip(),
                "stem_lines": [mq.group("stem")] if mq.group("stem").strip() else [],
                "options": {},
                "blank_count": 0,
            }
            state = "stem"
            last_option = None
            continue

        if cur_q is None:
            continue

        # 填空占位
        mb = RE_BLANK.match(line)
        if mb:
            n = int(mb.group("n"))
            if n > cur_q["blank_count"]:
                cur_q["blank_count"] = n
            cur_q["_blank_seen"] = max(n, cur_q.get("_blank_seen") or 0)
            state = "blanks"
            continue

        # 选项：字母独占一行
        mo = RE_OPTION_LETTER.match(line)
        if mo and state in ("stem", "options", "blanks"):
            last_option = mo.group("letter")
            cur_q["options"].setdefault(last_option, "")
            state = "options"
            continue

        # 选项：字母和内容同一行
        moi = RE_OPTION_INLINE.match(line)
        if moi and state in ("stem", "options") and moi.group("letter") in "ABCDEFGH":
            last_option = moi.group("letter")
            cur_q["options"][last_option] = moi.group("text").strip()
            state = "options"
            continue

        # 普通行：落到题干或上一个选项里
        s = line.strip()
        if s in NOISE_LINES:
            continue
        if state == "stem":
            cur_q["stem_lines"].append(s)
        elif state == "options" and last_option:
            cur_q["options"][last_option] = (cur_q["options"][last_option] + " " + s).strip()
        elif state == "blanks":
            pass  # 空后紧跟的占位符文本忽略
        else:
            cur_q["stem_lines"].append(s)

    flush_question()

    # ---- 自检
    total = sum(len(s["questions"]) for s in result["sections"])
    warn = result["warnings"]
    if result["meta"]["total_questions"] and total != result["meta"]["total_questions"]:
        warn.append(f"解析出 {total} 题，但页面标注 {result['meta']['total_questions']} 题")
    for sec in result["sections"]:
        if sec["count"] and len(sec["questions"]) != sec["count"]:
            warn.append(f"{sec['name']}：解析 {len(sec['questions'])} 题，标注 {sec['count']} 题")
        for q in sec["questions"]:
            if not q["stem"]:
                warn.append(f"第 {q['no']} 题题干为空")

    result["parsed_total"] = total
    return result


def main(argv=None):
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="超星作业文本 → 结构化 JSON")
    ap.add_argument("txt", help="纯文本文件；传 - 从 stdin 读")
    ap.add_argument("-o", "--out", help="输出 JSON 路径，默认打印到 stdout")
    a = ap.parse_args(argv)

    if a.txt == "-":
        raw = sys.stdin.read()
    else:
        raw = open(a.txt, encoding="utf-8").read()

    data = parse_work_text(raw)
    out = json.dumps(data, ensure_ascii=False, indent=2)
    if a.out:
        open(a.out, "w", encoding="utf-8").write(out)
        print(f"[ok] {a.out} · {data['parsed_total']} 题", file=sys.stderr)
        for w in data["warnings"]:
            print(f"[warn] {w}", file=sys.stderr)
    else:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
