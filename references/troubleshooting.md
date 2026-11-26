# 排错手册

这份文档记录的是**已经验证过的事实**，不是猜测。下次遇到同样症状，直接对号入座，不要再从头试。

## 一、为什么不能直接读 Edge 的 cookie

**想做什么**：拿到登录态，用 requests 直接打超星接口，完全绕开浏览器。
**结论**：在这台机器上**做不到**，别再试。

试过并失败的四条路：

| 做法 | 结果 |
|---|---|
| `shutil.copy2` 复制 `Network/Cookies` | `PermissionError: [WinError 32] 另一个程序正在使用此文件` |
| `CreateFileW` 显式请求 `FILE_SHARE_READ\|WRITE\|DELETE` | `ERROR_SHARING_VIOLATION (32)` |
| `sqlite3.connect("file:…?mode=ro&immutable=1", uri=True)` | `unable to open database file` |
| VSS 卷影副本（`vssadmin` / `Win32_ShadowCopy`） | 需要管理员，当前会话不是 |

**原因**：Chromium 系浏览器用**独占模式**打开 cookie 库，普通进程连读句柄都拿不到。

**唯一可行的替代**：让浏览器自己工作（Playwright 用独立 profile），或者让已打开的浏览器把内容复制出来（兜底通道）。

---

## 二、为什么 UI Automation 读不到题干

**症状**：`TextPattern.DocumentRange.GetText(-1)` 能返回一千多字符，里面**只有选项和题型标题**，题干整段缺失。

**已验证**：
- `uiautomation` 能正常找到 `Chrome_WidgetWin_1` → `DocumentControl`，树能挖到第 9~10 层
- `TextControl` 遍历也拿不到题干
- 遍历**所有**有 Name 的元素，题干依然不在

**结论**：超星把题干渲染成了不可选文本（`user-select: none` 或类似），而 UIA 的 TextPattern 只暴露**可选中**的文本。

**附带限制**：**只有当前激活的标签页有 `Document`**。后台标签在 UIA 树里是空的（或只有一个空 `DocumentControl`）。所以想读哪个标签，必须先切过去。

---

## 三、前台切换：哪种 API 能用

按顺序试，**只有第三个能用**：

| API | 结果 |
|---|---|
| `SetForegroundWindow(hwnd)` | 返回 `False`，前台不变 |
| `AttachThreadInput(cur_tid, fg_tid, True)` + `SetForegroundWindow` | 仍然 `False` |
| **`SwitchToThisWindow(hwnd, True)`** | ✅ **成功** |

`SwitchToThisWindow` 是模拟 Alt+Tab 的内部接口，不受前台锁限制。用法：

```python
import ctypes
u32 = ctypes.windll.user32
u32.SwitchToThisWindow.argtypes = [ctypes.c_void_p, ctypes.c_bool]
u32.SwitchToThisWindow(ctypes.c_void_p(hwnd), True)
```

**还原**：操作完用同样方式切回原来的窗口。

---

## 四、SendKeys 是全局键盘注入，必须断言

**踩过的坑**：第一次 `SetForegroundWindow` 失败后没验证就发了 `Ctrl+A` / `Ctrl+C`，结果打进用户正在看的 Obsidian，**把笔记全文选中了**。只是选中、没有删改，但这是实打实的误操作。

**硬规则**：

```python
if u32.GetForegroundWindow() != target_hwnd:
    raise SystemExit("抢前台失败，拒绝发送键盘事件")
```

`cx_fallback.py` 里做了**两次**断言：抢前台后一次、`SetFocus` 后再一次（`SetFocus` 有机会把焦点挪走）。

---

## 五、超星作业页的文本长什么样

`inner_text("body")` 或 Ctrl+A/C 出来的文本，结构大致是：

