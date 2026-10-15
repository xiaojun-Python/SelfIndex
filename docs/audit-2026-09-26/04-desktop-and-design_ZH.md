# 原生桌面交互、状态与设计审计

日期：2026-09-26。对象：当前工作树的 `desktop_mac/main.py`，不是 HEAD 中的旧版本。结论用于后续修复，本轮不实施修复。

收尾说明：本文由桌面子代理在额度中断前写入；主代理保留证据和附录并纳入交接。未完成真机 Dock/Spaces/VoiceOver 等验收，后续以 [交接计划](../../docs/audit-2026-09-26/07-backlog-and-handoff_ZH.md) 安排，不将离屏检查视为真机完成。

主代理收尾复核：文件 SHA-256 与本文基线一致；在独立 offscreen 进程重跑附录 A、B，所有审计断言成立，两个进程正常退出。A 再现草稿、按钮、焦点、状态、布局等问题；B 再现五个请求全部排队并确认 worker 回调线程。附录 C 的长文耗时没有再次重测，保留原专项记录，不把单次合成计时视为通用指标。

## 1. 范围与证据边界

- 唯一交付文件为本文。未修改生产代码、测试、真实业务数据、用户 Preferences；未连接真实业务 API，未退出、重启或操作真实 GUI。
- 使用仓库 `.venv/bin/python`：Python 3.12.13、PySide6-Essentials/Qt 6.11.2、macOS arm64；所有测试进程强制 `QT_QPA_PLATFORM=offscreen`，关闭 Python 字节码写入。每个测试窗口显式注入临时文件型 `QSettings(..., IniFormat)`。
- 时序测试拦截 `_run` 后手工交付回调；另以 mock API + **真实 QThreadPool/信号/事件循环**验证线程和完整搜索、详情、保存流程。未调用 `desktop_mac.main.main()`，不占用真实单实例 socket。已有单实例测试使用随机名字。
- 图片测试只加载临时生成的 8×8 PNG；HTTP 图片探测只访问测试进程自己的临时 loopback 计数服务器。截图由 offscreen 窗口在内存生成并目视检查，未留下额外图片文件。
- 原有未提交改动（含 `desktop_mac/main.py` 与三个桌面测试）保留。数据一致性、API 安全与运行架构由其他审计篇负责；本文仅记录与桌面交互直接相关的接口假设，不重复认定后端损坏。
- `desktop_mac/main.py` SHA-256：`0ef7b6ccaddfa9ab79d5f8b525a7d84ed8bd6217f815de098ffad1e136b96cdc`。行号均以此版本为准；后续模型应先核对版本再定位。

严重度沿用本目录 README：P1 为数据正确性或主要流程问题；P2 为可靠性、可达性和常见交互问题；P3 为局部兼容性改进。**offscreen 验证不等于 Finder/Dock、Spaces、VoiceOver 或多显示器验收。**

## 2. 当前结构与已通过项

主状态由 `pages`（首页/工作区）、`content_stack`（阅读/源码）、`current_memory_id`、`loaded_detail`、搜索/详情 generation，以及多个控件的 enabled/visible 属性共同表达。目前没有统一 dirty/saving 状态；按钮本身承担了一部分状态约束，所以绕开按钮禁用范围会破坏约束。

| 状态/路径 | 当前行为与证据 |
| --- | --- |
| 首页 | 居中品牌和搜索框；输入停顿 380 ms 自动进入工作区。`main.py:129–132, 384–387, 476–505`。 |
| 工作区 | 结果/详情双栏，自动加载第一条；请求以搜索 generation 和 memory ID + detail generation 防止旧响应覆盖。`506–569`。 |
| 阅读/编辑 | 阅读使用 QTextBrowser，编辑保留 Markdown 源码；取消恢复 loaded_detail。`451–462, 571–619`。 |
| 保存 | 锁编辑字段及保存/取消；成功切阅读，失败保留草稿。`627–684`。 |
| 生命周期 | 关闭窗口只隐藏；菜单退出进程；本地 socket 负责重复启动激活。`78–109, 404–410, 704–733`。 |
| 布局 | 500 ms 防抖保存 geometry；仅工作区可见时保存 splitter；不存查询和正文。`117–120, 363–382`。 |

已运行的现有测试：

```sh
cd /path/to/SelfIndex
env QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python -B -m unittest \
  tests.test_desktop_markdown \
  tests.test_desktop_preferences \
  tests.test_desktop_single_instance -v
```

结果：**9/9 通过**，约 0.215 秒。分别覆盖 Markdown 阅读/源码切换、显式取消、保存成功/失败、窗口和分栏恢复、首页不覆盖旧分栏、最大化、无效偏好、顺序单实例激活、首页往返。`tests/test_desktop_api_contract.py` 已阅读，但其服务端契约执行交由 API 审计，不计入这里的 9 项。

补充实测的正向结果：

