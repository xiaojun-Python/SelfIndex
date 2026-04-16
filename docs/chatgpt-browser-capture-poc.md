# ChatGPT 网页捕获 PoC

这份 PoC 的目标很克制：

- 只支持 ChatGPT 网页
- 只抓取当前页面里**已加载且可见**的消息
- 先导出标准化 JSON
- 暂时不直接写入 SelfIndex

## 目录

扩展目录：

`browser_capture/chatgpt_poc`

## 现在抓哪些字段

每条消息输出字段：

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

当前实现里：

- `conversation_id`：从 URL 的 `/c/<id>` 提取
- `message_id`：来自 `data-message-id`
- `role`：来自 `data-message-author-role`
- `model / model_slug`：来自 `data-message-model-slug`
- `content`：从消息容器文本提取
- `capture_index`：按 DOM 中 `section[data-testid^="conversation-turn-"]` 的顺序生成
- `timestamp`：先留空
- `sequence`：先留空
- `parent_message_id`：先留空

## 为什么第一版不用时间戳

当前网页 DOM 里已经能稳定看到：

- `conversation_id`
- `message_id`
- `role`
- 当前页面中的消息顺序

所以第一版可以先用 `capture_index` 表示顺序。

这意味着：

- 它适合做“网页捕获能力验证”
- 还不适合直接替代导出 JSON 的全部结构信息

## 如何加载扩展

1. 打开 Chrome
2. 进入 `chrome://extensions/`
3. 打开右上角“开发者模式”
4. 点击“加载已解压的扩展程序”
5. 选择目录：

`C:\Users\xiaoj\PycharmProjects\SelfIndex\browser_capture\chatgpt_poc`

## 如何使用

1. 打开某个 ChatGPT 对话页面
2. 确认当前页面已经加载出你想抓取的消息
3. 点击浏览器工具栏里的 `SelfIndex ChatGPT Capture PoC`
4. 点击“抓取当前对话”
5. 查看弹窗中的 JSON
6. 你可以选择：
   - “复制 JSON”
   - “下载 JSON”
   - “同步新增内容”

## 直接发送到 SelfIndex

后端接口：

`POST http://127.0.0.1:5000/api/ingest/chatgpt-browser`

使用前提：

1. SelfIndex 本地 Web 服务已经启动
2. 扩展弹窗里的接口地址与本地服务地址一致
3. 扩展已重新加载到最新版本

接口特点：

- 只接受本机请求
- 接收扩展抓到的标准化 ChatGPT JSON
- 复用现有导入链路写入 `raw_documents` / `memory_units`
- 默认会正常生成向量；如果以后需要，也可以在接口层再加 `skip_embedding`

## 半自动同步

当前扩展已经支持“半自动同步”：

- 每个 `conversation_id` 都会在扩展本地记住上次同步到哪条 `message_id`
- 下次打开同一个会话时，扩展会自动检查当前页面里是否有新增消息
- 如果找到了上次同步锚点，就只发送新增消息
- 如果没找到锚点，就回退成“重新同步当前已加载内容”

为了保证增量同步仍然能保持顺序，浏览器导入链路会优先使用消息自己的绝对 `capture_index` 作为 `sequence`。

## 如何验证结果

重点看以下字段：

- `conversation_id` 是否正确
- `message_count` 是否接近当前页面可见消息数
- `messages[*].message_id` 是否都存在
- `messages[*].capture_index` 是否从 0 开始连续增长
- `messages[*].role` 是否正确区分 `user / assistant`
- `messages[*].content` 是否没有混入复制/编辑按钮文本
- 同一个会话再次打开时，“同步新增内容”是否只发送新增消息

## 当前限制

- 只抓**当前已加载**的消息，不会自动向上滚动补抓历史
- 不处理 ChatGPT 分支关系
- 不处理 `parent_message_id`
- 不处理时间戳
- assistant 回复如果页面结构变化，文本提取规则可能要调整

## 下一步建议

PoC 验证通过后，再做第二阶段：

1. 把浏览器 JSON 导入 SelfIndex
2. 自动向上滚动补抓历史消息
3. 研究 Network / 页面状态里是否能拿到 `parent_message_id`

## 导入 SelfIndex

当前仓库已经支持把这份浏览器 JSON 直接走现有导入链路：

```powershell
.\.venv\Scripts\python.exe -m scripts.import_exports --file data/browser.json --skip-embedding
```

如果后续想补向量，再单独执行：

```powershell
.\.venv\Scripts\python.exe -m scripts.build_embeddings
```

## F12 手动调试

加载扩展后，也可以在 ChatGPT 页面控制台里手动执行：

```js
window.SELFINDEX_CAPTURE_CHATGPT()
```

它会直接返回当前页面捕获到的标准化对象。