```
暂时保存提交作业
作业一
题量: 27 满分: 100 作答时间:10-26 19:10至10-29 19:10
一. 单选题（共10题，37分）
1. (单选题) 题干……
A
选项内容

B
选项内容

二. 填空题（共10题，37分）
11. (填空题) 题干含____。
第1空

第2空

一. 单选题（37分）          ← 答题卡开始，后面全丢
12345678910
```

三个特征要记住：

1. **选项字母独占一行**，内容在下一行。也有字母和内容同一行的变体（`A. xxx`），解析器两种都支持。
2. **填空题的「第N空」** 是占位符，用来数空的数量，不是题干内容。
3. **答题卡里的题型标题和正文长得几乎一样**，唯一区别是**不带「共N题」**、而且**必然和前面重名**。解析器就靠这两点判断正文结束。

---

## 六、主通道失效的典型症状

| 症状 | 大概率原因 | 处理 |
|---|---|---|
| `check` 返回 `logged_in: false` | 登录态过期 / 被别处登录踢下线 | 重跑 `login` |
| `fetch` 的 txt 只有导航栏没有题目 | 页面渲染没完成 | 加 `--headful` 观察，或调大等待 |
| 解析题数 < 标注题数 | 某章节格式有变体 | 看 `warnings` 点名了哪个章节，给 `cx_parser.py` 补正则 |
| `run` 退出码 3 | 有 warning，通常是没抓全 | 别直接写笔记，先看 txt |

---

## 七、新版答题页（2025+）的三个坑（2026-10-27 实测，Windows + Edge）

### 1. 登录「成功」但下一次 check 又掉线

Chromium 的持久化 profile **只把带过期时间的 cookie 写盘**，超星的 `_uid`/`UID`/`uf`
是会话 cookie（expires=-1），关浏览器就没了。表现：`login` 报
`{"logged_in": true, "cookies": ["fid","_uid","UID","uf"]}`，下一次 `check` 只剩 `fid`，
`fetch` 抓到的是 `passport2.chaoxing.com/login` 的登录页（标题「用户登录」）。

已修：`cxwork.py` 增加 `STATE_FILE`（profile 目录下 `state.json`），登录成功与
每次 `Session.__exit__` 都存 `ctx.storage_state()`，启动时 `add_cookies` 灌回。

⚠️ 另一个坑：`fid` 只是学校编号（如 1415），**未登录时也存在**。旧代码
`is_logged_in()` 只要有任一 AUTH_COOKIES 就算登录，导致 `login` 一进循环就判定成功、
根本不等人扫码。现在改成必须命中 `STRONG_COOKIES = (_uid, UID, uf)` 之一。

### 2. 选择题不是 input，是 div 点击

```html
<div class="clearfix answerBg" onclick="addChoice(this)" qtype="0" qid="406119094">
  <span data="A" class="choice406119094 num_option">A</span>
  <div class="answer_p"><p>功能模型，对象模型……</p></div>
</div>
```

- 没有 `input[type=radio]` / `checkbox`，老的 `_classify` 一律判成 `unknown`。
- 点击后由 `addChoice()` 把选中的字母拼起来写入隐藏域 `#answer{qid}`。
- **判断题的 `span[data]` 是 `true` / `false`**，不是 A/B；`#answer{qid}` 的值也是 `true/false`。
- 多选 `qtype="1"`，走 `addMultipleChoice()`。

### 3. 填空 / 简答 / 案例是 UEditor 富文本

- 每个空一个编辑器，textarea 名 `answerEditor{qid}{空序号}`；整题一个编辑器时是 `answerEditor{qid}`。
- **textarea 不在 `.edui-editor` 里面**，它和编辑器是兄弟节点（同在 `.textDIV` / `.eidtDiv`），
  所以 `el.closest('.edui-editor')` 取不到。要往上找 1~4 层容器再取
  `iframe[id^=ueditor_]`，由 `ueditor_N` 推出实例名 `ueditorInstant` + N，再
  `UE.instants[key].setContent(html)` + `sync()`。
- 直接 `textarea.fill()` 只会写隐藏域，编辑器里仍然是空的。

