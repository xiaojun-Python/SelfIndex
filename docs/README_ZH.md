# 文档索引

本页是现行文档入口。根目录 `README_ZH.md` 说明启动和常用工作流；这里按用途区分运行说明、结构参考、审计记录和历史资料。

## 当前运行与维护

- [本机 API](local-api_ZH.md)：其他 App、桌面客户端和浏览器采集的接口。
- [浏览器采集扩展](browser-capture-extension_ZH.md)：扩展安装与使用。
- [索引一致性与模型切换](index-integrity_ZH.md)：只读对账、旧索引认领和修复前提。

## 结构参考

- [架构](architecture_ZH.md)：归档、记忆、召回三层及本机服务边界。
- [数据库结构](database-structure_ZH.md)：SQL 主表、删除队列和 Chroma 模型标识。
- 英文参考：[Architecture](architecture.md)、[Database Structure](database-structure.md)。

## 审计与历史

- [2026-09-26 审计索引](audit-2026-09-26/README_ZH.md)：当时的证据、风险和后续工作；其中未标注修复日期的结论可能不是当前代码状态。
- [审计处理进度](audit-2026-09-26/08-resolution-status_ZH.md)：当前各修复包、真实验收与用户暂缓事项。
- [归档目录](archive/README_ZH.md)：已被新入口取代的系统说明、代码地图和早期实施计划。文件保留供追溯，不作为当前操作步骤。

代码与命令的实际行为始终以当前仓库和测试结果为准；审计快照不是运行手册。