- 真实 worker 的 operation 在非 GUI 线程运行，成功回调回到 `app.thread()`，完成后 `_workers` 数量为 0。不能仅凭闭包 connect 就认定跨线程操作 QWidget。
- 旧搜索成功/失败响应不会覆盖新搜索，旧详情也不会覆盖当前详情。generation 防护有效，但不等于取消旧请求。
- 用 mock API 经真实 worker 完成搜索、读取、编辑、保存，最终回到 Markdown 预览且显示保存成功。
- 合成窗口关闭再调用 `show_window()`，未保存源码仍在内存中；**关闭隐藏本身不会丢草稿**。明确“取消”丢弃编辑属于现有产品语义，不单独列 bug。
- `file:`/`javascript:` 链接点击不调用外部打开；`https:`/`mailto:` 会调用。本地图片资源加载是另一条通路，见 R-01。

## 3. 已确认问题

### UI-01 · P1 · 搜索图标绕过编辑禁用，静默清空草稿

**证据：** `desktop_mac/main.py:347–359` 搜索按钮独立连接 `_search`；`451–462` 只禁用 query、结果列表和返回首页；`476–505` 没有编辑/dirty 守卫，直接清空结果与详情，`437–448` 清掉源码。

**复现：** 正常加载详情 → 编辑 → 输入 `DRAFT` → 点击工作区左侧放大镜。此时 query disabled，而搜索图标 enabled。实测 `current_memory_id=None`、源码 `''`、阅读模式恢复，完全没有确认或草稿备份。附录 A 的 UI-01 断言可运行。

**影响：** 一次正常鼠标点击即可丢失未保存内容，不需要恶意 API 或多线程竞争。

**修复边界/验收：** 搜索命令入口本身检查 editing/dirty/saving；按钮状态与命令规则一致。编辑期间点图标、Return、快捷键等路径不得清空草稿。若允许离开，必须显式保存/放弃/留在编辑；不要求引入框架或重写窗口。

### UI-02 · P1 · 保存中搜索使结果回调失效，并永久禁用后续保存/取消

**证据：** `main.py:631–634` 禁用按钮；`648–654, 677–683` 在恢复按钮前先检查详情 generation；`451–462` 新一轮编辑没有重置这两个按钮的 enabled 状态。触发入口与 UI-01 共用，但后果与所需回归断言不同。

**复现：** 发起保存，暂扣回调 → 点搜索图标 → 交付原保存成功或失败 → 重新加载任一详情并编辑。实测源码可编辑，**保存与取消均为 False**；原保存结果没有反馈。附录 A 的 UI-02。

**影响：** 后端可能已经提交，而界面不再显示结果；后续编辑陷入不能保存、不能取消的死路。不能将此描述为“后台一定没有保存”。

**修复边界/验收：** UI-01 的入口守卫优先修；同时让新编辑会话显式初始化按钮状态，并区分保存操作身份与当前详情身份。成功、失败、离开页面、重新进入均测试；后台已发出的写请求不得仅因前台 generation 变化就被当作不存在。

### UI-03 · P2 · 首页自动搜索中断继续输入，焦点跳到返回按钮

**证据：** `main.py:384–387, 476–505` 在 380 ms 后切页并禁用 query；成功时 `509` 只恢复 enabled，不恢复输入焦点。API 搜索 timeout 为 `desktop_mac/api.py:77–78` 的 60 秒。

**复现：** 首页输入 `first`，等 420 ms，不交付请求回调。实测 `pages=1`、query disabled，焦点为 `homeButton`。此时无法接着打完整句子。附录 A 的 UI-03。

**影响：** 思考停顿或慢服务会打断主要搜索流程。60 秒是请求 timeout 配置，不是本轮实际等待时间，也不是完整请求绝对耗时上限。

**修复边界/验收：** 自动搜索还是 Enter 提交是产品选择，**自动搜索导致不能继续输入不是必要代价**。若保留自动搜索，应保留可编辑输入及焦点，让新查询取代旧意图；中文输入法组合态不提前提交。验收 380 ms 前后停顿、慢服务、连续中文句子及成功后的继续输入。

### UI-04 · P2 · 重复搜索仍排队执行，generation 只丢响应不节流

**证据：** `main.py:412–430, 476–505` 每次点击都入池，没有同查询去重/最新待执行意图替换；图标在搜索中仍可点。

**复现：** 在注入的双线程测试池中连续发起 5 次搜索，mock API 用 Event 暂扣。实测释放前 `_workers=5`、已开始 2、active=2；释放后 **5 次 API 全执行**，最终只采用最后一份结果。附录 B。

**影响：** 慢检索时无效工作占满池；最新请求、详情或其他操作可能等待旧任务。这里确认的是客户端队列行为，不推断服务端实际 CPU/数据库负载。

**修复边界/验收：** 同查询正在执行时去重；只保留最新待执行查询，过期排队工作开始前即跳过。不能假设 `QThreadPool.clear()` 可以中止已经进入 urllib 的请求。压力验收中连续 20 次改词/点击，队列有明确上限，最后意图优先且无串页。

