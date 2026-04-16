![Index](docs/Index.png)

# SelfIndex

SelfIndex 是一个面向长期使用的个人记忆系统原型。

当前阶段的重点不是做“人格化 AI”，而是先把这条链路做稳：

- 保存原始资料
- 生成可检索的记忆单元
- 支持向量检索与回溯
- 支持可变来源的版本历史

## 当前核心结构

- `raw_documents`
  当前文档状态表。保存某条资料“现在是什么样子”。
- `raw_document_revisions`
  历史版本表。保存文档每次变化的快照，包括 `updated` 和 `deleted`。
- `memory_units`
  从当前 revision 派生出的记忆单元。用于检索、摘要、召回域控制。
- `protected_terms`
  受保护词规则表。数据库内以 `base64` 做弱混淆存储，不再以 `.env` 为主来源。
- `import_jobs`
  导入任务记录。

## 当前已完成能力

- ChatGPT / OpenAI 导出导入
- Markdown 目录同步
- Markdown 忽略规则
- Markdown 删除检测与 `inactive` 标记
- 独立 embedding workflow
- 解锁式查询
- SQLCipher 数据库支持

## 运行方式

启动 Web：

```bash
python -m app.main
```

启动桌面壳（系统托盘 + 后台页）：

```bash
python -m desktop.main
```

如果希望脱离终端窗口运行：

```bash
pythonw -m desktop.main
```

导入导出文件：

```bash
python -m scripts.import_exports --file data/raw_exports/your_export.json
```

只导入 archive / memory，不做 embedding：

```bash
python -m scripts.import_exports --file data/raw_exports/your_export.json --skip-embedding
```

单独构建 embeddings：

```bash
python -m scripts.build_embeddings
python -m scripts.build_embeddings --batch-size 16 --max-units 200
```

同步 markdown 目录：

```bash
python -m scripts.sync_markdown_directory --dir path/to/notes --ignore-file path/to/notes/.selfindexignore --skip-embedding
```

`.selfindexignore` 例子：

```text
archive/
templates/*
draft.md
```

查看 / 添加 protected terms：

```bash
python -m scripts.manage_protected_terms list
python -m scripts.manage_protected_terms add "敏感文本" --domain sensitive
python -m scripts.manage_protected_terms add "真实姓名" --domain identity
```

按规则回填 `recall_domain`：

```bash
python -m scripts.backfill_recall_domains --dry-run
python -m scripts.backfill_recall_domains
```

审计 ChatGPT 会话顺序 PoC：

```bash
python -m scripts.audit_chatgpt_order --conversation-id your-conversation-id --export data/raw_exports/chatgpt_export.json --browser-sample path/to/chatgpt_browser_sample.json
```

运行测试：

```bash
python -m unittest discover -s tests -v
```

## 解锁式查询

SelfIndex 支持基于 `recall_domain` 的解锁式查询。

- 默认查询只召回 `default`
- 显式前缀才会解锁受保护内容

当前前缀来自 `.env`：

```env
UNLOCK_PREFIX_IDENTITY=:
UNLOCK_PREFIX_SENSITIVE=!
```

## 当前建议阅读顺序

1. `docs/current-system.md`
2. `docs/architecture.md`
3. `docs/database-structure.md`
4. `docs/code-map.md`
