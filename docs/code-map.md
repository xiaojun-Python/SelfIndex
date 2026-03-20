# 代码地图

这份文档不是讲理念，而是讲“代码都放在哪、该从哪开始看”。

## Web 层

### `app/main.py`

本地开发入口。

### `app/__init__.py`

应用工厂，负责把这些东西装起来：

- 配置
- SQLite
- Chroma
- 启动自举逻辑

### `app/api/routes.py`

路由总入口。

里面同时有：

- 旧 Web 页面继续使用的接口
- 新记忆链路的 JSON API

## 配置层

### `app/core/settings.py`

项目的环境变量、路径和服务参数都在这里集中读取。

## 引擎层

### `engine/init_db.py`

定义数据库 schema。

如果你想知道“系统现在有哪些表”，先看这里。

### `engine/database.py`

最核心的数据访问层。

如果你想知道：

- 数据怎么写进 SQLite
- 向量怎么写进 Chroma
- 新旧两套模型怎么共存

就看这个文件。

### `engine/bootstrap.py`

启动时做的额外工作：

- 旧数据投影到新模型
- 预热 embedding

### `engine/chunker.py`

文本切分。

### `engine/memory.py`

把原始文档变成记忆单元。

### `engine/retriever.py`

搜索与回溯逻辑。

## 脚本层

### `scripts/import_legacy_data.py`

目前最重要的导入入口。

### `scripts/parsers/`

不同导出格式的解析器。

## 测试层

### `tests/test_memory_pipeline.py`

最小记忆链路测试。

它验证的是：

- 能导入
- 能生成新层数据
- 能检索
- 能回溯

## 推荐阅读顺序

如果你想自己系统理解当前项目，建议按下面顺序读：

1. `README.md`
2. `docs/current-system.md`
3. `app/__init__.py`
4. `engine/bootstrap.py`
5. `engine/database.py`
6. `engine/memory.py`
7. `engine/retriever.py`
8. `scripts/import_legacy_data.py`
9. `tests/test_memory_pipeline.py`
