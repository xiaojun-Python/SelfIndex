
![Index.png](docs/Index.png)

# SelfIndex

SelfIndex 是一个面向长期使用的个人记忆系统原型。  
当前阶段的目标不是做一个“会扮演人格的 AI”，而是先把最小记忆链路做扎实：能保存原始资料、能生成可检索的记忆单元、能通过向量搜索找回内容，并且能回溯到原文。

## 当前状态

目前已经完成第一阶段里“建立最小记忆链路”的核心骨架：

- 定义了 Archive Layer：`raw_documents`
- 定义了 Memory Layer：`memory_units`
- 定义了导入任务层：`import_jobs`
- 支持导入至少一种数据源：ChatGPT / OpenAI 导出
- 支持把记忆单元写入 Chroma 向量库
- 支持最小 JSON 检索接口和当前 Web 搜索页面
- 支持从检索结果回溯到原始文档
- 提供了基础自动化测试

## 现在的项目结构

```text
SelfIndex/
├── app/                 # Web 服务层（Flask）
│   ├── api/             # 路由
│   ├── core/            # 配置
│   ├── static/          # 静态资源
│   └── templates/       # 页面模板
├── data/                # 本地运行数据
│   ├── chroma_db/       # 向量索引
│   ├── raw_exports/     # 导出文件
│   └── selfindex-encrypted.db  # SQLite / SQLCipher 数据库
├── docs/                # 项目说明文档
├── engine/              # 数据模型、检索与记忆链路
├── scripts/             # 导入与格式解析
├── tests/               # 基础测试
└── README.md
```

## 运行方式

安装依赖：

```bash
pip install -r requirements.txt
```

启动 Web：

```bash
python -m app.main
```

导入导出文件：

```bash
python -m scripts.import_exports --file data/raw_exports/your_export.json
```

如果你想先只保住数据、暂时跳过 embedding 和 Chroma 写入：

```bash
python -m scripts.import_exports --file data/raw_exports/your_export.json --skip-embedding
```

Embedding Workflow

```bash
python -m scripts.build_embeddings --batch-size 16 --max-units 200
python -m scripts.build_embeddings
```

运行测试：

```bash
python -m unittest discover -s tests -v
```

## 解锁式查询

SelfIndex 现在支持“解锁式查询”。

- 默认查询只会检索 `default` 召回域
- 带前缀的查询才会额外解锁受保护的召回域
- 当前内置的召回域包括 `default`、`identity`、`sensitive`

前缀由环境变量控制：

```env
UNLOCK_PREFIX_IDENTITY=:
UNLOCK_PREFIX_SENSITIVE=!
```

实际调用链是：

- `app/core/settings.py` 读取环境变量
- `engine/retriever.py` 把前缀配置传给 `engine/query_syntax.py`
- `engine/query_syntax.py` 只负责解析，不直接读取环境变量

这样做的好处是查询解析层保持纯粹，配置来源则统一留在 `settings`。

## Recall Domain

`memory_units.recall_domain` 用来表示一条记忆属于哪个召回域。

- `default`：默认可检索
- `identity`：需要显式解锁后才允许召回的身份类信息
- `sensitive`：需要显式解锁后才允许召回的敏感信息

这里存的是“域名”，不是某个具体命中的关键词。  
例如命中 `PROTECTED_TERMS` 后，`recall_domain` 应该写成 `identity` 或 `sensitive`，而不是直接写成某个具体词。

## 回填现有数据

如果你已经有旧数据，可以用回填脚本按当前 `PROTECTED_TERMS` 重算 `memory_units.recall_domain`。

先看会改多少条：

```bash
python -m scripts.backfill_recall_domains --dry-run
```

真正写入数据库：

```bash
python -m scripts.backfill_recall_domains
```

当前脚本规则是：

- `memory_units.content` 包含任一 `PROTECTED_TERMS`
- 命中则设为 `sensitive`
- 未命中则设回 `default`

## 接口

Web 页面入口：

- `GET /`
- `GET /api/search`

新的最小记忆接口：

- `GET /api/memory/search?query=...&limit=10`
- `GET /api/memory/<memory_unit_id>`

## 现在最值得先理解什么

如果你要重新建立对项目的掌控感，建议按这个顺序读：

1. [docs/current-system.md](/C:/Users/xiaoj/PycharmProjects/SelfIndex/docs/current-system.md)
2. [docs/code-map.md](/C:/Users/xiaoj/PycharmProjects/SelfIndex/docs/code-map.md)
3. [docs/architecture.md](/C:/Users/xiaoj/PycharmProjects/SelfIndex/docs/architecture.md)

## 这次重构的意义

这轮工作的重点不是“外观变化”，而是把内部结构从“聊天记录搜索工具”推进到“有 Archive / Memory / Import 分层的记忆系统雏形”。

一句话说：

- 旧版更像“把对话切块后拿来搜”
- 现在开始变成“保存原始文档，再从原始文档中生成可重建的记忆单元”

这会直接决定后面能不能继续做摘要、标签、实体、关系、解释性排序，以及多数据源接入。
