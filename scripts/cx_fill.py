#!/usr/bin/env python3
"""把答案文件的内容批量填入超星答题页面。

答案由使用者提供，本脚本不生成内容，也不包含提交动作。

两步走：
    python cx_fill.py probe <url>            # 先看页面能识别出几道题
    python cx_fill.py fill <url> -a ans.json --commit   # 确认无误后再真填

答案文件格式（键是题号）：
    {
      "1":  "B",                         # 单选/判断：选项字母，或 "对"/"错"
      "5":  ["A", "C", "D"],             # 多选：字母数组
      "11": ["命令", "参数"],             # 填空：按空顺序
      "21": "终端是……控制台是……"          # 简答/操作：一整段文本
    }

也兼容 {"1": {"answer": "B", "explain": "..."}} 这种格式。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# 题干行：1. (单选题) xxx / 1、(单选题) xxx
RE_QHEAD = re.compile(r"^\s*(\d{1,3})\s*[.．、]\s*[（(]?\s*(单选题|多选题|填空题|判断题|简答题|操作题|案例)")

# 题目容器的候选选择器，按优先级排。超星改版频繁，所以准备多套。
BLOCK_SELECTORS = [
    ".questionLi",
    ".TiMu",
    ".Zy_TItle ~ .Zy_ulTop",
    "[class*='questionLi']",
    "[class*='TiMu']",
    "div[id^='question']",
    "li[id^='question']",
]

# 答题控件
INPUT_RADIO = "input[type=radio]"
INPUT_CHECK = "input[type=checkbox]"
INPUT_TEXT = "input[type=text]"
TEXTAREA = "textarea"
EDITABLE = "[contenteditable=true]"


@dataclass
class Slot:
    """页面上的一道题。"""
    no: int | None = None
    qtype: str = ""
    stem: str = ""
    handle: object = None          # Playwright ElementHandle
    kind: str = "unknown"          # radio | checkbox | blank | text
    controls: list = field(default_factory=list)


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def load_answers(path: str) -> dict[int, str | list[str]]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    out: dict[int, str | list[str]] = {}
    for k, v in raw.items():
        try:
            no = int(k)
        except ValueError:
            continue
        if isinstance(v, dict):
            v = v.get("answer") or v.get("ans") or ""
        if isinstance(v, list):
            out[no] = [str(x).strip() for x in v]
        else:
            out[no] = str(v).strip()
    return out


# ---------------------------------------------------------------- 探测

def _block_text(handle) -> str:
    try:
        return handle.inner_text() or ""
    except Exception:
        return ""


def find_blocks(page) -> list[Slot]:
    """把页面上所有题目容器找出来，顺便识别题号、题型、控件类型。"""
    slots: list[Slot] = []
    seen: set[str] = set()

    def mark(h) -> str | None:
        """给 DOM 元素打个一次性标记，用来去重。Playwright 的 handle 没有稳定 id。"""
        try:
            return h.evaluate("el => (el.__cxMark ||= 'cx' + Math.random().toString(36).slice(2))")
        except Exception:
            return None

    for sel in BLOCK_SELECTORS:
        try:
            handles = page.query_selector_all(sel)
        except Exception:
            continue
        for h in handles:
            key = mark(h)
            if key and key in seen:
                continue
            txt = _block_text(h)
            if not txt.strip():
                continue
            m = RE_QHEAD.search(txt.strip().split("\n")[0]) or RE_QHEAD.search(txt.strip()[:60])
            if not m:
                continue
            if key:
                seen.add(key)
            slots.append(Slot(
                no=int(m.group(1)),
                qtype=m.group(2),
                stem=txt.strip().split("\n")[0][:160],
                handle=h,
            ))
        if slots:
            break  # 第一个能用的选择器就够了

    # 认不出容器就退一步：按 input 分组反推
    if not slots:
        slots = _fallback_by_inputs(page)

    for s in slots:
        _classify(s)
    return slots


def _fallback_by_inputs(page) -> list[Slot]:
    """容器选择器全都匹配不上时的兜底：从答题控件往上找最近的块级祖先。"""
    slots: list[Slot] = []
    try:
        controls = page.query_selector_all(f"{INPUT_RADIO}, {INPUT_CHECK}, {INPUT_TEXT}, {TEXTAREA}")
    except Exception:
        return slots

    groups: dict[int, object] = {}
    for c in controls:
        try:
            box = c.evaluate_handle(
                "el => { let p = el; for (let i=0;i<8 && p.parentElement;i++){"
                " p = p.parentElement; if (p.querySelectorAll('input,textarea').length >= 1"
                " && /\\d+\\s*[.．、]/.test(p.innerText||'')) return p; } return null; }"
            )
            el = box.as_element()
            if el is None:
                continue
            key = id(el)
            groups.setdefault(key, el)
        except Exception:
            continue

    for h in groups.values():
        txt = _block_text(h)
        m = RE_QHEAD.search(txt.strip()[:80])
        slots.append(Slot(
            no=int(m.group(1)) if m else None,
            qtype=m.group(2) if m else "",
            stem=txt.strip().split("\n")[0][:160],
            handle=h,
        ))
    return slots


def _classify(s: Slot):
    """判断这道题该用哪种控件填。"""
    h = s.handle
    if h is None:
        s.kind = "unknown"
        return
    if h.query_selector(INPUT_RADIO):
        s.kind = "radio"
        s.controls = h.query_selector_all(INPUT_RADIO)
    elif h.query_selector(INPUT_CHECK):
        s.kind = "checkbox"
        s.controls = h.query_selector_all(INPUT_CHECK)
    elif h.query_selector(TEXTAREA) or h.query_selector(EDITABLE):
        s.kind = "text"
        s.controls = h.query_selector_all(f"{TEXTAREA}, {EDITABLE}")
    elif h.query_selector(INPUT_TEXT):
        s.kind = "blank"
        s.controls = h.query_selector_all(INPUT_TEXT)
    else:
        s.kind = "unknown"


# ---------------------------------------------------------------- 填写

def _click_option(slot: Slot, letter: str) -> bool:
    """点选项。优先点 label —— 很多前端框架只认用户点击，不认 setting checked。"""
    letter = letter.strip().upper()
    h = slot.handle
    try:
        labels = h.query_selector_all("label")
        for lb in labels:
            t = norm(_block_text(lb))
            if t.startswith(letter):
                lb.click(timeout=5000)
                return True
        # label 认不出来就按顺序点第 N 个控件
        idx = ord(letter) - ord("A")
        if 0 <= idx < len(slot.controls):
            slot.controls[idx].click(timeout=5000)
            return True
    except Exception:
        return False
    return False


def _click_judge(slot: Slot, word: str) -> bool:
    """判断题：对/错 通常也是两个 radio，按文字匹配。"""
    h = slot.handle
    try:
        for lb in h.query_selector_all("label"):
            t = norm(_block_text(lb))
            if word in t:
                lb.click(timeout=5000)
                return True
    except Exception:
        return False
    return False


def _fill_blanks(slot: Slot, values: list[str]) -> int:
    """填空题：按顺序填每个输入框。返回成功填了几个。"""
    n = 0
    for i, ctrl in enumerate(slot.controls):
        if i >= len(values):
            break
        try:
            ctrl.click(timeout=3000)
            ctrl.fill("")
            ctrl.fill(values[i])
            n += 1
            time.sleep(0.15)
        except Exception:
            try:
                ctrl.evaluate("(el, v) => { el.value = v; el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true})); }", values[i])
                n += 1
            except Exception:
                pass
    return n


def _fill_text(slot: Slot, text: str) -> bool:
    if not slot.controls:
        return False
    ctrl = slot.controls[0]
    try:
        ctrl.click(timeout=5000)
        ctrl.fill("")
        ctrl.fill(text)
        return True
    except Exception:
        try:
            ctrl.evaluate("(el, v) => { el.value = v; el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true})); }", text)
            return True
        except Exception:
            return False


def apply(slot: Slot, ans: str | list[str], commit: bool) -> dict:
    """把一条答案应用到一道题上。commit=False 时只检查可行性，不动页面。"""
    if slot.no is None:
        return {"no": None, "ok": False, "why": "没认出题号"}

    if slot.kind == "radio":
        if isinstance(ans, list):
            return {"no": slot.no, "ok": False, "why": "这是单选，答案却给了数组"}
        a = ans.strip()
        if a.upper() in list("ABCDEFGH"):
            return {"no": slot.no, "ok": commit and _click_option(slot, a), "why": f"选 {a.upper()}",
                    "planned": f"选 {a.upper()}"}
        return {"no": slot.no, "ok": commit and _click_judge(slot, a), "why": f"判断 {a}",
                "planned": f"判断 {a}"}

    if slot.kind == "checkbox":
        picks = ans if isinstance(ans, list) else [x.strip() for x in re.split(r"[,，\s]+", ans) if x.strip()]
        done = 0
        if commit:
            for p in picks:
                if _click_option(slot, p):
                    done += 1
                    time.sleep(0.12)
        return {"no": slot.no, "ok": (not commit) or done == len(picks),
                "why": f"多选 {''.join(picks)}", "planned": f"多选 {''.join(picks)}"}

    if slot.kind == "blank":
        vals = ans if isinstance(ans, list) else [ans]
        vals = [str(v) for v in vals]
        n = _fill_blanks(slot, vals) if commit else 0
        return {"no": slot.no, "ok": (not commit) or n == len(vals),
                "why": f"{len(vals)} 空 / 控件 {len(slot.controls)} 个",
                "planned": f"填 {vals}"}

    if slot.kind == "text":
        txt = ans if isinstance(ans, str) else " ".join(ans)
        return {"no": slot.no, "ok": (not commit) or _fill_text(slot, txt),
                "why": f"{len(txt)} 字", "planned": f"填 {len(txt)} 字"}

    return {"no": slot.no, "ok": False, "why": f"未知控件类型（{slot.kind}）"}


# ---------------------------------------------------------------- 主流程

def run(url: str, answers: dict[int, str | list[str]], commit: bool,
        headful: bool, out: str | None, probe: bool = False):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from cxwork import Session  # 复用会话层

    with Session(headless=not headful) as s:
        if not s.is_logged_in():
            print(json.dumps({"ok": False, "error": "未登录，先跑 cxwork.py login"}, ensure_ascii=False))
            return 2
        page = s.goto(url)
        time.sleep(2.0)  # 题目是异步渲染的，多等一会儿

        slots = find_blocks(page)

        if probe:
            report = {
                "ok": len(slots) > 0,
                "mode": "probe",
                "url": page.url,
                "slots_found": len(slots),
                "slots": [
                    {"no": sl.no, "type": sl.qtype, "kind": sl.kind,
                     "controls": len(sl.controls), "stem": sl.stem}
                    for sl in slots
                ],
                "no_number": sum(1 for sl in slots if sl.no is None),
            }
            text = json.dumps(report, ensure_ascii=False, indent=2)
            if out:
                Path(out).write_text(text, encoding="utf-8")
            print(text)
            return 0 if slots else 3

        by_no = {sl.no: sl for sl in slots if sl.no is not None}

        results = []
        for no, ans in sorted(answers.items()):
            slot = by_no.get(no)
            if slot is None:
                results.append({"no": no, "ok": False, "why": "页面上没找到这道题"})
                continue
            results.append(apply(slot, ans, commit))

        matched = sum(1 for r in results if r.get("ok"))
        report = {
            "ok": matched == len(answers) if commit else True,
            "mode": "commit" if commit else "dry-run",
            "url": page.url,
            "slots_found": len(slots),
            "answered": len(answers),
            "applied": matched,
            "details": results,
            "note": "本工具不会点击提交按钮。请自行核对后手动提交。",
        }
        text = json.dumps(report, ensure_ascii=False, indent=2)
        if out:
            Path(out).write_text(text, encoding="utf-8")
            print(f"[ok] 报告写到 {out}", file=sys.stderr)
        print(text)
        return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="把用户提供的答案批量填入超星答题页（不提交）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("probe", help="只看页面结构，能匹配上多少题")
    p.add_argument("url")
    p.add_argument("--headful", action="store_true")
    p.add_argument("-o", "--out")

    p = sub.add_parser("fill", help="实际填写（默认 dry-run）")
    p.add_argument("url")
    p.add_argument("-a", "--answers", required=True, help="答案 JSON")
    p.add_argument("--commit", action="store_true", help="真的填进去，不加只演练")
    p.add_argument("--headful", action="store_true")
    p.add_argument("-o", "--out")

    a = ap.parse_args(argv)

    if a.cmd == "probe":
        return run(a.url, {}, False, a.headful, a.out, probe=True)
    answers = load_answers(a.answers)
    return run(a.url, answers, a.commit, a.headful, a.out)


if __name__ == "__main__":
    raise SystemExit(main())
