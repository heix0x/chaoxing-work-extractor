#!/usr/bin/env python3
"""兜底通道：操作**用户已经打开**的 Edge 浏览器，把某个标签页的全文抓下来。

什么时候用：主通道（专用 profile + Playwright）不可用 —— profile 被踢、页面在 iframe 里
抓不到、或者用户根本不想登录第二次。

代价（必须在用之前知道）：
- 会抢前台，用户那几秒的焦点会被切走
- 会覆盖剪贴板
- 只能拿到「已渲染的纯文本」，未渲染/懒加载的内容拿不到
- 后台标签读不到，必须切过去

安全约束：**发键盘事件前必须断言目标窗口已是前台**。做不到就中止，
绝不允许把 Ctrl+A / Ctrl+C 打进别的程序（这个坑真踩过，会全选用户正在编辑的文档）。

用法：
    python cx_fallback.py list                      # 列出所有 Edge 标签
    python cx_fallback.py dump --tab 作业作答         # 抓标签名包含该串的页
    python cx_fallback.py dump --index 3            # 或按序号
"""
from __future__ import annotations

import argparse
import ctypes
import json
import sys
import time
from ctypes import wintypes

u32 = ctypes.windll.user32
k32 = ctypes.windll.kernel32

u32.GetForegroundWindow.restype = ctypes.c_void_p
u32.SwitchToThisWindow.argtypes = [ctypes.c_void_p, ctypes.c_bool]
u32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
u32.SetForegroundWindow.restype = ctypes.c_bool
u32.IsIconic.argtypes = [ctypes.c_void_p]
u32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
u32.OpenClipboard.argtypes = [ctypes.c_void_p]
u32.GetClipboardData.argtypes = [ctypes.c_uint]
u32.GetClipboardData.restype = ctypes.c_void_p
k32.GlobalLock.argtypes = [ctypes.c_void_p]
k32.GlobalLock.restype = ctypes.c_void_p
k32.GlobalUnlock.argtypes = [ctypes.c_void_p]

CF_UNICODETEXT = 13


def eprint(*a):
    print(*a, file=sys.stderr)


def read_clipboard(retries: int = 5):
    for _ in range(retries):
        if u32.OpenClipboard(None):
            try:
                h = u32.GetClipboardData(CF_UNICODETEXT)
                if h:
                    p = k32.GlobalLock(h)
                    try:
                        return ctypes.wstring_at(p)
                    finally:
                        k32.GlobalUnlock(h)
            finally:
                u32.CloseClipboard()
        time.sleep(0.2)
    return None


def edge_windows():
    """所有 Edge 顶层窗口。用 uiautomation 枚举，比 EnumWindows 干净。"""
    import uiautomation as auto

    auto.SetGlobalSearchTimeout(10)
    out = []
    for w in auto.GetRootControl().GetChildren():
        try:
            if w.ClassName == "Chrome_WidgetWin_1" and "Edge" in (w.Name or ""):
                out.append(w)
        except Exception:
            pass
    return out


def _walk_tabs(win):
    import uiautomation as auto

    tabs = []

    def walk(c, d=0, maxd=10):
        if d > maxd:
            return
        try:
            kids = c.GetChildren()
        except Exception:
            return
        for k in kids:
            try:
                if k.ControlTypeName == "TabItemControl":
                    tabs.append(k)
                walk(k, d + 1, maxd)
            except Exception:
                pass

    walk(win)
    return tabs


def _find_document(win, min_len=200):
    """当前激活标签的文档（len 最大的那个）。"""
    import uiautomation as auto

    docs = []

    def walk(c, d=0, maxd=12):
        if d > maxd:
            return
        try:
            kids = c.GetChildren()
        except Exception:
            return
        for k in kids:
            try:
                if k.ControlTypeName == "DocumentControl":
                    docs.append(k)
                walk(k, d + 1, maxd)
            except Exception:
                pass

    walk(win)

    best, best_len = None, 0
    for doc in docs:
        try:
            p = doc.GetPattern(auto.PatternId.TextPattern)
            n = len(p.DocumentRange.GetText(-1)) if p else 0
            if n > best_len:
                best, best_len = doc, n
        except Exception:
            pass
    return (best, best_len) if best_len >= min_len else (None, best_len)


def cmd_list(args):
    rows = []
    for win in edge_windows():
        for i, tab in enumerate(_walk_tabs(win)):
            rows.append({
                "window": win.NativeWindowHandle,
                "index": i,
                "name": tab.Name,
            })
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


def cmd_dump(args):
    import uiautomation as auto

    prev_fg = u32.GetForegroundWindow()
    targets = []

    for win in edge_windows():
        tabs = _walk_tabs(win)
        for i, tab in enumerate(tabs):
            name = tab.Name or ""
            if args.tab and args.tab in name:
                targets.append((win, tab, i, name))
            elif args.index is not None and i == args.index:
                targets.append((win, tab, i, name))

    if not targets:
        eprint("[!!] 没找到匹配的标签页。先跑 list 看看有哪些。")
        return 2

    results = []
    for win, tab, idx, name in targets:
        hwnd = win.NativeWindowHandle

        # 抢前台
        if u32.IsIconic(hwnd):
            u32.ShowWindow(hwnd, 9)
        u32.SwitchToThisWindow(ctypes.c_void_p(hwnd), True)
        time.sleep(0.8)

        # ⚠️ 硬断言：抢不到前台就绝不发键盘
        if u32.GetForegroundWindow() != hwnd:
            eprint(f"[!!] 抢前台失败（{name!r}），已中止，未发送任何键盘事件。")
            return 4

        # 切标签
        try:
            p = tab.GetPattern(auto.PatternId.SelectionItemPattern)
            p.Select()
        except Exception as e:
            eprint(f"[warn] 切标签失败：{e}")
        time.sleep(2.0)

        doc, n = _find_document(win)
        if doc is None:
            eprint(f"[!!] {name!r} 读不到文档（只拿到 {n} 字符），跳过。")
            continue

        try:
            doc.SetFocus()
        except Exception:
            pass
        time.sleep(0.3)

        # 再断言一次，防止 SetFocus 把焦点挪走
        if u32.GetForegroundWindow() != hwnd:
            eprint("[!!] 发键前前台已变化，已中止。")
            return 4

        auto.SendKeys("{Ctrl}a")
        time.sleep(0.4)
        auto.SendKeys("{Ctrl}c")
        time.sleep(1.0)

        txt = read_clipboard()
        results.append({"tab": name, "chars": len(txt or ""), "text": txt or ""})

    # 还原前台
    if prev_fg:
        u32.SwitchToThisWindow(ctypes.c_void_p(prev_fg), True)
        time.sleep(0.3)

    print(json.dumps(
        [{k: v for k, v in r.items() if k != "text"} for r in results],
        ensure_ascii=False, indent=2,
    ))
    if args.out and results:
        from pathlib import Path
        for r in results:
            safe = "".join(ch for ch in r["tab"] if ch.isalnum() or ch in " _-")[:40].strip() or "tab"
            p = Path(args.out) / f"{safe}.txt"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(r["text"], encoding="utf-8")
            eprint(f"[ok] {p} · {r['chars']} 字符")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="兜底：抓取用户已打开浏览器里的页面文本")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("list", help="列出 Edge 所有标签")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("dump", help="抓取标签页全文")
    s.add_argument("--tab", help="标签名包含这个字符串就抓")
    s.add_argument("--index", type=int, help="按序号抓（配合 list 用）")
    s.add_argument("-o", "--out", help="输出目录")
    s.set_defaults(func=cmd_dump)

    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
