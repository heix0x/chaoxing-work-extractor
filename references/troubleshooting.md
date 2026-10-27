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