### UI-05 · P2 · 连接徽标不会随恢复更新，还可能被旧健康检查覆盖

**证据：** `main.py:140–141` 仅启动时 health；`464–474, 527–532` 写连接状态，但搜索/详情/保存成功不更新它。health 回调无请求代次。

**复现：** `_health_failed('offline')` 后完成一次合法搜索，结果可用，徽标仍为“服务未连接”；搜索报错后成功也保留“服务连接异常”。附录 A 的 UI-05。

**影响：** 用户被错误提示引导重启服务；迟到的启动 health 也可能覆盖更新的失败状态。不能用“有定时器”推断有健康重试：现有定时器只负责搜索和布局。

**修复边界/验收：** 定义连接状态由哪次服务探测负责；成功请求后复核 health，或以有序观测更新状态。业务 4xx 与连接失败分开。验收离线启动后服务恢复、健康慢于搜索返回、详情断网，不需重启桌面。

### UI-06 · P2 · 详情失败后当前结果无法直接重试

**证据：** `main.py:215` 只监听 `currentRowChanged`；`605–609` 仅展示错误、禁用编辑，无重试动作。

**复现：** 只有一条搜索结果，详情失败后再次点击该行并按 Return，未新增请求，编辑仍 disabled。附录 A 的 UI-06。

**影响：** 短暂网络失败后必须重新做整次搜索；多结果可切别行再回来绕行，但不是失败项的直接恢复入口。

**修复边界/验收：** 详情错误态提供只重试当前 memory ID 的动作，支持键盘触发；或明确处理 itemActivated。成功后清错误、可编辑，不丢当前查询/选择；旧重试回调仍经过 generation 检查。

### UI-07 · P2 · 拖完分栏立即返回首页，最新布局不会保存

**证据：** `main.py:288, 371–382` 分栏防抖 500 ms 且保存时要求工作区可见；`389–402` 返回首页前不 flush。原测试 `tests/test_desktop_preferences.py:59–77` 只验证另一个纯首页会话不覆盖旧值，漏了这一边界。

**复现：** 工作区保存比例 A → 改为 B 并触发 splitterMoved → 500 ms 内返回首页 → 等 600 ms。内存 B 与 A 不同，但临时 INI 中仍为 A。附录 A 的 UI-07。

**影响：** 用户最后调整的分栏在下次启动失效；当前会话若后来再回工作区触发保存，可能暂时掩盖问题。

**修复边界/验收：** 离开可见工作区之前保存其最后有效 splitter，或在拖动时缓存状态供之后写入。保留“纯首页会话不覆盖旧比例”现有保护；新增拖动后立刻回首页再关闭/重开测试。

### UI-08 · P2 · show_window 不清除最小化状态（Qt 层已确认）

**证据：** `main.py:686–689` 只有 show/raise/activate，没有取消 WindowMinimized。单实例回调与菜单都调用该方法。

**复现：** offscreen 合成窗口 `showMinimized()` 后调用 `show_window()`，`isMinimized()` 仍 True。附录 A 的 UI-08。该平台输出 `This plugin does not support raise()` 是边界提示，不是应用报错。

**影响与限制：** 窗口激活入口没有在 Qt 状态层恢复可见窗口；**不能据此宣称真实 Dock 点击一定失败**，AppKit 可能另有行为。真实 Finder/Dock 验收尚未进行。

**修复边界/验收：** 针对 minimized 明确解除最小化，保留此前最大化/全屏语义；不要无条件 showNormal 破坏已保存状态。分别测试隐藏、最小化、后台正常窗以及重复启动；原生验收另见第 6 节。

### UI-09 · P2 · 长 Markdown 同步逐块排版长时间占住 GUI 线程

**证据：** `main.py:578–603` 每次加载、取消、保存都重新设置完整源码/Markdown，随后用 QTextCursor 逐块改格式。工作线程只覆盖 API，渲染仍在 GUI 回调。

**复现与计时：** 重复 `paragraph **bold** and `code`` 段落，100/1,000/3,000 块分别约 0.023/0.137/0.988 秒；10,000 块、310,000 ASCII 字节约 **13.501 秒**。零延迟 QTimer 在 `_render_markdown` 返回之前没有执行。数字是本机合成样本单次测量，非普遍 SLA。附录 C 可重测。

**影响：** 约 310 KB 已能让搜索、滚动、取消和 Dock 激活处理长时间等候。复制到源码区和预览两份文档还会增加峰值占用，本轮未做内存定量分析。

**修复边界/验收：** 优先量测 setMarkdown 与逐块 formatting 的独立成本，合并编辑事务/避免逐次重排、相同内容不重复渲染、按需填充源码。QWidget/QTextDocument 的线程归属必须保持正确，不能直接把现有渲染函数扔进 worker。建议 10,000 块夹具下 GUI heartbeat 最大停顿小于 200 ms，或进入明确可取消的分批加载状态；不能用静默截断正文达标。

