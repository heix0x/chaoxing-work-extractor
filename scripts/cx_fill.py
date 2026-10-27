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
      "21": "终端是……控制台是……"          # 简答/操作/案例：一整段文本
    }

也兼容 {"1": {"answer": "B", "explain": "..."}} 这种格式。

支持两种页面形态：
  ① 老版：input[type=radio] / input[type=checkbox] / input[type=text]
  ② 新版（2025+）：div.answerBg 点击式选项 + UEditor 富文本（填空/简答/案例）
     新版选项点中后把值写到 #answer{qid}，判断题的值是 true/false 而非 A/B；
     富文本每题对应 textarea[name=answerEditor{qid}]，填空则是 answerEditor{qid}{n}。
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

# 新版：点击式选项 + UEditor
CHOICE_BG = ".answerBg"
UE_TEXTAREA = "textarea[name^='answerEditor']"


@dataclass
class Slot:
    """页面上的一道题。"""
    no: int | None = None
    qtype: str = ""
    stem: str = ""
    handle: object = None          # Playwright ElementHandle
    kind: str = "unknown"          # radio/checkbox/blank/text/choice/choice_multi
    controls: list = field(default_factory=list)
    qid: str = ""


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
        controls = page.query_selector_all(f"{INPUT_RADIO}, {INPUT_CHECK}, {INPUT_TEXT}, {TEXTAREA}, {CHOICE_BG}")
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
    """判断这道题该用哪种控件填。老版控件优先，其次才是新版点击式/富文本。"""
    h = s.handle
    if h is None:
        s.kind = "unknown"
        return
    s.qid = h.get_attribute("data") or h.get_attribute("id") or ""
    s.qid = re.sub(r"^question", "", s.qid)
    try:
        if h.query_selector(INPUT_RADIO):
            s.kind = "radio"
            s.controls = h.query_selector_all(INPUT_RADIO)
        elif h.query_selector(INPUT_CHECK):
            s.kind = "checkbox"
            s.controls = h.query_selector_all(INPUT_CHECK)
        elif h.query_selector(CHOICE_BG):
            # 新版点击式选项：qtype=1 是多选，其余按单选处理
            bgs = h.query_selector_all(CHOICE_BG)
            qt = bgs[0].get_attribute("qtype") or ""
            s.kind = "choice_multi" if qt == "1" else "choice"
            s.controls = bgs
        elif h.query_selector(UE_TEXTAREA):
            tes = h.query_selector_all(UE_TEXTAREA)
            s.controls = tes
            s.kind = "blank" if "填空" in s.qtype else "text"
        elif h.query_selector(TEXTAREA) or h.query_selector(EDITABLE):
            s.kind = "text"
            s.controls = h.query_selector_all(f"{TEXTAREA}, {EDITABLE}")
        elif h.query_selector(INPUT_TEXT):
            s.kind = "blank"
            s.controls = h.query_selector_all(INPUT_TEXT)
        else:
            s.kind = "unknown"
    except Exception:
        s.kind = "unknown"


# ---------------------------------------------------------------- 新版：点击式选项

def _choice_letter(bg) -> str:
    try:
        return (bg.evaluate("el => { const s = el.querySelector('span[data]'); return s ? s.getAttribute('data') : ''; }") or "")
    except Exception:
        return ""


def _click_choice(slot: Slot, letter: str, page) -> bool:
    """点 div.answerBg。新版选项不认 setting checked，只能真点。"""
    letter = letter.strip().upper()
    try:
        for bg in slot.controls:
            data = _choice_letter(bg)
            if data.upper() == letter:
                bg.scroll_into_view_if_needed()
                bg.click(timeout=5000)
                return True
        # 兜底：按 aria-label 前缀匹配（"A 功能模型……"）
        for bg in slot.controls:
            lbl = bg.get_attribute("aria-label") or ""
            if lbl.strip().upper().startswith(letter + " "):
                bg.click(timeout=5000)
                return True
    except Exception:
        return False
    return False


def _click_judge_new(slot: Slot, word: str) -> bool:
    """新版判断题：选项文字的 data 是 true/false，按文字点。"""
    want = "true" if word.strip() in ("对", "正确", "T", "true") else "false"
    try:
        for bg in slot.controls:
            if _choice_letter(bg).lower() == want:
                bg.click(timeout=5000)
                return True
    except Exception:
        return False
    return False


def _read_choice(slot: Slot, page) -> str:
    """回读 #answer{qid}，确认真的写进去了。"""
    try:
        return page.evaluate(
            "q => { const el = document.getElementById('answer' + q); return el ? el.value : ''; }",
            slot.qid,
        ) or ""
    except Exception:
        return ""


# ---------------------------------------------------------------- 新版：UEditor

