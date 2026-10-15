# API、信任边界与外部客户端

日期：2026-09-26。该专项子代理被自动审查拦截，本文由主代理完成防御性代码审查和既有只读证据整理。没有针对运行服务尝试攻击、导出正文或令牌；不是渗透测试，也未完成漏洞库扫描。

## 1. 已有边界与应保留项

- 服务入口限制 loopback，实际监听 127.0.0.1:5050；v1 与旧主 blueprint 检查来源地址及 Host。
- 写 API 要求本机 token，文件创建使用 0600；使用 hmac.compare_digest；参数化 SQL 被广泛使用。
- GET 查询有长度和 limit 限制；生产 Waitress 关闭 debug，限制请求体 64 MiB。
- env/data/backup 没有进入当前 Git 跟踪清单。请求日志不记录 query string/body，但 path 可能包含资料 ID/文件相对路径。
- 扩展 CORS `*` 与本机 token 搭配不自动等于无鉴权漏洞；不得仅凭 CORS 宣称任意网页可以写库。

入口：[v1 API](../../app/api/v1.py#L18)、[旧路由](../../app/api/routes.py)、[本机 token](../../app/core/local_auth.py#L17)。

## 2. 问题与决策

### SEC-01 / P1（使用旧网页阅读导入内容时）：Markdown HTML 未净化

证据：旧路由 `_render_memory_document` 将内容交给 Python-Markdown；[详情模板](../../app/templates/document_detail.html) 用 `content_html|safe` 输出，路径没有 HTML allowlist sanitizer。导入正文属于不可信内容，Markdown 不是 HTML 安全净化器。

影响范围是仍可访问的旧浏览器详情页，不是宣称 PySide QTextBrowser 会运行网页脚本。建议原生模式下默认禁用不需要的旧网页，或在保留网页时做安全 HTML 净化和资源策略；扩展 ingest 路由需独立保留。验收用无副作用的 HTML fixtures，确保非允许标签、事件属性、不安全 URL 不进入最终 DOM；不使用真实敏感资料复现。

### SEC-02 / P1（若目标是资料整体加密）：SQLCipher 不覆盖整个语料

只读 Chroma SQLite 检查确认有 **16,520 条非空明文 `chroma:document`**。向量库、原始导出、配置/令牌和备份不受 SQLCipher 数据库加密保护。这是加密范围差异，不是破解 SQLCipher。

建议明确威胁模型：防磁盘丢失、其他用户读取、恶意同用户进程分别不是同一问题。文档不能只写“已加密”而暗示全部受保护。短期核实系统/备份加密与目录权限；长期评估 Chroma 是否必须存重复正文、密钥管理与加密备份。删掉 Chroma documents 也不代表向量完全没有信息泄露。验收从真实存储布局清单出发，不能只检查主 DB 文件头。

### SEC-03 / P2 / 产品决策：本机读接口无鉴权，解锁前缀只是过滤

GET search/detail 没有 token；`:`、`!` 只是请求选择 recall_domain，详情还可以直接按 ID 读取。适合“信任本机所有进程”的个人 MVP，不适合承诺应用级隐私隔离。其他本机用户也可能连接 loopback，用户目录权限不等于 API 权限。

在对接其他 App 前决定是否读写均需 token、是否按客户端发凭据与权限范围、如何撤销。保持只监听本机，不顺手改成 0.0.0.0。受保护域若只是避免日常搜索出现敏感资料，应在 UI/API 文档明确，不称为授权保护。

### API-01 / P2 / 代码确认：错误响应并非全部 JSON

v1 只有部分参数/文档异常转换为 `{code,message}`；未知路由、方法不符、请求过大及非预期后端异常没有统一 handler，默认 Flask 错误可能为 HTML。与 [API 文档](../../docs/local-api_ZH.md) 的统一错误描述不符。

验收：400/401/403/404/405/409或412/413/500/503 的机器可读错误、稳定 code 和可选 request_id；内部堆栈只进日志。客户端不得把 HTML 当业务 JSON。不能用统一 200 掩盖失败。

### API-02 / P2 / 代码确认：token 空文件与初始化竞争不可恢复

[get_write_token](../../app/core/local_auth.py#L23) 先创建文件再写内容，遇到已存在文件直接读，不验证非空/格式/权限。创建中断或并发读取可得到空值，随后一直复用空值；写 API 可能持续 401。非 ASCII 值交给字符串 compare_digest 还可能抛异常。

建议在锁或安全原子发布方案内创建/校验 token，异常时给明确恢复指引，不静默更换有效凭据。验收覆盖空/损坏文件、两进程创建、错误字符、目录权限；不打印 token。当前 raw token 无 Bearer 前缀也会被接受只是协议宽松，不是免 token 绕过。

### API-03 / P2 / 代码确认：health 只表示 HTTP handler 能响应

固定 `ok/service/version` 不检查 embedding 加载、待索引数、只读/可写状态和资料库身份。不要把它升级成每次加载模型的昂贵检查；拆分存活与能力/任务状态，并返回稳定 instance/profile 标识。配合 RUN-01，健康查询短超时不应自动强杀。

### EXT-01 / P2 / 代码确认：扩展同步游标未绑定目标资料库

[popup.js](../../browser_capture/ai_capture_extension/popup.js#L55) key 只有 platform:conversationId，与 endpoint/profile 无关。ChatGPT 增量计划在旧 anchor 后截断；切换新资料库仍沿用旧游标，可能漏掉此前消息或显示 up_to_date。Grok 当前走 snapshot_merge，不能把这个问题泛化成所有平台相同。

建议 key 包含服务返回的稳定 profile ID，目标变化时提示首次同步；提供显式全量重同步。验收同一会话切到空目标库，应发送当前完整已加载内容，不能继承旧目标成功状态。

### EXT-02 / P2 / 代码确认：ChatGPT 旧消息改动不进入增量计划

[buildSyncPlan](../../browser_capture/ai_capture_extension/popup.js#L165) 仅基于最后消息 ID；anchor 仍存在且没有新消息时不发送，即使旧消息内容改变。需要内容哈希/版本比较或受控 snapshot merge，并说明抓取只含页面已加载内容，不承诺完整平台备份。

扩展 fetch 没有超时/取消，DOM adapter 缺少 fixture 测试，属于后续可靠性补项。本轮没有加载真实浏览器扩展验收；不要把源码路径检查当成端到端成功。

## 3. 原生资源策略

桌面报告 R-01 已用临时图片确认 QTextDocument 可读取 `file:` 图片；限制链接点击不等于限制图片加载。没有证据表明已发生远程追踪或文件外传。后续明确只读归档附件根、相对路径解析、符号链接和尺寸上限，默认不自动联网；与网页净化分开验收。

## 4. 外部 App 的最小可行协议

继续使用版本化本机 HTTP 即可，不需要 Xcode 服务端或复杂 RPC。先稳定 profile/version、读权限、错误协议、查询取消/超时、乐观并发、索引状态。再写一份带超时和结构化错误的最小调用示例及契约测试。UI 不应该成为其他 App 必须启动的依赖。

## 后续状态（sol，2026-09-27）

SEC-01 的旧网页详情路径已在 Markdown 转 HTML 后使用 Bleach allowlist 净化，允许常见排版、表格与安全链接，丢弃脚本/嵌入资源、事件属性和不安全协议。合成 HTML fixture 已覆盖脚本、图片事件、iframe、SVG、危险链接及正常 Markdown。模板保留 `|safe`，其输入现已净化；后续新增 HTML 渲染入口必须使用相同边界。此项不代表 PySide 文档资源策略 R-01、读鉴权 SEC-03 或整体资料加密 SEC-02 已解决。