### UI-10 · P2 · 最小窗口下长标题/作者被直接裁切，全文不可读

**证据：** `main.py:136, 229–239` 标题虽然 wordWrap，但元信息在不可滚动布局；作者不换行。`571–577` 直接注入无限长文本。

**复现：** 760×540 窗口，标题 `'Long title ' * 100`：实际高 78 px，`heightForWidth` 所需 552 px；截图显示最后一行被切半。作者 `'X' * 300` 所需宽约 2544 px，实际约 426 px，右端直接消失，既无横滚也无全文提示。附录 A 的 UI-10。

**影响：** 长标题无法完整辨认，作者不可检查；不应通过强迫窗口超出屏幕解决。没有声称所有正常长度都重叠。

**修复边界/验收：** 标题限定可见行数并提供展开/可选择全文，作者有换行或省略+完整可访问值；长错误信息也采用可换行、可复制的区域，不任由 QLabel 的 minimumSizeHint 撑布局。760×540、1120×760 和大字号下逐项截图验证，正文和底部操作始终可达。

### UI-11 · P2 · 关键可访问控件没有名称

**证据：** `main.py:211–215, 245–262, 347–359` 创建列表、编辑字段、阅读器和纯图标按钮，未给 accessibleName/buddy。实测 Qt accessibility interface：query、title、author、source、list、preview、search 的 Name 均为空；前三者和 search 有 placeholder/tooltip 派生 Description，但 source/list/preview 的 Description 也为空。

**复现：** 附录 A 的 UI-11 查询 `QAccessible.queryAccessibleInterface(...).text(QAccessible.Name)`。

**影响与限制：** 控件缺乏稳定语义标签，尤其原始 Markdown 编辑区和结果列表。**这确认的是 Qt 暴露的语义缺口，不是一次 VoiceOver 实机测试结果。**

**修复边界/验收：** 为搜索、结果、阅读区、标题、作者、源码及图标动作命名；设置必要的 label buddy 和可预期 Tab 顺序。保留 tooltip，但不把它当 accessibleName 的替代品。用 Qt 接口断言 + VoiceOver 逐项核验，错误/保存完成可被感知，焦点可见。

### UI-12 · P3 · 普通 Markdown 标题没有生成可跳转锚点

**证据：** `main.py:585` 默认 setMarkdown；`621–623` 对片段链接调用 scrollToAnchor，但没有建立标题 slug/锚点。

**复现：** `[jump](#target)` + 80 段 + `# Target`。富文本文档所有 fragment 的 anchorNames 为空，滚动最大值 2862，但点击后 value 仍 0。附录 A 的 UI-12。

**影响：** 常见目录页内跳转无效，不等同于所有 Markdown 链接都坏。HTTP/mailto 点击路径已单独验证。

**修复边界/验收：** 若支持标题目录，生成确定性的标题锚点，覆盖重复标题、中文和编码片段；否则明确范围，避免看似可跳转却无反馈。外链协议白名单继续保留。

### UI-13 · P2 · 保存成功展示的是请求副本，不是服务器实际规范化内容

**证据：** `main.py:636–640, 655–670` 成功后直接将 body 写入 loaded_detail/列表，不回读。`app/services/documents.py:39–41` 则 trim 标题/作者/正文，为空标题、作者填默认值；返回对象 `89–94, 137–142` 不含规范化后的正文和元信息。

**复现：** mock 成功保存 title=`'  Name  '`、author=`'  '`、content=`'  body  '`，UI 的 loaded_detail 保留原样；按当前服务代码实际值应为 `Name`、`unknown`、`body`。用后者模拟随后的详情响应，显示立即改变。附录 A 的 UI-13；没有写真实文档。

**影响：** “已保存”后的阅读/再次编辑与实际持久化版本不一致。这里只确认客户端认知差异，后端是否应保留空白属于数据/API篇的契约决策。

**修复边界/验收：** 保存响应携带 canonical detail，或成功后按新 memory ID 回读；回读失败时区分“已保存但刷新失败”和“未保存”，避免引导重复提交。验收空标题、空作者、首尾空白、202 pending、保存后立刻重新打开。

### UI-14 · P2 · 显式退出无未保存检查

**证据：** `main.py:404–410` 菜单动作直接连 `QApplication.instance().quit`；`139` aboutToQuit 只保存窗口布局，没有 dirty 检查或草稿持久化。此项不同于关闭窗口隐藏。

**复现：** 构造合成窗口时拦截其 QApplication.quit，编辑出 `UNSAVED` 后触发“退出 SelfIndex”，直接调用 quit，一次也不经过保存/放弃选择。附录 A 的 UI-14 拦截真正退出，所以不会终止任何真实 GUI。

**影响：** 误点退出即可丢未保存草稿；保存进行中退出的确认/结果语义也未定义。不要求无条件持久化私有正文到偏好。

**修复边界/验收：** 用户退出命令经过统一 dirty/saving 决策，提供保存/放弃/取消退出；关闭隐藏继续保留内存草稿。若另做崩溃草稿恢复，应独立选择存储位置与隐私策略，不能塞入 QSettings。原生 Cmd+Q 是否走相同门禁需实机验证。

