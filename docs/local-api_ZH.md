# 本机 API v1

SelfIndex 后台服务默认监听 `http://127.0.0.1:5050`。当前接口仅供同一台 Mac 上的应用调用，不支持跨设备访问。桌面 App 和外部客户端共用此接口。

本机读接口不要求令牌；受保护域的解锁前缀是**搜索过滤**，不是访问授权。同一登录用户下的其他进程可调用读接口，写接口令牌也不能抵御已取得该用户文件读取权限的恶意进程。SQLCipher 只加密 SQL 数据库，Chroma 向量/元数据、原始导出、Markdown 来源、日志与备份不因此自动加密。长期运行应保持本机用户账户和资料目录权限，备份另行加密及异盘保存；不把服务暴露到局域网。

## 健康检查

`GET /api/v1/health`

```json
{"ok":true,"service":"selfindex","version":"0.1.0"}
```

该接口表示服务进程可响应请求，不保证 embedding 模型已加载。

## 服务能力状态

`GET /api/v1/status`

返回稳定的 `profile_id`（资料库身份）和每次服务启动变化的 `instance_id`，以及 `index`、`pending`、`capabilities`。`index.state` 可能为 `empty`、`ready`、`unlabelled`、`model_mismatch`；后两种情况下 `/health` 仍可返回 200，但检索与新增向量不可用。`pending.embeddings` 只统计活跃当前修订版的待索引单元，`pending.source_writes` 是已归档但尚未写回 Markdown 文件的数量。`index.model_loaded` 只读取内存状态，不为探测而加载模型。`archive_write` 和 `index_write` 是路径权限与配置的即时判断，不是下一次写入必定成功的承诺。

调用方应先用 `/health` 判断服务是否可响应，再用 `/status` 判断索引能力；不要因一次状态超时自动强制重启服务。状态端点不会返回资料库绝对路径。

## 查询记忆

`GET /api/v1/search?query=<文本>&limit=<1-50>`

- `query` 必填，去除首尾空白后长度不超过 4096；可使用现有的受保护域解锁前缀。
- `limit` 可选，默认 10，范围 1–50。
- 返回 `query`、`count`、`results`。每个结果包含 `memory_unit_id`、`raw_document_id`、`title`、`summary`、`preview`、`content`、`source`、`created_at`、`recall_domain` 和 `trace` 等字段。

```bash
curl -G --data-urlencode 'query=示例' --data-urlencode 'limit=10' \
  http://127.0.0.1:5050/api/v1/search
```

`score` 当前是向量距离值，不应作为跨版本固定阈值。调用方应使用 `memory_unit_id` 获取详情。

## 记忆详情

`GET /api/v1/memory/<memory_unit_id>`

返回 `memory_unit` 和 `raw_document` 两个对象。`raw_document.latest_revision_id` 和 `raw_document.edit_version` 是保存时必须回传的乐观并发凭据；`historical=true` 的详情不可直接编辑。ID 可能含 `/`、空格和中文，客户端构造 URL 时应对 ID 做路径编码。不存在或已失活的记录返回 `404`。

## 编辑原文

`PUT /api/v1/memory/<memory_unit_id>`，请求体为 JSON：

```json
{"title":"标题","author":"作者","content":"原文内容","expected_revision_id":"详情中的修订 ID","expected_edit_version":3}
```

标题、作者和正文都必须是字符串，`content` 不能只含空白；两个 expected 字段必须来自刚读取的详情（版本为整数）。如果其他编辑或同步已改动文档，返回 `409`，客户端应保留草稿并重新读取，不可无条件重试。请求头需包含 `Authorization: Bearer <写令牌>`。默认写令牌由服务生成在 `data/api-write-token`，文件权限为 `0600`；也可通过 `API_WRITE_TOKEN` 环境变量覆盖。

首次创建令牌使用临时文件加原子发布；已有令牌为空、格式不合法或权限过宽时服务会明确报错，不会自动更换有效凭据。修复前请停止相关客户端并检查令牌文件，勿把令牌内容发到日志或聊天中。

- `200`：归档、搜索索引和（若适用）Markdown 源文件均已更新。
- `202`：归档已保存，但 `index_status=pending` 或 `source_status=pending`。前者可运行 `python -m scripts.build_embeddings` 恢复；后者会在服务下次启动时重试，若源文件已被外部修改则需人工核对。
- 响应含新 `memory_unit_id`、`revision_id`、`edit_version`、`revision_changed`、`index_status`、`source_status` 和服务端规范化后的 `document`。`source_status` 为 `ready`、`pending` 或 `not_applicable`。

由 Markdown 目录同步的文档，App 编辑正文会原子写回源 `.md` 文件；标题和作者由源文件管理，不能在 App 中修改。写回前后均比较源文件内容，检测到外部更改时拒绝覆盖。源文件待写入期间目录同步会停止，以免把尚未落盘的 App 编辑覆盖回去。旧 Windows 根路径尚未迁移的文档无法在当前 Mac 写回，须等来源映射确认后再处理。

不要将令牌写入 URL、日志或公开代码仓库。浏览器扩展也使用同一写令牌进行导入。

旧版浏览器导入 `POST /api/ingest/browser-conversation` 另有独立响应语义：`200` 表示本次归档与索引完成；`202`、`index_status=pending` 表示归档已提交但索引待补建，不能当作可立即搜索。`202` 不承诺自动后台重试。文件导入 CLI 同样输出 `Index: ready/pending`。

## 错误格式

v1 应用层错误使用 `{"code":"...","message":"..."}`。常见状态码为 `400`（参数错误）、`401`（写令牌无效）、`403`（非本机请求或 Host）、`404`（不存在）、`405`（方法不支持）、`409`（文档或源文件冲突）、`413`（请求体过大）、`428`（缺少版本凭据）、`500`（内部错误）、`503`（状态或索引不可用）。新客户端应根据状态码和 `code` 判断错误，不解析 `message` 文案；HTTP 服务器在请求进入 Flask 之前拒绝的报文可能不是此格式，客户端仍须处理非 JSON 错误体。

旧 `/api/...` 路由为网页和浏览器扩展保留，HTML 返回值不属于 v1 契约。破坏性接口变更应使用新的版本前缀。
