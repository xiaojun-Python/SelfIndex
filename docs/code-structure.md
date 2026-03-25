# SelfIndex 项目代码结构详解

## 1. 项目概述

SelfIndex 是一个**个人记忆系统**，核心目标是：
- 保存原始资料 (Archive Layer)
- 生成可检索的记忆单元 (Memory Layer)  
- 通过向量搜索找回内容，并能回溯到原文

---

## 2. 完整目录结构

```
SelfIndex/
├── app/                          # Web 服务层（Flask）
│   ├── __init__.py               # Flask 应用工厂 create_app()
│   ├── main.py                   # 开发入口，运行 `python -m app.main`
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py             # 所有路由和视图逻辑（核心）
│   ├── core/
│   │   ├── __init__.py
│   │   └── settings.py           # 集中配置管理
│   ├── static/
│   │   └── css/
│   │       └── custom.css        # 自定义样式
│   └── templates/                # HTML 模板
│       ├── base.html             # 基础模板
│       ├── index.html            # 首页（搜索界面）
│       ├── search_results.html   # 搜索结果片段
│       ├── document_detail.html  # 文档详情
│       ├── document_form.html    # 文档编辑表单
│       ├── add_form.html         # 添加数据表单
│       └── close_modal.html
│
├── engine/                       # 数据模型、检索与记忆链路（核心）
│   ├── __init__.py
│   ├── database.py               # SQLite + Chroma 访问层（最重要）
│   ├── retriever.py              # 检索层逻辑，向量搜索封装
│   ├── embedder.py               # 向量嵌入模型管理
│   ├── chunker.py                # 文本分块策略
│   ├── memory.py                 # 记忆单元构建工具
│   ├── bootstrap.py              # 启动时自举旧数据
│   ├── init_db.py                # 数据库 Schema 初始化
│   └── query_syntax.py           # 解锁式查询语法解析
│
├── scripts/                      # 导入与格式解析脚本
│   ├── __init__.py
│   ├── import_exports.py         # 导入导出数据
│   ├── backfill_recall_domains.py # 回填召回域
│   ├── format_timestamp.py
│   └── parsers/
│       ├── __init__.py
│       ├── chatgpt_parser.py
│       ├── deepseek_parser.py
│       └── grok_parser.py
│
├── tests/                        # 单元测试
│   ├── test_memory_pipeline.py
│   ├── test_unlock_query.py
│   └── test_backfill_recall_domains.py
│
├── data/                         # 运行数据
│   ├── selfindex.db              # SQLite 数据库
│   ├── chroma_db/                # Chroma 向量数据库
│   └── raw_exports/              # 原始导出文件
│
├── docs/                         # 项目文档
├── .env                          # 环境变量配置
├── requirements.txt              # 依赖
└── README.md
```

---

## 3. 路由和视图逻辑

**入口文件**: `app/api/routes.py` (345 行)

| 路由 | 函数 | 说明 |
|------|------|------|
| `GET /` | `index()` (在 `__init__.py`) | 首页 |
| `GET /api/search` | `search_view()` | 旧版搜索（返回 HTML） |
| `GET /api/update_filters` | `update_filters()` | 更新过滤条件 |
| `GET /api/memory/search` | `search_memory_view()` | **新版 JSON 检索接口** |
| `GET /api/memory/<id>` | `memory_unit_detail()` | 记忆单元详情 |
| `GET /api/view/<chunk_id>` | `view_document()` | 查看文档（按 chunk） |
| `GET /api/edit/<chunk_id>` | `edit_document()` | 编辑表单 |
| `PUT /api/document/<chunk_id>` | `update_document()` | 保存编辑 |
| `GET /api/metadata/fields` | `get_metadata_fields()` | 获取元数据字段 |
| `GET /api/metadata/values/<field>` | `get_metadata_values()` | 获取字段值列表 |

---

## 4. 核心运行逻辑

### 4.1 应用启动流程 (`app/__init__.py`)

```python
create_app() 执行:
1. 创建 Flask 实例
2. 加载配置 (settings)
3. 初始化 SQLite (DatabaseManager)
4. 初始化 Chroma (VectorManager)
5. 自举旧数据 (bootstrap_legacy_memory_layer)
6. 预热搜索栈 (warm_up_search_stack)
7. 注册蓝图 (bp)
```

### 4.2 数据流

```
用户查询 
  → routes.py:search_view()
  → retriever.py:search()
  → retriever.py:search_memory()
  → VectorManager.search() (Chroma 向量搜索)
  → DatabaseManager.get_memory_unit_detail() (SQLite 回溯)
  → 返回结果
```

### 4.3 两套数据模型

