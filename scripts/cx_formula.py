#!/usr/bin/env python3
"""超星答题页的图片公式还原。

超星把题干/选项里的 LaTeX 公式渲染成图片：

    <img class="ans-latex-moudle" data="%22O(mn)%22" src="https://p.ananas...png">

`data` 是 URL 编码（有时编码两三层）的 LaTeX。纯 `inner_text("body")` 拿不到图片内容，
公式整段丢失，表现为「选项只剩 A/B/C/D 字母」「矩阵链维数不见了」。

本模块提供两种用法：

1. **自动**（推荐）：`cxwork.py fetch` / `run` 调用 `replace_formula_images(page)`，
   在页面内把公式图片替换成文本后再取文本，产出的 `.txt` 天然含公式，无需额外命令。
2. **单独导出**：`python cx_formula.py "<URL>" -o 题目.json`，输出逐题题干+选项 JSON。

只改浏览器内的临时 DOM，不向服务器写任何东西，不碰提交按钮。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
from pathlib import Path

FORMULA_IMG_SEL = "img.ans-latex-moudle"

# JS 侧解码：URL 编码可能套了两三层；%D7 是 GBK 的 ×，decodeURIComponent 会抛异常，
# 先换成字符再解；解不动就保留原样，至少不丢信息。
JS_DEC = r"""
  const dec = s => {
    let v = s || '';
    for (let i = 0; i < 3; i++) {
      try {
        const n = decodeURIComponent(v.replace(/%D7/g, '×').replace(/%A1%C1/g, '±'));
        if (n === v) break;
        v = n;
      } catch (e) { break; }
    }
    return v.replace(/^"+|"+$/g, '').trim();
  };
"""

JS_REPLACE = "() => {\n" + JS_DEC + r"""
  const imgs = [...document.querySelectorAll('img.ans-latex-moudle')];
  if (!imgs.length) return 0;
  imgs.forEach(im => {
    const t = document.createTextNode(' {' + dec(im.getAttribute('data')) + '} ');
    im.parentNode.replaceChild(t, im);
  });
  return imgs.length;
}"""

JS_EXTRACT = "() => {\n" + JS_DEC + r"""
  const clean = t => (t || '').replace(/\s+/g, ' ').trim();
  return [...document.querySelectorAll('.questionLi')].map((q, idx) => {
    const clone = q.cloneNode(true);
    clone.querySelectorAll('img.ans-latex-moudle').forEach(im => {
      const t = document.createTextNode(' {' + dec(im.getAttribute('data')) + '} ');
      im.parentNode.replaceChild(t, im);
    });
    const h3 = clone.querySelector('h3');
    const opts = [...clone.querySelectorAll('.answerBg')].map(o => clean(o.textContent));
    return {
      no: idx + 1,
      type: q.getAttribute('typename') || '',
      qid: (q.id || '').replace('question', ''),
      stem: clean(h3 ? h3.textContent : ''),
      opts: opts
    };
  });
}"""


def decode_latex(s: str) -> str:
    """Python 侧同款解码，供测试和离线处理使用。"""
    v = s or ""
    for _ in range(3):
        n = urllib.parse.unquote(v.replace("%D7", "×").replace("%A1%C1", "±"))
        if n == v:
            break
        v = n
    return v.strip('"').strip()


def replace_formula_images(page) -> int:
    """在当前页面就地替换公式图片为文本节点，返回替换数量。

    只影响浏览器内的临时 DOM；调用方随后重新取 inner_text 即可拿到含公式的文本。
    """
    return int(page.evaluate(JS_REPLACE) or 0)


def extract_questions(page) -> list[dict]:
    """逐题导出题干与选项（含公式），供人工解题/生成笔记用。"""
    return page.evaluate(JS_EXTRACT)


def main(argv=None):
    ap = argparse.ArgumentParser(description="还原超星答题页的图片公式，输出完整题目")
    ap.add_argument("url")
    ap.add_argument("-o", "--out", help="输出 JSON 路径；不传则打印到 stdout")
    ap.add_argument("--text", action="store_true", help="同时把可读文本打印到 stdout")
    a = ap.parse_args(argv)

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from cxwork import Session  # 延迟导入，避免与 cxwork 的循环引用

    with Session(headless=True) as s:
        if not s.is_logged_in():
            print(json.dumps({"ok": False, "error": "未登录，先跑 cxwork.py login"}, ensure_ascii=False))
            return 2
        page = s.goto(a.url)
        time.sleep(2.5)
        items = extract_questions(page)

    if a.out:
        Path(a.out).write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.text or not a.out:
        for q in items:
            print(f"[{q['no']}] ({q['type']}) {q['stem']}")
            for o in q["opts"]:
                print("    ", o)
    if a.out:
        print(f"[ok] {len(items)} 道题 -> {a.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