## 4. 已确认行为、风险与产品选择（不混入 bug 数量）

**R-01：Markdown 资源策略尚未定义。** `main.py:256–259, 584–585` 的 `setOpenLinks(False)` 只控制点击导航，不阻止 QTextDocument 的图片资源读取。临时 `file:///.../probe.png` 被解析为有效 QPixmap，无需点击；相同环境对本机 HTTP 计数服务器的图片请求数为 0。不能因此宣称“已发生远程追踪/文件外传”，也不能宣称所有资源已安全隔离。允许归档附件还是禁止任意本地路径属于产品/安全决策。建议只允许明确归档根目录的资源，并校验解析后的路径、符号链接及图片尺寸；默认不自动联网。后续用受控 fixtures 验证 `file:`、相对路径、HTML `<img>`、data URI、超大图片、缺图和正文外链，禁止拿真实敏感文件复现。

**R-02：退出等待 worker 的生命周期。** 单独 offscreen 子进程 mock health 延迟 1.5 秒、20 ms 后 quit；事件循环立即返回，但进程退出约需 1.83 秒。说明 event loop 返回不等于后台任务结束。`main.py:44, 412–430` 无取消/退出协调；真实网络搜索配置 60 秒、保存 30 秒。但未执行真实阻塞请求，不认定某一固定“退出必卡 60 秒”。后续应定义读请求有界收尾、在途写请求结果与退出反馈，并测试成功/异常 callback、窗口销毁、进程收尾，无悬挂线程。

**R-03：单实例覆盖有限。** 顺序双调用已通过，不能证明多进程同时抢占、僵死 socket 清理、旧进程忙时握手、不同用户隔离。`main.py:92–99` 在 listen 失败且连接失败后移除 socket；是否可能误移除活实例须用**随机 socket 名的独立测试进程**验证，不能在真实 `local.selfindex.desktop.<uid>` 上试验或清理。没有足够证据认定现有单实例一定竞态失效。

**R-04：QLabel 默认富文本。** `main.py:575–577` 元信息 setText 使用 AutoText；`<b>Literal title</b>` 会被当作样式而非字面标题。应决定元信息统一 PlainText；这不是浏览器 JavaScript 执行证据。与正文资源策略一起补原始 HTML、超长元信息测试。

**产品边界：** 原生版暂不含旧页面筛选、导入、调试分数等，不因此判为回归。保留干净搜索首页、结果/详情双栏、阅读/源码分离、布局持久化、Dock 常驻即可。旧 `app/templates/index.html:4–122`、`document_detail.html:36–46` 与 `app/static/css/custom.css:114–210, 764` 只作结构和阅读层次参考，不能把旧网页全部控件搬回首页。

**仍需决策：** 首页自动检索或显式提交、取消编辑是否二次确认、是否跨退出保存草稿、分栏是否允许完全折叠、阅读位置是否随记录记忆、远程图片/本地附件范围。QSplitter 默认可折叠，现无显式“重置布局”，这是可恢复性设计选择；目前未证明布局数据损坏。202 的“索引处理中”只是当前响应快照，没有轮询，不能让文案暗示一定有后台任务自动推进，需与数据/API篇对齐。

## 5. 有界设计建议与修复顺序

1. **先修状态入口：** 在现有 MainWindow 内集中维护 editing/dirty/saving 事实及动作可用性；每次转换统一更新字段、按钮、焦点，命令入口独立校验。先覆盖 UI-01、02、14，不要求建立庞大状态框架。
2. **再修请求和恢复：** 保留有效 generation 防护，加入同查询去重/最新意图排队、详情重试、连接状态的有序恢复。搜索框在加载中仍可继续输入，加载标记放在现有结果状态行，不增加首页说明卡片。
3. **保持阅读优先：** 顶部简洁标题/作者/时间，正文占主要面积；长标题可展开，错误可复制；阅读区与源码区明确名称，编辑动作维持小规模工具栏。保留原始 Markdown，不以预览反序列化覆盖源码。
4. **针对长内容做局部优化：** 先 profile 格式循环，控制布局事务，减少取消/重选时完整重排；再决定是否分批渲染。附件资源单独门禁，不为支持 Markdown 升级成任意网页容器。
5. **保存用户已选布局：** 转页前 flush 有效分栏，恢复几何只负责几何，不夹带查询或草稿；增加可发现的重置布局动作，需用户主动触发。最小化恢复不破坏最大化/全屏。
6. **补原生惯例而不堆界面：** 建议 Cmd+F/L 聚焦搜索、Cmd+S 保存、明确 Escape 的取消/退出含义；列表上下键和 Enter 可达详情/重试。快捷键只在语义有效时执行，不能再次绕过 dirty 门禁。快捷键、菜单和 VoiceOver 需在同一验收中核对。

## 6. 后续执行验收

