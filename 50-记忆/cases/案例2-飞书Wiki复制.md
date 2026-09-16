# 案例2：飞书 Wiki 内容复制（2026-04-10）

**任务：** 将飞书 Wiki 多维表格内容复制到自有飞书文档。

## 第1层·事实

- 图片下载尝试了 4 种方法，只有 `docs +media-preview` 成功（3 种 403）
- Lark CLI 安装后 PowerShell 调用有编码问题，需 `cmd /c` 包装
- 最终图片无法通过 Markdown API 内嵌，只能生成 HTML 文件

## 第2层·原因

- 图片 403：飞书权限体系复杂——bot token、tenant token、user token 三种身份权限不同，逐个试才知道哪个能用
- PowerShell 编码：没提前确认 PowerShell 管道传参的编码限制
- 追问：为什么不先列出所有可能的权限路径再试？→ 因为默认假设"文档说的就是对的"，碰到 403 才换

## 第3层·底层模型

> **「平台 API 权限黑盒」**：第三方平台的权限体系通常是黑盒，文档描述与实际行为常有偏差。唯一可靠的方式是逐个验证。但逐个验证不等于盲目试——可以先列出所有可能的权限路径，按成功概率排序，从高到低试。
>
> 与「行动优先 vs 确认优先」同源：没有先分析权限结构就动手调用 API。

## 第4层·能力

缺失「权限路径预判能力」——在调用第三方 API 前系统性梳理权限层级和可用凭证类型，而不是碰到 403 再换。

## 第5层·基本功

对第三方平台默认假设"文档说的就是对的"。但平台文档经常滞后或不完整。应该先小规模验证，再大规模执行。

---

# 续篇（2026-08-02 ~ 08-06）：禁下载附件搬运 + docx v1 API 实战

**任务：** 把 yitanger 租户 3 篇禁复制文档搬到荣总名下。其中王欢那篇正文里嵌了一个 `.md` **文件附件**，源侧禁止下载，导入后只剩占位符。

## 第1层·事实

**A. 附件提取（禁下载绕行）**
- `GET /drive/v1/files/{token}/download` → **403**；`GET /docx/v1/documents/{file_token}/content` → **404**（file token 不是 docx token）。API 侧无路。
- agent-browser 自带 Chromium **无登录态**，打开租户链接直接卡登录页。
- 唯一通路：CDP 接管荣总本机已登录 Chrome —— 以 `--remote-debugging-port=9222 --user-data-dir=<原 User Data>` 重启（登录态/书签全保留），Playwright `chromium.connectOverCDP('http://127.0.0.1:9222')` 接管。
- 附件卡片渲染在内嵌 iframe：选择器 `iframe[data-sel="box-preview-code-iframe"]`，src 是 `internal-api-drive-stream.feishu.cn/.../preview_tpl3/?tpl_id=md`，模板靠父页 `postMessage({key:'initData'})` 注入后才渲染。
- `page.frames()` 找不到该帧；必须 `page.$(sel).contentFrame()` 才能进。读 `#content` 的 `innerHTML` 拿到 22638 字符带标签 HTML（标题/代码/列表/表格结构完整）。

**B. docx v1 写块接口（踩满一圈）**

