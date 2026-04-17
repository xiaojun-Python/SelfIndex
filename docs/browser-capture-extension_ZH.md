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

`C:\Users\xiaoj\PycharmProjects\SelfIndex\browser_capture\ai_capture_extension`

## 使用扩展

1. 打开支持的 AI 对话页面
2. 点击扩展图标
3. 查看检测到的同步状态
4. 选择以下操作之一：
   - 捕获当前对话
   - 同步到 SelfIndex
   - 复制 JSON
   - 下载 JSON

## 同步模式

### ChatGPT

ChatGPT 目前使用半自动增量同步：

- 扩展记住每个对话上次同步的 `message_id`
- 如果当前页面包含该锚点，则只发送较新的消息
- 如果锚点缺失，扩展回退到较大范围的重新同步

### Grok

Grok 目前使用快照合并：

- 每次同步发送当前加载的 DOM 快照
- 后端使用重叠的 `message_id` 值作为锚点
- 为完整对话重新对齐 `sequence`，而不重写内容

这是必要的，因为 Grok 懒加载旧消息，而不是立即交付完整对话。

## 本地摄入端点

当前端点：

`POST http://127.0.0.1:5000/api/ingest/browser-conversation`

路由名称仍有历史遗留，但载荷现在接受多种浏览器平台。

要求：

1. SelfIndex 在本地运行
2. 扩展端点与本地运行时匹配
3. 请求来自本机

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
- 浏览器捕获仍依赖 DOM 结构
- 大多数浏览器捕获来源的 `parent_message_id` 仍缺失
- 时间戳不保证准确
- 提供商支持仍是手工构建，而非通用

## 为什么本文档重要

浏览器捕获不再只是一个边缘实验。

它现在是 SelfIndex 的主要摄入路径之一，特别是对于没有干净导出工作流的平台。