### 4. 最大的坑：不点「暂时保存」等于白填

超星答题页**不会自动暂存**。填完直接关浏览器，刷新后所有作答归零（实测 31 题全空）。
页面顶部有两个按钮：

| 按钮 | 函数 | 能不能调 |
|---|---|---|
| 暂时保存 | `saveWork()` | 能，且必须调，否则作答不落库 |
| 提交 | `submitValidate()` / `submitWork()` | **永远不调** |

`cx_fill.py` 现在有 `--save`，填完调 `saveWork()`；不加则只在页面上填、刷新即丢。

### 5. 重复执行会把答案点没

新版选项是「点一下切换」：同一个选项点第二次就取消。所以脚本里做了幂等：
`#answer{qid}` 已经是目标值就跳过，不重复点。

---

## 八、题干里的公式是图片（2026-11-06 实测）

**症状**：`fetch` 出来的 `.txt` 里，某些题的选项只有 A/B/C/D 字母、后面是空的；
或「矩阵链 ____，最优乘法顺序…」这类关键数据整段消失，题目根本没法算。

**原因**：超星把 LaTeX 公式渲染成图片，但 `data` 属性里存着公式源码：

```html
<img class="ans-latex-moudle" data="%22O(mn)%22" src="https://p.ananas.chaoxing.com/...png">
```

`inner_text("body")` 拿不到图片内容；而 `data` 常被 URL 编码**两三层**，
`%D7` 是 GBK 的 `×`，直接 `decodeURIComponent` 会抛异常解出乱码。

**已修（2026-11-06 二次修复）**：`scripts/cx_formula.py` 提供 `replace_formula_images(page)`，
`fetch` / `run` 的 `extract_page()` 会**自动调用**它——先把公式图片替换成文本节点，
再取 `inner_text`，所以主 `.txt` 天然含公式（形如 `{O(mn)}`），原始文本另存 `*.raw.txt`，
输出 JSON 里的 `formula_images` 给出还原数量。不用再手动跑任何命令。

需要逐题的题干+选项 JSON 时才单独跑：

```bash
python scripts/cxwork.py formula "<作业页URL>" -o 题目.json
```

只改浏览器内的临时 DOM，不向服务器写任何东西，不碰提交按钮。

**另外两个小坑**：

- `answerId=0`（还没生成答案记录）不影响填入，也不影响 `saveWork()`；
  保存后继续用原 URL 仍能完整读回作答，不用去找新的 answerId。
- `cxwork.py fill` 之前没有 `--save`，与 `SKILL.md` 里的示例不一致，
  会导致「填完刷新全空」。已给 CLI 补上 `--save` 并转发给 `cx_fill.run(save=...)`。

---

## 九、解析题数卡在半路：数值型选项被当成答题卡（2026-11-06 实测）

**症状**：`parse` 只解出 14 题，页面标注 54 题，`warnings` 说「单选题：解析 14 题，标注 25 题」，
而且判断题、简答题一题都没有。换成未还原公式的 `.raw.txt` 结果一样（说明与公式无关）。

**原因**：第 14 题的四个选项是 `18000 / 12000 / 10000 / 16000`——都是 5 位纯数字。
旧 `RE_CARD_DIGITS = r"^\s*\d{5,}\s*$"` 本意是识别答题卡里连成一串的题号，
结果把这行数值选项判成答题卡入口，置 `pending_card = True` 后**后面所有行无条件丢弃**，
`flush_question()` 也再没机会执行，于是「卡在第 14 题」。

**已修**：

1. 判据收紧到 `\d{8,}`（真正的题号串通常很长，5 位数字太常见）。
2. 即使命中，只要 `state == "options"`（正处于选项上下文）也一律放行，
   让数字走「追加到上一个选项」的分支。
3. `tests/test_cli.py::TestParserRegression` 留了两条回归：
   内联的数值选项样本 + 真实整卷 54 题样本。