**新模型** (当前推荐):
- `raw_documents` - 原始文档存档
- `memory_units` - 记忆单元（可检索的 chunks）

**旧模型** (兼容层):
- `conversations` - 对话
- `messages` - 消息
- `chunks` - 文本块

---

## 5. 数据库 Schema (`engine/init_db.py`)

**新模型表**:
```sql
raw_documents     -- 原始文档存档
memory_units      -- 记忆单元（关联 raw_documents）
```

**旧模型表** (兼容):
```sql
conversations     -- 对话
messages          -- 消息
chunks            -- 文本块（关联 messages）
```

**辅助表**:
```sql
import_logs        -- 导入日志
```

---

## 6. 前端文件

| 文件 | 说明 |
|------|------|
| `templates/base.html` | 基础模板，使用 Pico CSS + HTMX |
| `templates/index.html` | **主搜索页面**（包含完整 JS 交互逻辑） |
| `templates/search_results.html` | 搜索结果 HTML 片段 |
| `static/css/custom.css` | 自定义样式 |

**前端技术栈**:
- **Pico CSS** - 轻量级 CSS 框架
- **HTMX** - 高效的 AJAX 交互（无需完整 SPA）
- **原生 JavaScript** - 模态框、浮动按钮等交互

---

## 7. 关键模块说明

| 模块 | 路径 | 职责 |
|------|------|------|
| `EmbeddingManager` | `engine/embedder.py` | 封装 HuggingFace embedding 模型调用 |
| `DatabaseManager` | `engine/database.py` | SQLite 所有 CRUD 操作 |
| `VectorManager` | `engine/database.py` | Chroma 向量库封装 |
| `smart_chunking` | `engine/chunker.py` | 文本智能分块 |
| `build_memory_units` | `engine/memory.py` | 从原文档构建记忆单元 |
| `parse_unlock_prefixes` | `engine/query_syntax.py` | 解锁式查询语法解析 |

---

## 8. 配置管理 (`app/core/settings.py`)

关键配置项：
- `sqlite_db_path` - SQLite 路径
- `chroma_db_path` - Chroma 路径
- `embedding_model` - 嵌入模型 (默认 `BAAI/bge-small-zh-v1.5`)
- `embedding_device` - 设备 (`cuda` 或 `cpu`)
- `unlock_prefix_identity` / `unlock_prefix_sensitive` - 解锁前缀
- `secret_key`, `debug`, `host`, `port` - Flask 运行配置

---

## 9. 运行方式

```bash
# 启动 Web 服务
python -m app.main

# 导入 ChatGPT 导出数据
python -m scripts.import_exports --file data/raw_exports/xxx.json

# 回填召回域
python -m scripts.backfill_recall_domains --dry-run  # 预览
python -m scripts.backfill_recall_domains            # 执行

# 运行测试
python -m unittest discover -s tests -v
```

---

## 10. 系统架构图

```
┌─────────────────────────────────────────────────────────────┐
│                      用户 (浏览器)                           │
│                    Pico CSS + HTMX                         │
└─────────────────────┬───────────────────────────────────────┘
                      │ HTTP 请求
┌─────────────────────▼───────────────────────────────────────┐
│                  Flask Web 层                               │
│          app/api/routes.py (路由 + 视图逻辑)                │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                  应用初始化 (app/__init__.py)                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ SQLite 初始化 │  │ Chroma 初始化 │  │ 自举旧数据        │   │
│  │DatabaseManager│  │VectorManager │  │bootstrap_legacy  │   │
│  └──────────────┘  └──────────────┘  └──────────────────┘   │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                 引擎层 (engine/)                             │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────────┐  │
│  │embedder  │ │database  │ │ retriever│ │ memory.py      │  │
│  │ 嵌入模型  │ │ SQLite   │ │ 向量检索  │ │ 记忆单元构建   │  │
│  └──────────┘ └──────────┘ └──────────┘ └────────────────┘  │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                    数据层                                   │
│  ┌──────────────────────┐  ┌───────────────────────────┐   │
│  │  SQLite (selfindex.db)│  │  Chroma (chroma_db/)      │   │
│  │  - raw_documents      │  │  向量嵌入存储              │   │
│  │  - memory_units       │  │                           │   │
│  │  - conversations      │  │                           │   │
│  │  - messages/chunks    │  │                           │   │
│  └──────────────────────┘  └───────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 总结

这是一个**双模型并行**的记忆系统：
1. **旧模型**维持现有 Web UI 正常工作
2. **新模型**（raw_documents + memory_units）提供更清晰的分层架构

核心向量搜索依赖 **Chroma**，嵌入模型使用 **BAAI/bge-small-zh-v1.5**。前端使用轻量级的 **HTMX** 实现动态交互，避免了复杂 SPA 架构。
