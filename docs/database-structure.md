# 数据库结构

当前主数据库是 SQLite / SQLCipher。

## 当前主表

| 表名 | 作用 |
| --- | --- |
| `raw_documents` | 当前文档状态 |
| `raw_document_revisions` | 历史版本快照 |
| `memory_units` | 当前 revision 派生的记忆单元 |
| `protected_terms` | 受保护规则表 |
| `import_jobs` | 导入任务记录 |

## 关系

```text
raw_documents (1) ────< raw_document_revisions (N)
raw_document_revisions (1) ────< memory_units (N)
import_jobs (独立)
protected_terms (独立规则表)
```

## `raw_documents`

当前态表。

关键字段：

- `raw_document_id`
- `source`
- `source_type`
- `external_id`
- `root_document_id`
- `title`
- `author`
- `content`
- `content_hash`
- `current_content_hash`
- `latest_revision_id`
- `is_active`
- `raw_payload`
- `metadata_json`

说明：

- `UNIQUE(source, external_id)`
- `is_active = 0` 表示文件已被同步器判定为失活

## `raw_document_revisions`

历史版本表。

关键字段：

- `revision_id`
- `raw_document_id`
- `content`
- `content_hash`
- `title`
- `author`
- `raw_payload`
- `metadata_json`
- `change_type`
  - `created`
  - `updated`
  - `deleted`
- `is_current`
- `captured_at`

说明：

- 一个 `raw_document` 可以有多个 revisions
- 当前 revision 由 `is_current = 1` 标记

## `memory_units`

记忆单元表。

关键字段：

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

说明：

- 当前主检索只面向 active document 的 current revision
- `recall_domain` 是最终打标结果，不是规则本身

## `protected_terms`

受保护规则表。

关键字段：

- `term_id`
- `term_encoded`
- `encoding`
- `domain`
- `is_active`
- `notes`
- `created_at`
- `updated_at`

说明：

- 当前 `term_encoded` 使用 `base64`
- 这是弱混淆，不是强加密
- 程序读取时会解码后参与匹配

## `import_jobs`

导入任务记录。

关键字段：

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

## 当前检索默认行为

检索默认会排除：

- `raw_documents.is_active = 0`
- 不符合解锁域的 `memory_units`

这意味着被删除或失活的 markdown 不会继续出现在默认召回里，但历史 revision 仍然存在。
