# macOS 运行、运维与发布

日期：2026-09-26。现有服务未停止、重启或重新安装。下面的故障通过 mock 复现或静态检查确认，不表示本机已经发生相应故障。

## 1. 当前适合怎样运行

近期继续使用 **用户级 LaunchAgent 管理一个本机服务，PySide6 App 按需打开**。GUI 关闭/退出与服务退出是不同动作。无需为了纯 Python/Qt 开发先建设 Xcode 工程；正式分发的签名、公证、安装更新是另一个阶段，不等于完全不需要 Apple 工具链。

这是登录用户会话下的常驻方案，不是整台机器永不休眠的 24x7 服务器。登出、睡眠、关机和机器断网时的承诺必须写清楚。现在不建议仅为“像 App”而改成 GUI 同进程内跑模型/数据库，也不建议同时使用 LaunchAgent 和 nohup 管理同一实例。

本轮快照：一个服务、一个 GUI、5050 单监听；收尾再次只读访问 `/api/v1/health` 返回 `ok=true, service=selfindex, version=0.1.0`。这是存活证据，不是模型/检索/全部任务可用证明。

## 2. 已确认问题

### RUN-01 / P1：一次健康失败即可强制重启已加载服务

[ensure](../../scripts/macos_launch_agent.py#L91) 首次探测超时 1 秒，随后若 launchd job 已加载即 `kickstart -k`。隔离 mock 第一次 False、下一次 True，仍记录 forced_restart=true。

触发条件：服务正在忙、启动尚未完成、健康请求排队或暂时异常时再次启动 App。服务入口有 4 个 Waitress 线程，检索/索引同步占用线程；健康 handler 也需要调度，因此排队是合理风险，不是已证明本机发生过的重启原因。Waitress 的有限线程池与排队行为见[官方设计说明](https://docs.pylonsproject.org/projects/waitress/en/latest/design.html)。

修复：区分未安装、未加载、正在启动、健康、繁忙/不可用和确定失败；首次失败应等待/提示，强制重启是显式恢复操作，并考虑在途写入。验收：一次/短暂失败不发 `-k`；已加载慢启动不被反复杀死；真正退出可恢复；端口被别的服务占用给出明确错误。不要把超时简单从 1 秒改成大数字就宣告问题已解决。

### RUN-02 / P2：DATA_DIR 不会统一迁移数据库位置

[Settings](../../app/core/settings.py#L45) 的 SQLite、Chroma、raw_exports 默认路径分别从 BASE_DIR/data 计算，而非 data_dir。隔离环境只设置 DATA_DIR 后，两个库均不在新目录内。

影响：token/log 和内容库可能落在不同位置，备份/迁移误以为移动了整个资料库。修复为明确的 profile path resolution，显式子路径 override 优先，缺省才从统一根派生；保留旧安装兼容和迁移提示。验收用不同 cwd、空格/中文路径、相对路径、仅 DATA_DIR、全部 override 的配置矩阵。严禁直接修改当前真实 .env 测试。

### RUN-03 / P2：进程单实例不是资料库单写者

launchd label 和单端口限制一份受管服务，GUI socket 限制一份窗口进程；它们都不约束另一端口服务/CLI 对同一数据目录写入。app 创建存储对象在 bind 端口之前，端口冲突也不等于完全没有碰存储。

建议按规范化 profile 建立操作系统级独占所有权，CLI 走服务或停服维护模式；health/status 返回 profile/instance 身份用于诊断，不暴露本机敏感路径。验收用临时资料库启动两个独立进程，包括不同端口、符号链接路径和异常退出后的锁释放。未对真实数据库做双写压力测试。

### RUN-04 / P2：IPv6 支持声明与客户端路径不一致

[服务入口](../../app/service_main.py#L13) 接受 ::1，ensure 固定访问 127.0.0.1，GUI 的 host:port 拼接未统一处理 IPv6 方括号，扩展权限也仅含 IPv4/localhost。当前 IPv4 配置正常。

可以先明确仅支持 127.0.0.1，或真正统一 URL 构造/Host 校验/探测；不要只改一端。验收 host 矩阵；改变 host 不得意外扩大网络监听范围。

### RUN-05 / P2：两套服务控制和陈旧 PID 的风险

[shell 控制](../../scripts/selfindex_service.sh#L76) 用 kill -0 判断 PID 存活，stop 随后 kill / kill-KILL，没有核对进程身份与启动时刻。陈旧 PID 被其他进程复用时可能误操作。此为代码确认，**未向任何进程发送信号复现**。start 在 nohup 后立即报告启动，未等待 API ready。

优先统一用户文档与控制入口为 launchd；若保留备用脚本，必须检查管理权和就绪状态，不能只按 PID 杀进程。验收全部在 mock 子进程/临时 PID 文件内完成。

### RUN-06 / P2：开发 .app 仍绑定源码和虚拟环境

[构建脚本](../../scripts/build_macos_dev_app.py#L27) 写入 checkout/.venv 绝对路径；移动/删除项目后 .app 不能独立工作。launcher 使用 ASCII 写入，中文项目路径会触发编码异常；`ensure || true` 允许服务启动失败后继续 GUI，Finder 用户未必能看见详细原因。

暂保留开发 wrapper 并准确标名。正式打包另做独立验证：Python/Qt/SQLCipher/Chroma/Torch 原生库、模型缓存/首次下载、离线启动、安装体积、签名、公证、升级回退、数据留存。Qt 的 [macOS 部署文档](https://doc.qt.io/qt-6/macos-deployment.html) 可作核对入口，工具选择前用当前依赖做小型打包试验，不预估“换个后缀即可交付”。

## 3. 持续运行缺口

- **RUN-07 / P2：运维与恢复未闭环。** stdout/stderr 文件没有轮转/留存限制；无持续任务指标、最近失败和恢复入口；安装/restart 直接停止旧 job，无业务 drain。KeepAlive 当前只对失败退出重启，正常退出不会自动重启，这是配置语义，需要与常驻承诺一致。
- **RUN-08 / P2：备份未演练恢复。** 本机 `.selfindex-backup-20260926` 为同盘副本，不能防磁盘丢失；尚无跨版本/密钥恢复演练。建立备份清单、受保护独立副本、校验与恢复测试，再承诺长期归档可靠性。
- **RUN-09 / P3：依赖与维护记录。** 有 uv.lock 和 requirements，但 pyproject 混入 JupyterLab 等开发依赖，未见 CI、正式构建配置或发布流水线。先统一安装说明和 Python 支持矩阵，区分运行/开发依赖，再在隔离环境验证最小安装。不要在当前 .venv 中大规模升级试错。
- **RUN-10 / P3：仓库卫生。** `.gitignore` 忽略自身，未忽略 .DS_Store，文档混有旧 Windows 默认流程。逐项整理，不在高风险数据修复提交里混入格式/换行改写。

## 4. 必做运行验收

临时 profile：首次启动、重复启动、慢模型、端口冲突、写入中退出、异常退出、索引中断、磁盘满/权限错误。独立账户或用户安排的测试时段：Finder/Dock、最小化恢复、登录/登出、睡眠唤醒、重启、无源码目录安装、升级和卸载后数据保留。

本轮没有执行这些真实生命周期测试。LaunchAgent 的设计背景可参考 Apple [创建 launchd jobs](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html)，这是归档文档，正式分发时还应核对目标 macOS 的现行 ServiceManagement 要求。

## 后续状态（sol，2026-09-26）

RUN-01 已改为先等待健康恢复；对仍无响应但已加载的 job，只调用不带 `-k` 的 `kickstart`，不强杀正在运行的服务。临时 mock 测试覆盖短暂失败、持续失败和未加载 job；原审计脚本现在输出 `forced_restart=false`。API-03 的深度能力状态、RUN-03 单写者与其他运行/发布项仍未处理。当前运行服务未重启，源码改变不会使已运行进程热更新。
