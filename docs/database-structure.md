# SelfIndex 数据库结构

这份文档描述的是 `data/selfindex.db` 当前实际使用到的 SQLite 结构，同时补充说明代码层正在维护的新模型、旧兼容层，以及数据库里仍然存在的历史遗留表。

## 总览

当前数据库可以分成三组：

1. 新记忆链路
   - `raw_documents`
   - `memory_units`

2. 旧 Web / 旧导入兼容层
   - `conversations`
   - `messages`
   - `chunks`
   - `import_logs`

3. 历史遗留表
   - `items`
   - `entities`
   - `links`

现在代码层主要围绕第一组工作，第二组仍然保留给旧页面和历史数据，第三组目前不在主链路里，但它们还真实存在于数据库文件中。

## 核心关系

### 新模型

```text
raw_documents (1) ────< memory_units (N)
```

- 一条 `raw_document` 表示一条原始文档记录
- 一条 `memory_unit` 表示从原始文档切分出来的一个可检索记忆单元
- `memory_units.raw_document_id -> raw_documents.raw_document_id`

### 旧兼容层

```text
conversations (1) ────< messages (N) ────< chunks (N)
```

- `conversations` 保存对话级信息
- `messages` 保存消息级信息
- `chunks` 保存旧链路里的切块结果

## 表结构

### `raw_documents`

当前原始文档层主表。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `raw_document_id` | `TEXT PRIMARY KEY` | 原始文档唯一 ID |
| `source` | `TEXT NOT NULL` | 数据来源，如 `chatgpt` |
| `source_type` | `TEXT NOT NULL` | 来源类型，如 `conversation_message` |
| `external_id` | `TEXT NOT NULL` | 来源系统的外部 ID |
| `root_document_id` | `TEXT` | 上层文档或对话 ID |
| `title` | `TEXT` | 标题 |
| `author` | `TEXT` | 作者或发送者 |
| `created_at` | `TEXT` | 原始创建时间 |
| `imported_at` | `DATETIME DEFAULT CURRENT_TIMESTAMP` | 导入时间 |
| `content` | `TEXT NOT NULL` | 原始正文 |
| `content_hash` | `TEXT NOT NULL` | 内容哈希 |
| `raw_payload` | `TEXT` | 原始结构化负载，通常是 JSON |
| `metadata_json` | `TEXT` | 扩展元数据，通常是 JSON |

约束：

- 主键：`raw_document_id`
- 唯一约束：`UNIQUE(source, external_id)`

索引：

- `idx_raw_documents_source_external_id`
- `idx_raw_documents_root_document_id`

### `memory_units`

当前记忆层主表。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `memory_unit_id` | `TEXT PRIMARY KEY` | 记忆单元唯一 ID |
| `raw_document_id` | `TEXT NOT NULL` | 对应原始文档 ID |
| `unit_index` | `INTEGER NOT NULL` | 在原始文档中的顺序 |
| `unit_type` | `TEXT NOT NULL DEFAULT 'chunk'` | 单元类型 |
| `recall_domain` | `TEXT NOT NULL DEFAULT 'default'` | 召回域，如 `default` / `identity` / `sensitive` |
| `content` | `TEXT NOT NULL` | 记忆单元正文 |
| `summary` | `TEXT` | 摘要 |
| `start_char` | `INTEGER NOT NULL` | 在原文中的起始位置 |
| `end_char` | `INTEGER NOT NULL` | 在原文中的结束位置 |
| `embedding_version` | `TEXT` | 当前向量模型版本 |
| `metadata_json` | `TEXT` | 扩展元数据，通常是 JSON |
| `created_at` | `DATETIME DEFAULT CURRENT_TIMESTAMP` | 创建时间 |
| `updated_at` | `DATETIME DEFAULT CURRENT_TIMESTAMP` | 更新时间 |
| `is_embedded` | `INTEGER DEFAULT 0` | 是否已完成向量化 |

约束：

- 主键：`memory_unit_id`
- 外键：`raw_document_id -> raw_documents.raw_document_id ON DELETE CASCADE`

索引：

- `idx_memory_units_raw_document_id`
- `idx_memory_units_is_embedded`

说明：

- `recall_domain` 是后期补进来的轻量迁移字段，旧数据库会在启动时自动补列
- Chroma 向量库通常使用 `memory_unit_id` 作为向量 ID

### `conversations`

旧版对话级表，主要用于兼容旧 Web 结构。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `conversation_id` | `TEXT PRIMARY KEY` | 对话 ID |
| `title` | `TEXT` | 对话标题 |
| `created_at` | `TEXT` | 对话创建时间 |
| `source` | `TEXT` | 来源 |
| `raw_meta` | `TEXT` | 原始元数据 |

