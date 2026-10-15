# 数据身份、修订与一致性

日期：2026-09-26。数据子代理因额度中断未提交报告；本文由主代理依据只读快照、代码和临时数据库复现补齐。没有对真实数据执行同步、修复或迁移。

## 1. 真实数据快照

读取方式：直接 SQLCipher `mode=ro` / `query_only=ON`；Chroma 的 SQLite 文件以只读方式查看。没有实例化指向真实库的 DatabaseManager/PersistentClient。两库读取不是跨库原子快照，因此只说明检查时所见状态。

| 指标 | 结果 |
| --- | ---: |
| raw_documents | 8,000 |
| raw_document_revisions | 8,124 |
| memory_units（含历史） | 16,982 |
| 当前活跃 memory units | 16,520 |
| Chroma IDs | 16,520 |
| 当前单元缺失向量 / 向量无 SQL 对应 | 0 / 0 |
| 当前活跃待 embedding | 0 |
| 历史单元无向量 | 462，符合历史不参与当前检索，不是 462 条损坏 |
| latest revision 缺失 / current 数量异常 / 孤立 memory | 0 / 0 / 0 |
| import_jobs | 36，其中成功 35、失败 1；未调查该历史失败原因 |
| 两库 quick_check | ok |

来源：ChatGPT 3,231、DeepSeek 935、Grok 3,708、Markdown 126，均为活跃文档。全部 memory 的模型版本一致。126 篇 Markdown 的 root 仍为同一个 Windows 路径，该根目录在本机不存在。**数据目前快照一致，不等于以下故障路径安全。**

## 2. 可重复确认的问题

复现脚本：[verify_data_findings.py](../../docs/audit-2026-09-26/verify_data_findings.py)。只建立临时库/临时 Markdown 文件，使用假向量和假模型；输出不含用户内容。

### DATA-01 / P1：不同 Markdown 根目录的同名文件覆盖同一文档