| 坑 | 表现 | 真相 |
|---|---|---|
| 接口选型 | `children` 追加接口连最简 heading 块都 `1770001 invalid param` | 批量写块**必须用 descendant**：`POST /docx/v1/documents/{d}/blocks/{d}/descendant`，body `{children_id:[顶层块id...], index:N, descendants:[全部块]}`。`children` 端点另有 50 块上限，descendant 无 |
| 精确定位 | — | descendant 支持 `index`（0基），可把新块**插到占位符原位置** |
| 删块 | `DELETE /blocks/{id}` → **404**（但 `GET` 同路径 200，说明是路由不存在不是业务错） | 正确是 `DELETE /blocks/{parent}/children/batch_delete`，body `{start_index, end_index}` 区间删 |
| 删块陷阱 | `children` 端点的 `delete_blocks` 字段 | 强制要求同时带非空 `children`（min len 1），每删一个就被迫新增一个 → **"删一个留一个"死循环** |
| 写后一致性 | 插入返回 `code 0`，立刻重读 `pos=-1` | 飞书 docx 写后有**秒级一致性延迟**。我据此误判失败并 abort，测试块变成孤儿块污染目标文档 |
| 代码块格式 | `style` 传 `1` 或 `{}` 都报错 | 正确 `code.style = {"language": <枚举>, "wrap": false}`，且 `text_run` 必须带完整 `text_element_style`（bold/inline_code/italic/strikethrough/underline 全字段）。语言枚举：bash=7、shell=60、yaml=67、json=28、python=49 |
| 改块 | — | `PATCH /blocks/{id}`，body `{"update_text_style":{"style":{...},"fields":[4,5]}}` 可用 |
| 表格块 | — | descendant 可建表；`property` 只透传 `row_size/column_size/header_row`（带 `column_width/merge_info` 会 1770001） |

**C. HTML→块转换的两个静默错误**
- 用带分隔符的 `get_text()` 处理 `<pre>` → span 边界被插入换行，`mkdir -p sources` 变成 `mkdir\n \n-p sources`，**10 个代码块全中**。必须用 `code.get_text()` 原样取。
- 转换器**整类漏掉 `<table>`**：4 个表格、约 937 字符凭空消失。接口全返回 0，回读块数也"对"，只有做**源/目标字符覆盖率比对**才暴露。

## 第2层·原因

- **接口选型错**：手上已有跑通的 `feishu_import.py`（用 descendant 成功写过 276 块），我却另起炉灶用 children，白烧 10+ 轮调试。根因是"我记得有个 children 接口"，凭印象选路而不是先读自己的成功代码。
- **误判失败留垃圾**：默认"写成功=立刻可读"，没给一致性延迟留余量，abort 后不清理，孤儿块直接污染目标文档。
- **完成判定太松**：接口返回 0 + 块数对得上就宣称完成。表格漏转是我自己核验时发现的，如果不做覆盖率比对就交付了。

## 第3层·底层模型

> **「渲染层是最后的读取通道」**：平台可以禁下载、禁复制、禁 API，但只要还要给人看，内容就必须渲染进 DOM。渲染层就是最后一层可读通道。前提是**必须带用户真实登录态**——独立浏览器实例没用，只能 CDP 接管本机已登录进程。这是对案例2原模型「平台API权限黑盒」的补充：权限黑盒在 API 层封死时，通道还在渲染层。

> **「已验证路径优先于文档路径」**：手上有跑通的代码时，第一动作是读自己的成功实现，而不是查官方文档或凭印象选 API。自己的成功代码是**已验证事实**，文档是**声称**。顺序反了就是把已验证资产扔掉重新试错。

> **「写成功 ≠ 可读，跑完 ≠ 转全」**：分布式写入的 `code 0` 只保证受理，不保证可读——校验必须带重试。结构转换的"无报错"只保证语法通，不保证内容全——必须做**源与目标的量化对齐**（字符覆盖率 / 块类型分布 / 元素计数），逐类核对而不是抽查。

## 第4层·能力

缺失「**调试残留的幂等与回滚意识**」——在**生产目标文档**上直接做插入测试，失败后既没回滚也没记录测试块 id，导致孤儿块混进正文；又因为不熟删块接口，清理时陷入"删一个留一个"循环，越清越乱。正确做法：测试插入应在**临时文档**上做，验证通过再对目标文档执行；若必须在目标上测，先记下 block_id 并准备好回滚命令。

## 第5层·基本功

"完成"的判定标准必须是**源与目标的量化对齐**，不是"接口返回 0"。本次最终核验口径值得固化：顶层块数 + 块类型分布（H1/H2/H3/code/table/list/divider）+ 代码块逐个全等比对 + 归一化字符覆盖率。跑这套才敢说搬完了。