### `messages`

旧版消息级表。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `message_id` | `TEXT PRIMARY KEY` | 消息 ID |
| `conversation_id` | `TEXT` | 所属对话 |
| `sub_title` | `TEXT` | 子标题 |
| `sender_type` | `TEXT` | 发送者类型 |
| `content` | `TEXT` | 正文 |
| `content_length` | `INTEGER` | 正文长度 |
| `model` | `TEXT` | 模型名 |
| `content_hash` | `TEXT` | 内容哈希 |
| `sequence` | `INTEGER` | 顺序号 |
| `timestamp` | `TEXT` | 消息时间 |

约束：

- 外键：`conversation_id -> conversations.conversation_id`

索引：

- `idx_messages_conversation_id`
- `idx_content_hash`

### `chunks`

旧版切块表，仍然被旧页面编辑和查看流程使用。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `chunk_id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | 切块 ID |
| `message_id` | `INTEGER NOT NULL` | 所属消息 ID |
| `chunk_index` | `INTEGER NOT NULL` | 在消息中的顺序 |
| `start_char` | `INTEGER NOT NULL` | 起始位置 |
| `end_char` | `INTEGER NOT NULL` | 结束位置 |
| `content` | `TEXT NOT NULL` | 切块内容 |
| `hash` | `TEXT` | 内容哈希 |
| `embedding_version` | `TEXT DEFAULT 'bge-small-zh-v1.5'` | 向量版本 |
| `created_at` | `DATETIME DEFAULT CURRENT_TIMESTAMP` | 创建时间 |
| `updated_at` | `DATETIME DEFAULT CURRENT_TIMESTAMP` | 更新时间 |
| `is_embedded` | `INTEGER DEFAULT 0` | 是否已向量化 |

索引：

- `idx_chunks_item_id`

注意：

- 实际数据库里的 `chunks` 定义带有更早期遗留的外键痕迹，和当前代码里的 `init_db.py` 不完全一致
- 当前代码主要按字段访问它，而不是依赖这个旧外键定义

### `import_logs`

导入日志表。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `import_id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | 导入记录 ID |
| `source` | `TEXT` | 导入来源 |
| `file_name` | `TEXT` | 文件名 |
| `import_time` | `DATETIME DEFAULT CURRENT_TIMESTAMP` | 导入时间 |
| `records_count` | `INTEGER` | 记录数 |
| `status` | `TEXT DEFAULT 'success'` | 状态 |
| `error_message` | `TEXT` | 错误信息 |
| `notes` | `TEXT` | 备注 |

索引：

- `idx_import_logs_import_time`

## 历史遗留表

这些表当前不在主代码路径里，但仍存在于数据库中。

### `items`

更早期的原始长文本表。

主要字段：

- `item_id`
- `user_id`
- `title`
- `sender`
- `timestamp`
- `content`
- `hash`
- `created_at`
- `updated_at`

### `entities`

更早期的实体表。

主要字段：

- `entity_id`
- `name`
- `type`
- `description`
- `created_at`

### `links`

更早期的关系表。

主要字段：

- `link_id`
- `entity_a_id`
- `entity_b_id`
- `chunk_id`
- `item_id`
- `relation_type`
- `weight`
- `created_at`

相关索引：

- `idx_links_entity_a`
- `idx_links_entity_b`
- `idx_links_item_id`

## 向量库对应关系

除了 SQLite 之外，项目还维护一个 Chroma 持久化目录：`data/chroma_db/`。

当前约定是：

- Chroma collection 名称：`my_knowledge_chunks`
- 向量 ID：通常使用 `memory_unit_id`
- metadata：通常保存 `raw_document_id`、`title`、`source`、`source_type`、`author`、`created_at`、`summary`、`recall_domain`

也就是说：

- SQLite 负责结构化真相和可追溯关系
- Chroma 负责向量召回
- 最终展示结果时，会从 Chroma 命中再回查 SQLite 取完整细节

## 当前代码的真实关注点

如果从“现在还在维护什么”这个角度看，最重要的是：

1. `raw_documents`
2. `memory_units`
3. `conversations/messages/chunks` 兼容层

如果从“数据库文件里还残留了什么历史结构”看，则还包括：

1. `items`
2. `entities`
3. `links`

这也意味着：以后如果你要继续清理数据库结构，这三张历史遗留表值得被单独评估，而不应该和当前主链路混在一起理解。
