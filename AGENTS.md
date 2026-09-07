# AGENTS.md

面向 AI 代理（Claude Code / Codex / Cursor / Workbuddy 等）的项目说明与工作约定。**完整版见 [`CLAUDE.md`](CLAUDE.md)，开工前请先完整阅读并遵守。**

## 必须遵守的关键规矩

1. **数据操作一律走 MCP 工具 / 平台服务，禁止直接写脚本读写 `.db` 文件。**
   - 数据导入、创建主数据、任何业务操作，通过 MCP 工具调用（先启动 `python -m fde_platform.mcp_server --user admin`，把它配进你的 MCP 客户端）。
   - 工具名为 `组__应用__服务`，例如导入销量历史用 `psc__sales_history__import_batch`、创建物料用 `psc__md_material__create`。
   - 直接往 `.db` 文件 INSERT 会绕过业务校验、审计列（created_at/updated_at/created_by/updated_by）、跨应用引用校验，且与运行中的服务抢库，属于错误做法。
2. **改代码先读文档**：`design-plus/CONVENTION.md`（后端约定）、`design-plus/VIEW_CONVENTION.md`（前端约定）、目标组的 `app/<组>/architecture.md` 与各应用 `应用详设.md`（可按需用 `platform_read_app_doc` 工具读取）。
3. **改了服务签名必须重冻结契约**：重跑 `python -m fde_platform.contract_dump <组>` 更新 `app/<组>/_contracts.md`。
4. **测试红线**：跑 `verify_*` 脚本前先停 dev server；测试在 dbguard 隔离下运行，绝不污染用户数据。

## 常用入口

- 平台核心架构 / 应用约定 / 九步法 / 测试红线：见 [`CLAUDE.md`](CLAUDE.md) 和 [`README.md`](README.md)。
- 应用组构建流水线（九步法）：见 `design-plus/工具链使用说明.md`。
- 快速上手 / 部署：见 [`HOW-TO-USE.md`](HOW-TO-USE.md)。
