# 代码地图

这份文档回答：

“如果我要读当前项目，先看哪些文件最值。”

## 入口层

### `app/main.py`

本地运行入口。

### `app/__init__.py`

应用工厂。负责：

- 读取 settings
- 初始化 SQLite / SQLCipher
- 初始化 Chroma
- 注册 Flask 路由

## Web 层

### `app/api/routes.py`

当前最核心的 Web 路由文件。

包括：

- 搜索
- 查看详情
- 编辑保存
- JSON memory API

## 配置层

### `app/core/settings.py`

集中读取 `.env` 与默认配置。

重点看：

- 数据库路径
- Chroma 路径
- embedding 配置
- 解锁前缀

## 引擎层

### `engine/init_db.py`

当前 schema 与轻量迁移入口。

重点：

- `raw_documents`
- `raw_document_revisions`
- `memory_units`
- `protected_terms`
- `import_jobs`

### `engine/database.py`

当前最关键的后端文件之一。

负责：

- SQLite 读写
- revisions 落盘
- inactive 标记
- protected_terms 读写
- memory detail 批量读取
- Chroma 访问封装

### `engine/memory.py`

负责：

- 构建 `raw_document`
- 构建 `raw_document_revision`
- 构建 `memory_units`
- recall_domain 命中范围

### `engine/retriever.py`

负责：

- query 向量化
- Chroma 搜索
- recall_domain 过滤
- inactive 过滤
- 回溯结构组装

### `engine/query_syntax.py`

负责解锁式查询的前缀解析。

### `engine/protected_terms.py`

负责 `protected_terms` 的编码 / 解码辅助。

## 脚本层

### `scripts/import_exports.py`

导入导出文件的正式入口。

### `scripts/build_embeddings.py`

单独运行 embedding workflow。

### `scripts/sync_markdown_directory.py`

同步 markdown 目录，支持：

- 忽略规则
- 更新检测
- 删除检测

### `scripts/backfill_recall_domains.py`

按 `protected_terms` 回填 `memory_units.recall_domain`。

### `scripts/manage_protected_terms.py`

管理受保护词规则。

## 测试层

### `tests/test_memory_pipeline.py`

覆盖 archive -> memory -> retrieval 主链路。

### `tests/test_markdown_sync.py`

覆盖 markdown 同步、忽略规则、更新、删除检测。

### `tests/test_backfill_recall_domains.py`

覆盖 protected terms、回填、标题命中。

### `tests/test_unlock_query.py`

覆盖解锁式查询。

### `tests/test_sqlcipher_migration.py`

覆盖 SQLCipher 导出与迁移。