| 阶段 | 可执行验收与完成标准 |
| --- | --- |
| 状态修复首批 | 把附录 A 的“当前缺陷为真”断言改成预期保护行为，补入桌面测试；覆盖图标/键盘/菜单、保存成功/失败、切页及隐藏重开。UI-01/02 修复必须一起验收。 |
| 时序回归 | mock Event 控制真实 pool，逆序交付搜索和详情；20 次连续意图保持有界工作量，只有最新结果可见；业务错误、离线、恢复、迟到 health 分别断言。 |
| 布局回归 | 临时 INI：拖动后 0/100/600 ms 回首页、关闭，再新建窗口，比例恢复；无效 bytes、纯首页、最大化现有测试继续通过。只检查 geometry/splitter 键，不出现正文/查询。 |
| 阅读/编辑 | 0、短、1,000/10,000 段，宽表格、长代码行、中英文、重复标题、HTML、图片和错误资源；原文不被静默截断，取消/保存后显示与服务 canonical detail 一致。 |
| 尺寸/可访问性 | 760×540、1120×760、1440×900 和大字号截图；所有操作在窗内，长文本有完整可达路径；Qt Name 非空、Tab 顺序、焦点可见、列表键盘重试。真实 VoiceOver 再逐项验证。 |
| macOS 原生，需用户安排隔离验收 | 在独立测试账户或明确同意的测试 App 中验证 Finder 双击/重复启动、红色关闭后 Dock 重开、最小化后 Dock/菜单恢复、应用已在前台但窗口隐藏、Cmd+Tab、Spaces/全屏、多显示器拔插及屏外几何恢复。记录实际事件类型、窗口状态与焦点，不能用手工发 ApplicationActivate 代替。 |
| 生命周期 | 只读 worker 与保存 worker 各自 pending 时关闭/隐藏/退出，确认不丢草稿、不误报保存结果、不影响本机服务；测试 socket 名随机化，结束只清理测试 socket。发布/服务启停验收交运行篇。 |

现有测试缺口定位：`tests/test_desktop_markdown.py:27–28` patch `_run`，无法覆盖真实线程、队列和回调生命期；`70–97` 保存测试只覆盖留在当前详情的路径；`tests/test_desktop_single_instance.py:26–38` 是同进程顺序 socket 测试；`tests/test_desktop_preferences.py:24–77` 缺转页防抖边界。应扩展这些测试的具体边界，而不是笼统增加测试数量。

## 附录 A：可运行状态与可达性复现

以下是**审计断言**：断言当前缺陷存在；修复后预期需要反向修改。全部数据为合成字符串，QSettings 在 TemporaryDirectory 中；API 构造和异步调度均被 mock。只在新 offscreen 进程执行，不在真实 GUI 进程执行。

