---
summary: "工作流规范与自我更新日志"
read_when:
  - Every session start
---

# AGENTS.md - 工作流规范

## 任务处理流程

1. 理解任务意图，判断是否触发"调研→备选→执行→复盘"工作流
2. 触发时：搜索最佳实践 → 提供 3 个方案 → 执行选定方案 → 写入复盘日志
3. 不触发时：直接执行

## 自我更新日志

> 每次完成触发完整工作流的任务后，在此追加复盘记录。

---

### #001 ｜ 2026-04-10 ｜飞书 Wiki 内容读取与复制

**任务**：读取他人有编辑权限的飞书 Wiki 页面，创建新文档并写入完整结构内容

**方案对比**：

| 方案 | 可行性 | 结论 |
|------|--------|------|
| A. web_fetch 直接抓取 | ❌ | 飞书 Wiki 受鉴权保护，HTTP 请求无法绕过 |
| B. 浏览器自动化 (agent-browser / Playwright) | ❌ | Chrome for Testing 被 GFW 屏蔽，无法安装 |
| C. 飞书 Open API 直调 (Python SDK) | ⚠️ | 可行但需自行处理 OAuth 流程和凭证管理 |
| D. **Lark CLI (飞书官方)** | ✅ **采用** | npm 安装无翻墙要求；内置 docs/wiki 命令；Device Flow 授权 |

**执行结果**：成功读取源 Wiki 并创建新文档

**方法优劣**：
- ✅ 国内网络直接可用，无需代理
- ✅ 官方维护，API 同步及时
- ✅ 支持 Markdown 流式读写，使用简单
- ❌ Device Flow 授权流程对非交互式场景不够友好（需后台进程等待）
- ❌ 内部文档链接（token 形式）Markdown 写入时丢失超链接
- ❌ 复杂组件（callout 样式、多维表格嵌入）还原度有限

**适用条件**：
- 飞书文档读写类任务 → 首选 Lark CLI
- 需要高保真还原复杂排版 → 需配合 Block API 逐块构建
- 批量操作场景 → 建议预先获取长期 token

---

### #001-v2 ｜ 2026-04-10 ｜飞书嵌入表格数据提取（补充）

**问题**：v1 版本丢失了 Wiki 页面中嵌入的多维表格数据

**新发现**：
1. **飞书文档 raw 格式**：`docs +fetch --format raw` 返回的 JSON 中，实际内容在 `markdown` 字段（非 `result`），包含 XML/HTML 标签（`<callout>`, `<lark-table>` 等）
2. **嵌入电子表格 ≠ 独立 Spreadsheet**：Wiki 中 `<sheet token="xxx"/>` 引用的是嵌入块，不是独立电子表格，Spreadsheet API 的 `sheets +read` 返回 invalid
3. **表格数据存储位置**：嵌入表格的实际数据以 `<lark-table><lark-tr><lark-td>...</lark-td></lark-tr></lark-table>` HTML 格式存在于文档原始 markdown 中
4. **正确提取路径**：raw JSON → 解析 `<lark-table>` HTML → 提取行/单元格 → 转 Markdown 表格 → `docs +update --mode overwrite` 覆写
5. **PowerShell + Python 注意事项**：
   - PowerShell stdout 默认 GBK 编码，输出中文需设置 `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")`
   - JSON 文件可能有 UTF-8 BOM，用 `utf-8-sig` 打开
   - `--app-secret-stdin` 管道传参在 PowerShell 下有编码问题，用 `cmd /c type file | ...` 绕过

**方法优劣补充**：
- ✅ 嵌入表格数据可完整提取（158 行全部成功）
- ❌ `<sheet token>` 引用的外部多维表格无法通过 API 读取（权限隔离）
- ⚠️ callout 样式、颜色等视觉属性在 Markdown 转换中会丢失

---

### #002 ｜ 2026-04-25 ｜ xwlb → 飞书多维表格自动化同步

**任务**：AkShare `news_cctv` 数据 → 飞书 Bitable 每日同步，含初始化、回填、自动化

**方案对比**：

| 方案 | 可行性 | 结论 |
|------|--------|------|
| A. 用 wiki URL 中的 app_token 直接操作 | ❌ | URL 中的 token 是 wiki 节点 token，不是 bitable app_token |
| B. 继续用 wiki 嵌入的 bitable，修复 app_token | ⚠️ | app_token 可通过 wiki API 纠偏，但 wiki 继承权限体系复杂 |
| C. **新建独立 bitable（无 wiki 嵌入）** | ✅ **采用** | 权限体系独立干净，app_token 和 table_id 直接可见 |

**执行结果**：6 字段初始化成功，23 条记录回填（4/25: 12条, 4/26: 11条），每日 23:30 自动化任务已激活

**关键发现**：

1. **飞书 Bitable 写权限的双入口机制**（最重要）：
   - "添加协作者" → tenant_access_token 只读
   - "添加文档应用" → tenant_access_token 可写
   - 两者在 API 层无区分标志，只能通过 bitable UI 操作
   - **这是 91403 Forbidden 的根因，API 调试无法解决**

2. **Wiki URL token ≠ bitable app_token**：
   - Wiki URL 中的 token 是 wiki 节点 token
   - 实际 bitable app_token 需通过 `GET /wiki/v2/spaces/get_node` 查询 `obj_token`
   - 独立 bitable URL 直接暴露：`base/{app_token}?table={table_id}`

3. **Bitable 日期字段格式**：需要毫秒级 Unix 时间戳，不接受 `YYYY-MM-DD` 字符串

**方法优劣**：
- ✅ 最终路径正确：独立 bitable + UI 添加文档应用 + API 初始化/同步/回填
- ✅ 回填逻辑健壮（按日期查重，防重复写入）
- ❌ 在 app_token 错误路径上停留太久（应在首次 404/403 时立即排查 token 来源）
- ❌ 在 91403 错误上穷举 API 路径，未及时识别这是 UI 操作场景
- ❌ **任务开始时未读 MEMORY.md** → 丧失复用 #001-v2 中"飞书嵌入表格权限隔离"经验的机会

**适用条件**：
- 飞书 Bitable 写权限报错 91403 → **先提示用户在 bitable UI 中点击"添加文档应用"**，不要继续 API 调试
- 需要操作 bitable → **首选独立 bitable**（URL 直接给 app_token + table_id），不依赖 wiki 嵌入
- 日期字段同步 → 注意飞书要求毫秒级 Unix 时间戳
- **任何飞书相关任务开始前 → 必须先读 MEMORY.md/AGENTS.md 复用历史经验**
