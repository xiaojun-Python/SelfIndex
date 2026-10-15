# 数据库结构

主数据库是 SQLite 或 SQLCipher，取决于配置。

## 主要表

| 表 | 用途 |
| --- | --- |
| `raw_documents` | 当前文档状态 |
| `raw_document_revisions` | 历史快照 |
| `memory_units` | 从当前修订版派生的面向检索的分块 |
| `protected_terms` | 受保护的召回规则 |
| `import_jobs` | 导入任务历史 |
| `vector_deletion_outbox` | SQL 提交后待重放的 Chroma 删除意图 |
| `profile_identity` | 资料库的随机持久身份，用于本机客户端区分同步目标 |
| `markdown_sources` | 已注册 Markdown 根目录与身份命名空间 |
| `source_write_outbox` | App 编辑已入库、待写回源 Markdown 的持久意图 |

## 关系模型

```text
raw_documents (1) ────< raw_document_revisions (N)
raw_document_revisions (1) ────< memory_units (N)
protected_terms（独立规则）
import_jobs（独立任务日志）
vector_deletion_outbox（独立删除队列）
source_write_outbox（独立源文件写回队列）
markdown_sources（独立来源注册表）
```

## `raw_documents`

当前状态表。

重要字段：

- `raw_document_id`
- `source`
- `source_type`
- `external_id`
- `root_document_id`
- `sequence`
- `title`
- `author`
- `created_at`
- `content`
- `content_hash`
- `current_content_hash`
- `latest_revision_id`
- `edit_version`（每次有意义的当前状态变动递增，A→B→A 也不会复用旧版本）
- `is_active`
- `raw_payload`
- `metadata_json`

备注：

- `UNIQUE(source, external_id)` 是主要身份保护
- `root_document_id` 将属于同一对话的消息分组
- `sequence` 存储对话中的当前线性顺序（如适用）
- `is_active = 0` 表示当前状态应在默认检索中被忽略

## `raw_document_revisions`

修订历史表。

重要字段：

- `revision_id`
- `raw_document_id`
- `content`
- `content_hash`
- `title`
- `author`
- `created_at`
- `raw_payload`
- `metadata_json`
- `change_type`
- `is_current`
- `captured_at`

备注：

- 一个原始文档可以有许多修订版
- 当前修订版标记为 `is_current = 1`
- 浏览器捕获的纯序列调整目前只更新当前修订版元数据，而不创建新的内容修订版

## `memory_units`

面向检索的分块表。

重要字段：

- `memory_unit_id`
- `revision_id`
- `raw_document_id`
- `unit_index`
- `unit_type`
- `recall_domain`
- `content`
- `summary`
- `start_char`
- `end_char`
- `embedding_version`
- `metadata_json`
- `is_embedded`

备注：

- 记忆单元从当前修订版派生
- 检索默认只针对活跃文档
- `recall_domain` 是存储的结果标签，而非原始规则定义
- `embedding_version` 标识该单元的嵌入模型；Chroma 集合另以 `selfindex_embedding_model` 记录整体模型

## `vector_deletion_outbox`

归档变更在同一 SQL 事务中排入旧向量 ID。重放时持有 SQL 写锁，确认 ID 不再属于活跃当前修订版后删除 Chroma 向量，再确认队列项。删除失败不会丢失意图；SQL 与 Chroma 并非原子事务，仍需定期对账。

## `source_write_outbox`

App 编辑同步自 Markdown 目录的文档时，先在同一 SQL 事务中保存新正文与待写源文件意图。提交后核对源文件旧内容哈希，并用同目录临时文件原子替换；失败的意图留在队列，服务启动时重试。若源文件被外部编辑，拒绝覆盖并等待人工核对。待写期间目录同步拒绝运行，避免旧文件覆盖新归档。SQL 与文件系统不是单一原子事务。

## `markdown_sources`

第一个或旧版 Markdown 根目录保留既有原始文档 ID；其后的根目录使用根路径摘要作为命名空间，避免不同目录里的同名文件碰撞。旧 Windows 路径到 Mac 的身份迁移尚未执行。

## `protected_terms`

受保护的召回规则表。

重要字段：

- `term_id`
- `term_encoded`
- `encoding`
- `domain`
- `is_active`
- `notes`
- `created_at`
- `updated_at`

备注：

- 术语目前使用轻量级编码存储，而非强加密
- 规则持久化在数据库中，而非仅作为 `.env` 设置

## `import_jobs`

导入执行历史。

重要字段：

- `import_id`
- `source`
- `file_name`
- `file_path`
- `file_hash`
- `started_at`
- `finished_at`
- `raw_documents_count`
- `memory_units_count`
- `skipped_count`
- `status`
- `error_message`
- `import_config_json`
- `notes`

## 对话排序说明

类对话来源依赖 `root_document_id` 加 `sequence`。

当前行为：

- ChatGPT 导出在导入前重建顺序
- ChatGPT 浏览器同步通常增量追加新尾消息
- Grok 浏览器同步可能合并部分懒加载快照，然后使用重叠的 message id 作为锚点重新对齐 `sequence`

这意味着顺序作为一等字段存储在数据库中，即使原始浏览器来源只暴露了部分 DOM 快照。
