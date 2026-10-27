---
name: chaoxing-work-extractor
description: 从超星学习通（mooc1.chaoxing.com）的作业/考试页面提取全部题目，整理成 Markdown 笔记与结构化 JSON；也支持把答案批量填回答题页。Use when: 学习通作业, 超星作业, 抓题目, 作业转笔记, 导出题目, 把作业整理进笔记, 填写答题页, 把答案填进去, 填答案, chaoxing work extract。
---

# 超星作业抓取

从学习通作业页拿题目，产出两样东西：**机器读的 JSON** 和 **人读的 Markdown**。

## 先判断这条路适不适合

**适合**：题目在超星标准作业页（`mooc1.chaoxing.com/mooc-ans/mooc2/work/dowork`），题型是单选/多选/填空/判断/简答/操作/案例。

**不适合**：题目是图片、需要富文本编辑器才能看全的、或者页面在 iframe 里跨域加载不出来。这些情况先跑 `fetch` 看一眼 `.txt`，里面没有题干就换方案。

## 首次准备（只做一次）

```bash
cd <这个 skill 的目录>
python install.py        # 装依赖 + 探测浏览器 + 冒烟测试，全绿再往下
python scripts/cxwork.py login      # 弹出浏览器，登录一次
python scripts/cxwork.py check      # 确认登录态已保存
```

`install.py` 会告诉你本机该用哪个 Python 解释器。**如果 `python` 不在 PATH**（这台机器就是这样），用绝对路径，例如 `~/.workbuddy/binaries/python/versions/3.13.12/python`，后文命令里的 `python` 都替换成它。

`login` 会打开一个**独立的浏览器实例**，profile 存在 `~/.workbuddy/browser-profiles/chaoxing`（可用环境变量 `CXWORK_PROFILE` 改），和用户日常用的浏览器完全隔离。登录完会自动检测并退出。

浏览器不写死 Edge，按 `msedge → chrome → 内置 chromium` 顺序试；也可用 `CXWORK_BROWSER` 强指定。

> ⚠️ **不要让用户把专用浏览器当成日常浏览器用**。超星多数情况下同一账号只允许一处活跃会话，用户在主 Edge 或手机上登录，可能把这边踢下线。真被踢了就重跑一次 `login`。

## 日常用法

```bash
# 一条龙：抓 + 解析 + 渲染
python scripts/cxwork.py run "<作业页 URL>" -c "Linux 操作系统" -o ./out --placeholder

# 分步
python scripts/cxwork.py fetch "<URL>" -o ./out      # → .txt / .html / .meta.json
python scripts/cxwork.py parse ./out/作业一.txt       # → .json
python scripts/cxwork.py render ./out/作业一.json -c "课程名" -o 笔记.md -a answers.json
```

`run` 的输出是 JSON，关键字段：`questions`（解析到的题数）、`declared`（页面标注的题数）、`warnings`（两者对不上时会说明）。

**退出码 3 表示有 warning**，通常是没抓全，别直接往下走。

## 答案怎么来

`render` 不负责答题，它只负责排版。答案单独存一份 JSON：

```json
{
  "1":  {"answer": "B", "explain": "Ctrl+Alt+T 是 GNOME 默认快捷键……"},
  "11": {"answer": "命令 ｜ 参数", "explain": "完整形式是……"}
}
```

键是题号（字符串）。答案由你（模型）逐题做，拿不准的要在 explain 里标出来，不要装确定。

## 把答案填回答题页

答案文件由用户提供，本工具只负责搬运，不生成内容。
不要把模型生成的答案直接灌进答题页，那超出了这个工具的设计范围。

```bash
# 第一步：探测。只看页面结构、能匹配上几道题，不动页面
python scripts/cxwork.py fill "<答题页 URL>" --probe

# 第二步：演练。报告"打算填什么"，仍然不动页面
python scripts/cxwork.py fill "<URL>" -a answers.json

# 第三步：真填（确认上一步无误后再加 --commit）
# --save 会调页面的 saveWork()（暂时保存），不加则只在页面上填、刷新即丢
python scripts/cxwork.py fill "<URL>" -a answers.json --commit --save
```

> ⚠️ **超星答题页不会自动暂存**。不调 `saveWork()`，关掉浏览器后作答全部归零。
> `--save` 走的是「暂时保存」，不是「提交」；提交按钮（`submitValidate`/`submitWork`）
> 永远不碰。页面结构细节见 `references/troubleshooting.md` 第七节。