def _to_html(text: str) -> str:
    """纯文本转成编辑器里的 HTML。保守处理：一行一个 <p>，空行用 <p><br></p>。"""
    lines = (text or "").replace("\r\n", "\n").split("\n")
    out = []
    for ln in lines:
        ln = ln.strip()
        out.append("<p>" + (ln if ln else "<br>") + "</p>")
    return "".join(out)


def _set_ue(page, textarea, text: str) -> bool:
    """往这个 textarea 所属的 UEditor 实例里写内容，并回写 textarea。"""
    html = _to_html(text)
    try:
        key = textarea.evaluate("""el => {
            // textarea 是编辑器的兄弟节点（在 .textDIV / .eidtDiv 里），
            // 不在 .edui-editor 内部，所以往上找几层容器再取 iframe。
            let p = el.parentElement;
            for (let i = 0; i < 4 && p; i++) {
                const f = p.querySelector("iframe[id^='ueditor_']");
                if (f) {
                    const m = /ueditor_(\\d+)/.exec(f.id);
                    return m ? ('ueditorInstant' + m[1]) : null;
                }
                p = p.parentElement;
            }
            return null;
        }""")
    except Exception:
        key = None

    ok = False
    if key:
        try:
            ok = bool(page.evaluate(
                """([k, html]) => {
                    const e = window.UE && UE.instants && UE.instants[k];
                    if (!e) return false;
                    e.setContent(html);
                    try { e.sync(); } catch (_) {}
                    return true;
                }""",
                [key, html],
            ))
        except Exception:
            ok = False

    # 无论走没走编辑器，都把 textarea 的值写进去兜底
    try:
        textarea.evaluate(
            """(el, t) => {
                el.value = t;
                el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
            }""",
            text,
        )
    except Exception:
        pass
    return ok


def _fill_blanks_ue(page, slot: Slot, values: list[str]) -> int:
    n = 0
    for i, ta in enumerate(slot.controls):
        if i >= len(values):
            break
        if _set_ue(page, ta, values[i]):
            n += 1
        time.sleep(0.2)
    return n


def _fill_text_ue(page, slot: Slot, text: str) -> bool:
    if not slot.controls:
        return False
    return _set_ue(page, slot.controls[0], text)


# ---------------------------------------------------------------- 老版控件

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
    """填空题（老版 input）：按顺序填每个输入框。返回成功填了几个。"""
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


# ---------------------------------------------------------------- 应用一条答案

def apply(slot: Slot, ans: str | list[str], commit: bool, page=None) -> dict:
    """把一条答案应用到一道题上。commit=False 时只检查可行性，不动页面。"""
    if slot.no is None:
        return {"no": None, "ok": False, "why": "没认出题号"}

    # --- 新版点击式选项（单选） ---
    if slot.kind == "choice":
        if isinstance(ans, list):
            return {"no": slot.no, "ok": False, "why": "这是单选，答案却给了数组"}
        a = ans.strip()
        if a.upper() in list("ABCDEFGH"):
            if not commit:
                return {"no": slot.no, "ok": True, "planned": f"选 {a.upper()}"}
            before = _read_choice(slot, page)
            # 已经是这个答案就不再点：新版选项是"点一下切换"，重复点会把答案取消
            if before.strip().upper() == a.upper():
                return {"no": slot.no, "ok": True, "planned": f"选 {a.upper()}",
                        "readback": before, "skipped": "已经是这个答案"}
            ok = _click_choice(slot, a, page)
            time.sleep(0.35)
            got = _read_choice(slot, page)
            return {"no": slot.no, "ok": bool(ok) and a.upper() in got,
                    "planned": f"选 {a.upper()}", "readback": got, "before": before}
        if not commit:
            return {"no": slot.no, "ok": True, "planned": f"判断 {a}"}
        want = "true" if a in ("对", "正确") else "false"
        got0 = _read_choice(slot, page)
        if got0.strip().lower() == want:
            return {"no": slot.no, "ok": True, "planned": f"判断 {a}",
                    "readback": got0, "skipped": "已经是这个答案"}
        ok = _click_judge_new(slot, a)
        time.sleep(0.35)
        got = _read_choice(slot, page)
        return {"no": slot.no, "ok": bool(ok) and got.lower() == want,
                "planned": f"判断 {a}", "readback": got}

    # --- 新版点击式选项（多选） ---
    if slot.kind == "choice_multi":
        picks = ans if isinstance(ans, list) else [x.strip() for x in re.split(r"[,，\s]+", ans) if x.strip()]
        picks = [p.upper() for p in picks]
        if not commit:
            return {"no": slot.no, "ok": True, "planned": f"多选 {''.join(picks)}"}
        got0 = _read_choice(slot, page)
        if sorted(got0.upper()) == sorted(picks):
            return {"no": slot.no, "ok": True, "planned": f"多选 {''.join(picks)}",
                    "readback": got0, "skipped": "已经是这个答案"}
        done = 0
        for p in picks:
            if _click_choice(slot, p, page):
                done += 1
                time.sleep(0.25)
        time.sleep(0.3)
        got = _read_choice(slot, page)
        return {"no": slot.no, "ok": done == len(picks) and all(p in got for p in picks),
                "planned": f"多选 {''.join(picks)}", "readback": got}

    # --- 老版单选（radio） ---
    if slot.kind == "radio":
        if isinstance(ans, list):
            return {"no": slot.no, "ok": False, "why": "这是单选，答案却给了数组"}
        a = ans.strip()
        if a.upper() in list("ABCDEFGH"):
            return {"no": slot.no, "ok": commit and _click_option(slot, a), "why": f"选 {a.upper()}",
                    "planned": f"选 {a.upper()}"}
        return {"no": slot.no, "ok": commit and _click_judge(slot, a), "why": f"判断 {a}",
                "planned": f"判断 {a}"}

    # --- 老版多选（checkbox） ---
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

    # --- 填空 ---
    if slot.kind == "blank":
        vals = ans if isinstance(ans, list) else [ans]
        vals = [str(v) for v in vals]
        if page is not None and slot.controls and slot.controls[0].evaluate("el => el.tagName") == "TEXTAREA":
            n = _fill_blanks_ue(page, slot, vals) if commit else 0
        else:
            n = _fill_blanks(slot, vals) if commit else 0
        return {"no": slot.no, "ok": (not commit) or n == len(vals),
                "why": f"{len(vals)} 空 / 控件 {len(slot.controls)} 个",
                "planned": f"填 {vals}"}

    # --- 简答/操作/案例 ---
    if slot.kind == "text":
        txt = ans if isinstance(ans, str) else " ".join(ans)
        is_ue = False
        if slot.controls:
            try:
                is_ue = slot.controls[0].evaluate("el => el.tagName") == "TEXTAREA"
            except Exception:
                is_ue = False
        if is_ue and page is not None:
            ok = _fill_text_ue(page, slot, txt) if commit else True
        else:
            ok = _fill_text(slot, txt) if commit else True
        return {"no": slot.no, "ok": ok, "why": f"{len(txt)} 字", "planned": f"填 {len(txt)} 字"}

    return {"no": slot.no, "ok": False, "why": f"未知控件类型（{slot.kind}）"}


