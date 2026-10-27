#!/usr/bin/env python3
"""把整个工具打成一个 zip，可以直接发给别人。

用法：
    python pack.py              # 输出到 dist/
    python pack.py --version 1.1.0

打包时自动排除：__pycache__、虚拟环境、抓取结果、临时 profile。
"""
from __future__ import annotations

import argparse
import fnmatch
import zipfile
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT_NAME = "chaoxing-work-extractor"

EXCLUDE_DIRS = {
    "__pycache__", ".git", ".idea", ".vscode",
    "dist", ".cxwork", ".smoke-profile", "out",
}
EXCLUDE_FILES = {"*.pyc", "*.pyo", ".DS_Store", "Thumbs.db"}


def should_skip(rel: Path) -> bool:
    for part in rel.parts:
        if part in EXCLUDE_DIRS:
            return True
    name = rel.name
    return any(fnmatch.fnmatch(name, pat) for pat in EXCLUDE_FILES)


def collect() -> list[Path]:
    files = []
    for p in sorted(HERE.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(HERE)
        if should_skip(rel):
            continue
        files.append(rel)
    return files


def main(argv=None):
    ap = argparse.ArgumentParser(description="打包工具")
    ap.add_argument("--version", default=f"1.0.{date.today():%Y%m%d}")
    ap.add_argument("-o", "--out", default=str(HERE / "dist"))
    a = ap.parse_args(argv)

    files = collect()
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    zp = out_dir / f"{ROOT_NAME}-{a.version}.zip"

    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in files:
            z.write(HERE / rel, f"{ROOT_NAME}/{rel.as_posix()}")

    total = sum((HERE / f).stat().st_size for f in files)
    print(f"[ok] {zp}")
    print(f"     {len(files)} 个文件 · 原始 {total/1024:.1f} KB · 压缩后 {zp.stat().st_size/1024:.1f} KB")
    print()
    print("包里包含：")
    for rel in files:
        print(f"  {rel.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
