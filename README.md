# FDE 技术平台 v2（fde-v2）

一个「**领域驱动 + 约定优于配置**」的轻量业务平台，以及一条「**原始业务说明 → 可运行业务系统**」的全自动构建流水线。

- **平台（运行期）**：把 `app/` 下符合约定的聚合根应用自动发现、加载、暴露为服务，并提供 Web 控制台、AI Agent、MCP、定时任务、鉴权等多入口。
- **流水线（构建期）**：`design-plus/` 轻量九步法（后端五步 + 前端四步），配合 AI 代理从一段业务说明出发，自动产出**架构设计 → 详设 → 编码 → 测试用例/执行 → 契约冻结 → 前端四步**，端到端交付一个可运行系统。

> 仓库内自带现行约定样板 `app/e2e/`（成员/任务，最小完整、九步产物齐全）。

---

## 目录

- [核心设计](#核心设计)
- [仓库结构](#仓库结构)
- [快速开始](#快速开始)
- [平台运行期能力](#平台运行期能力)
- [应用约定（CONVENTION v2）](#应用约定convention-v2)
- [构建流水线（九步法）](#构建流水线九步法)
- [测试与验收红线](#测试与验收红线)
- [配置](#配置)
- [深入阅读](#深入阅读)

---

## 核心设计

三条贯穿平台与约定的设计原则：

1. **业务内聚于一个文件**——业务对象（数据）与业务规则（逻辑）全部封装在单个主文件 `<应用>.py` 里，主文件中的那个类就是 DDD 意义上的**聚合根**。
2. **约定优于配置**——应用名、服务名、库名全部从文件夹名 / 公共方法名推导，**无任何 manifest**。
3. **按名调用、运行期绑定**——跨应用调用只认「名字」（`self.fde.call("应用","服务", **参数)`），不 `import`、不共享事务，编译可过、运行才校验。

由此得到的根基等式（`design-plus/CONVENTION.md` §2 / §8）：

> **一个聚合根 = 一个应用 = 一个同名文件夹 = 一个同名类 = 一个同名 SQLite 库 = 一个独立事务 / 一致性边界。**

聚合的公共方法即对外**服务**；聚合之间用 **ID 弱引用 + 跨应用调用**协作，一致性靠幂等 / 补偿（无分布式事务）。

---

## 仓库结构

```
fde-v2/
├── main.py                    # 平台启动入口（python main.py → http://127.0.0.1:4000）
├── fde.py                     # 平台 SDK（对应用的公共依赖，目前含业务异常基类 FdeError）
├── fde_platform/              # 平台实现（发现/加载/注入/路由/鉴权/Agent/MCP/调度…）
│   ├── web.py                 #   Flask 应用与控制台路由
│   ├── runtime.py / scanner.py#   运行期加载与跨调用静态扫描器
│   ├── agent_agentscope.py    #   Agent 编排唯一后端（AgentScope 2.0，import 失败回落降级）
│   ├── agent_common.py        #   Agent 共享基座（提示词 / 进度 / 会话 helper）
│   ├── agent_state.py         #   会话持久化（AgentScope 原生 state，取代 chatstore）
│   ├── agentscope_bridge.py   #   工具桥接（平台工具定义 + 危险操作 HITL）
│   ├── skills.py              #   自进化 skill 库（draft→approve→published）
│   ├── agent_admin.py         #   Agent 管理页 /agent-admin
│   ├── llm.py / llm_admin.py  #   LLM 接入与管理（可插拔）
│   ├── mcp_server.py          #   MCP 服务（stdio）
│   ├── platform_mcp_tools.py  #   平台管理能力开放为 MCP tools
│   ├── scheduler.py           #   定时任务（APScheduler，可插拔）
│   ├── auth.py / users.py     #   鉴权（可插拔，删除即回落无认证）
│   ├── integration.py         #   集成接口管理（外部系统适配器 / 网关）
│   ├── view_registry.py       #   前端视图扫描与菜单装配
│   ├── listsort.py            #   列表排序（平台保留参数 sort_by/sort_dir）
│   ├── dbguard.py             #   测试数据库隔离
│   └── static/ · templates/   #   控制台前端资源
├── app/                       # 全部 FDE 应用（组 = 一级目录）
│   ├── e2e/                   #   应用组「e2e」——现行约定样板（member/task）
│   │   ├── 架构设计.md         #     ① 组级总体架构
│   │   ├── _contracts.md       #     冻结的服务契约
│   │   └── <应用>/             #     member / task，各含
│   │       ├── <应用>.py        #       聚合根（数据+规则，一个文件）
│   │       ├── README.md        #       Agent 操作指南
│   │       ├── 应用详设.md       #       后端详设（设计态，不 serve）
│   │       ├── 前端详设.md       #       前端详设（设计态，不 serve）
│   │       ├── view.js/view.html#       前端页面（落盘即进菜单）
│   │       └── <应用>.db        #       运行期自建（不提交）
├── view/                      # 组级聚合页（无后端应用的页面，如 e2e/dashboard）
│   ├── lib/                   #   前端公共库（alpine / shell / api / styles，只读环境前提）
│   └── pages/                 #   平台通用页（console / agent）
├── design-plus/                    # ★ 主规格：轻量技能体系（九步法 + 前后端约定正本，含完成门禁）
│   ├── CONVENTION.md          #   ★ 后端应用约定正本（CONVENTION v2，唯一来源）
│   ├── VIEW_CONVENTION.md     #   ★ 前端视图约定正本（VIEW_CONVENTION v1，唯一来源）
│   ├── view-convention/       #   前端约定参考资料（architecture/patterns/design-system/pitfalls）
│   ├── 工具链使用说明.md        #   手工执行轨（Claude Code / 工程师逐步执行九步法）
│   ├── 架构设计.md             #   第①步：聚合根识别
│   ├── 应用设计.md             #   第②步：逐聚合根应用设计
│   ├── 应用编码.md             #   第③步：按 CONVENTION 生成应用
│   ├── 应用测试.md             #   第④步：后端测试用例生成（整组一份）
│   ├── 测试执行.md             #   第⑤步：用例 → 可运行集成测试并跑通
│   ├── 前端设计.md             #   第⑥步：逐应用前端详设（+ 组级看板设计）
│   ├── 前端编码.md             #   第⑦步：按 VIEW_CONVENTION 生成 view.{js,html}
│   ├── 前端测试.md             #   第⑧步：前端测试用例生成（逐应用 + 组级补充）
│   └── 前端测试执行.md          #   第⑨步：用例 → 逐应用 verify_view 脚本 + 组级脚本并跑通
├── config/                    # 配置与运行期数据库
│   └── .env.example           #   配置模板（复制为 .env）
└── scripts/                   # 部署与运维脚本（deploy.sh / gen-cert.sh / smoke_test.py）
```

---

## 快速开始

**环境**：Python 3.10+，依赖可导入 `fde_platform`（Flask 等）。前端验收另需 `pip install playwright && python -m playwright install chromium`。

```bash
# 1. 配置（可选，仅运行期对话 Agent 需要 LLM；未配置不影响应用清单/手工调用/MCP）
cp config/.env.example config/.env      # 按需填 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL

# 2. 启动平台
python main.py
# 浏览器访问 http://127.0.0.1:4000
```

启动横幅会打印：鉴权 / 定时任务 / LLM / Agent 编排四个**可插拔**模块的开关状态，以及发现的应用清单（按组分组）。

- **鉴权**：默认开启，首次登录 `admin / admin`（请尽快改密）。删除 `fde_platform/auth.py` 与 `users.py` 即回落无认证模式。
- **MCP 服务**（stdio，另起进程）：`python -m fde_platform.mcp_server`

### 从零构建一个新业务系统

推荐入口：将设计规格与业务说明发给 AI 代理（如 Claude Code），按 `design-plus/工具链使用说明.md` 逐步执行九步法（含完成门禁，每步强制 100% 覆盖度）。

也可手工驱动 Claude，把下面这句话连同你的业务说明发给它：

```
按 design-plus/ 九步法构建应用组 <组>（逐步照 design-plus/工具链使用说明.md 执行），业务说明如下：
<背景 / 目标 / 主流程 / 涉及数据 / 角色，越具体越好>
```

Claude 会读规范、逐步推进，你只需在「第①步 应用划分」「第②步 字段/规则/验收」两处把关。

---

## 平台运行期能力

| 能力 | 说明 |
|---|---|
| **发现与加载** | 扫描 `app/` 下应用（分组或直接放置皆可），按路径动态加载主文件、缓存、调用其必选的 `_init_db()` 幂等建表。 |
| **多入口服务暴露** | 公共方法以 `应用名.方法名` 暴露，经 Web 控制台 / REST API / Agent / MCP / 定时任务多入口调用，走同一 `platform.call` 调用链。 |
| **跨应用路由** | 实现 `self.fde.call` 的按名解析与运行期绑定，身份 `ctx` 自动透传且不可伪造。 |
| **身份与鉴权** | 平台认证调用人、注入权威 `ctx`；授权维度是「应用下的开放服务」，Web / MCP / Agent / 调度四处一致强制。 |
| **静态扫描器** | `python -m fde_platform.scanner` 用 AST 在**不运行**前提下校验所有 `self.fde.call` 的目标与参数契约（退出码可入 CI）；结果见控制台 `/api/scan`。 |
| **AI Agent（AgentScope）** | 唯一后端 `agent_agentscope.py`（AgentScope 2.0 编排，import 失败自动回落降级）；自进化 skill 库（`skills.py` draft→approve→published）；危险操作经 `_meta.dangerous` 走 HITL 人工确认；会话持久化用 AgentScope 原生 state（`agent_state.py`，取代 chatstore）。 |
| **资源目录** | 每个应用自动建 `resource/import-file`（上传）/ `export-file`（产出），配套内置文件工具供 Agent / MCP 做数据导入。 |
| **定时任务** | APScheduler 按 cron 调度公共服务，管理页 `/scheduler`，日志落 `config/scheduler.db`。 |
| **视图装配** | 扫描各应用 `view.{js,html}` 的自描述 `PAGE_META`（key/name/ic/order/bold/col_default_hidden），零接线装配进所属组菜单；组级聚合页放 `view/<组>/`，经 `view_registry.py` 统一扫描与 `/view/<组>/` 路由 serve。 |
| **列表排序（零改动）** | 平台保留参数 `sort_by/sort_dir` + `watchSortableTables()` 自动装饰表头：点击列头由后端排序后返回当前页，应用 list 契约与前端代码均无需改动（`fde_platform/listsort.py`）。 |
| **自定义显示列（跟账号）** | 工具栏右侧注入列设置图标，弹层可对**全部已渲染列**勾选显隐（表头文本标识 + nth-child 隐藏，扛 x-for 重渲染）；配置存 `/api/prefs/cols:<页>`（`user_prefs` 表，per-user 持久化）。`list()` 约定返回全字段、视图渲染全列，`PAGE_META.col_default_hidden` 声明默认隐藏的非关键列（默认只显示关键列），用户调整后个人配置覆盖。范例 `md_material`。 |
| **数据库双模** | 默认 SQLite，配置 `DATABASE_URL` 即可切换 PostgreSQL；建表语句、SQL 方言自动翻译，应用零改动。 |
| **自动审计** | `CREATE TABLE` 自动追加 `created_at / updated_at / created_by / updated_by`；INSERT / UPDATE 自动注入当前用户与时间。 |
| **集成接口管理** | `/integration`：扫描发现外部系统适配器与网关应用，支持 HTTP 方法 / 鉴权（Basic/Bearer/API Key）/ Mock / 连通测试 / 调用日志统计。 |
| **平台 MCP 工具** | 用户管理、LLM 配置、集成接口等平台管理能力开放为 MCP tools，Agent 可对话式管理平台。 |

**可插拔**：鉴权 / 调度 / 大模型配置均以「import 失败即回落」实现——删除对应模块文件，平台照常运行，其余代码无需改动。

---

## 应用约定（CONVENTION v2）

完整正文见 `design-plus/CONVENTION.md`（唯一正本）。最小骨架：

```python
# app/<组>/<应用>/<应用>.py
from fde import FdeError

class Todo:                                  # 类 = 聚合根，PascalCase（文件夹名 snake_case）
    def _init_db(self):                       # 必选：加载时平台调用，幂等建表
        self.db.execute("CREATE TABLE IF NOT EXISTS todo (id INTEGER PRIMARY KEY, title TEXT, owner_no TEXT)")

    def create(self, title: str):             # 公共方法 = 对外服务（服务名 = 方法名）
        if not title.strip():
            raise FdeError("标题不能为空")     # 业务失败 → 抛业务异常
        owner = self.ctx["userno"]           # 平台注入的身份上下文
        cur = self.db.execute("INSERT INTO todo (title, owner_no) VALUES (?,?)", (title, owner))
        return {"id": cur.lastrowid, "title": title, "owner": owner}

    def remind(self, todo_id: int):           # 跨应用调用：按名、不 import、运行期绑定
        self.fde.call("notify", "send", to=self.ctx["userno"], text=f"待办 #{todo_id} 该处理")
        return {"notified": todo_id}
```

平台向每个聚合根实例注入三样东西（应用**不写 `__init__`**）：

| 注入属性 | 用途 |
|---|---|
| `self.ctx` | 身份上下文 `{userno, departmentno, role}`——平台权威、跨应用自动透传、不可伪造；**应用不实现鉴权**，只读。 |
| `self.db` | 指向同名 `.db` 的 SQLite 连接（已开 WAL / busy_timeout / 行工厂）；**事务归平台**，应用只管 `execute`。 |
| `self.fde` | 跨应用网关 `self.fde.call("应用","服务", **参数)`。 |

**返回与错误**：成功直接返回业务值（可 JSON 序列化）；业务失败 `raise FdeError("人话")`（跨调用原样传播，调用方可 `try/except`）；未预期异常由平台归一为系统错误并屏蔽细节。

---

## 构建流水线（九步法）

编排总纲：见 `design-plus/工具链使用说明.md`（Claude Code / 工程师逐步执行），从一段业务说明到完整可运行系统。

| 步 | 做什么 | 任务 kind | 产出 | 人工关注 |
|---|---|---|---|---|
| ① | 聚合根识别 / 总体架构 | `arch` | `app/<组>/架构设计.md` | ★★★ 应用划分 |
| ② | 应用详设（逐应用） | `detail` | `app/<组>/<应用>/应用详设.md` | ★★★ 字段/规则/验收 |
| ③ | 应用编码（CONVENTION） | `code` | `app/<组>/<应用>/<应用>.py` + `README.md` | 编码后跑 scanner 契约对齐 |
| ④ | 测试用例生成（只生成不运行） | `testcase` | `app/<组>/测试用例.md`（整组一份） | 可抽查覆盖度 |
| ⑤ | 测试执行（真实树直跑 · 清表初始化） | `testexec` | `app/<组>/tests/verify_chain_<组>.py`（+ parts）+ `app/<组>/tests/测试报告_<组>.md`（+ `app/<组>/tests/BUGS_<组>.md`） | ★★ 是否全绿；失败先 triage |
| — | 契约冻结（前端段依赖屏障） | `contracts` | `app/<组>/_contracts.md` | ★ 屏障检查 |
| ⑥ | 前端设计 | `fdesign` | 逐应用 `前端详设.md` + 组级 `前端详设/dashboard.md` | 可看页面规划 |
| ⑦ | 前端编码（VIEW_CONVENTION） | `fcode` | `app/<组>/<应用>/view.{js,html}` + `view/<组>/dashboard.{js,html}` | 落盘即进菜单 |
| ⑧ | 前端测试用例（只生成不运行） | `ftest` | 逐应用 `前端测试用例.md` + 组级补充 `app/<组>/前端测试用例.md` | — |
| ⑨ | 前端测试执行（playwright 串行真跑） | `fverify` | `app/<组>/tests/verify_view_<组>_*.py` + `app/<组>/tests/前端测试报告.md` | ★ 0 报错 |

**两个硬关卡**：

1. **依赖屏障（⑤ → ⑥）**：契约冻结 `_contracts.md` 是前端段的唯一前置——契约未冻结不开工前端（防止前端 `svc` 调用与后端签名漂移）。
2. **出口闸（⑨）**：前端 0 报错通过（0 console error · 0 pageerror · 0 HTTP≥400）= 整个工作台验收完成；跨应用集成由第⑤步联通测试兜底（覆盖单应用验收覆盖不到的跨应用 `self.fde.call` 编排）。

**可重入**：每步幂等地「吃上游产物 → 写本步产物」；上线后持续演进 = 单步重执行。

---

---

## 测试与验收红线

一切验收（第⑤步测试执行 / 第⑨步前端测试执行）共同遵守、不可逾越（规格见 `design-plus/测试执行.md`、`design-plus/前端测试执行.md`）：

1. **数据库隔离（最高优先）**：在 `fde_platform/dbguard.py isolate_dbs()` 下跑——测试前移走全部应用库 / 平台库，结束原样还回，**绝不污染用户 demo 数据**。
2. **串行**：dbguard 带跨进程锁（`fde_platform/.dbguard.lock`），并行触发会被干净拒绝。
3. **跑前杀 dev server**：Windows 下运行中的 `main.py` 会占用 `.db` 句柄导致隔离失败，验收前先终止。
4. **静态扫描入闸**：第③步编码后跑 `python -m fde_platform.scanner` 至退出码 0（跨应用调用契约左移校验；值域/结构错位靠第⑤步真实跑通逼出）。
5. **前端零报错**：以「0 console error · 0 pageerror · 0 HTTP≥400」为硬指标。
6. **视图资源红线**：前端只经写死端点 `/app/<名>/view.{js,html}` serve；同目录 `.py` / `.db` / `resource/` 绝不暴露。
7. **身份与鉴权**：ctx 平台权威、自动透传且不可伪造；应用不实现鉴权；服务仅绑 `127.0.0.1`。

常用入口：

```bash
python -m fde_platform.scanner             # 跨应用调用契约左移校验（有问题退出码 1）
python app/<组>/tests/verify_chain_<组>.py  # 后端主链端到端（各组自含，dbguard 隔离）
python design-plus/前端验收样板/verify_view_e2e.py            # e2e 前端验收（playwright，需 Chromium）
```

---

## 配置

`config/.env`（由 `.env.example` 复制，**已 gitignore，勿提交**）：

| 变量 | 说明 |
|---|---|
| `PLATFORM_PORT` | 平台浏览器端端口（默认 `4000`） |
| `PLATFORM_HOST` | 监听地址（默认 `127.0.0.1`；Docker 部署设为 `0.0.0.0`） |
| `DATABASE_URL` | PostgreSQL 连接串（留空 = SQLite；Docker 部署自动切换） |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | 运行期对话 Agent 用（兼容 OpenAI 接口）；留空则 Agent 降级，不影响应用清单 / 手工调用 / MCP |
| `SECRET_KEY` | 会话签名密钥（留空则自动生成随机密钥，持久化到 `config/.secret_key`） |

**构建流水线的设计 / 生成 / 验收步骤不需要 LLM 配置**，未配置也能跑完全流程。

---

## 深入阅读

| 想了解 | 读 |
|---|---|
| 怎么驱动流水线构建系统（操作手册 · 九步法全景） | `design-plus/工具链使用说明.md` |
| 后端应用约定（CONVENTION v2，唯一正本） | `design-plus/CONVENTION.md` |
| 聚合根识别方法（第①步，本体驱动 + DDD） | `design-plus/架构设计.md` |
| 应用详设模板（第②步） | `design-plus/应用设计.md` |
| 前端视图约定正本（第⑥–⑨步） | `design-plus/VIEW_CONVENTION.md`（+ 参考 `design-plus/view-convention/`） |
| 上线后持续演进 | 修改详设 → AI 代理单步重执行 → 回归测试 |
| 外部系统对接 | `/integration` 集成接口管理（扫描/配置/测试/跟踪） |
| 平台 MCP 管理 | `python -m fde_platform.mcp_server --user admin` |
| 部署指南 | `HOW-TO-USE.md`（本地开发 / Docker HTTP / Docker HTTPS+PG / deploy.sh 一键部署） |
| 活的参考实现（只读） | `app/e2e/`（现行约定样板：架构 / 详设 / 前端详设 / view / 契约一应俱全） |
