# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 常用命令

```bash
python main.py                                    # 启动平台 → http://127.0.0.1:4000（默认账号 admin/admin）
python -m fde_platform.scanner                    # 跨应用调用契约静态扫描（有问题退出码 1，可入 CI）
python -m fde_platform.mcp_server [--user admin]  # 本地 stdio MCP 服务，暴露全部应用（供外部 AI 工具接入）
python scripts/verify_mcp_http.py                 # 远端 MCP 端点（POST /mcp）end-to-end 验收（需 dev server 在跑）
python scripts/verify_agent_quality.py            # 与平台智能体真对话，校验分析/决策结论是否等于权威值（需平台+agent_service+LLM 在跑，对着真实演示数据）
python scripts/br_coverage.py                     # BR 输出字段级覆盖取证（详设的「输出」↔ 脚本里 TC 步的断言；--write 刷新《测试用例.md》§4 的表）
python scripts/run_gates.py                       # 验证门禁：static+oracle 两层，约 12 秒，**不停服、不动业务数据** —— 改完代码先跑这个
python scripts/verify_psc_oracles.py --scenario   # PSC 对账体检：冗余双路径对账 + 不变式 + 静态探针 + 影子库全链/穿透/注入
python app/nasa_pms/demo/demo_build.py            # nasa_pms 演示环境一键重建（清空 → 造数 → 体检）；见 app/nasa_pms/demo/README.md
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
- 必选 `schema.sql`：应用同目录 DDL 文件，平台加载时解析建表（SQLite/PG 双兼容）。

### 前端
- 每个应用 `app/<组>/<应用>/view.{js,html}`：`view.js` 导出 `PAGE_META`（key/name/ic/title/crumb/order）+ 默认导出工厂；模板经 `new URL("view.html", import.meta.url)` 抓取。落盘即被扫描装配进菜单，**零接线**。
- 组级聚合页（无后端应用，如 dashboard / 流程总览）放 `app/<组>/<页>.{js,html}`（key = 文件名；松散文件，与组内应用子目录并列）。
- `view/lib/`（shell.js / api.js / alpine / styles）是**平台公共基座，只 import 不修改**；`view/pages/` 是平台通用页（Agent）。
- 前端调服务一律 `svc("应用","服务",...)` **字面量**（不能变量拼名）——后端靠扫描源码里的字面量派生「页→服务」隐式放行边。

### 构建流水线（九步法）
`design-plus/` 是**主规格**（含每步完成门禁，强制 100% 覆盖度）。构建入口见 `design-plus/工具链使用说明.md`：

- ① 架构设计 → ② 应用详设 → ③ 编码（CONVENTION）→ ④ 测试用例 → ⑤ 测试执行（`verify_chain`）→ **契约冻结 `app/<组>/_contracts.md`（前后端依赖屏障，未冻结不开工前端）** → ⑥ 前端设计 → ⑦ 前端编码（VIEW_CONVENTION）→ ⑧ 前端测试用例 → ⑨ 前端测试执行（`verify_view`，出口闸）。

参考实现（只读样板）：`app/e2e/`（member/task + dashboard.* / process.* 组级页）。
✅ **该样板现已九步产物齐全**（2026-09-18 补齐，此前只有 ①②③ + 契约冻结 + ⑥⑦）：
`brd/` + `architecture.md` + `architecture_review.md`（①）、`<应用>/应用详设.md`（②）、
`_contracts.md`（契约冻结）、`测试用例.md` + `tests/`（④⑤）、
`前端详设/` + `前端测试用例.md` + `tests/verify_view_e2e*.py`（⑥⑦⑧⑨）。
**照它抄全流程可以照抄**。

> ⚠ 但有一条**别照抄**：本组的 `brd/` 是**据已冻结设计反向整理**的（样板组没有真实业务方递交 BRD），
> 所以 `architecture_review.md` 那份 100% 含一层**同源成分** —— 详见 `app/e2e/brd/00-目录.md` 与
> `architecture_review.md` §五。真实项目里 BRD 是**业务方独立交付**的上游，不能这么反推。

## 迭代（修改现有应用）

对已有应用组提出改动需求时，**先读 `design-plus/迭代执行.md`**：先读组文档（`architecture.md` / `应用详设.md` / `_contracts.md` / `测试用例.md` / `前端详设.md`）→ 改代码 + 同步改文档（改了服务签名必须重跑 `contract_dump` 重新冻结契约）→ 跑 scanner + verify_chain + verify_view。别只改代码，漏改文档、漏跑测试、漏重冻结契约。

## 测试与验收红线（不可逾越，规格见 design-plus/测试执行.md）

1. **数据库隔离（最高优先）**：verify 脚本**绝不污染用户 demo 数据**。按场景选机制：

   | 场景 | 机制 | 起点 | 要停服？ |
   |---|---|---|---|
   | 链测试 `verify_chain_*` | **影子库** `shadow_dbs()` + `shadow_clear(组)` | 空表 | **不用** |
   | 前端 e2e `verify_view_*` | **影子库** `shadow_dbs(env=True, inprocess=False, config=True)` | 空表 | **不用** |
   | 对账体检（破坏性注入） | **影子库**（不清表） | 真实数据 | 不用 |
   | eval `verify_agent_quality` | **真库 + 数据指纹** | 真实数据 + 真 `config/` | 不用（它本就要服务在跑） |
   | 备用 | `dbguard.isolate_dbs()`（**移库**） | 空库 | 要 |

   **`fde_platform/shadowdb.py`（复制副本）**：真库零字节接触，靠 `FDE_DB_ROOT` /
   `FDE_CONFIG_ROOT` 两个环境变量把业务库与平台库导向副本（**环境变量能穿透子进程** ——
   view e2e 是 `subprocess.Popen([python, main.py])` 起平台的，进程内的补丁过不去）。
   ⚠ 2026-09-18 修过一处隔离缺口：`FDE_CONFIG_ROOT` 原先**只有 `users.py` 认**，
   其余模块硬编码真 `config/` ⇒ 测试起的平台会**真读真 cron 并触发定时任务**（run 记录写进真 `scheduler.db`）。
   现在各模块统一走 **`fde_platform/config_paths.py`** 的 `config_path()`（**调用时解析**，别写成模块级常量）；
   `shadowdb` 的副本集合 = 「除 `agent_service.db`（102.6 MB 对话记录）外的 config 库」（其余合计 0.6 MB）。
   详见 `design-plus/验证门禁.md` §五之三 与 `app/psc/BUGS_psc_2026-09-15.md` §7。
   **`dbguard.py`（移库）仍可用**，是「要停服、但真库被移走所以最保险」的那条路；
   **不再是唯一要求**。（实测：服务在跑的同时跑 PSC 链测试与 view e2e 均 PASS，
   业务库 19 个文件哈希与 mtime 全未变。）
2. **跑前杀 dev server**：**只有用 `dbguard`（移库）的脚本**需要 —— Windows 下 `main.py`
   占用 `.db` 句柄会让文件移不动。用**影子库**的**不需要**（只读复制，无锁冲突）。
3. **串行**：`dbguard` 带跨进程锁（`fde_platform/.dbguard.lock`），并行会被干净拒绝。
   影子库不受此限（各用各的临时目录），但**同一个组不要并行**（会争同一份业务数据）。
4. **静态扫描入闸**：编码后 `python -m fde_platform.scanner` 至退出码 0（校验 `self.fde.call` 目标与参数契约）。
5. **前端零报错**：0 console error · 0 pageerror · 0 HTTP≥400 为硬指标。
6. **对账体检与门禁**：改完代码先跑 `python scripts/run_gates.py`（static+oracle，约 12 秒，**不停服、不动业务数据**）。第⑤步的 `verify_chain_<组>.py` 用例与代码**同源于《应用详设》**，同一份盲点——它对账不出「同一件事只修了一半」这类缺陷。新增的**冗余双路径对账 + 不变式 + 静默降级反证 + 影子库**见 `design-plus/验证门禁.md`（含三条纪律与「怎么加一条新检查」）。

> ⚠ **eval 是影子库的例外，别去「顺手也改一下」**：它的 ground truth 在**本进程**算，
> 而跟智能体对话走的 **HTTP 打到另一个已跑着的平台** —— 只影子化本进程 ⇒
> ground truth 看副本、智能体写真库 ⇒ **指纹失效而污染照旧**，比不改更糟。
> 它继续用「真库 + 数据指纹」兜底。

## 其他要点

- 数据库默认 SQLite；配 `DATABASE_URL` 即切 PostgreSQL，建表/SQL 方言自动翻译，应用零改动。
  **DML 编译层**（2026-09-26 加，`fde_platform/sqlc.py`）：应用照旧写 SQLite 方言裸 SQL + `?` 占位符，
  平台用 sqlglot 在 AST 层做方言翻译（审计列注入 / 占位符命名化 / 字面量 `%` 按驱动转义 / 多方言）。
  `FDE_SQL_COMPILER=sqlglot` 启用（**默认 `legacy`**：仍是 `db.py` 内联的字符串手术）；两条路由
  `scripts/verify_pg_translate.py`（现名「SQL 方言编译层」）同时覆盖。PG 池大小用
  `FDE_PG_POOL_MIN`/`FDE_PG_POOL_MAX`（默认 2/10）。评估与决策见 `design-plus/数据库层评估.md`。
- 并发：waitress 工作线程数由 `PLATFORM_THREADS` 控制（默认 64）。**每个请求占一个线程直到响应结束**，而 Agent 对话是 SSE 长连接（一次对话从头占到尾），所以这个数约等于「同时能几个人对话」，超出的排队等而不报错。翻页面这类短请求不受影响（毫秒级完成）。真实的墙通常是 LLM 速率限制而非线程数。再往上（几百并发）要把浏览器协议层下沉到 `agent_service`（`/api/agent2/chat/stream` 现在做的事：确保 leader、建会话、触发、把 AgentScope 事件翻译成前端协议、暂存 HITL 待确认），让 nginx 直接反代 SSE——那是 ~200 行代码搬移 + nginx `auth_request` 子请求解决身份注入，不是配置改动；且 agent_service 直接对外后必须只放行 `/browser/*`。
- MCP 双传输：**协议分发只有一份**（`fde_platform/mcp_server.py`——`initialize/tools/list/tools/call` + 按 `is_effectively_granted` 过滤），两种传输共用它。stdio（`python -m fde_platform.mcp_server`，身份启动时绑定）与 **Streamable HTTP**（`fde_platform/mcp_http.py`，`POST /mcp` + `Authorization: Bearer` 令牌，身份**按请求**注入 `handle_as`——绝不能写 `self.user`，waitress 多线程会互相覆盖）。令牌存 `config/auth.db` 的 `mcp_tokens` 表（只存 sha256、明文仅创建时显示一次、可吊销、记 `last_used_at`），在 `/auth/users` 页按用户生成。`/mcp` 在 `auth.OPEN_PATHS` 里（无 cookie 的机器请求过不了会话闸门），**不是开洞**：端点自己校验令牌，解出的身份照样走同一套授权过滤。nginx 见 `nginx.conf` 的 `location /mcp`（显式透传 Authorization）。
- 平台模块「import 失败即回落」：删掉 `auth.py`/`users.py` 即回落无认证；删 scheduler / llm / mcp_http 模块同理，其余代码无需改动。
- LLM 仅运行期对话 Agent 需要（`LLM_BASE_URL/LLM_API_KEY/LLM_MODEL`）；构建流水线的设计/生成/验收步骤不依赖 LLM。
- Agent 编排层：唯一后端 `fde_platform/agent_service.py`（AgentScope 2.0 编排，双进程 leader 自治建队，import 失败自动回落降级提示）。业务角色下沉到各组 `app/<组>/_roles.py` 声明（`fde_platform/agent_roles.py` 扫描装配），按角色过滤工具在 `fde_platform/agent_tool_filter.py`（软隔离 + 硬兜底）；**用户级**授权在 `users.is_effectively_granted`（显式 ∪ 角色 ∪ 页面派生，唯一实现；`bridge.execute`／工具面装配／`mcp_server` 三处共用），工具面按它给**组**打标（无权限的组保留名字+描述、清空工具——全貌照给、动作空间收紧）；flow 节点按它收窄，收窄到空抛 `FlowAbort` 中止整条流程（详见 `design-plus/多智能体方案.md` §5.1）；共享基座（提示词/进度/组级架构文档读取 + 应用详设按需读取）在 `fde_platform/agent_common.py`；工具桥接在 `fde_platform/agentscope_bridge.py`（含 `_platform_tool_defs`：skill 沉淀全员 + 集成/定时任务配置仅 admin，危险操作 `_meta.dangerous` 走 HITL）；智能体常驻 context 仅组级架构文档，应用级设计文档（`应用详设.md`/`README.md` 等）经 `platform_read_app_doc` **按需读取**（just-in-time，不全量灌 prompt）——各应用应提供 `应用详设.md`（BR/FUNC/数据字典）供其查询；skill 库在 `fde_platform/skills.py`（draft→approve→published，`platform_propose_skill` 提议）；告警在 `fde_platform/alerts.py`（`platform_raise_alert`）。危险操作 HITL 经 `ask_rules` 停车、`/api/agent/confirm` 确认。管理页 `/agent-admin`（`fde_platform/agent_admin.py`）。
- 流程编排（Flow）：声明式 DAG 工作流，组级 `app/<组>/_flow_<key>.yaml` 声明（节点 `id/role/task/output/input/depends_on/when/until/max_loop`），`fde_platform/flow.py` 扫描装配并拓扑分层 + 并行 + 条件分支 + 循环执行；节点 = 轻量 ReAct（`llm.chat` + 工具）。前端「流程编排」页（画布/表单/YAML 三标签）；平台工具 `platform_list_flows/run_flow/save_flow/delete_flow/flow_progress`。格式正本见 `design-plus/智能体角色声明.md`、`design-plus/流程编排方案.md`（可选增强，九步法第⑩⑪步）。
- 参考更细的约定/坑：`design-plus/CONVENTION.md`（后端）、`design-plus/VIEW_CONVENTION.md` + `design-plus/view-convention/`（前端，含 patterns/pitfalls）。
