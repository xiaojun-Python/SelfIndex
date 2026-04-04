# 架构说明

## 系统目标

SelfIndex 的当前目标是：

- 尽量完整保存个人资料
- 用轻量可维护的方式建立可检索记忆
- 支持后续逐步增强，而不是一次性做成复杂平台

## 三层结构

### 1. Archive Layer

职责：

- 保存原始资料
- 保存当前文档状态
- 保存历史版本
- 处理新增 / 重复 / 更新 / 删除

当前落地：

- `raw_documents`
- `raw_document_revisions`

### 2. Memory Layer

职责：

- 从当前 revision 派生记忆单元
- 保存 `content` 与 `summary`
- 保存 `recall_domain`
- 为 embedding workflow 提供稳定输入

当前落地：

- `memory_units`
- `Chroma collection`

### 3. Recall Layer

职责：

- 查询解析
- 向量召回
- 召回域过滤
- inactive 文档过滤
- 回溯到原始文档

当前落地：

- `engine/query_syntax.py`
- `engine/retriever.py`
- `/api/memory/search`

## 设计选择

### 为什么要引入 revisions

因为 SelfIndex 现在已经不是一次性导入工具，而要支持：

- markdown 笔记反复修改
- 对话记录增量变化
- 未来更多会变化的数据源

如果没有 revisions，当前态一更新，旧内容就会被覆盖掉。

### 为什么 memory_units 仍然保留

因为它不是 archive，而是“记忆表示层”。

它负责：

- 搜索友好的切块
- 摘要
- 召回域
- embedding 状态

### 为什么 protected_terms 独立成表

因为 `.env` 只适合作配置，不适合作长期保存敏感规则。

所以现在：

- 规则存数据库
- 结果存 `memory_units.recall_domain`
- `.env` 只作为种子来源

## 当前技术边界

- SQLite / SQLCipher：结构化主存储
- Chroma：向量索引
- Flask：Web 层
- Python 脚本：导入、回填、同步、后台工作流雏形

## 当前刻意不做的事

- 不做复杂图谱关系系统
- 不做多用户平台抽象
- 不做“人格化代理”产品层
- 不做 watcher 优先于同步协议

