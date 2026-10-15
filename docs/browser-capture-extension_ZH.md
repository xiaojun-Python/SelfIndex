# 浏览器捕获扩展

本文档描述 SelfIndex 使用的浏览器捕获扩展。

尽管文件夹名称，它已不再仅限于 ChatGPT。

## 范围

该扩展的范围刻意收窄：

- 仅捕获当前页面中加载的消息
- 将其规范化为 SelfIndex 友好的载荷
- 可将载荷直接发送到本地 SelfIndex 摄入端点

当前支持的站点：

- ChatGPT
- Grok

## 扩展位置

`browser_capture/ai_capture_extension`

## 捕获字段

每个规范化消息可能包含：

- `platform`
- `source_label`
- `conversation_id`
- `conversation_title`
- `message_id`
- `parent_message_id`
- `role`
- `model`
- `model_slug`
- `content`
- `content_hash`
- `timestamp`
- `sequence`
- `capture_index`
- `dom_turn_testid`
- `dom_turn_id`
- `page_url`

并非每个提供商都暴露每个字段。缺失值在需要时保留为 `null`。

## 当前提供商行为

### ChatGPT

- 对话 ID 来自 `/c/<id>`
- 消息 ID 来自 `data-message-id`
- 角色来自 `data-message-author-role`
- 模型来自 `data-message-model-slug`
- 顺序从 DOM 顺序开始，后续可增量同步

### Grok

- 对话 ID 来自 `/c/<id>` 或规范链接
- 消息 ID 来自 `id="response-..."`
- 角色目前从布局类推断，如 `items-start` 和 `items-end`
- 顺序基于当前加载的 DOM 快照
- 同步模式为快照合并，因为 Grok 懒加载旧历史

## 加载扩展

1. 打开 Chrome
2. 进入 `chrome://extensions/`
3. 启用开发者模式
4. 点击 `加载已解压的扩展程序`
5. 选择：

在当前仓库中选择此文件夹：

`browser_capture/ai_capture_extension`

在 Windows 上，选择仓库内同一个 `browser_capture\ai_capture_extension` 文件夹。

## 使用扩展

1. 打开支持的 AI 对话页面
2. 点击扩展图标
3. 查看检测到的同步状态
4. 选择以下操作之一：
   - 捕获当前对话
   - 同步到 SelfIndex
   - 重同步当前已加载内容
   - 复制 JSON
   - 下载 JSON

## 同步模式

### ChatGPT

ChatGPT 目前使用半自动增量同步：

- 扩展先读取 `/api/v1/status` 的资料库 `profile_id`，每个目标库分别保存同步位置；服务身份不可读时仍可抓取/导出，但不执行同步
- 扩展记住每个目标库、每个对话上次同步的 `message_id` 和已加载消息的内容摘要
- 如果当前页面包含该锚点，则只发送较新的消息
- 如果旧消息内容改变、旧状态无摘要或锚点缺失，扩展重同步当前已加载快照；也可手动点击“重同步已加载内容”

### Grok

Grok 目前使用快照合并：

- 每次同步发送当前加载的 DOM 快照
- 后端使用重叠的 `message_id` 值作为锚点
- 为完整对话重新对齐 `sequence`，而不重写内容

这是必要的，因为 Grok 懒加载旧消息，而不是立即交付完整对话。

## 本地摄入端点

当前端点：

`POST http://127.0.0.1:5050/api/ingest/browser-conversation`

路由名称仍有历史遗留，但载荷现在接受多种浏览器平台。

要求：

1. SelfIndex 在本地运行
2. 扩展端点与本地运行时匹配
3. 请求来自本机
4. 在扩展弹窗的“本机写入令牌”输入框中配置写令牌

写令牌由 SelfIndex 本机文件 `data/api-write-token` 提供。将该文件中的令牌粘贴到扩展设置；扩展通过 `chrome.storage.local` 保存在当前浏览器配置中，并在每次导入 POST 请求中发送 `Authorization: Bearer <token>`。令牌输入默认隐藏，可用旁边的按钮切换显示。未配置令牌时扩展会阻止发送并提示先完成配置。

请勿将令牌放入对话载荷、导出的 JSON 或公开内容中。更改或轮换本机令牌后，也要更新扩展中的保存值。

导入响应为 `200` 且 `index_status=ready` 时，本次内容已归档并索引；`202` 且 `index_status=pending` 表示内容已归档，但搜索索引尚未完成。扩展会显示待索引提示，当前仍保存同步游标；需要运行 `python -m scripts.build_embeddings` 补建，或在受控维护窗口做一致性审计。`202` 不表示后台自动任务已排队。发送超时后服务可能仍已归档，重试采用同一消息 ID 幂等导入，不把超时当作“确认未写入”。

## 手动调试

也可以直接在浏览器控制台中测试捕获。

ChatGPT：

```js
window.SELFINDEX_CAPTURE_CHATGPT()
```

Grok：

```js
window.SELFINDEX_CAPTURE_GROK()
```

通用：

```js
window.SELFINDEX_CAPTURE_CONVERSATION()
```

## 当前限制

- 仅捕获当前加载的消息
- 内容摘要只能发现**当前已加载**的旧消息变化；没加载到的历史消息无法检查，不等于平台完整备份
- 浏览器捕获仍依赖 DOM 结构
- 大多数浏览器捕获来源的 `parent_message_id` 仍缺失
- 时间戳不保证准确
- 提供商支持仍是手工构建，而非通用

## 为什么本文档重要

浏览器捕获不再只是一个边缘实验。

它现在是 SelfIndex 的主要摄入路径之一，特别是对于没有干净导出工作流的平台。