**排查口诀**：题数不是「少几题」而是「从某一题往后整段消失」，
优先怀疑正文里有没有哪一行触发了提前 `break` / `pending_card`，
而不是先去改题干正则。

---

## 十、为什么每次用都要重新摸索：环境、三态与零测试（2026-11-06 复盘）

一次 54 题的作业耗时约 35 分钟，其中约 10–15 分钟花在本可避免的重复摸索上：

| 现象 | 根因 | 已修 |
| --- | --- | --- |
| 第一条命令就抛裸 `ModuleNotFoundError: playwright` | 管理型 Python 升级（3.13.12→3.13.14）会清空 site-packages；没有任何命令做依赖自检，`install.py` 只能手动跑 | `scripts/cx_deps.py`，`cxwork.py` / `cx_fill.py` 入口自动检测，缺失就 pip 安装一次（`CXWORK_NO_AUTOINSTALL=1` 可关） |
| 照 SKILL.md 跑 `fill --commit --save` 报参数错 / 填完刷新全空 | `50faf06` 只给 `cx_fill.py` 加了 `--save`，`cxwork.py` 的 argparse 漏了；**修复留在工作区没 commit** | 两个入口都有 `--save`；`tests/test_cli.py` 逐条读 SKILL.md / README.md 核参数 |
| 抓到的题目缺公式，得自己写脚本还原 | `fetch` 只取 `inner_text` | 第八节，已自动化 |
| 解析题数 14/54 | 第九节 | 已修 + 回归测试 |
| 填完不敢确定有没有存住 | 没有重载核对命令，只能临时写 `cx_verify.py` | `cxwork.py verify` |

**三态不一致是总根源**：`git HEAD`、`dist/*.zip`、工作区三份代码行为不同。
改完代码不 commit、不重打包，下次从仓库 clone 或拿 zip 的人（或换一个会话的助手）
拿到的还是旧版本，于是同样的坑再踩一遍。
现在 `install.py` 会跑 CLI 冒烟测试，SKILL.md 末尾写明「改完记得 commit + 重打包」。

---

## 十一、「简答题」也能挂多个空，答案会被塞进第一个空（2026-11-23 实测）

**症状**：某题的四个空是四个类名（`DatabaseSource` / `TextSource` / `XMLTransformer` /
`XLSTransformer`），答案文件写的是四项数组，填完重载核对发现
`editors = ["DatabaseSource TextSource XMLTransformer XLSTransformer", "", "", ""]`——
四个值拼成一段挤进第一空，后三空为空。`--commit` 报告却是 `ok: true`、`filled: true`。

**原因**：`probe` 把这类题判成 `type=简答题, kind=text, controls=4`（不是 `blank`）。
`apply()` 的 `text` 分支只认字符串，`" ".join(ans)` 把数组拼成一段，再交给
`_fill_text_ue()` 写进 `slot.controls[0]`。判 `ok` 时只看"有没有写进去"，所以不会报错。

**已修**：新增 `_text_values(ans, n_controls)`——答案数组 + 多个控件时按空返回列表，
走 `_fill_blanks_ue()` 逐个 setContent；单控件时保持原来的拼接行为。
`tests/test_cli.py` 加了两条（4 空分填 / 单控件合并）。

**怎么提前发现**：`probe` 之后先看目标题的 `controls` 数量。大于 1 的简答题，
答案必须是等长数组，且填完要用 `verify` 看 `editors` 数组，而不是只看 `filled`。
`filled=True` 只代表"至少有一个控件非空"。

**顺带**：`cx_render.py` 的简答题解析原来是 `**【解析】** 考点 思路 补充说明` 挤成一行，
多段推导读不出结构。现在考点、思路、补充说明各自成段（`**【考点】**` / `**【思路】**`），
选择题输出不变。

---

## 十二、登录「成功」但其实是失效的；多选答案点 0 下（2026-11-26 实测）

### 1. `check` 说已登录，`fetch` 抓回来的是登录页