```python
# AUDIT_REPRO_A
import tempfile
from contextlib import contextmanager
from unittest.mock import patch
from PySide6.QtCore import QEvent, QSettings, Qt, QUrl
from PySide6.QtGui import QAccessible
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolButton
from desktop_mac.main import MainWindow

app = QApplication.instance() or QApplication([])
app.setQuitOnLastWindowClosed(False)

@contextmanager
def window():
    with tempfile.TemporaryDirectory() as td, \
         patch('desktop_mac.main.SelfIndexApi'), \
         patch.object(MainWindow, '_run') as run:
        w = MainWindow(QSettings(td + '/ui.ini', QSettings.IniFormat))
        w.resize(760, 540)
        w.show()
        app.processEvents()
        try:
            yield w, run
        finally:
            w.home_search_timer.stop()
            w.layout_save_timer.stop()
            w.hide()
            w.deleteLater()
            app.sendPostedEvents(None, QEvent.DeferredDelete)

def detail(w, title='Note', author='Author', content='# Original'):
    w._detail_ready({'memory_unit': {}, 'raw_document': {
        'title': title, 'author': author, 'content': content,
    }}, w.current_memory_id, w.detail_generation)
    app.processEvents()

def loaded(w):
    w.pages.setCurrentIndex(1)
    w.query.setText('synthetic')
    w._search_ready({'results': [{'memory_unit_id': 'a', 'title': 'A'}]},
                    w.search_generation)
    detail(w)

def icon(w):
    return w.pages.widget(1).findChild(QToolButton, 'searchIcon')

with window() as (w, run):
    loaded(w)
    w._begin_edit()
    w.content_field.setPlainText('DRAFT')
    assert not w.query.isEnabled() and icon(w).isEnabled()
    icon(w).click()
    assert w.current_memory_id is None
    assert w.content_field.toPlainText() == ''
    print('UI-01: draft discarded')

for outcome in ('success', 'failure'):
    with window() as (w, run):
        loaded(w)
        w._begin_edit()
        w.content_field.setPlainText('SAVING')
        w._save()
        operation, success, failure = run.call_args.args
        icon(w).click()
        if outcome == 'success':
            success((200, {'memory_unit_id': 'b', 'index_status': 'ready'}))
        else:
            failure('synthetic failure')
        loaded(w)
        w._begin_edit()
        assert w.content_field.isEnabled()
        assert not w.save_button.isEnabled()
        assert not w.cancel_button.isEnabled()
        print('UI-02:', outcome, 'leaves actions disabled')

with window() as (w, run):
    w.home_query.setFocus()
    QTest.keyClicks(w.home_query, 'first')
    QTest.qWait(420)
    assert w.pages.currentIndex() == 1 and not w.query.isEnabled()
    assert app.focusWidget() is not w.query
    print('UI-03: focus =', app.focusWidget().objectName())

with window() as (w, run):
    w._health_failed('offline')
    w.home_query.setText('synthetic')
    w._search()
    w._search_ready({'results': []}, w.search_generation)
    assert '\u672a\u8fde\u63a5' in w.connection.text()
    print('UI-05:', w.connection.text())

with window() as (w, run):
    loaded(w)
    w._detail_failed('offline', 'a', w.detail_generation)
    before = run.call_count
    rect = w.list.visualItemRect(w.list.item(0))
    QTest.mouseClick(w.list.viewport(), Qt.LeftButton, pos=rect.center())
    QTest.keyClick(w.list, Qt.Key_Return)
    assert run.call_count == before and not w.edit_button.isEnabled()
    print('UI-06: no retry')

with window() as (w, run):
    loaded(w)
    w.resize(1120, 760)
    app.processEvents()
    w.splitter.setSizes([300, 700])
    w._save_ui_state()
    old = w.ui_settings.value('window/splitter')
    w.splitter.setSizes([500, 500])
    w.splitter.splitterMoved.emit(500, 1)
    assert old != w.splitter.saveState()
    w._show_home()
    QTest.qWait(600)
    assert old == w.ui_settings.value('window/splitter')
    print('UI-07: new splitter state not persisted')

with window() as (w, run):
    w.showMinimized()
    app.processEvents()
    w.show_window()
    app.processEvents()
    assert w.isMinimized()
    print('UI-08: still minimized (offscreen only)')

with window() as (w, run):
    loaded(w)
    detail(w, title='Long title ' * 100)
    assert w.title_view.height() < w.title_view.heightForWidth(w.title_view.width())
    detail(w, author='X' * 300)
    assert w.author_view.width() < w.author_view.sizeHint().width()
    print('UI-10: metadata clipped')
    for obj in (w.content_field, w.list, w.content_preview):
        accessible = QAccessible.queryAccessibleInterface(obj)
        assert accessible.text(QAccessible.Name) == ''
    print('UI-11: source/list/preview names empty')
    detail(w, content='[jump](#target)\n\n' + 'paragraph\n\n' * 80 + '# Target\n\nend')
    bar = w.content_preview.verticalScrollBar()
    assert bar.maximum() > 0
    bar.setValue(0)
    w._open_markdown_link(QUrl('#target'))
    assert bar.value() == 0
    print('UI-12: heading jump did not scroll')

with window() as (w, run):
    loaded(w)
    w._begin_edit()
    w.title_field.setText('  Name  ')
    w.author_field.setText('  ')
    w.content_field.setPlainText('  body  ')
    w._save()
    operation, success, failure = run.call_args.args
    success((200, {'memory_unit_id': 'a', 'index_status': 'ready'}))
    assert w.loaded_detail['title'] == '  Name  '
    assert w.loaded_detail['author'] == '  '
    assert w.loaded_detail['content'] == '  body  '
    detail(w, title='Name', author='unknown', content='body')
    assert w.loaded_detail['content'] == 'body'
    print('UI-13: reload changes the supposedly saved representation')

with patch.object(app, 'quit') as quit_mock:
    with window() as (w, run):
        loaded(w)
        w._begin_edit()
        w.content_field.setPlainText('UNSAVED')
        menu = w.menuBar().actions()[0].menu()
        menu.actions()[-1].trigger()
        assert quit_mock.call_count == 1
        assert w.content_field.toPlainText() == 'UNSAVED'
        print('UI-14: quit called directly with unsaved text')
```

## 附录 B：真实 worker 与有界模拟服务

不 patch `_run`；只替换 API，测试池只属于合成窗口。所有等待有超时，finally 释放 gate 并等待池结束。