> ⚠️ **填完必须在回复里明确告诉用户：按 `Ctrl+F5` 强制刷新页面，答案才会显示出来。**
> 超星只在页面加载时读一次作答数据，填完不刷新页面是空的。用户看到空页面会以为没填上。
> 这句话必须写进回复正文，不能只放在文档里。

答案文件格式：

```json
{
  "1":  "B",
  "5":  ["A", "C", "D"],
  "11": ["命令", "参数"],
  "21": "一整段文字……"
}
```

- 单选/判断给字符串（`"B"` 或 `"对"`）
- 多选/填空给数组（填空题按空的顺序）
- 简答/操作给一整段文本

也兼容 `{"1": {"answer": "B", "explain": "..."}}` 这种从笔记里来的格式。

**实现约束（后续改代码时保持）**：

- 代码中不包含提交按钮的选择器，也不要添加
- 不加 `--commit` 一律 dry-run
- 填完输出核对表，由用户核对后自行提交
- 超星的作答是即选即存，填入会触发页面自身的暂存请求；回复时要说明这一点，避免用户误以为已提交

**页面结构未知时**：先跑 `--probe`。如果 `slots_found` 是 0，说明 `BLOCK_SELECTORS` 里的选择器全没命中，
加 `--headful` 看着浏览器跑一遍，把真实容器的 class 补进 `BLOCK_SELECTORS`。

## 关键约束

- **解析器只吃纯文本**，不依赖 HTML 结构。超星改版频繁，DOM 选择器一改就废，纯文本正则更耐操。
- **题型分组用加粗行，题目用 `##`**。这是用户明确的排版要求：大纲里展开一级就是全部题目。
- **答题卡的识别靠「重名章节 + 标题里没有共 N 题」**，不靠数字串。超星答题卡里的「一、单选题（37分）」和正文标题长得几乎一样。

## 失败怎么退

按顺序试，别跳步：

1. **`check` 说没登录** → 重跑 `login`。登录态过期是最高频的失败。
2. **`fetch` 出来的 txt 没有题干** → 页面结构变了或有 iframe。加 `--headful` 看着浏览器跑一遍，看内容到底渲染在哪。
3. **解析出的题数和标注对不上** → 看 `warnings` 点名了哪个章节。多半是该章节的题干格式有变体（比如选项和字母在同一行），需要给 `cx_parser.py` 加一条正则。
4. **整条路都不可用** → 退到 `cx_fallback.py`：直接操作**用户已打开的浏览器**，抢前台全选复制。这条路不需要登录态，但会抢焦点、会覆盖剪贴板、只能拿到已渲染的纯文本。详见 `references/troubleshooting.md`。

## 已知坑

- **中文括号的全半角**：超星两种混用，正则里 `[（(]` 必须成对写。
- **填空题的「第N空」占位**会混在正文里，它是结构信息不是题干内容，解析时要单独计数。
- **`inner_text("body")` 和 Ctrl+A/C 出来的文本不完全一样**：前者保留 DOM 顺序但可能漏掉 `aria-hidden` 的内容，后者是用户视角的可见文本。两条路都要能解析。
- **别在用户正用浏览器时跑 `login`**，会多开一个窗口；`run` 是 headless，不会打扰。

## 文件

```
install.py            # 一键自检 + 装依赖（接手这个包先跑它）
README.md             # 给人看的说明书
requirements.txt      # 依赖清单
pack.py               # 打 zip 分发用
scripts/cxwork.py     # CLI：login / check / fetch / parse / render / run / fill
scripts/cx_parser.py  # 纯文本 → 结构化 JSON
scripts/cx_render.py  # JSON → Markdown
scripts/cx_fill.py    # 把答案填进答题页（默认演练）
scripts/cx_fallback.py# 兜底：操作已打开的浏览器（仅 Windows）
references/troubleshooting.md  # 已踩过的坑，出问题先看
tests/sample_linux.txt         # 回归样本
```

## 分发

```bash
python pack.py --version 1.x.x     # → dist/chaoxing-work-extractor-1.x.x.zip
```

默认排除 `__pycache__`、`.cxwork`、抓取结果、临时 profile。收包的人解压后跑 `python install.py`，按提示走三步即可。

> 注意：**登录态不随包走**。每个使用者必须用自己的账号登录一次。
