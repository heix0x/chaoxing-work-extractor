# 超星作业抓取工具

**English:** Scrape Chaoxing (XueXiTong) assignment pages into Markdown notes, and bulk-fill answers back — a Playwright-based AI agent skill.

把学习通（超星）作业页的题目抓下来，整理成笔记；也能把答案批量填回答题页。

---

## 安装

需要桌面端助手（能读写本地文件、能跑命令）。只会聊天的网页版不行，它碰不到你的电脑。

把下面这段整段复制给助手，WorkBuddy、Claude Code 都一样：

```
帮我装一个技能：https://github.com/heix0x/chaoxing-work-extractor
装到你自己的 skills 目录（WorkBuddy 是 ~/.workbuddy/skills），目录名保持 chaoxing-work-extractor。
有 git 就 clone；没有就下这个 zip 解压，再把解压出来的 chaoxing-work-extractor-main
改成 chaoxing-work-extractor：
https://github.com/heix0x/chaoxing-work-extractor/archive/refs/heads/main.zip
装完跑 python install.py 自检，缺依赖你自己装，浏览器用本机已有的 Edge 或 Chrome；
报错你自己处理，不用问我。
只有一件事要我做：自检到登录那步弹浏览器，我扫码。
装完告诉我：这个技能叫什么名字、我在对话里怎么调它。
```

