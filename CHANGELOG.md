# 更新日志

## [1.2.4] - 2026-11-24

### 文档

- README 改为安装优先：第一个二级标题就是「安装」，第一屏是一段可直接转发给 AI 助手的提示词（助手自己判断 skills 目录、有 git 用 clone 无 git 下 zip、装完跑 `install.py` 自检、报错贴原文、最后报告三件事）
- 删除「新增能力速查（2026-11-06）」这节带日期的快照，`formula` / `verify` / `--style exam` 合并进「命令参考」
- 新增本文件，追记 1.2.2 与 1.2.3

### 测试

- 整卷样本回归改用 `CXWORK_SAMPLE` 环境变量指向本地样本，去掉硬编码的用户目录（样本含作业内容，不进仓库）

### 说明

- 相对 v1.2.1，本版一并对齐 1.2.2 / 1.2.3 的全部修复，装最新包即到位

## [1.2.3] - 2026-11-23

### 修复

- 简答题多个空被拼成一段塞进第一个空：现在按空位顺序分别填写，页面只有一个编辑器时才拼成一段
- 简答解析改为分段输出（考点 / 思路 / 各自成段），长答案不再挤成一行

### 文档

- `references/troubleshooting.md` 补该故障的触发条件与「`filled=true` 不等于全填对」

## [1.2.2] - 2026-11-06

### 新增

- 图片公式自动还原：`fetch` / `run` 识别 `img.ans-latex-moudle`，把 URL 编码的 LaTeX 还原成 `{O(mn)}` 形式的内联文本，输出 `formula_images` 计数，并额外备份原始文本 `*.raw.txt`
- `formula` 子命令：单独导出逐题题干 + 选项（含公式）
- `verify` 子命令：重载页面逐题核对已填内容，对比 `filled` 与 `questions`
- `--style exam` 笔记风格：全选项 + 引用块解析，先做题后对答案；格式固化为 `references/note-format.md`
- `scripts/cx_deps.py`：运行前依赖自检，缺依赖自动 `pip install`，`CXWORK_NO_AUTOINSTALL=1` 可关闭

### 改进

- `install.py` 重写为五步：Python 版本 / 装依赖 / 探测 Edge 或 Chrome / 冒烟测试 / 打印下一步命令，任一步失败返回 1
- `fill` 的 `--commit` / `--save` 语义在两个 CLI 入口统一（此前只有 `cx_fill.py` 有 `--save`）

### 测试

- `tests/test_cli.py` 增加文档一致性回归：逐条读 `SKILL.md` / `README.md` 的示例命令，与 CLI `--help` 核对参数
