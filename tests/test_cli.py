#!/usr/bin/env python3
"""CLI / 文档一致性冒烟测试。

这个包反复出现的问题是「文档教的命令，代码里没有」（例如 SKILL.md 写
`fill --commit --save`，但 cxwork.py 的 argparse 没定义 --save，照做就丢数据）。
本测试直接读 SKILL.md，把里面的示例命令逐个拿去对 CLI 的 --help 输出核参数，
以后谁改了文档或代码而忘了另一边，这里会红。

跑法：
    python -m unittest discover -s tests -v
    python tests/test_cli.py
"""
from __future__ import annotations

import contextlib
import io
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import cx_fill  # noqa: E402
import cx_formula  # noqa: E402
import cx_render  # noqa: E402
import cx_verify  # noqa: E402
import cxwork  # noqa: E402
from cx_parser import parse_work_text  # noqa: E402


def help_output(mod, argv):
    """跑 `<mod>.main(argv + ['--help'])`，返回 (exit_code, 输出文本)。

    --help 会在 argparse 阶段 SystemExit，因此不会触发依赖自检、不会开浏览器。
    """
    buf = io.StringIO()
    code = None
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        try:
            mod.main(list(argv) + ["--help"])
        except SystemExit as e:
            code = e.code
    return code, buf.getvalue()


class TestDocCliDrift(unittest.TestCase):
    """SKILL.md 里的每条 `python scripts/cxwork.py ...` 都必须对得上 CLI。"""

    def test_skill_md_commands_match_cli(self):
        md = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        cmds = re.findall(r"^\s*python scripts/cxwork\.py\s+(\w+)([^\n]*)$", md, re.M)
        self.assertGreaterEqual(len(cmds), 4, "没从 SKILL.md 抽到足够的示例命令")
        for sub, rest in cmds:
            with self.subTest(subcmd=sub, line=rest.strip()[:70]):
                code, out = help_output(cxwork, [sub])
                self.assertEqual(code, 0, f"cxwork {sub} --help 退出码异常")
                for flag in set(re.findall(r"--[a-zA-Z][\w-]*", rest)):
                    self.assertIn(flag, out,
                                  f"SKILL.md 在 `{sub}` 用了 {flag}，但 CLI 里没有这个参数")

    def test_readme_commands_match_cli(self):
        md = (ROOT / "README.md").read_text(encoding="utf-8")
        cmds = re.findall(r"^\s*python scripts/cxwork\.py\s+(\w+)([^\n]*)$", md, re.M)
        for sub, rest in cmds:
            with self.subTest(subcmd=sub, line=rest.strip()[:70]):
                code, out = help_output(cxwork, [sub])
                self.assertEqual(code, 0)
                for flag in set(re.findall(r"--[a-zA-Z][\w-]*", rest)):
                    self.assertIn(flag, out,
                                  f"README.md 在 `{sub}` 用了 {flag}，但 CLI 里没有")


class TestFillCli(unittest.TestCase):
    def test_save_exists_in_both_entrypoints(self):
        for mod in (cxwork, cx_fill):
            with self.subTest(mod=mod.__name__):
                _, out = help_output(mod, ["fill"])
                self.assertIn("--save", out, f"{mod.__name__} fill 缺 --save")
                self.assertIn("--commit", out)

    def test_probe_forms_are_equivalent(self):
        # cxwork: fill --probe；cx_fill: probe 子命令 + fill --probe
        _, out = help_output(cxwork, ["fill"])
        self.assertIn("--probe", out)
        _, out = help_output(cx_fill, ["fill"])
        self.assertIn("--probe", out)
        code, _ = help_output(cx_fill, ["probe"])
        self.assertEqual(code, 0)

    def test_verify_and_formula_subcommands_exist(self):
        for sub in ("verify", "formula"):
            with self.subTest(sub=sub):
                code, out = help_output(cxwork, [sub])
                self.assertEqual(code, 0)
                self.assertIn("url", out)

    def test_submit_never_exposed(self):
        """提交按钮绝不能变成 CLI 能力。"""
        for mod in (cxwork, cx_fill):
            _, out = help_output(mod, ["fill"])
            self.assertNotIn("--submit", out)


class TestAnswerFormats(unittest.TestCase):
    """render 与 fill 都要认两种答案格式（审计发现 render 只认 dict，紧凑格式会崩）。"""

    def _render(self, answers):
        data = parse_work_text((ROOT / "tests" / "sample_linux.txt").read_text(encoding="utf-8"))
        return cx_render.render(data, answers, "测试课程", False)

    def test_render_compact_string(self):
        self.assertIn("**答案：B**", self._render({"1": "B"}))

    def test_render_compact_list(self):
        self.assertIn("命令 ｜ 参数", self._render({"11": ["命令", "参数"]}))

    def test_render_dict_with_explain(self):
        md = self._render({"1": {"answer": "B", "explain": "因为 Ctrl+Alt+T"}})
        self.assertIn("**答案：B**", md)
        self.assertIn("因为 Ctrl+Alt+T", md)

    def test_load_answers_both_formats(self):
        import json
        import tempfile
        raw = {"1": "B", "5": ["A", "C"], "11": {"answer": "命令 ｜ 参数", "explain": "略"}}
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as f:
            json.dump(raw, f, ensure_ascii=False)
            path = f.name
        got = cx_fill.load_answers(path)
        Path(path).unlink(missing_ok=True)
        self.assertEqual(got[1], "B")
        self.assertEqual(got[5], ["A", "C"])
        self.assertEqual(got[11], "命令 ｜ 参数")


