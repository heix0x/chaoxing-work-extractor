#!/usr/bin/env python3
"""重载核对：重新打开答题页，逐题读回已保存的作答。

超星只在页面加载时读一次作答数据，所以「填完看着是有的」不等于「存住了」。
本模块用全新会话重新加载页面，检查每题的隐藏域 `#answer{qid}`、选中项、
以及 UEditor 富文本内容，产出可用于核对的报告。

用法：
    python cxwork.py verify "<答题页URL>" -o 核对.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

JS_VERIFY = r"""() => {
  const clean = t => (t || '').replace(/\s+/g, ' ').trim();
  return [...document.querySelectorAll('.questionLi')].map((q, idx) => {
    const qid = (q.id || '').replace('question', '');
    const h3 = q.querySelector('h3');
    const m = h3 ? /^\s*(\d{1,3})/.exec(h3.textContent) : null;
    const ansEl = document.getElementById('answer' + qid);
    const value = ansEl ? (ansEl.value || '') : '';
    const editors = [...q.querySelectorAll("iframe[id^='ueditor_']")].map(f => {
      try {
        return clean(f.contentDocument.querySelector('body').innerText);
      } catch (e) { return ''; }
    });
    const picked = [...q.querySelectorAll('.answerBg')]
      .filter(d => d.getAttribute('aria-checked') === 'true' ||
                   d.querySelector('.check_answer, .check_answer_dx'))
      .map(d => {
        const s = d.querySelector('span[data]');
        return s ? s.getAttribute('data') : '';
      });
    const filled = !!(value || editors.some(t => t) || picked.length);
    return {
      no: m ? parseInt(m[1], 10) : idx + 1,
      type: q.getAttribute('typename') || '',
      qid: qid,
      value: value,
      picked: picked,
      editors: editors,
      filled: filled
    };
  });
}"""


def verify_report(url: str, headful: bool = False) -> dict:
    """重载页面，返回核对报告（不打印、不写文件）。

    给 `fill --commit --save` 收尾时自动调用，也供 verify 子命令复用。
    每次自己开一个 Session：调用方填答案的那个浏览器必须先关掉，
    否则同一个 profile 会被占住（Chromium 的 ProcessSingleton 会直接拒绝）。
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from cxwork import Session

    with Session(headless=not headful) as s:
        if not s.is_logged_in():
            raise RuntimeError("未登录，先跑 cxwork.py login")
        page = s.goto(url)
        time.sleep(3.0)   # UEditor 是异步初始化的，多等一会儿
        items = page.evaluate(JS_VERIFY)
        final_url = page.url

    filled = sum(1 for it in items if it["filled"])
    return {
        "ok": filled == len(items) and len(items) > 0,
        "url": final_url,
        "questions": len(items),
        "filled": filled,
        "empty": [it["no"] for it in items if not it["filled"]],
        "items": items,
        "note": "本工具只读，不点击提交按钮。若页面仍显示空白，按 Ctrl+F5 强制刷新。",
    }


def verify(url: str, out: str | None = None, headful: bool = False) -> int:
    try:
        report = verify_report(url, headful)
    except RuntimeError as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        return 2
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if out:
        Path(out).write_text(text, encoding="utf-8")
        print(f"[ok] 核对报告 -> {out}", file=sys.stderr)
        print(json.dumps({k: v for k, v in report.items() if k != "items"},
                         ensure_ascii=False, indent=2))
    else:
        print(text)
    return 0 if report["ok"] else 3


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="重载核对答题页已保存的作答")
    ap.add_argument("url")
    ap.add_argument("-o", "--out")
    ap.add_argument("--headful", action="store_true")
    a = ap.parse_args()
    raise SystemExit(verify(a.url, a.out, a.headful))