```python
# AUDIT_REPRO_B
import tempfile
import threading
import time
from unittest.mock import patch
from PySide6.QtCore import QEvent, QSettings, QThread, QThreadPool
from PySide6.QtWidgets import QApplication, QToolButton
from desktop_mac.main import MainWindow

app = QApplication.instance() or QApplication([])
app.setQuitOnLastWindowClosed(False)
gate = threading.Event()
calls = []

class Api:
    def health(self):
        return {'ok': True, 'service': 'selfindex', 'version': 'mock'}
    def search(self, query):
        calls.append(query)
        gate.wait(3)
        return {'results': [{'memory_unit_id': 'a', 'title': 'A'}]}
    def memory(self, memory_id):
        return {'memory_unit': {}, 'raw_document': {'title': 'A', 'content': '# body'}}
    def update_memory(self, memory_id, **body):
        return 200, {'memory_unit_id': 'a', 'index_status': 'ready'}

def until(predicate, seconds=3):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert predicate(), 'synthetic wait timed out'

with tempfile.TemporaryDirectory() as td, patch('desktop_mac.main.SelfIndexApi', Api):
    w = MainWindow(QSettings(td + '/ui.ini', QSettings.IniFormat))
    w.pool = QThreadPool(w)
    w.pool.setMaxThreadCount(2)
    try:
        until(lambda: not w._workers)
        affinity = []
        w._run(lambda: QThread.currentThread() == app.thread(),
               lambda result: affinity.append((result, QThread.currentThread() == app.thread())),
               lambda error: affinity.append(error))
        until(lambda: not w._workers)
        assert affinity == [(False, True)]
        w.show()
        w.home_query.setText('synthetic')
        w._search()
        button = w.pages.widget(1).findChild(QToolButton, 'searchIcon')
        for _ in range(4):
            button.click()
        until(lambda: len(calls) == 2)
        assert len(w._workers) == 5
        print('UI-04: queued workers =', len(w._workers), 'started =', len(calls))
        gate.set()
        until(lambda: not w._workers and w.loaded_detail is not None)
        assert len(calls) == 5
        w._begin_edit()
        w.content_field.setPlainText('# changed')
        w._save()
        until(lambda: not w._workers)
        assert w.content_stack.currentIndex() == 0
        assert w.loaded_detail['content'] == '# changed'
        print('worker affinity, real signal flow, and save passed')
    finally:
        gate.set()
        w.pool.waitForDone()
        app.processEvents()
        w.hide()
        w.deleteLater()
        app.sendPostedEvents(None, QEvent.DeferredDelete)
```

## 附录 C：资源与长内容探测

10,000 块可能卡住**这个测试进程**十余秒。不会阻塞真实 GUI；不把特定毫秒数做跨机器硬断言。临时 PNG 会随目录自动删除。

```python
# AUDIT_REPRO_C
import tempfile
import time
from unittest.mock import patch
from PySide6.QtCore import QEvent, QSettings, QTimer, QUrl
from PySide6.QtGui import QColor, QImage, QTextDocument
from PySide6.QtWidgets import QApplication
from desktop_mac.main import MainWindow

app = QApplication.instance() or QApplication([])
with tempfile.TemporaryDirectory() as td, \
     patch('desktop_mac.main.SelfIndexApi'), patch.object(MainWindow, '_run'):
    w = MainWindow(QSettings(td + '/ui.ini', QSettings.IniFormat))
    w.show()
    w.pages.setCurrentIndex(1)
    app.processEvents()
    try:
        img = QImage(8, 8, QImage.Format_ARGB32)
        img.fill(QColor('magenta'))
        assert img.save(td + '/probe.png')
        url = QUrl.fromLocalFile(td + '/probe.png')
        w._render_markdown('![local](' + url.toString() + ')')
        app.processEvents()
        resource = w.content_preview.document().resource(QTextDocument.ImageResource, url)
        assert not resource.isNull()
        print('R-01: local image resource loaded without a click')
        for count in (100, 1000, 3000, 10000):
            content = 'paragraph **bold** and `code`\n\n' * count
            ticks = []
            QTimer.singleShot(0, lambda: ticks.append(1))
            start = time.perf_counter()
            w._render_markdown(content)
            elapsed = time.perf_counter() - start
            assert not ticks
            print('UI-09:', count, 'blocks,', len(content), 'bytes,', round(elapsed, 3), 'seconds')
            app.processEvents()
    finally:
        w.hide()
        w.deleteLater()
        app.sendPostedEvents(None, QEvent.DeferredDelete)
```

附录直接执行方式（不生成脚本文件；把末尾 `A` 换成 `B`/`C` 可运行对应段）：

```sh
cd /path/to/SelfIndex
env QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python -B - A <<'PY'
import re
import sys
from pathlib import Path
path = Path('docs/audit-2026-09-26/04-desktop-and-design_ZH.md')
blocks = re.findall(r'```python\n(.*?)\n```', path.read_text(), re.S)
marker = '# AUDIT_REPRO_' + sys.argv[1]
source = next(block for block in blocks if block.startswith(marker))
exec(compile(source, str(path) + ':' + marker, 'exec'))
PY
```

## 后续状态（sol，2026-09-26）

UI-01/02/13/14 的代码路径已修复：草稿导航确认、保存期间锁定与失败恢复、服务规范化正文展示、退出动作保护；补充离屏回归测试。本文附录 A 中对应条目的**缺陷断言预期不再成立**，不能继续以它们全数通过作为验收。真实 Finder/Dock/Cmd+Q 行为没有在用户当前 App 上执行，仍按本报告第 6 节验收。UI-03～12 及资源策略 R-01 未处理。
