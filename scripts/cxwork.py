#!/usr/bin/env python3
"""cxwork —— 超星学习通作业页工具（抓取 + 回填）

设计前提：不碰用户正在用的浏览器。
用一个独立的、持久化的 Edge/Chrome profile，登录一次，cookie 常驻，
之后所有操作都由 Playwright 直接读 DOM，不需要抢前台、不需要剪贴板。

用法：
    python cxwork.py login                  # 首次登录（会弹窗，登录完自动退出）
    python cxwork.py check                  # 检查登录态是否还有效
    python cxwork.py fetch <url> -o out/    # 抓一个作业页
    python cxwork.py run <url> -c 课程       # 一条龙：抓 → 解析 → 渲染
    python cxwork.py fill <url> --probe     # 探测答题页结构
    python cxwork.py fill <url> -a ans.json --commit   # 填答案
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

PROFILE_DIR = Path(
    os.environ.get("CXWORK_PROFILE")
    or (Path.home() / ".workbuddy" / "browser-profiles" / "chaoxing")
)
DEFAULT_OUT = Path.cwd() / ".cxwork"

# 登录态旁路存档。Chromium 只把带过期时间的 cookie 写进 profile 的 SQLite，
# 超星的 _uid/UID/uf 是会话 cookie（expires=-1），关浏览器就没了 ——
# 表现为 login 报成功、下一次 check 又变成未登录。所以额外存一份 storage_state。
STATE_FILE = PROFILE_DIR / "state.json"

# 浏览器优先级。别人机器上可能只有 Chrome，所以不能写死 Edge。
# 可以用环境变量 CXWORK_BROWSER 强指定，例如 CXWORK_BROWSER=chrome
BROWSER_ORDER = ("msedge", "chrome", "chromium")

# 超星登录后必然存在的 cookie，用来判断登录态。
# ⚠️ fid 只是学校编号（如 1415），未登录时也有，不能单独作为登录依据。
AUTH_COOKIES = ("_uid", "UID", "uf", "fid")
# 真正代表"已登录"的强凭证，必须命中至少一个
STRONG_COOKIES = ("_uid", "UID", "uf")

# 登录页特征
LOGIN_URL_HINTS = ("passport2", "/login", "passport.chaoxing.com")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0"
)


def eprint(*a):
    print(*a, file=sys.stderr)


# ---------------------------------------------------------------- 会话

class Session:
    """持久化浏览器会话。用 with 语句确保关闭。"""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._pw = None
        self.ctx = None
        self.page = None
        self.channel = None

    def __enter__(self) -> "Session":
        from playwright.sync_api import sync_playwright

        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()

        # 按 msedge → chrome → 自带 chromium 的顺序试，第一个能起来的就用它。
        # 别人机器上不一定装 Edge，写死会直接劝退。
        forced = os.environ.get("CXWORK_BROWSER")
        candidates = (forced,) if forced else BROWSER_ORDER
        last_err = None
        for ch in candidates:
            try:
                self.ctx = self._pw.chromium.launch_persistent_context(
                    user_data_dir=str(PROFILE_DIR),
                    channel=None if ch == "chromium" else ch,
                    headless=self.headless,
                    viewport={"width": 1440, "height": 900},
                    user_agent=UA,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                self.channel = ch
                break
            except Exception as e:
                last_err = e
                continue

        if self.ctx is None:
            self._pw.stop()
            raise RuntimeError(
                "没有可用的浏览器。装了 Edge 或 Chrome 就行，"
                "或者跑 `playwright install chromium` 下载内置内核。"
                f"最后一条错误：{last_err}"
            )

        self.ctx.set_default_timeout(30_000)
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.load_state()
        return self

    def __exit__(self, *exc):
        try:
            self.save_state()
        except Exception:
            pass
        try:
            if self.ctx:
                self.ctx.close()
        finally:
            if self._pw:
                self._pw.stop()
        return False

    # -- 登录态存档 ----------------------------------------------

    def save_state(self):
        """把当前 cookie 存成 storage_state，补 profile 不落盘会话 cookie 的坑。"""
        if self.ctx is None:
            return
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.ctx.storage_state(path=str(STATE_FILE))

    def load_state(self):
        """启动时把上次存的 cookie 灌回去。"""
        if self.ctx is None or not STATE_FILE.exists():
            return
        try:
            st = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return
        cookies = st.get("cookies") or []
        if cookies:
            try:
                self.ctx.add_cookies(cookies)
            except Exception as e:
                eprint(f"[warn] 恢复登录态失败：{e}")

    # -- 登录态 --------------------------------------------------

    def auth_cookies(self) -> dict:
        out = {}
        for c in self.ctx.cookies():
            if c.get("name") in AUTH_COOKIES and c.get("value"):
                out[c["name"]] = c["value"]
        return out

    def is_logged_in(self) -> bool:
        return any(k in self.auth_cookies() for k in STRONG_COOKIES)

    def goto(self, url: str, wait_selector: str | None = None, timeout: int = 45_000):
        """打开页面并尽量等到内容渲染完。"""
        self.page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        # 超星的题目是异步渲染的，networkidle 比 load 可靠
        try:
            self.page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass
        if wait_selector:
            try:
                self.page.wait_for_selector(wait_selector, timeout=15_000)
            except Exception:
                eprint(f"[warn] 等待选择器超时：{wait_selector}")
        return self.page


# ---------------------------------------------------------------- 抓取

def extract_page(page) -> dict:
    """从一个已加载的页面抽三样东西：URL、纯文本、HTML。

    纯文本给解析器用，HTML 留作坏样本排查。
    """
    text = page.inner_text("body")
    html = page.content()
    return {
        "url": page.url,
        "title": page.title(),
        "text": text,
        "html": html,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def cmd_login(args):
    """打开登录页，轮询等待用户登录，登录成功后 profile 自动带上 cookie。"""
    eprint("正在打开专用浏览器，请在其中登录超星（学校统一身份认证）。")
    eprint(f"登录成功会自动检测并退出，最多等 {args.wait} 秒。\n")
    eprint("注意：这个浏览器是独立的，和日常用的浏览器互不影响，")
    eprint("      登录态只存在它自己的 profile 里。\n")

    with Session(headless=False) as s:
        s.goto("https://mooc1.chaoxing.com/")
        deadline = time.time() + args.wait
        last_note = 0
        while time.time() < deadline:
            if s.is_logged_in():
                cookies = s.auth_cookies()
                s.save_state()
                eprint(f"\n[ok] 登录态已保存，关键 cookie：{', '.join(cookies)}")
                eprint(f"[ok] profile 目录：{PROFILE_DIR}")
                print(json.dumps({"logged_in": True, "cookies": list(cookies)}, ensure_ascii=False))
                return 0
            if time.time() - last_note > 15:
                left = int(deadline - time.time())
                eprint(f"  …等待登录中，还剩 {left} 秒")
                last_note = time.time()
            time.sleep(3)

        eprint("\n[!!] 超时，没检测到登录 cookie。")
        eprint("     可能是登录没完成，或者超星改了 cookie 名（检查 AUTH_COOKIES）。")
        return 2


def cmd_check(args):
    with Session(headless=not args.headful) as s:
        if s.is_logged_in():
            cookies = s.auth_cookies()
            print(json.dumps({"logged_in": True, "cookies": list(cookies)}, ensure_ascii=False))
            return 0
        print(json.dumps({"logged_in": False, "cookies": []}, ensure_ascii=False))
        return 1


def cmd_fetch(args):
    out_dir = Path(args.out) if args.out else DEFAULT_OUT
    out_dir.mkdir(parents=True, exist_ok=True)

    with Session(headless=not args.headful) as s:
        if not s.is_logged_in():
            eprint("[!!] 未登录。先跑：python cxwork.py login")
            return 2
        page = s.goto(args.url)
        data = extract_page(page)

    # 文件名：优先用页面标题，去掉非法字符
    stem = re.sub(r'[\\/:*?"<>|\s]+', "_", (data["title"] or "page"))[:60]
    if not stem.strip("_"):
        stem = "page"

    txt_path = out_dir / f"{stem}.txt"
    html_path = out_dir / f"{stem}.html"
    meta_path = out_dir / f"{stem}.meta.json"

    txt_path.write_text(data["text"], encoding="utf-8")
    html_path.write_text(data["html"], encoding="utf-8")
    meta_path.write_text(
        json.dumps({k: v for k, v in data.items() if k != "html"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(json.dumps({
        "ok": True,
        "text": str(txt_path),
        "html": str(html_path),
        "meta": str(meta_path),
        "chars": len(data["text"]),
    }, ensure_ascii=False, indent=2))
    return 0


# ---------------------------------------------------------------- 流水线

def cmd_parse(args):
    from cx_parser import parse_work_text

    out_dir = Path(args.out) if args.out else DEFAULT_OUT
    out_dir.mkdir(parents=True, exist_ok=True)

    raw = sys.stdin.read() if args.txt == "-" else Path(args.txt).read_text(encoding="utf-8")
    data = parse_work_text(raw)
    stem = args.name or re.sub(r'[\\/:*?"<>|\s]+', "_", data.get("title") or "work")[:60]

    jp = out_dir / f"{stem}.json"
    jp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "ok": True,
        "json": str(jp),
        "title": data.get("title"),
        "questions": data.get("parsed_total"),
        "declared": data["meta"].get("total_questions"),
        "warnings": data.get("warnings", []),
    }, ensure_ascii=False, indent=2))

    # 有警告就以非零码退出，方便上游判断"抓全了没有"
    return 0 if not data.get("warnings") else 3


def cmd_render(args):
    from cx_render import render

    data = json.loads(Path(args.json).read_text(encoding="utf-8"))
    answers = json.loads(Path(args.answers).read_text(encoding="utf-8")) if args.answers else None

    md = render(data, answers, args.course, args.placeholder)

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(md, encoding="utf-8")
        print(json.dumps({"ok": True, "markdown": args.out, "chars": len(md)}, ensure_ascii=False))
    else:
        print(md)
    return 0


def cmd_run(args):
    """一条龙：抓页面 → 解析 → 渲染。答案文件可选。"""
    from cx_parser import parse_work_text
    from cx_render import render

    out_dir = Path(args.out) if args.out else DEFAULT_OUT
    out_dir.mkdir(parents=True, exist_ok=True)

    with Session(headless=not args.headful) as s:
        if not s.is_logged_in():
            eprint("[!!] 未登录。先跑：python cxwork.py login")
            return 2
        page = s.goto(args.url)
        page_data = extract_page(page)

    stem = re.sub(r'[\\/:*?"<>|\s]+', "_", (page_data["title"] or "work"))[:60] or "work"
    (out_dir / f"{stem}.txt").write_text(page_data["text"], encoding="utf-8")
    (out_dir / f"{stem}.html").write_text(page_data["html"], encoding="utf-8")

    parsed = parse_work_text(page_data["text"])
    jp = out_dir / f"{stem}.json"
    jp.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")

    answers = None
    if args.answers:
        answers = json.loads(Path(args.answers).read_text(encoding="utf-8"))
    md = render(parsed, answers, args.course, args.placeholder)
    mp = out_dir / f"{stem}.md"
    mp.write_text(md, encoding="utf-8")

    print(json.dumps({
        "ok": True,
        "title": parsed.get("title"),
        "questions": parsed.get("parsed_total"),
        "declared": parsed["meta"].get("total_questions"),
        "raw_text": str(out_dir / f"{stem}.txt"),
        "json": str(jp),
        "markdown": str(mp),
        "warnings": parsed.get("warnings", []),
    }, ensure_ascii=False, indent=2))
    return 0 if not parsed.get("warnings") else 3


# ---------------------------------------------------------------- 填写

def cmd_fill(args):
    """把答案文件的内容填进答题页。"""
    from cx_fill import load_answers, run

    if args.probe:
        return run(args.url, {}, False, args.headful, args.out, probe=True)

    if not args.answers:
        eprint("[!!] 需要 -a answers.json。只想看页面结构就跑 --probe。")
        return 2
    answers = load_answers(args.answers)
    if not answers:
        eprint("[!!] 答案文件是空的。")
        return 2
    return run(args.url, answers, args.commit, args.headful, args.out)


# ---------------------------------------------------------------- CLI

def main(argv=None):
    p = argparse.ArgumentParser(prog="cxwork", description="超星作业页抓取工具")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("login", help="首次登录，保存登录态")
    sp.add_argument("--wait", type=int, default=300, help="等待登录的秒数，默认 300")
    sp.set_defaults(func=cmd_login)

    sp = sub.add_parser("check", help="检查登录态")
    sp.add_argument("--headful", action="store_true", help="显示浏览器窗口")
    sp.set_defaults(func=cmd_check)

    sp = sub.add_parser("fetch", help="抓取一个页面，输出 txt/html/meta")
    sp.add_argument("url")
    sp.add_argument("-o", "--out", help="输出目录")
    sp.add_argument("--headful", action="store_true", help="显示浏览器窗口（排错用）")
    sp.set_defaults(func=cmd_fetch)

    sp = sub.add_parser("parse", help="纯文本 → 结构化 JSON")
    sp.add_argument("txt", help="文本文件；传 - 从 stdin 读")
    sp.add_argument("-o", "--out", help="输出目录")
    sp.add_argument("--name", help="输出文件名（不含扩展名）")
    sp.set_defaults(func=cmd_parse)

    sp = sub.add_parser("render", help="结构化 JSON → Markdown")
    sp.add_argument("json")
    sp.add_argument("-a", "--answers", help="答案 JSON")
    sp.add_argument("-c", "--course", help="课程名")
    sp.add_argument("-o", "--out", help="输出 Markdown 路径")
    sp.add_argument("--placeholder", action="store_true", help="没答案时留占位")
    sp.set_defaults(func=cmd_render)

    sp = sub.add_parser("run", help="一条龙：抓取 → 解析 → 渲染")
    sp.add_argument("url")
    sp.add_argument("-o", "--out", help="输出目录")
    sp.add_argument("-a", "--answers", help="答案 JSON")
    sp.add_argument("-c", "--course", help="课程名")
    sp.add_argument("--placeholder", action="store_true", help="没答案时留占位")
    sp.add_argument("--headful", action="store_true", help="显示浏览器窗口")
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("fill", help="把答案填入答题页（默认演练）")
    sp.add_argument("url")
    sp.add_argument("-a", "--answers", help="答案 JSON")
    sp.add_argument("--probe", action="store_true", help="只探测页面结构，能匹配上几题")
    sp.add_argument("--commit", action="store_true", help="真的填进去（不加只演练）")
    sp.add_argument("--headful", action="store_true", help="显示浏览器窗口")
    sp.add_argument("-o", "--out", help="报告输出路径")
    sp.set_defaults(func=cmd_fill)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
