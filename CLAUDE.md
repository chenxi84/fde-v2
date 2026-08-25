# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 常用命令

```bash
python main.py                                    # 启动平台 → http://127.0.0.1:4000（默认账号 admin/admin）
python -m fde_platform.scanner                    # 跨应用调用契约静态扫描（有问题退出码 1，可入 CI）
python -m fde_platform.mcp_server [--user admin]  # 以 stdio MCP 服务暴露全部应用（供外部 AI 工具接入）
```

测试（每个脚本自包含、独立运行；**必须先停掉 dev server**）：

```bash
python app/<组>/tests/verify_chain_<组>.py            # 后端主链端到端（如 app/psc/tests/verify_chain_psc.py）
python app/<组>/tests/verify_view_<组>_<应用>.py      # 前端单页 e2e（playwright，如 verify_view_psc_inventory_projection.py）
python app/<组>/tests/verify_view_<组>.py             # 组级壳/菜单/dashboard/受限用户
```

## 核心架构（大图景）

这是一个「**领域驱动 + 约定优于配置**」平台。最关键的等式（正本见 `design-plus/CONVENTION.md`）：

> **一个聚合根 = 一个应用 = 一个同名文件夹 = 一个同名类 = 一个同名 SQLite 库 = 一个独立事务/一致性边界。**

- **应用 = 一个主文件**：`app/<组>/<应用>/<应用>.py`，里面那个类就是聚合根，数据 + 规则全封在一个文件里，**无 manifest**——应用名/服务名/库名全从文件名与公共方法名推导。
- **平台注入三样东西，应用不写 `__init__`**：
  - `self.db`：指向同名 `.db` 的 SQLite 连接（WAL / 行工厂 / 自动审计列 `created_at/updated_at/created_by/updated_by`）；事务归平台，应用只 `execute`。
  - `self.fde`：跨应用网关 `self.fde.call("应用", "服务", **kw)`——**按名调用、不 import、运行期绑定**。
  - `self.ctx`：身份上下文 `{userno, departmentno, role}`——平台权威、自动透传、不可伪造；**应用不实现鉴权**。
- **公共方法 = 服务**；业务失败 `raise FdeError("人话")`（跨调用原样传播）；返回直接返回可 JSON 序列化值。
- 必选 `_init_db()`：平台加载时调用，幂等建表。

### 前端
- 每个应用 `app/<组>/<应用>/view.{js,html}`：`view.js` 导出 `PAGE_META`（key/name/ic/title/crumb/order）+ 默认导出工厂；模板经 `new URL("view.html", import.meta.url)` 抓取。落盘即被扫描装配进菜单，**零接线**。
- 组级聚合页（无后端应用，如 dashboard / 流程总览）放 `view/<组>/<页>.{js,html}`（key = 文件名）。
- `view/lib/`（shell.js / api.js / alpine / styles）是**平台公共基座，只 import 不修改**；`view/pages/` 是平台通用页（Agent / 服务台）。
- 前端调服务一律 `svc("应用","服务",...)` **字面量**（不能变量拼名）——后端靠扫描源码里的字面量派生「页→服务」隐式放行边。

### 构建流水线（九步法）
`design-plus/` 是**主规格**（含每步完成门禁，强制 100% 覆盖度）。构建入口见 `design-plus/工具链使用说明.md`：

- ① 架构设计 → ② 应用详设 → ③ 编码（CONVENTION）→ ④ 测试用例 → ⑤ 测试执行（`verify_chain`）→ **契约冻结 `app/<组>/_contracts.md`（前后端依赖屏障，未冻结不开工前端）** → ⑥ 前端设计 → ⑦ 前端编码（VIEW_CONVENTION）→ ⑧ 前端测试用例 → ⑨ 前端测试执行（`verify_view`，出口闸）。

参考实现（只读样板）：`app/e2e/`（member/task，九步产物齐全）+ `view/e2e/dashboard.*`。

## 测试与验收红线（不可逾越，规格见 design-plus/测试执行.md）

1. **数据库隔离（最高优先）**：所有 verify 脚本在 `fde_platform/dbguard.py` 的 `isolate_dbs()` 下跑——移走真实库 → 空库跑 → 结束还回，**绝不污染用户 demo 数据**。
2. **跑前杀 dev server**：Windows 下运行中的 `main.py` 占用 `.db` 句柄会导致隔离失败。
3. **串行**：dbguard 带跨进程锁（`fde_platform/.dbguard.lock`），并行会被干净拒绝。
4. **静态扫描入闸**：编码后 `python -m fde_platform.scanner` 至退出码 0（校验 `self.fde.call` 目标与参数契约）。
5. **前端零报错**：0 console error · 0 pageerror · 0 HTTP≥400 为硬指标。

## 其他要点

- 数据库默认 SQLite；配 `DATABASE_URL` 即切 PostgreSQL，建表/SQL 方言自动翻译，应用零改动。
- 平台模块「import 失败即回落」：删掉 `auth.py`/`users.py` 即回落无认证；删 scheduler / llm 模块同理，其余代码无需改动。
- LLM 仅运行期对话 Agent 需要（`LLM_BASE_URL/LLM_API_KEY/LLM_MODEL`）；构建流水线的设计/生成/验收步骤不依赖 LLM。
- Agent 编排层：唯一后端 `fde_platform/agent_agentscope.py`（AgentScope 2.0 编排，import 失败自动回落降级提示）。会话持久化用 AgentScope 原生 state（`fde_platform/agent_state.py`，取代 chatstore，跨进程 `model_dump(mode="json")` + `model_validate` 恢复，前端历史从 `context` 派生）。共享基座（提示词/进度/会话 helper）在 `fde_platform/agent_common.py`；工具桥接在 `fde_platform/agentscope_bridge.py`（含 `_platform_tool_defs`：skill 沉淀全员 + 集成/定时任务配置仅 admin，危险操作 `_meta.dangerous` 走 HITL）；skill 库在 `fde_platform/skills.py`（draft→approve→published，`platform_propose_skill` 提议）。危险操作 HITL 经 `ask_rules` 停车、`/api/agent/confirm` 确认。管理页 `/agent-admin`（`fde_platform/agent_admin.py`）。
- 参考更细的约定/坑：`design-plus/CONVENTION.md`（后端）、`design-plus/VIEW_CONVENTION.md` + `design-plus/view-convention/`（前端，含 patterns/pitfalls）。