# ---------------------------------------------------------------- 主流程

def run(url: str, answers: dict[int, str | list[str]], commit: bool,
        headful: bool, out: str | None, probe: bool = False, save: bool = False):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from cxwork import Session  # 复用会话层

    with Session(headless=not headful) as s:
        if not s.is_logged_in():
            print(json.dumps({"ok": False, "error": "未登录，先跑 cxwork.py login"}, ensure_ascii=False))
            return 2
        page = s.goto(url)
        time.sleep(2.5)  # 题目是异步渲染的，多等一会儿

        slots = find_blocks(page)

        if probe:
            report = {
                "ok": len(slots) > 0,
                "mode": "probe",
                "url": page.url,
                "slots_found": len(slots),
                "slots": [
                    {"no": sl.no, "type": sl.qtype, "kind": sl.kind,
                     "controls": len(sl.controls), "qid": sl.qid, "stem": sl.stem}
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
            results.append(apply(slot, ans, commit, page))
            time.sleep(0.25)

        matched = sum(1 for r in results if r.get("ok"))

        # 超星答题页不会自动暂存：不调 saveWork()，刷新后作答全部丢失。
        # 注意：saveWork 是"暂时保存"，页面上的"提交"走的是 submitValidate，绝不调用。
        saved = None
        if commit and save:
            try:
                page.evaluate("() => { if (typeof saveWork === 'function') { saveWork(); return true; } return false; }")
                time.sleep(5.0)   # 等它把 ajax 发完
                saved = True
            except Exception as e:
                saved = f"失败：{e}"

        report = {
            "ok": matched == len(answers) if commit else True,
            "mode": "commit" if commit else "dry-run",
            "url": page.url,
            "slots_found": len(slots),
            "answered": len(answers),
            "applied": matched,
            "saved": saved,
            "details": results,
            "note": "填完后按 Ctrl+F5 强制刷新页面，答案才会显示（超星只在页面加载时读一次作答数据）。"
                    "本工具不会点击提交按钮，请自行核对后手动提交。",
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
    p.add_argument("--save", action="store_true",
                   help="填完调 saveWork() 做『暂时保存』（不是提交）。不加则只在页面上填，刷新即丢")
    p.add_argument("--headful", action="store_true")
    p.add_argument("-o", "--out")

    a = ap.parse_args(argv)

    if a.cmd == "probe":
        return run(a.url, {}, False, a.headful, a.out, probe=True)
    answers = load_answers(a.answers)
    return run(a.url, answers, a.commit, a.headful, a.out, save=getattr(a, "save", False))


if __name__ == "__main__":
    raise SystemExit(main())
