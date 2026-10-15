# 索引一致性与模型切换

SQLite/SQLCipher 是归档与记忆单元的来源真相，Chroma 是可重建的检索索引。两者不支持原子提交：SQL 中的 `vector_deletion_outbox` 保留删除意图，新增向量仅在记忆单元仍属于活跃当前修订版时写入，并由 SQL 写锁协调。仍需审计发现旧版本遗留的孤儿、缺失向量或内容漂移。

## 只读对账

确认当前配置指向预期的 SQLite 和 Chroma 路径后运行：

```bash
.venv/bin/python -m scripts.repair_chroma_consistency
```

默认不执行修复：SQL 以 `mode=ro`、`query_only=ON` 连接，Chroma 只调用 `get_collection`、`count`、`get`。报告当前/已嵌入/待嵌入单元数、待删任务、孤儿与缺失 ID、待嵌入但仍有向量的 ID、正文与元数据漂移、SQL 模型版本分布及 Chroma 集合模型标识。Chroma 的 `PersistentClient` 初始化可能触碰其内部持久化文件，因此这不是文件系统级取证只读；严格取证请先在停服状态复制两库，再对副本运行。运行中跨库扫描也不是原子快照，可能出现瞬时差异。

## 旧索引认领模型

新集合在首次写入时自动记录 `selfindex_embedding_model`。非空的旧集合若无标识，检索和新增向量会停止，避免在未知模型上继续混用。只有在**确认旧向量确实由当前 `EMBEDDING_MODEL` 生成**之后才能认领；SQL 版本标签和正文对账无法从向量数值反推出模型。

1. 停止 SelfIndex 服务和所有导入/补建进程，备份 SQLite/SQLCipher 与 Chroma，确认两者路径及嵌入模型配置。
2. 运行上述对账。若存在孤儿、缺失、正文/元数据漂移、待删任务或当前单元模型版本混杂，先调查，不认领。
3. 审计干净且来源可证明时执行：

```bash
.venv/bin/python -m scripts.repair_chroma_consistency \
  --adopt-index-model 'BAAI/bge-small-zh-v1.5' \
  --confirm-offline-adoption
```

命令要求认领值与当前 `EMBEDDING_MODEL` 相同，并再次检查对账结果；只修改 Chroma 集合元数据，不重算向量。示例模型名仅适用于确实使用该模型的资料库。变更模型不是修改 `.env` 即可完成：必须规划完整重建/切换索引，不能把旧向量改贴新标签。

## 修复边界

`--drain-pending-deletions`、`--delete-orphans`、`--mark-missing-unembedded`、`--rebuild-missing` 都会修改资料库或索引。仅在停服、备份、确认目标路径和审计结果后执行；不要用真实资料库做试验。旧版本已遗留的孤儿不会自动进入新删除队列。若需重建，先处理模型版本与 Chroma manifest，再决定批量补建；不能在混合模型集合中直接补写。

`--repair-metadata --confirm-offline-repair` 可把当前 SQL 的标题、来源、作者、时间、摘要和召回域同步到已有 Chroma 向量，不重算 embedding。它会直接修改 Chroma，必须停服并持有可恢复的整套资料备份；先运行默认只读对账确认仅有可解释的元数据漂移。此步骤和模型认领必须分开执行。2026-09-28 在旧备份的隔离副本上验证过 3,936 条元数据漂移可清零，未执行真实库修复或认领。
