# SelfIndex
项目刚从旧有版本迭代，目前可以实现的功能是：导入从ChatGPT、Grok导出而来的对话jscon格式的数据，存储到SQLite数据库里，同时向量化保存，然后通过web页面检索展示出来。

SelfIndex 正在从旧的 `my_rag_story_lib` 原型项目重新整理为一个更清晰的项目结构，以便更容易地通过 API 和 LLM 编排进行扩展。

## 推荐的项目结构

```text
SelfIndex/
├── app/                 # Flask/FastAPI 服务层
│   ├── api/             # 路由定义
│   ├── core/            # 配置、未来 LLM 编排、提示词
│   ├── static/          # 现有 Flask UI 的静态资源
│   └── templates/       # 现有 Flask UI 的 HTML 模板
├── data/                # 本地数据，不纳入 Git 版本管理
│   ├── chroma_db/       # Chroma 持久化存储
│   ├── raw_exports/     # 来自 ChatGPT / Grok / DeepSeek 的原始导出
│   └── selfindex.db     # SQLite 结构化数据
├── engine/              # RAG 引擎
│   ├── chunker.py
│   ├── database.py
│   ├── embedder.py
│   ├── init_db.py
│   └── retriever.py
├── scripts/             # 导入和迁移工具
│   ├── parsers/
│   ├── format_timestamp.py
│   └── import_legacy_data.py
├── legacy/              # 归档的旧实现
├── .env.example
├── requirements.txt
└── README.md
```

## 为什么这个结构更好

- `app/` 现在专注于服务边界，而不是混和 UI、检索和存储代码。
- `engine/` 存放可复用的 RAG 核心代码，这使得后续迁移到 FastAPI 更加容易。
- `data/` 清晰地分离了运行时状态和源代码。
- `scripts/` 专门用于导入、清理和旧数据迁移工作。
- `legacy/` 保留了旧的 `my_rag_story_lib` 快照，同时不会阻塞新的项目结构。

## 针对原始方案的调整建议

- 目前保留 `app/templates/` 和 `app/static/`，因为现有的 Flask UI 在过渡期间仍然有用。
- 添加 `data/raw_exports/`，因为你现有的工作流程已经依赖于导出的归档文件。
- 在迁移期间保留 `legacy/` 文件夹，使重构工作保持安全和可追溯。

## 当前状态

- 旧代码已归档到 `legacy/my_rag_story_lib`。
- SQLite 数据已复制到 `data/selfindex.db`。
- Chroma 持久化数据已复制到 `data/chroma_db/`。
- 原始导出归档已复制到 `data/raw_exports/`。
- Flask 入口点现在是 `python -m app.main`。

## 安装

```bash
pip install -r requirements.txt
```

将 `.env.example` 复制为 `.env` 并根据需要调整配置值。

## 运行应用

```bash
python -m app.main
```

## 导入旧数据

```bash
python -m scripts.import_legacy_data --file data/raw_exports/chatgpt_data-2026-03-10.json
```

## 下一步建议

- 决定 `app/` 是继续保持 Flask 优先还是完全迁移到 FastAPI。
- 在确定提供商策略后，添加 `app/core/llm.py`。
- 在进行更深入的功能开发之前，先为导入、分块和检索添加测试。
