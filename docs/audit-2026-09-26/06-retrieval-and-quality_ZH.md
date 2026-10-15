# 检索、性能与质量验证

日期：2026-09-26。没有使用私人查询构建外部评测，没有把真实正文写入报告。以下行为复现使用假模型和假向量，不需要下载模型或更改真实索引。

## 1. 当前检索路径

解析解锁前缀 -> embedding query -> Chroma 取 top-N -> SQL 批量读取 -> 过滤失活/历史/recall_domain -> 格式化结果 -> 截断 limit。语义检索为主，summary 是截短正文，不是生成式摘要。score 是 cosine distance，越低越相近，不是概率/置信度。

源码：[search_memory](../../engine/retriever.py#L114)、[VectorManager](../../engine/database.py#L17)、[EmbeddingManager](../../engine/embedder.py)。

## 2. 已复现问题

统一脚本：[verify_findings.py](../../docs/audit-2026-09-26/verify_findings.py)。输出 RUN-01、RUN-02 和以下 RET 项；这些脚本记录当前缺陷行为，未来修复后输出理应改变，不能把保持缺陷当验收。

### RET-01 / P2：冷启动并发重复构造模型

EmbeddingManager.model 以 `if self._model is None` 延迟初始化，没有锁。两线程 Barrier 模型替身实测 constructors=2、distinct_instances=true。生产有 4 个请求线程，因此首次多个请求可同时进入构造；真实内存峰值未测，不声称一定 OOM。

建议一次初始化并共享结果/错误，有界等待，失败允许后续受控重试；不要把整个推理串行化来掩盖初始化竞态。验收多线程首次调用只有一次构造、异常不永久卡锁，health 不被模型加载绑定。

### RET-02 / P2：先取候选再过滤，可能漏掉实际存在的公开结果

`n_results=max(limit,min(default_search_k,limit*10))`。合成前 100 条 identity 域、排名 101 为 default：普通查询 limit=10 请求 100 候选，返回 0；同样查询 limit=11 请求 110，返回 1。这不是语义相关性不够，而是候选集合提前截断。

建议对可用于向量过滤的状态/domain 提前约束，并在 SQL 复核；或有界自适应补取，不能无限扩张到全库。同步状态/元数据正确性先解决。验收 protected/历史/失活候选占前列时仍可返回满足域和 limit 的公开结果，无越权显示。

### RET-03 / P2：同一结果会混用旧向量正文和当前 SQL 预览

结果 content 优先 Chroma documents，summary 优先 Chroma metadata，preview 来自 SQL 当前 memory_content。合成旧向量/新 SQL 后输出 OLD_VECTOR_TEXT、OLD_SUMMARY、CURRENT_SQLITE_TEXT。

建议 SQL 作为展示内容事实来源，向量只提供 ID/距离及需要的过滤字段；索引过期状态可见。验收陈旧向量存在时不展示已被替换的正文，旧版本与当前版本处理一致。与 DATA-03 和 DATA-08 一起设计修复，但可先单独改展示来源并补回归测试。

## 3. 代码确认与设计缺口

- **RET-04 / P2：模型/索引版本缺少强校验。** 固定 collection `my_knowledge_chunks`，配置模型可变，没有显式索引 manifest/版本隔离。相同维度不同模型可能混合不可比向量，不同维度可能报错。真实快照版本一致，不能说当前已经混用。验收改模型不会继续静默写旧集合；重建、切换、回退有步骤。
- **RET-05 / P2：日期排序可能丢失时区语义。** normalize_timestamp 优先按前 19 字符解析。对带偏移或不同来源时间，应有 UTC 标准值和展示值，不直接比较本地壁钟字符串。待补跨时区 synthetic fixtures，未断言真实现有记录已排序错误。
- **RET-06 / P3：搜索质量未形成可测目标。** 没有独立标注集、词法召回兜底、结果按原文去重和可解释的命中片段选择。同一长文的多个 chunk 可占列表；先确定用户需要“段落”还是“文档”结果，不马上上复杂 reranker。
- **RET-07 / P2：负载与超时。** import/embedding 在同步请求内执行，GUI generation 丢弃旧响应但不取消服务工作；见 UI-04/RUN-01。先限制客户端并发和重任务调度，监测队列/超时，不能只增加 Waitress 线程数。

## 4. 测试覆盖的真实含义

本轮完整 unittest 69/69 通过，覆盖解析、查询前缀、导入维护、编辑恢复、SQLCipher 迁移、桌面 Markdown/偏好/单实例等。许多使用 fake embedder/向量字典；不能据此推导真实 Chroma 重复 add、SQLite/Chroma 跨库故障、并发编辑或 App 打包通过。

建议测试分层：

1. 纯函数与协议单元测试，快速默认执行。
2. 临时真实 SQLCipher + 临时 Chroma + 固定假 embedding 的集成测试，覆盖持久化及重复 ID 语义，不依赖模型下载。
3. 多进程单 profile/写锁测试，故障注入测试，恢复一致性检查。
4. Qt 离屏状态机测试；独立真实 macOS 生命周期/可访问性测试。
5. 明确许可的匿名化检索评测和性能基线，不把私人内容上传给外部服务。

## 5. 下一阶段测量方案

建立 20-50 条人工认可的固定查询，覆盖精确文件名、人名/术语、中英混合、日期、代码片段、多段长文、敏感域隐藏、空结果。记录 Recall@k、MRR、同文重复率、首屏可用性；样本小需说明偏差，避免凭几个好结果就升级模型。

性能分冷模型/暖模型，记录查询/详情/保存的 p50/p95、并发 1/2/4、排队、内存峰值和索引积压；硬件/数据量/版本随结果记录。禁止用一次 idle RSS 推断模型没有加载，禁止用 offscreen 合成内容渲染时间当全应用 SLA。

没有完成真实检索质量评测或并发性能压测。本轮可靠的输出是故障条件与复现，不是“性能已经达标”。

## 后续状态（sol，2026-09-27）

RET-03 已修：搜索结果的正文、摘要和预览均取 SQL 当前记忆单元，向量库只提供命中 ID 与距离。临时数据回归测试覆盖 Chroma 文本/摘要副本陈旧；隔离脚本现在三个字段均输出 `CURRENT_*`。这只修正展示一致性，不保证过期向量的排序质量或物理索引完整；RET-02、RET-04 仍待处理。

2026-09-27 第四批补充：写向量前现在复核单元在 SQL 中的 `embedding_version` 未变化，防止延迟任务跨版本误写；但尚无 Chroma 集合级模型 manifest，也未阻断“配置模型已切换、待补建单元仍标旧版本”的情况。RET-04 仍未关闭。
