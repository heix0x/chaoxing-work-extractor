#!/usr/bin/env python3
"""运行前依赖自检 / 自愈。

管理型 Python 升级时（实测 3.13.12 → 3.13.14）site-packages 会被清空，
playwright 随之消失。旧行为是任何命令都抛裸 ModuleNotFoundError，
使用者得自己猜「原来要重跑 install.py」。这里把这一步自动化。

行为：
  - 能 import playwright.sync_api  → 直接通过
  - 缺失且允许自动安装           → 用当前解释器 pip install -r requirements.txt，再验一次
  - 设 CXWORK_NO_AUTOINSTALL=1    → 只打印明确指引，不联网
"""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

HINT = "[!!] 缺少 playwright。用当前解释器重跑一次安装即可：\n" \
       '     "{py}" "{install}"\n' \
       '     或： "{py}" -m pip install -r "{req}"'


def _playwright_ok() -> bool:
    try:
        importlib.invalidate_caches()
        importlib.import_module("playwright.sync_api")
        return True
    except Exception:
        return False


def ensure_deps(auto_install: bool | None = None) -> bool:
    """返回 True 表示依赖就绪；False 表示已打印指引、调用方应退出码 2。"""
    if _playwright_ok():
        return True

    if auto_install is None:
        auto_install = os.environ.get("CXWORK_NO_AUTOINSTALL") != "1"

    here = Path(__file__).resolve().parent
    req = here.parent / "requirements.txt"
    install_py = here.parent / "install.py"

    if auto_install and req.exists():
        print("[deps] playwright 缺失，正在自动安装依赖…", file=sys.stderr)
        try:
            r = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", str(req)],
                capture_output=True, text=True, timeout=180,
            )
        except Exception as e:
            print(f"[deps] 自动安装失败：{e}", file=sys.stderr)
        else:
            if r.returncode == 0 and _playwright_ok():
                print("[deps] 依赖已就绪", file=sys.stderr)
                return True
            print("[deps] 自动安装未成功：" + (r.stdout + r.stderr)[-600:], file=sys.stderr)

    print(HINT.format(py=sys.executable, install=install_py, req=req), file=sys.stderr)
    return False


if __name__ == "__main__":
    raise SystemExit(0 if ensure_deps() else 2)
