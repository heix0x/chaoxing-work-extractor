#!/usr/bin/env python3
"""一键自检 + 装依赖。拿到这个包的人先跑这个。

用法：
    python install.py

它会依次：
1. 检查 Python 版本
2. 安装 requirements.txt 里的依赖
3. 探测本机可用的浏览器（Edge / Chrome）
4. 跑一次冒烟测试
5. 告诉你下一步该干什么
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MIN_PY = (3, 10)

# 常见浏览器安装路径
BROWSER_PATHS = {
    "win32": [
        ("msedge", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        ("msedge", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        ("chrome", r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        ("chrome", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    ],
    "darwin": [
        ("msedge", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        ("chrome", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    ],
}


def say(msg=""):
    print(msg, flush=True)


def ok(msg):
    say(f"  [ok] {msg}")


def warn(msg):
    say(f"  [!]  {msg}")


def fail(msg):
    say(f"  [x]  {msg}")


def check_python() -> bool:
    say(f"[1/5] 检查 Python 版本")
    v = sys.version_info
    if v[:2] >= MIN_PY:
        ok(f"Python {v.major}.{v.minor}.{v.micro}（{sys.executable}）")
        return True
    fail(f"需要 Python {MIN_PY[0]}.{MIN_PY[1]} 或更新，当前是 {v.major}.{v.minor}")
    return False


def install_deps() -> bool:
    say("\n[2/5] 安装依赖")
    req = HERE / "requirements.txt"
    if not req.exists():
        fail(f"找不到 {req}")
        return False
    r = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(req)],
        capture_output=True, text=True,
    )
    if r.returncode == 0:
        ok("playwright / uiautomation 已就绪")
        return True
    fail("pip 安装失败，原始输出：")
    say(r.stdout[-1500:])
    say(r.stderr[-1500:])
    return False


def detect_browser() -> str | None:
    say("\n[3/5] 探测本机浏览器")
    key = sys.platform if sys.platform in BROWSER_PATHS else "win32"
    for channel, path in BROWSER_PATHS.get(key, []):
        if Path(path).exists():
            ok(f"找到 {channel}：{path}")
            return channel
    warn("没找到 Edge 或 Chrome。主通道需要其中之一。")
    warn("去装一个 Edge 就能用：https://www.microsoft.com/edge")
    return None


def smoke_test(channel: str | None) -> bool:
    say("\n[4/5] 冒烟测试")
    sys.path.insert(0, str(HERE / "scripts"))
    try:
        import cx_parser
    except Exception as e:
        fail(f"解析器导入失败：{e}")
        return False

    sample = HERE / "tests" / "sample_linux.txt"
    if not sample.exists():
        warn("没有回归样本，跳过解析测试")
    else:
        data = cx_parser.parse_work_text(sample.read_text(encoding="utf-8"))
        total = data.get("parsed_total") or 0
        secs = len(data.get("sections") or [])
        if total >= 9 and secs >= 4:
            ok(f"解析器正常：{secs} 个章节 / {total} 道题")
        else:
            fail(f"解析器异常：只解析出 {secs} 章节 {total} 题")
            return False

    if channel:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                ctx = pw.chromium.launch_persistent_context(
                    user_data_dir=str(HERE / ".smoke-profile"),
                    channel=channel,
                    headless=True,
                )
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto("about:blank")
                ctx.close()
            ok("Playwright 能启动浏览器")
        except Exception as e:
            fail(f"Playwright 启动失败：{e}")
            return False
        finally:
            import shutil
            shutil.rmtree(HERE / ".smoke-profile", ignore_errors=True)

    return True


def next_steps(channel: str | None):
    say("\n[5/5] 下一步")
    if not channel:
        say("  先装 Edge 或 Chrome，然后重新跑本脚本。")
        return
    py = sys.executable
    say(f"  1) 登录超星（只会弹一次窗，登录完自动退出）：")
    say(f'     "{py}" scripts/cxwork.py login')
    say(f"")
    say(f"  2) 检查登录是否还在：")
    say(f'     "{py}" scripts/cxwork.py check')
    say(f"")
    say(f"  3) 抓一份作业试试：")
    say(f'     "{py}" scripts/cxwork.py run "<作业页URL>" -c "课程名" -o ./out --placeholder')
    say("")
    say("  详细说明看 README.md；出问题先看 references/troubleshooting.md。")


def main():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    say("=" * 56)
    say("  超星作业抓取工具 · 环境自检")
    say(f"  {platform.system()} {platform.release()} · {platform.machine()}")
    say("=" * 56)
    say()

    if not check_python():
        return 1
    if not install_deps():
        return 1
    channel = detect_browser()
    if not smoke_test(channel):
        return 1
    next_steps(channel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
