# SelfIndex

SelfIndex 是一个面向长期使用的个人记忆系统原型。  
当前阶段的目标不是做一个“会扮演人格的 AI”，而是先把最小记忆链路做扎实：能保存原始资料、能生成可检索的记忆单元、能通过向量搜索找回内容，并且能回溯到原文。

## 当前状态

目前已经完成第一阶段里“建立最小记忆链路”的核心骨架：

- 定义了 Archive Layer：`raw_documents`
- 定义了 Memory Layer：`memory_units`
- 保留了旧版 `conversations/messages/chunks` 作为过渡兼容层
- 支持导入至少一种数据源：ChatGPT / OpenAI 导出
- 支持把记忆单元写入 Chroma 向量库
- 支持最小 JSON 检索接口和旧 Web 搜索页面
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
│   └── selfindex.db     # SQLite 数据库
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
python -m scripts.import_legacy_data --file data/raw_exports/your_export.json
```

运行测试：

```bash
python -m unittest discover -s tests -v
```

## 接口

旧页面继续使用：

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

现在的 Web 用起来和旧版很像，这是正常的。  
这轮工作的重点不是“外观变化”，而是把内部结构从“聊天记录搜索工具”推进到“有 Archive / Memory 分层的记忆系统雏形”。

一句话说：

- 旧版更像“把对话切块后拿来搜”
- 现在开始变成“保存原始文档，再从原始文档中生成可重建的记忆单元”

这会直接决定后面能不能继续做摘要、标签、实体、关系、解释性排序，以及多数据源接入。
