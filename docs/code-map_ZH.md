# 代码地图

本文档回答一个实际问题：

如果你刚接触这个仓库，哪些文件值得优先阅读。

## 入口点

### `app/main.py`

最小的本地 Web 入口点。

### `app/__init__.py`

应用工厂。

它组装了：

- 设置
- SQLite / SQLCipher
- Chroma
- Flask 路由

### `scripts/selfindex_service.ps1`

推荐的本地启动入口。

它管理：

- 统一启动
- 关闭
- 重启
- 状态检查

默认它启动桌面运行时和托盘，然后托盘启动本地 Web 服务。

## Web 层

### `app/api/routes.py`

主要 Flask 路由文件。

包含：

- 搜索路由
- 详情视图路由
- 编辑 / 更新路由
- 最小化 JSON 记忆 API
- 浏览器摄入端点

## 桌面运行时

### `desktop/main.py`

桌面运行时入口点。

设置：

- 系统托盘
- 后端控制窗口
- 单实例保护
- 统一运行时 pid 交接

### `desktop/controller.py`

控制本地服务进程和辅助命令。

重要功能：

- 启动和停止 Web 服务
- 重启行为
- 附加到已运行的监听器
- 运行时日志流

### `desktop/tray.py`

原生 Windows 托盘图标和弹出菜单。

## 设置

### `app/core/settings.py`

中央 `.env` 和默认配置加载器。

重要值包括：

- 数据库路径
- Chroma 路径
- 嵌入配置
- 解锁前缀
- 主机和端口

## 引擎层

### `engine/init_db.py`

模式初始化和轻量迁移。

重要表：

- `raw_documents`
- `raw_document_revisions`
- `memory_units`
- `protected_terms`
- `import_jobs`

### `engine/database.py`

核心后端持久层。

职责：

- SQLite 读写
- 修订存储
- 序列更新
- 非活跃标记
- 受保护术语存储
- 记忆详情加载
- Chroma 包装器集成

### `engine/memory.py`

构建规范化的原始文档、修订版和记忆单元。

### `engine/retriever.py`

检索组装层。

职责：

- 查询嵌入
- Chroma 搜索
- recall-domain 过滤
- 非活跃过滤
- 追溯载荷组装

### `engine/query_syntax.py`

用于 recall-domain 感知搜索的解锁前缀解析。

### `engine/protected_terms.py`

受保护术语的编码和解码辅助函数。

## 导入和同步脚本

### `scripts/import_exports.py`

导出的对话文件和浏览器载荷的主要导入入口。

### `scripts/parsers/chatgpt_parser.py`

ChatGPT 导出解析器，用于导出的对话序列重建。

### `scripts/parsers/browser_capture_parser.py`

浏览器捕获载荷的解析器。

现在支持来自多个平台的浏览器载荷，包括 ChatGPT 和 Grok。

### `scripts/parsers/grok_parser.py`

Grok 导出文件的解析器。

### `scripts/sync_markdown_directory.py`

Markdown 目录同步，带：

- 忽略规则
- 更新检测
- 缺失文件的非活跃检测

### `scripts/build_embeddings.py`

作为独立工作流运行嵌入。

## 浏览器捕获

### `browser_capture/ai_capture_extension/manifest.json`

Chrome 扩展清单文件。

### `browser_capture/ai_capture_extension/content.js`

支持的 AI 站点的 DOM 捕获逻辑。

目前用于：

- ChatGPT 可见对话捕获
- Grok 可见对话捕获

### `browser_capture/ai_capture_extension/popup.js`

弹出窗口逻辑，用于：

- 捕获
- 半自动同步
- Grok 快照合并行为
- 本地端点提交

## 测试

### `tests/test_browser_capture_parser.py`

涵盖浏览器载荷解析和来源映射。

### `tests/test_browser_sequence_merge.py`

涵盖基于锚点的懒加载浏览器来源序列合并。

### `tests/test_chatgpt_parser_order.py`

涵盖 ChatGPT 导出序列重建。
