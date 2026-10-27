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
