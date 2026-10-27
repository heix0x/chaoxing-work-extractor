# 超星作业抓取工具

把学习通（超星）作业页里的题目抓下来，转成结构化 JSON 和 Markdown 笔记；
也支持把答案文件批量填回答题页。

需要 Python 3.10+ 和基本的命令行操作。

## 获取

```bash
git clone https://github.com/heix0x/chaoxing-work-extractor.git
cd chaoxing-work-extractor
python install.py
```

如果使用 AI 助手（WorkBuddy、Claude Code 等），把整个目录放进它的 skills 目录，
然后说「用 chaoxing-work-extractor 抓一份作业」，助手会读取 `SKILL.md` 并自行处理环境。

---

## 功能

- 抓取作业页的**全部题目**：题干、选项、题型、分值、作答时间
- 输出 `JSON`（机器可读，可合并成题库、导 Anki、做版本对比）和 `Markdown`（Markdown 笔记）
- 支持单选、多选、填空、判断、简答、操作、案例七种题型
- 把答案文件的内容批量填回答题页，省去逐题点击

## 不支持的场景

- **不生成答案**，也不包含提交动作。答案由使用者提供，提交由使用者完成
- **不绕过登录**。每个使用者需要用自己的账号登录一次
- **抓不到动态加载的内容**（必须滚动或翻页才渲染的题目），这类需要先手动展开
- 兜底通道（操作已打开的浏览器）**仅支持 Windows**

---

## 环境要求

1. **Python 3.10 或更新**
   - Windows：从 [python.org](https://www.python.org/downloads/) 安装，勾选 **Add Python to PATH**
   - macOS：`brew install python`
   - 验证：`python --version`
2. **Edge 或 Chrome**（任选其一）
3. **超星账号**（学校统一身份认证）

---

## 快速开始

### 1. 自检

```bash
python install.py
```

检查 Python 版本、安装依赖、探测浏览器、运行冒烟测试。全部通过后继续。

### 2. 登录

```bash
python scripts/cxwork.py login
```

会打开一个**独立的浏览器窗口**。在其中登录学习通，检测到登录成功后窗口自动关闭。

登录态保存在独立 profile 中，与日常浏览器互不影响。副作用是：在手机或日常浏览器登录同一账号时，
可能把这个会话挤下线，重新执行 `login` 即可。

**关于为什么需要单独登录**

浏览器的 cookie 库在运行期间以独占方式打开，其他程序无法读取（Windows 报 `ERROR_SHARING_VIOLATION`，
macOS 同样有文件锁）。可行替代只有两条：管理员权限做卷影副本，或者抢焦点模拟键盘复制。
后者会打断当前操作，且只能得到可见文本，无法写入表单。

因此：**抓取题目**可以走兜底通道（`cx_fallback.py`，操作已打开的浏览器）；
**填写答案**必须使用专用 profile，需要先执行一次 `login`。

### 3. 抓取

复制作业页地址，执行：

```bash
python scripts/cxwork.py run "<作业页网址>" -c "课程名" -o ./out --placeholder
```

输出目录中会生成：

| 文件 | 内容 |
|---|---|
| `作业一.json` | 结构化题目 |
| `作业一.md` | Markdown 笔记，可直接放入 Obsidian |
| `作业一.txt` / `.html` | 原始文本与网页，用于排查问题 |

检查输出中的 `questions` 和 `declared` 两个数字：相等表示抓全；不相等时查看 `warnings`，
其中会指出哪个章节解析异常。

---

## 答案文件

`--placeholder` 会在每道题下留一行 `**答案：** *(待填)*`，可以直接在编辑器中逐题填写；
也可以准备一份答案 JSON 一次灌入：

```json
{
  "1":  { "answer": "B", "explain": "Ctrl+Alt+T 是 GNOME 默认快捷键" },
  "11": { "answer": "命令 ｜ 参数", "explain": "完整形式是 提示符+命令+选项+参数" }
}
```

```bash
python scripts/cxwork.py render ./out/作业一.json -a answers.json -c "课程名" -o 作业一.md
```

---

## 填写答案

把一个答案文件批量填进答题页。分三步，每步都可以停下检查：

```bash
# 1. 探测：确认页面上的题目能被识别，不修改页面
python scripts/cxwork.py fill "<答题页网址>" --probe

# 2. 演练：输出将要填入的内容，仍然不修改页面
python scripts/cxwork.py fill "<网址>" -a answers.json

# 3. 执行：确认无误后加 --commit
python scripts/cxwork.py fill "<网址>" -a answers.json --commit
```

答案文件格式：

```json
{
  "1":  "B",
  "5":  ["A", "C", "D"],
  "11": ["命令", "参数"],
  "21": "一整段文字"
}
```

单选与判断题给字符串，多选与填空题给数组（填空按空位顺序），简答与操作题给完整文本。
也兼容上文的 `{"answer": ...}` 格式。

**注意事项**

- 学习通的作答是即选即存，填入后会触发页面自身的暂存请求
- 多选题的点击定位偶尔会偏，提交前请完整核对一遍

---

## 命令参考

```bash
python scripts/cxwork.py login [--wait 300]     # 登录，--wait 指定最长等待秒数
python scripts/cxwork.py check [--headful]       # 检查登录态
python scripts/cxwork.py fetch <url> -o ./out    # 只抓原始文本
python scripts/cxwork.py parse <txt>             # 文本 → JSON
python scripts/cxwork.py render <json> -a ans.json -c "课程" -o x.md
python scripts/cxwork.py run <url> -c "课程" -o ./out --placeholder
python scripts/cxwork.py fill <url> --probe      # 探测答题页结构
python scripts/cxwork.py fill <url> -a ans.json [--commit]
```

`run` 的退出码 3 表示存在警告（通常是没有抓全），可在脚本中据此判断。

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

**为什么使用独立浏览器**：直接操作日常浏览器需要抢占前台、模拟按键、读取剪贴板，
会打断当前工作，且 macOS 上不可行。

**为什么解析基于纯文本而不是网页选择器**：超星改版频繁，选择器容易失效；
题目排版的文本格式相对稳定。

---

## 常见问题

先查看 `references/troubleshooting.md`，其中记录了已验证的故障现象与处理方法。

| 现象 | 处理 |
|---|---|
| `check` 提示未登录 | 重新执行 `login` |
| 抓取结果没有题目 | 加 `--headful` 观察浏览器实际渲染位置 |
| 题数少于标注 | 查看 `warnings` 指出的章节 |

---

## 使用要求

需要能够运行 Python 脚本。若目标机器无法安装 Python，可以在其他机器上完成抓取与渲染，
只把生成的 Markdown 交付给最终使用者。

图形界面版本暂未提供。

---

## 目录结构

```
.
├── install.py              环境自检与依赖安装
├── requirements.txt        依赖清单
├── README.md               本文件
├── SKILL.md                AI 助手的调用说明
├── scripts/
│   ├── cxwork.py           CLI 主入口
│   ├── cx_parser.py        纯文本 → JSON
│   ├── cx_render.py        JSON → Markdown
│   ├── cx_fill.py          把答案填进答题页
│   └── cx_fallback.py      兜底：操作已打开的浏览器（仅 Windows）
├── references/
│   └── troubleshooting.md  排错手册
└── tests/
    ├── sample_linux.txt    回归样本
    └── answers.example.json 答案格式示例
```

登录态与抓取结果不在仓库内：

- 浏览器登录态：`~/.workbuddy/browser-profiles/chaoxing`（环境变量 `CXWORK_PROFILE` 可改）
- 抓取结果：默认当前目录下的 `.cxwork/`
