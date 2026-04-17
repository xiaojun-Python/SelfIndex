![Index](docs/Index.png)

# SelfIndex

SelfIndex 是一个 alpha 阶段的个人记忆系统，专注于保存原始资料、构建可搜索的记忆单元，并为变化的数据保持修订历史。

它目前还不是一个通用 AI Agent 产品。当前的目标是让记忆管道稳定可靠：

- 保存原始资料
- 保留当前状态和修订历史
- 派生可搜索的记忆单元
- 支持可追溯的本地向量检索
- 支持浏览器捕获的 AI 对话和文件导入

## 当前状态

SelfIndex 适合本地个人使用和持续实验。

已支持的功能：

- ChatGPT、Grok、DeepSeek 导出的json文件导入
- ChatGPT 浏览器捕获与半自动同步
- Grok 浏览器捕获与懒加载快照合并
- Markdown 目录同步
- 修订感知的原始文档存储
- 可追溯到源文档的本地向量检索
- 受保护的召回域和解锁式查询
- SQLite / SQLCipher 存储

目前仍是 alpha 软件：

- 浏览器捕获依赖页面结构，网站变更可能导致功能失效
- 多平台支持仍在早期阶段
- 对话回放界面尚未完成
- 桌面运行时是本地优先的，面向 Windows

## 推荐启动方式

使用统一服务脚本。它现在可以将桌面运行时、系统托盘图标和 Web 服务一起启动：

```powershell
.\scripts\selfindex_service.ps1 start
```

常用命令：

```powershell
.\scripts\selfindex_service.ps1 status
.\scripts\selfindex_service.ps1 restart
.\scripts\selfindex_service.ps1 stop
```

如果只需要 Web 服务而不需要托盘运行时：

```powershell
.\scripts\selfindex_service.ps1 start -NoTray
```

默认地址：

- Web UI: `http://127.0.0.1:5000/`
- 浏览器采集: `http://127.0.0.1:5000/api/ingest/browser-conversation`

## 主要工作流程

### 导入导出的对话文件

```bash
python -m scripts.import_exports --file data/raw_exports/your_export.json
```

导入时跳过嵌入：

```bash
python -m scripts.import_exports --file data/raw_exports/your_export.json --skip-embedding
```

后续再构建嵌入：

```bash
python -m scripts.build_embeddings
python -m scripts.build_embeddings --batch-size 16 --max-units 200
```

### 同步 Markdown 目录

```bash
python -m scripts.sync_markdown_directory --dir path/to/notes --ignore-file path/to/notes/.selfindexignore --skip-embedding
```

`.selfindexignore` 示例：

```text
archive/
templates/*
draft.md
```

### 管理受保护术语

```bash
python -m scripts.manage_protected_terms list
python -m scripts.manage_protected_terms add "敏感文本" --domain sensitive
python -m scripts.manage_protected_terms add "真实姓名" --domain identity
```

回填召回域：

```bash
python -m scripts.backfill_recall_domains --dry-run
python -m scripts.backfill_recall_domains
```

### 浏览器捕获

浏览器扩展位于：

`browser_capture/ai_capture_extension`

当前支持的浏览器：

- ChatGPT：新增消息的增量同步
- Grok：懒加载历史的快照合并

该扩展目前面向本地采集到运行中的 SelfIndex 实例。

## 检索模型

SelfIndex 使用召回域来控制敏感内容的检索。

- 默认查询只检索 `default` 域
- 显式前缀可解锁受保护的域

当前前缀在 `.env` 中配置：

```env
UNLOCK_PREFIX_IDENTITY=:
UNLOCK_PREFIX_SENSITIVE=!
```

## 文档

推荐阅读顺序：

1. `docs/current-system.md`
2. `docs/architecture.md`
3. `docs/database-structure.md`
4. `docs/code-map.md`

## 运行测试

```bash
python -m unittest discover -s tests -v
```

## 项目定位

SelfIndex 最好的描述是：

- 本地优先的个人记忆原型
- 修订感知的归档加检索系统
- 活跃的研究和实现仓库

它目前还不应作为成熟的终端用户产品呈现。