证据：[build_raw_document](../../engine/memory.py#L59) 的 ID 为 source + source_type + external_id；[Markdown adapter](../../scripts/sync_markdown_directory.py#L66) 只将相对路径作为 external_id，root 不参与 ID。临时根 A 和根 B 的 same.md 得到完全相同 ID。

影响：同步第二个资料目录可以改变第一个目录的文档正文、root 和归属，不只是结果重复。建议引入稳定 source_instance_id，不直接以会变化的绝对路径充当永久身份。验收：两根同名文件独立；根迁移不复制/覆盖；既有 ID 引用有明确迁移兼容方案。不要直接批量改真实主键。

### DATA-02 / P1：不存在的根目录被视为空目录并执行失活

证据：[sync_markdown_directory](../../scripts/sync_markdown_directory.py#L112) 扫描前不验证根存在/可读/扫描完整，随后对不在扫描结果的文档失活。临时根第一次同步 1 篇，移除测试根再同步，返回 inactivated=1。

影响：外置盘未挂载、路径写错、目录临时不可用可能使资料从检索消失；不是物理删除正文。建议先验证根和扫描完整性，删除阶段支持 dry-run、数量阈值与确认。验收：缺根、权限错误、扫描中断不修改 SQL/向量；真正空目录的删除语义由显式策略决定。

### DATA-03 / P1：SQLite 回滚无法回滚事务内已经删除的向量

证据：[同步的事务及 delete_vectors](../../scripts/sync_markdown_directory.py#L122)。假向量库先完成删除再抛异常，实测 SQL 正文回到 Original，但旧向量缺失，且 SQL pending=0。常规 build_missing_embeddings 因而不会发现缺口。

建议将索引更新意图与正文一同提交，再幂等执行向量变更；失败保留可重试任务。验收：在事务前后、向量删除/添加、状态回写各阶段注入故障和模拟中断，重试后收敛且不丢可恢复正文。purge 脚本同样先删向量后做 SQL，应纳入共用故障测试，不能只修 Markdown 分支。

### DATA-04 / P2：未改变正文的保存会把 pending 误报 ready

证据：[save_document 的 no-reindex 分支](../../app/services/documents.py#L86)。第一次新正文保存因假模型失败返回 pending；再原样保存返回 ready，但 SQL 仍有 1 个未索引单元。

建议从真实当前索引状态派生响应，并提供明确可重试工作；不是无条件把相同内容标成功。验收：失败后无修改重试、重启后重试、metadata-only 修改均不误报 ready。202 不能让客户端误以为自动任务已经排队。

### DATA-05 / P1：旧详情/旧草稿可以覆盖另一个客户端的新内容

证据：[保存入口](../../app/services/documents.py#L24)、[详情读取](../../engine/retriever.py#L193)、[PUT](../../app/api/v1.py#L68)。没有 expected_revision 或 If-Match；历史 memory ID 仍可读取并提交更新。临时测试中 A、B 用同一个原始 ID 依次保存，B 的旧草稿被接受并成为最新内容。

建议读取返回 revision，更新在 SQL 事务内原子比较版本；冲突 409/412，保留客户端草稿。不能只在请求开头读取一次版本。验收：两个客户端从同版本开始，只有一个无冲突提交；另一个收到冲突并可合并；重试同一已成功请求不再造新修订。桌面单实例不能代替服务端并发保护。

### DATA-06 / P2 / 语义决策：修订是内容去重，不是完整事件历史

证据：[revision ID](../../engine/memory.py#L21) 来自正文哈希前 12 位，[upsert](../../engine/database.py#L250) 使用 INSERT OR REPLACE。临时 A -> B -> A 只有 2 行修订；仅改标题/作者会就地改当前修订。

如果“历史”承诺每一次编辑可审计，此实现不满足；如果只保留不同正文快照，则需明确告知。建议正文 blob 去重与 revision event 分开，metadata 修改是否形成事件由产品确定。验收：A-B-A、连续改标题、删除/恢复的历史语义都有测试。这里不把正常去重本身定为数据库损坏。

## 3. 代码确认/待补验证

- **DATA-07 / P2 / 产品边界未定义：本地编辑与来源同步冲突。** 桌面保存改数据库，不写回 Markdown 文件；再次同步旧源正文或重复导入旧导出可覆盖本地编辑。需决定只读来源、双向同步或本地覆盖层，禁止默认开启双向写回。验收以“导入 A -> App 改 B -> 再导入 A”为基础。
- **DATA-08 / P2 / 代码确认：导入 job failed 不代表归档回滚。** [import_exports](../../scripts/import_exports.py#L298) 先提交 SQL，后索引；后段失败会将整个 job 记为 failed。重新导入相同正文又不一定重做 embedding。保留正文是好事，但需分别显示 archived/indexed/failed、已处理数量及恢复动作；补中断后重入测试。
- **DATA-09 / P2 / 现场确认：Windows 根路径未完成映射。** 126 篇仍可由库内内容读取，但不等于源文件同步已迁移成功。先让用户指定真实 macOS 源目录，生成映射 dry-run，与 DATA-01 的身份方案一起处理，不能猜路径后同步。
- **DATA-10 / P2 / 代码确认：历史 chunk 与当前原文混合。** 详情不要求 revision_is_current，SQL join 同时返回历史 memory_content 和当前 raw_content。需明确历史详情还是重定向最新文档，避免用当前正文解释旧偏移。结合 DATA-05 验收，不另起一套版本系统。
- **待验证：同内容重新导入、回滚旧版本、仅 metadata 变化时的 Chroma add 行为。** 实际 VectorManager 使用 collection.add，部分 FakeVectors 相当于 upsert；不能凭假库测试证明真实重复 ID 更新正确。用临时 PersistentClient 集成测试核对，禁止针对真实库试验。

## 4. 恢复和迁移原则

现有同盘备份不是灾难恢复副本，且尚未做恢复演练。任何真实修复前：停止写入或取得独占维护锁，备份 SQL/向量/配置和必要密钥到受保护位置，记录版本和数量，在临时目录恢复并核对，再迁移。Chroma 可重建不代表原始资料、修订和身份映射可丢。

真实库构造器会初始化结构/种子数据，不适合只读审计；下一模型继续统计时应沿用只读连接。不要把“462 个历史无向量”交给 repair 自动补齐。

## 后续状态（sol，2026-09-26）

DATA-02 的缺根、扫描失败、扫描期间根目录被替换已加保护，并用临时数据库回归测试。扫描为空且已有文档时默认拒绝整批失活；用户确认后可用 `--allow-empty-source` 明确清空。原报告中的“缺根仍失活”是修复前证据；`verify_data_findings.py` 现在输出 `missing_root_rejected=true`、`document_still_active=true`。DATA-01 身份迁移和批量删除预览仍待处理；不要把 DATA-02 关闭理解为同步全流程已安全。

## 后续状态（sol，2026-09-27）

- **DATA-03：已缓解，未关闭。** Markdown 同步、按来源及日期清理均先提交 SQL，再删旧向量；事务回滚不再提前删向量。向量删除失败会明确报告“归档已提交”，新版本仍保持 pending。临时 SQLCipher + 真实临时 Chroma 的故障注入覆盖回滚、清理失败及重建后收敛；`verify_data_findings.py` 现在可见 `archive_committed=true`、`pending_units=1`。但索引操作意图尚未持久化为 outbox，提交后进程崩溃可能留下孤儿向量，须在独占维护窗口用一致性审计确认并清理；不要仅靠重复同步推断已收敛。
- **DATA-04：误报已修。** 未改变正文的保存从当前单元 `is_embedded` 派生状态；pending 不再变成 ready。未自动启动后台重试，`ready` 仍只反映 SQL 标记，物理 Chroma 缺项需要一致性审计。`verify_data_findings.py` 的两次状态均为 pending。
- **DATA-08：部分修复。** 导入先完成 SQL 归档，再执行可重试的向量阶段；索引失败记录 `index_pending` 并返回 `index_status=pending`，相同正文再次导入会重试未嵌入单元，Chroma 相同 ID 采用先删后加。浏览器 ingest 对已归档但待索引返回 202。导入任务表仍不是完整的归档/索引状态机；`--skip-embedding` 下 job 仍记 `success` 而响应为 pending；未覆盖跨进程崩溃恢复与单写者约束。
- **恢复顺序：** 先在无并发写入的维护窗口审计 SQL/Chroma ID 差异，再补建 pending，最后处理孤儿；不要对当前真实数据直接运行 repair、purge 或 sync。现有审计只比对 ID，不验证向量内容/模型版本。

## 第三批状态（sol，2026-09-27）

DATA-03 的删除侧持久恢复已加入：`vector_deletion_outbox` 与文档修改、Markdown 同步、导入及两个 purge 的 SQL 事务一起提交；即便本次没有打开 Chroma（例如 `--skip-embedding`），旧 ID 仍会排队。重放器以 `BEGIN IMMEDIATE` 串行领取每批任务，复核 ID 是否重新成为当前活跃版本；只删除不再当前的 ID，Chroma 删除成功后才从 outbox 确认。删除已执行但确认前退出可以重复执行。服务启动只重放删除，不主动加载模型；手动补建和显式维护命令也可重放。

临时 SQLCipher + 真实临时 Chroma 覆盖提交后未删除、删除后未确认、重新打开库、当前 ID 保护和 SQL 回滚；两个重放线程竞争使用临时 SQL 测试。此前“没有 outbox、重复同步不恢复”的说明是第二批历史状态，**不再代表当前代码**。仍需在独占维护窗口对既有库做迁移前备份和实际验证；新 outbox 不能倒推记录旧版本运行期间已遗留的孤儿。当前单写者约束只覆盖 outbox 领取与对应删除，不覆盖所有 Chroma 写入或索引模型切换；跨进程并发尚未做集成测试。完整崩溃恢复仍需 SQL/Chroma 对账及 pending embedding 补建。不要把这一阶段标记成 T04 全部完成。

维护入口：`python -m scripts.repair_chroma_consistency` 显示待删除任务数和 ID 差异；仅在确认资料库、备份并停止其他写入后，才显式加 `--drain-pending-deletions` 重放。新服务启动会尝试重放；若 Chroma 报错，服务仍启动、任务仍在 SQL 中，需下次启动、后续索引写入或手动维护重试。没有后台定时重试器。

## 第四批状态（sol，2026-09-27）

常规索引写入（编辑、导入、批量补建）已共用 `write_current_vectors`：embedding 可在锁外计算，真正写 Chroma 前使用 `BEGIN IMMEDIATE` 与删除 outbox 互斥；在锁内复核单元仍是活跃当前版本、正文和 `embedding_version` 未变且 SQL 仍待索引。写入的 Chroma 元数据从当前 SQL 构造，成功后才把当前单元标记为 embedded。延迟完成的旧任务不会重新写回历史向量；Chroma 已添加但 SQL 状态回写失败时仍可重试覆盖。维护命令的 `--delete-orphans` 也改为先持久排队，再由同一重放器删除。

临时真实 Chroma 覆盖编辑、导入和批量补建的晚完成竞争，另有写入/删除两个线程的锁竞争、回写失败重试、版本不符跳过与维护命令测试。**范围边界：**这不是模型级 manifest 校验，不能证明已有向量的内容/维度与当前模型一致；跨进程 Chroma 写入、长时间锁等待、旧版本留下的孤儿向量和服务真机重启尚未验收。DATA-05 的旧草稿覆盖属于 SQL 编辑版本契约，本轮未解决。真实库仍未执行 repair 或迁移。

## 第五批状态（sol，2026-09-27）

在第四批基础上，新增 Chroma 集合模型 manifest；新空集合首次写入记录模型，已有非空无标识集合需离线对账后显式认领，模型配置变更会阻断检索与新增向量。认领检查 SQL 当前单元模型版本一致、删除队列为空、ID/正文/元数据无漂移；但它不能证明向量数值确由该模型生成，仍需来源证据。默认维护命令的 SQL 连接使用 `mode=ro` 和 `query_only=ON`，Chroma 只调用读取接口；Chroma 客户端初始化不保证文件系统级只读，运行中扫描也不是跨库原子快照。使用方法见 `docs/index-integrity_ZH.md`。

临时库独立进程测试确认写入和删除重放在 SQL 写锁下串行，SQLCipher 只读模式、漂移识别和拒绝脏索引认领均有断言。完整测试 114 项通过。**仍未完成：**旧真实索引的备份、来源核对、离线认领与真机运行；旧孤儿不会自动进入新 outbox，也没有周期性自动重试。此前“只比对 ID”“未做跨进程测试”是早期阶段记录，现不代表当前代码。
