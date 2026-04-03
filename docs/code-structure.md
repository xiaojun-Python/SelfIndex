# 项目结构详解

## 顶层目录

```text
SelfIndex/
├── app/
├── data/
├── docs/
├── engine/
├── scripts/
├── tests/
└── README.md
```

## `app/`

Web 服务层。

```text
app/
├── __init__.py
├── main.py
├── api/
│   └── routes.py
├── core/
│   └── settings.py
├── static/
│   └── css/
│       └── custom.css
└── templates/
    ├── base.html
    ├── index.html
    ├── search_results.html
    ├── document_detail.html
    ├── document_form.html
    └── add_form.html
```

## `engine/`

核心后端逻辑。

```text
engine/
├── chunker.py
├── database.py
├── embedder.py
├── init_db.py
├── memory.py
├── protected_terms.py
├── query_syntax.py
├── retriever.py
└── sqlite_backend.py
```

## `scripts/`

围绕导入、同步、回填、维护的脚本。

```text
scripts/
├── backfill_recall_domains.py
├── build_embeddings.py
├── import_exports.py
├── manage_protected_terms.py
├── migrate_to_sqlcipher.py
├── sync_markdown_directory.py
└── parsers/
    ├── chatgpt_parser.py
    ├── deepseek_parser.py
    └── grok_parser.py
```

## `tests/`

当前最关键的自动化验证。

```text
tests/
├── test_backfill_recall_domains.py
├── test_markdown_sync.py
├── test_memory_pipeline.py
├── test_protected_terms.py
├── test_sqlcipher_migration.py
└── test_unlock_query.py
```

## 当前主路径

如果只抓当前最重要的 8 个文件：

1. `app/__init__.py`
2. `app/api/routes.py`
3. `engine/init_db.py`
4. `engine/database.py`
5. `engine/memory.py`
6. `engine/retriever.py`
7. `scripts/import_exports.py`
8. `scripts/sync_markdown_directory.py`