装完怎么确认：在对话框点 **+**（有的助手是输入 **/**），列表里能看到 `chaoxing-work-extractor` 就是好了。
看不到就发这句：

```
我在技能列表里看不到 chaoxing-work-extractor，你查一下为什么没被识别，修好后告诉我怎么调它。
```

> 助手装不上、你想手动来：到 <https://github.com/heix0x/chaoxing-work-extractor/releases/latest>
> 下最新的 `chaoxing-work-extractor-*.zip`，解压到任一 skills 目录，进去跑 `python install.py`。

## 用法：跟助手说这几句话

之后每次说一句话就行。

### 抓题目

```
帮我抓这个作业的题目，整理成笔记：
<作业页网址>
```

或者带上课程名，笔记的 frontmatter 会更完整：

```
用 chaoxing-work-extractor 抓这个作业，课程是「Linux 操作系统」：
<作业页网址>
```

### 填答案

```
把这份答案填进去，填完别提交，我要自己核对：
<答题页网址>
```

答案文件放在手边就行，助手会问你路径。

**填完按 `Ctrl+F5` 刷新页面，答案才会显示出来。**

超星只在页面加载时读一次作答数据，填完不刷新，页面就是空的——**那不是没填上，是页面没重新读**。数据已经存到服务端了。

### 查登录还在不在

```
检查一下超星登录还有效吗
```

### 你会看到什么

抓完之后，助手通常会在工作目录下生成三样东西：

| 文件 | 用途 |
|---|---|
| `作业一.md` | 笔记，可以直接放进 Obsidian |
| `作业一.json` | 结构化数据，可合并成题库、导 Anki |
| `作业一.txt` | 原始文本，出问题时用来排查 |

助手会把「解析出多少题、页面标注多少题」告诉你。两个数字对不上就说明没抓全，它会接着查。

### 需要你做的只有三件

1. **登录一次**（第一次使用时浏览器会弹出来，正常登录即可）
2. **填完按 `Ctrl+F5` 刷新页面**，确认答案都进去了
3. **核对后自己点提交**（工具不碰提交按钮）

其余全部自动。

---

## 自己敲命令（可选）

习惯命令行的话，任何一步都可以自己来。

```bash
git clone https://github.com/heix0x/chaoxing-work-extractor.git
cd chaoxing-work-extractor
python install.py                              # 自检 + 装依赖
python scripts/cxwork.py login                 # 登录一次
python scripts/cxwork.py run "<作业页网址>" -c "课程名" -o ./out --placeholder
```

`install.py` 会检查 Python 版本、装依赖、找浏览器、跑冒烟测试，任何一步不过都会说明原因。

---

## 命令参考

```bash
python scripts/cxwork.py login [--wait 300]     # 登录，--wait 指定最长等待秒数
python scripts/cxwork.py check [--headful]       # 检查登录态
python scripts/cxwork.py fetch <url> -o ./out    # 只抓原始文本（自动还原图片公式）
python scripts/cxwork.py formula <url> -o 题目.json   # 逐题题干 + 选项，含公式
python scripts/cxwork.py parse <txt>             # 文本 → JSON
python scripts/cxwork.py render <json> -a ans.json -c "课程" -o x.md
python scripts/cxwork.py render <json> -a ans.json --style exam -o 笔记.md   # 先做题后对答案
python scripts/cxwork.py run <url> -c "课程" -o ./out --placeholder
python scripts/cxwork.py fill <url> --probe      # 探测答题页结构
python scripts/cxwork.py fill <url> -a ans.json --commit --save   # 填完后按 Ctrl+F5 刷新
python scripts/cxwork.py verify <url> -o 核对.json    # 重载页面逐题核对已填内容
```

`run` 的退出码 3 表示存在警告（通常是没有抓全）。

`--style exam` 生成的笔记是「全选项 + 引用块解析」，先做题、后对答案；格式规范见
`references/note-format.md`。不加 `--style` 时输出保持原样。

---

## 功能

- 抓取作业页的**全部题目**：题干、选项、题型、分值、作答时间
- **图片形式的公式自动还原**成文字（超星把 LaTeX 渲染成图片，`data` 属性里存着源码）
- 输出 `JSON`（机器可读）和 `Markdown`（笔记，支持「先做题后对答案」的 exam 风格）
- 支持单选、多选、填空、判断、简答、操作、案例七种题型
- 把答案文件的内容批量填回答题页，填完能重载页面逐题核对

## 不支持的场景

- **答案内容由调用方负责**（用户给的，或上层 agent 做的），本工具只负责搬运；也不包含提交动作
- **不绕过登录**。每个使用者需要用自己的账号登录一次
- **抓不到动态加载的内容**（必须滚动或翻页才渲染的题目）
- 兜底通道（操作已打开的浏览器）**仅支持 Windows**

---

## 答案文件

每道题在笔记里留一行 `**答案：** *(待填)*`，可以直接在编辑器里逐题写；
也可以准备一份 JSON 让助手一次灌进去：

```json
{
  "1":  { "answer": "B", "explain": "Ctrl+Alt+T 是 GNOME 默认快捷键" },
  "11": { "answer": "命令 ｜ 参数", "explain": "完整形式是 提示符+命令+选项+参数" }
}
```

填回答题页时用紧凑格式：

```json
{
  "1":  "B",
  "5":  ["A", "C", "D"],
  "11": ["命令", "参数"],
  "21": "一整段文字"
}
```

单选与判断题给字符串，多选与填空题给数组（填空按空位顺序），简答与操作题给完整文本。两种格式都认。

---

## 填写答案

把答案文件批量填进答题页。分三步，每步都可以停下检查：

```bash
# 1. 探测：确认页面上的题目能被识别，不修改页面
python scripts/cxwork.py fill "<答题页网址>" --probe

# 2. 演练：输出将要填入的内容，仍然不修改页面
python scripts/cxwork.py fill "<网址>" -a answers.json

# 3. 执行：确认无误后加 --commit 和 --save
python scripts/cxwork.py fill "<网址>" -a answers.json --commit --save
```

**两个参数缺一不可**：

| 参数 | 作用 | 不加会怎样 |
|---|---|---|
| `--commit` | 真的去点选项、填输入框 | 只在报告里说「打算填什么」 |
| `--save` | 调页面的 `saveWork()` 做暂时保存 | **只在当前页面填了，刷新就没了** |

### 填完必须按 Ctrl+F5 刷新

超星只在**页面加载时**读一次作答数据，之后不会实时同步。

所以填完之后看页面还是空的，这是正常的——数据已经存到服务端了（浏览器开发者工具里能看到 `answerId`），只是当前这个页面没有重新读。

按 `Ctrl+F5` 强制刷新，答案就会全部出现。**这不是没填上，是页面没刷新。**

> 这里说的「保存」是超星页面上的「暂时保存」，不是「提交」。
> 提交按钮（`submitValidate` / `submitWork`）脚本永远不碰，核对完请自己点。

---

## 关于登录

登录态保存在一个**独立的浏览器 profile** 里，与日常浏览器互不影响。副作用是：在手机或日常浏览器
登录同一账号时，可能把这个会话挤下线，重新登录一次即可。

**为什么不能复用已经登录好的浏览器**

浏览器的 cookie 库在运行期间以独占方式打开，其他程序无法读取（Windows 报 `ERROR_SHARING_VIOLATION`，
macOS 同样有文件锁）。可行替代只有两条：管理员权限做卷影副本，或者抢焦点模拟键盘复制。
后者会打断当前操作，且只能得到可见文本，无法写入表单。

所以抓取题目可以走兜底通道（`cx_fallback.py`，操作已打开的浏览器）；
填写答案必须使用专用 profile。

---

## 工作原理

```
专用浏览器（独立 profile，登录一次）
      ↓  读取 DOM
  纯文本
      ↓  正则解析（不依赖网页结构）
  结构化 JSON
      ↓  模板渲染
  Markdown 笔记
```

解析基于纯文本而非网页选择器：超星改版频繁，选择器容易失效，题目排版的文本格式相对稳定。

---

## 常见问题

先看 `references/troubleshooting.md`，其中记录了已验证的故障现象和处理方法。

| 现象 | 处理 |
|---|---|
| 提示未登录 | 重新登录 |
| 抓出来没有题目 | 加 `--headful` 观察浏览器实际渲染位置 |
| 题数少于标注 | 查看 `warnings` 指出的章节 |

---

## 目录结构

```
.
├── install.py              环境自检与依赖安装
├── requirements.txt        依赖清单
├── README.md               本文件
├── CHANGELOG.md            版本记录
├── SKILL.md                AI 助手的调用说明
├── scripts/
│   ├── cxwork.py           CLI 主入口（含 verify / formula 子命令）
│   ├── cx_parser.py        纯文本 → JSON
│   ├── cx_render.py        JSON → Markdown
│   ├── cx_fill.py          把答案填进答题页
│   ├── cx_formula.py       图片公式还原（fetch / run 自动调用）
│   ├── cx_verify.py        重载页面逐题核对作答
│   ├── cx_deps.py          运行前依赖自检 / 自动安装
│   └── cx_fallback.py      兜底：操作已打开的浏览器（仅 Windows）
├── references/
│   ├── note-format.md      笔记模板规范（exam 风格的唯一依据）
│   └── troubleshooting.md  排错手册
└── tests/
    ├── test_cli.py         CLI / 文档一致性 / 解析器回归测试
    ├── sample_linux.txt    回归样本
    └── answers.example.json 答案格式示例
```

登录态与抓取结果不在仓库内：

- 浏览器登录态：`~/.workbuddy/browser-profiles/chaoxing`（环境变量 `CXWORK_PROFILE` 可改）
- 抓取结果：默认当前目录下的 `.cxwork/`

---

## 维护（改这个仓库时看）

- 依赖缺失时 CLI 会尝试自动 `pip install`；离线环境设 `CXWORK_NO_AUTOINSTALL=1`，再手动跑 `python install.py`。
- **测试有两道自动闸**：`.githooks/pre-commit`（`python install.py` 时自动 `git config core.hooksPath .githooks`）
  和 `.github/workflows/test.yml`（push / PR 都跑）。以前测试只在有人记得时跑，一个多选 bug 就这样活了四个版本。
- 改完代码先跑 `python install.py`（内含 `tests/test_cli.py`）或 `python -m unittest discover -s tests -v`。
  测试会逐条核对 SKILL.md / README.md 里的示例命令与 CLI 参数，防止「文档教的参数代码里没有」这类漂移。
- 改完记得 `git commit` 并重新打包 `dist/`（`python pack.py --version x.y.z`），否则工作区、仓库 HEAD、
  分发包三份行为不一致，别人装到的还是旧代码。
