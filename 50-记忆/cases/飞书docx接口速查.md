# 飞书 docx / lark-cli 接口速查

> 由工作区 MEMORY.md「项目/工具」表移出（2026-09-16 系统减脂）。技术手册，用的时候查。
> 配套案例：`案例10-飞书文档863篇垃圾写入.md`、`案例2-飞书Wiki复制.md`

## 一、lark-cli 用法

### `--markdown` 三种传参方式（案例10 血泪）

1. `--markdown "内容"` —— 直接传内容字符串
2. `--markdown @./file.md` —— 读**相对路径**文件（必须在当前目录下）
3. `--markdown -` —— 从 **stdin** 读取（最可靠，用 `subprocess.Popen` 管道）

**关键：它不是文件路径参数，是内容参数。** 传路径 = 文档内容变成路径字符串（863 篇垃圾的根因）。

### 默认 profile

- **App B** `cli_a95d0d5f0e781bc9`（荣总）—— 默认
- App A `cli_a9528e80dc385bcf`（赵以纶）—— 保留但不再默认
- 调用前先 `lark-cli config show` 确认 profile

---

## 二、飞书 docx v1 写块速查

| 操作 | 接口 | 要点 |
|---|---|---|
| **写块** | `POST /docx/v1/documents/{d}/blocks/{d}/descendant` | body `{children_id:[顶层id...], index:N, descendants:[全部块]}`；支持 index 精确插入、**无 50 块上限**。`children` 追加接口连最简块都报 `1770001`，别用 |
| **删块** | `DELETE /blocks/{parent}/children/batch_delete` + `{start_index,end_index}` | `DELETE /blocks/{id}` 是 404，路由不存在 |
| **改块** | `PATCH /blocks/{id}` + `{"update_text_style":{"style":{...},"fields":[4,5]}}` | — |
| **代码块** | `style={"language":枚举,"wrap":false}` | bash=7 / shell=60 / yaml=67 / json=28 / python=49；text_run 需带完整 text_element_style |
| **表格** | property 只透传 `row_size` / `column_size` / `header_row` | — |

**注意：写后有秒级一致性延迟，校验必须带重试。**

---

## 三、文档所有权

- API 创建的文档默认 owner = **应用本身**，不是人
- 必须调 `transfer_owner` 转移给荣总
- **调用者必须是当前所有者**（即创建文档的那个 App 的 token）

```
POST /open-apis/drive/v1/permissions/{token}/members/transfer_owner?type=docx
body: {"member_type":"openid","member_id":"ou_xxx"}
```

---

## 四、禁下载附件的提取通道（案例2 续篇）

API 全封死（download→403、docx content→404）时走**渲染层**：

1. CDP 接管本机已登录 Chrome（`--remote-debugging-port=9222` + 原 user-data-dir）
2. `connectOverCDP`
3. `page.$('iframe[data-sel="box-preview-code-iframe"]').contentFrame()`
4. 读 `#content` innerHTML

注意：agent-browser 自带 Chromium 无登录态，**不可用**。

---

## 五、相关脚本

| 脚本 | 路径 | 说明 |
|---|---|---|
| `feishu_import.py` | `C:\Users\Admin\Desktop\脚本程序\feishu_import.py` | 禁复制文档整篇搬运工具（descendant 重建方案）；凭据走 `feishu_cred.py`（Windows DPAPI 加密） |
| `feishu_config.py` | — | 统一飞书配置模块，从环境变量 / `E:\douyin_downloads\.env` 读 secret，不硬编码 |
| `fix_feishu_docs.py` | — | 863 篇内容修复脚本（新增于案例10），含断点续传 `fix_progress.json` |