class TestExamStyle(unittest.TestCase):
    """render --style exam：先做题、后对答案的范本格式。"""

    def _data(self):
        return parse_work_text((ROOT / "tests" / "sample_linux.txt").read_text(encoding="utf-8"))

    def test_exam_full_structure(self):
        answers = {
            "1": {
                "answer": "B",
                "concept": "考点定位",
                "derivation": "无选项推导",
                "option_notes": {"A": "A 错", "B": "正确。B 对", "C": "C 错", "D": "D 错"},
            }
        }
        md = cx_render.render(self._data(), answers, "测试", False, "exam")
        self.assertIn("###### 1. （单选题）", md)
        self.assertIn("A. ", md)                      # 全选项
        self.assertIn("> **解析**：", md)
        self.assertIn("> * **考点**：考点定位", md)
        self.assertIn("> * **推导**：无选项推导", md)
        self.assertIn("> * **B. ", md)                # 正确项加粗
        self.assertIn("> **答案**：**B**", md)        # 答案在引用块末行
        self.assertIn("***", md)

    def test_classic_is_unchanged_by_default(self):
        md = cx_render.render(self._data(), {"1": {"answer": "B", "explain": "因为"}}, "测试", False)
        self.assertIn("**答案：B**", md)
        self.assertNotIn("######", md)
        self.assertNotIn("> **答案**：", md)

    def test_exam_accepts_compact_answer(self):
        md = cx_render.render(self._data(), {"1": "B"}, "测试", False, "exam")
        self.assertIn("> **答案**：**B**", md)

    def test_exam_judge_two_sided(self):
        data = {
            "meta": {"total_questions": 1}, "parsed_total": 1, "title": "T",
            "sections": [{
                "index": "一", "name": "判断题", "count": 1, "score": 10,
                "questions": [{"no": 1, "type": "判断题", "stem": "某命题",
                               "options": {"A": "对", "B": "错"}, "blank_count": 0}],
            }],
        }
        md = cx_render.render(
            data, {"1": {"answer": "B", "option_notes": {"A": "判对会错在…", "B": "命题不成立…"}}},
            None, False, "exam",
        )
        self.assertIn("判「对」", md)
        self.assertIn("判「错」", md)
        self.assertIn("> **答案**：**B**", md)

    def test_exam_short_answer_not_quoted(self):
        data = {
            "meta": {"total_questions": 1}, "parsed_total": 1, "title": "T",
            "sections": [{
                "index": "一", "name": "简答题", "count": 1, "score": 10,
                "questions": [{"no": 1, "type": "简答题", "stem": "简述…",
                               "options": {}, "blank_count": 0}],
            }],
        }
        md = cx_render.render(
            data, {"1": {"answer": "答案文本", "explain": "完整推导"}},
            None, False, "exam",
        )
        self.assertIn("**【正确答案】** 答案文本", md)
        self.assertIn("完整推导", md)
        self.assertNotIn("> **答案**：", md)

    def test_style_flag_on_cli(self):
        for mod, argv in ((cxwork, ["render"]), (cxwork, ["run"])):
            with self.subTest(mod=mod.__name__, argv=argv):
                _, out = help_output(mod, argv)
                self.assertIn("--style", out)


class TestParserRegression(unittest.TestCase):
    """数值型选项曾被误判成答题卡，导致后面所有题被整段丢弃。"""

    def test_numeric_options_do_not_truncate(self):
        text = """暂时保存
提交
作业
测试卷
题量: 3 满分: 100

一. 单选题（共3题，100分）
1. (单选题) 最优乘法次数是多少？
A

18000

B

12000

2. (单选题) 第二题
A

对

B

错

3. (单选题) 第三题
A

x

B

y
"""
        d = parse_work_text(text)
        nos = [q["no"] for s in d["sections"] for q in s["questions"]]
        self.assertEqual(nos, [1, 2, 3])
        self.assertEqual(d["sections"][0]["questions"][0]["options"]["A"], "18000")
        self.assertFalse(d["warnings"], f"不该有 warning：{d['warnings']}")

    def test_real_homework_full_count(self):
        """若 e2e 抓到的样本存在，用它验证整卷题数（54 题）。"""
        p = Path(r"C:\Users\31524\WorkBuddy\学科\cx\算法第三章\e2e\作业作答.txt")
        if not p.exists():
            self.skipTest("没有 e2e 样本")
        d = parse_work_text(p.read_text(encoding="utf-8"))
        self.assertEqual(d["parsed_total"], 54)
        self.assertEqual(d["warnings"], [])


class TestFormulaDecode(unittest.TestCase):
    def test_single_encoded(self):
        self.assertEqual(cx_formula.decode_latex("%22O(mn)%22"), "O(mn)")

    def test_gbk_times_sign(self):
        # %D7 是 GBK 的 ×，直接 decodeURIComponent 会抛异常
        out = cx_formula.decode_latex("%22%20A_1%20%2810%20%D7%2020%29%20%22")
        self.assertIn("10 × 20", out)

    def test_double_encoded(self):
        self.assertEqual(cx_formula.decode_latex("%2522dp%255Bi%255D%2522"), "dp[i]")


class TestModulesImportable(unittest.TestCase):
    def test_no_circular_import(self):
        # cxwork 会 import cx_formula / cx_verify；cx_formula 延迟 import cxwork
        self.assertTrue(callable(cx_formula.replace_formula_images))
        self.assertTrue(callable(cx_verify.verify))
        self.assertTrue(callable(cxwork.extract_page))


if __name__ == "__main__":
    unittest.main(verbosity=2)