**症状**：`check` 返回 `{"logged_in": true, "cookies": ["fid","_uid","UID","uf"]}`，
但 `fetch` 产出的文件名是「用户登录.txt」，正文只有 299 字；`login` 也一进循环就报成功、
根本不等扫码。

**原因**：`_uid`/`uf` 服务端过期后仍留在本地 profile 里，只看 cookie 在不在等于没查。
更迷惑的是 **`i.chaoxing.com` 的会话和 mooc 域是分开的**：失效时个人空间仍显示用户名，
而 `mooc1/mooc2-ans` 一律跳 passport。所以「个人空间能打开」不能当登录依据。

**已修**：`Session.probe_session()` 用 `ctx.request.get(PROBE_URL)` 打一次受保护页面，
最终 URL 落到 `passport2` 即判失效。`check` / `login` 都改用它；
`fetch` / `run` 打开作业页后若落到登录页，直接报错退出，不再静默产出一个登录页 txt。

**探活地址的坑**：

| 地址 | 结果 |
| --- | --- |
| `i.chaoxing.com/base` | ❌ 失效时仍显示个人空间，假阳性 |
| `mooc2-ans/mycourse/stu` | ❌ 缺 courseid，登录后显示「无效的参数」，看着像失败 |
| `mooc1.chaoxing.com/visit/interaction` | ✅ 失效跳 passport，有效是正常页面 |

**另一个坑**：`login` 里别用「页面还在登录页就不探活」来省开销——扫码后页面不一定立刻跳走，
会一直等到超时。用 `ctx.request` 探活是纯 HTTP，不开标签页、不干扰用户窗口，可以每 3 秒打一次。

### 2. 多选题全部填不上，报告只说 `ok: false` / `readback: ""`

**症状**：35 题的卷子里，单选、填空、简答都进去了，5 道多选全是空；`--commit` 报告
`applied 30/35`，失败项只有 `planned: 多选 ABD` 和空的 `readback`，没有原因。

**原因**：答案文件里多选写成紧凑字符串 `"ABD"`，而 `apply()` 只按 `[,，\s]+` 切分，
`"ABD"` 没分隔符 → 被当成**一个字母**去匹配选项 → 一个都没点中 → `done=0`。
`done==len(picks)` 恒假，但报告没把 `done` 打出来，所以看不出是「没找到选项」还是「点了没生效」。

**已修**：

1. 新增 `_multi_picks()`：`["A","C"]`、`"A,C,D"`、`"ACD"` 三种写法都拆成字母列表；
   长度 1 的字母（`"B"`）保持原样，不会被拆坏。`choice_multi` 与老版 `checkbox` 共用。
2. `_click_choice()` 优先点内层 `span.num_option_dx`。实测内外层都能触发点击事件，
   内层是页面真正绑事件的那个元素，更稳。
3. `tests/test_cli.py::TestMultiPicks` 四条回归（紧凑串 / 带分隔符 / 数组 / 单字母）。

**排查口诀**：多选失败先看答案格式，再看点击目标，最后才怀疑页面改版。
`ok: false` 且 `readback` 为空，八成是「压根没点」，不是「点了没存」。

### 3. 失败信息太薄，定位靠猜（已改）

同一批 35 题里 5 道多选全空，报告只有 `{"ok": false, "planned": "多选 ABD", "readback": ""}`。
为了补上「到底哪一步没成」，得写 6 个调试脚本、开 6 次浏览器。

现在两处加强：

- `apply()` 的失败项带 `why`：`选项里找不到 A` / `点了 3 个，回读 'AB'，缺 D`；
  多选还额外给 `clicked: "2/3"`。
- `fill --commit --save` **结尾自动重载核对**：报告里多一个 `verify` 字段
  （`questions / filled / empty`），有空格就逐题打印 `why`，并以退出码 3 结束。
  不需要再单独跑一次 `verify`（单独跑仍然可用，用于事后复查）。
