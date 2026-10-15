# 基线与架构判断

日期：2026-09-26。本报告是当日工作树的阶段性审计，不是发布认证。后续先读 [交接计划](../../docs/audit-2026-09-26/07-backlog-and-handoff_ZH.md)。

## 1. 总体结论

SelfIndex 已是“原生桌面客户端 + 本机知识服务”，不再只是一个网页项目。方向适合用户的目标：日常点击打开、关闭窗口不影响服务、以后其他本机 App 查询同一资料库。**无需为此重写为 Swift、引入微服务或恢复以浏览器为主的 UI。**

当前定位应是可使用的个人开发版，而非可独立安装、无人值守且具备恢复保证的成熟产品。优先事项是数据身份、编辑保护、失败恢复和服务生命周期；再做发布打包和界面细节。UI 与服务已在进程和 HTTP 层分开，但部署、配置、令牌路径、导入脚本还没有彻底分离。

## 2. 当日基线

| 项目 | 实测/检查结果 |
| --- | --- |
| Git | HEAD `c530366`，提交标题 `2026.09.26：01`；前一提交 `b107da3` |
| 系统 | macOS 27.0，build 26A428，arm64 |
| Python | 项目 `.venv`，3.12.13 |
| UI | PySide6-Essentials / Qt 6.11.2 |
| 服务 | Flask 3.1.3、Waitress 3.0.2，127.0.0.1:5050，4 个线程 |
| 检索 | Chroma 1.5.5、Torch 2.10.0、sentence-transformers 5.5.1、BAAI/bge-small-zh-v1.5、CPU |
| 数据库 | SQLCipher，sqlcipher3-wheels 0.5.7；密钥已配置，未收集或写入报告 |
| 文件体积 | `.venv` 约 1.3 GB；data 约 510 MB；同机备份约 510 MB |
| 测试 | 本轮已有完整 unittest 69/69 通过；不代表故障/并发/实机验收通过 |
| 运行快照 | 服务 PID 71563、GUI PID 74832；5050 只有一个监听进程，LaunchAgent 指向该服务 |

PID 和版本仅是本次审计时刻的事实，不可作为下次运维命令的参数。`.env` 中 DEBUG=True，但生产入口明确强制关闭 Flask debug 和异常传播，不能据 `.env` 判定生产调试器开放。

审计开始前已有未提交修改：README_ZH.md、desktop_mac/main.py、docs/macos-desktop-service-plan_ZH.md；另有三个新增桌面测试和 `.DS_Store`。这些不是本轮新增的业务改动。Git 已建立，不能再沿用早期“项目没有 Git”的描述。

## 3. 实际结构

```text
Finder / Dock -> 开发版 .app -> desktop_mac (PySide6)
                                  |
                                  | loopback HTTP /api/v1
                                  v
LaunchAgent -> app.service_main -> Waitress -> Flask API
                                              |
                          app.services.documents / engine.retriever
                                              |
                          SQLCipher 归档/修订 + Chroma 向量投影

浏览器扩展 -> 旧 /api/ingest/... -> 导入逻辑
维护 CLI -----------------------> 直接访问 SQLCipher / Chroma
旧网页模板 ---------------------> 仍由同一个 Flask 服务提供
```

证据入口：[服务](../../app/service_main.py#L10)、[应用组装](../../app/__init__.py#L19)、[文档保存](../../app/services/documents.py#L24)、[数据库](../../engine/database.py#L17)、[桌面](../../desktop_mac/main.py)。

优点：薄 HTTP 客户端、SQLite 事务、原始资料与检索单元区分、索引失败时保留已提交正文、Loopback 默认边界、GUI 后台 worker、版本化 API。这些已有价值应保留。

## 4. 结构性缺口

- **ARCH-01 / P2 / 代码确认：写入口不统一。** 编辑走 app service，导入/同步/修复直接访问存储；不同入口各自编排 SQLite 与 Chroma，失败语义不一致。先统一写入协议和单写者约束，再决定是否抽共用服务，不必先建立复杂框架。
- **ARCH-02 / P2 / 代码确认：配置仍以源码目录为中心。** engine 导入 app.core.settings，GUI 和服务也共享本地配置/令牌 helper。当前属于进程解耦，不是可独立部署的通用 SDK。逐步改为入口装配配置和依赖，内部纯逻辑避免读取全局环境。
- **ARCH-03 / P2 / 设计缺口：任务生命周期没有持久化协议。** embedding 在请求中同步运行，pending 不是有调度器负责的后台任务。可以先以 SQL 中的任务状态/幂等键和单 worker 实现，不需要 Redis 或分布式队列。
- **ARCH-04 / P2 / 维护缺口：兼容面未收敛。** Windows 入口、旧网页、v1 API、浏览器扩展端点、两套 macOS 进程控制并存。先列支持矩阵和弃用策略，不能删旧路由时顺带破坏扩展。

## 5. 建议边界

1. SQL 归档是内容事实来源；向量库是可重建投影，不承担正文权威职责。
2. 所有写入先获得文档版本/资料库写入约束，在 SQL 事务中记录变更及待索引任务；外部索引成功后再确认任务。
3. 服务发布稳定的查询、详情、编辑及状态协议；桌面只承担呈现、草稿和用户操作，不直接修数据库。
4. 维护命令通过服务执行，或显式进入独占维护模式。用户界面无权因一次超时擅自强杀服务。
5. 数据、配置、缓存、日志与程序安装目录分离；实际迁移必须备份、dry-run、校验和可回退。

## 6. 尚未验收

没有完成长时间 soak test、睡眠唤醒/登出、崩溃恢复、干净 macOS 账户安装、并发多客户端写入或真实扩展端到端测试。数据子代理额度中断，数据报告由主代理补写；桌面子代理已写报告，但不能把离屏结果当作真实 Dock/VoiceOver 验收。未作漏洞库扫描或依赖许可证完整核查。
