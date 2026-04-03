# 当前系统说明

这份文档回答一个问题：

SelfIndex 现在已经是什么，不再是什么。

## 当前阶段定义

SelfIndex 现在已经不再是“旧聊天记录检索工具的重命名版”。

它当前已经是一个具备以下边界的个人记忆系统原型：

- Archive：保存原始资料与当前状态
- Revision History：保存可变来源的历史版本
- Memory：从当前 revision 派生记忆单元
- Retrieval：向量检索 + 回溯
- Protection：受保护召回域与解锁式查询

## 关键数据流

### 导入时

```text
数据源
-> 标准化为 raw_document
-> upsert 当前 raw_document
-> 如内容变化则生成新的 raw_document_revision
-> 从当前 revision 构建 memory_units
-> 可选写入 Chroma 向量
```

### 检索时

```text
查询
-> 查询向量
-> Chroma 返回候选 memory_units
-> SQLite 批量取回 detail
-> 过滤 recall_domain / inactive document
-> 返回结果与回溯信息
```

### Markdown 同步时

```text
扫描目录
-> 忽略规则过滤
-> relative path 作为 external_id
-> 内容 hash 判断新增 / 跳过 / 更新
-> 丢失文件标记为 inactive + 追加 deleted revision
```

## 当前已经成立的设计原则

### 1. 当前态与历史态分离

- `raw_documents` 保存当前态
- `raw_document_revisions` 保存历史

这意味着 markdown、笔记文件、可变对话记录以后都能沿同一条线处理。

### 2. 记忆单元绑定 revision

`memory_units` 不只是挂在 `raw_document_id` 上，而是挂到 `revision_id`。

这意味着：

- 记忆知道自己来自哪个版本
- 文档更新后可以重建新的记忆单元
- 历史内容不需要覆盖掉

### 3. 受保护规则与受保护结果分离

- `protected_terms`：规则
- `memory_units.recall_domain`：结果

这样查询阶段不需要实时重判整库。

### 4. inactive 不等于删除

对于 markdown 同步这类可变来源：

- 文件消失时不物理删除历史
- 当前态标记 `is_active = 0`
- 检索默认忽略
- 历史仍保留

这和 SelfIndex 的“允许遗忘发生，而不是强制删除”一致。

## 当前还没有完成的部分

- Web 编辑 / 添加页面仍未完全收口
- 没有历史版本浏览 UI
- summary workflow 还没有正式独立出来
- 托盘 / 常驻后台还没开始做
- markdown 同步目前还是“脚本触发”，不是 watcher

## 当前最值得继续做的方向

1. Memory summary workflow
2. 更多数据源导入器
3. 设置页 / 任务状态
4. 历史版本浏览

