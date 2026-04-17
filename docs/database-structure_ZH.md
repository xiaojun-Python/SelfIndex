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

## 关系模型

```text
raw_documents (1) ────< raw_document_revisions (N)
raw_document_revisions (1) ────< memory_units (N)
protected_terms（独立规则）
import_jobs（独立任务日志）
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
