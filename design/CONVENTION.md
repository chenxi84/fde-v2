# FDE 应用约定（v2）

> 本文件是 FDE v2 的**唯一约定正本**，置于 `design/CONVENTION.md`（原 `skill/app-convention.md`、`app/CONVENTION.md` 先后迁至此处，旧路径已随 `skill/` 退场）。凡符合本约定的应用（`app/` 下——或其**应用组**子目录下——一个同名文件夹 + 主文件），FDE 平台即可加载、暴露并运行它；
> 凡本约定未规定之事，一律由 FDE 平台负责，应用不必关心。
>
> 三条设计原则：
> 1. **业务内聚于一个文件**——业务对象（数据）与业务规则（逻辑）全部封装在单个主文件 `.py` 里；
> 2. **约定优于配置**——应用名、服务名、db 名全部从文件夹名/方法名推导，无需任何 manifest；
> 3. **按名调用、运行期绑定**——跨应用调用只认"名字"（短名按调用方所在组解析，亦可 `组/名` 显式跨组），不 `import`，编译可过、运行才校验。

---

## 1. 目录与文件布局

所有 FDE 应用都在 `app/` 目录下，**一个应用 = 一个同名文件夹**，文件夹内放主文件与同名库。
应用可按**应用组**归类——**组 = `app/` 下的一级目录**（一个组通常对应一个业务系统）：

```
fde-v2/
├── design/CONVENTION.md             # 本文件（FDE 应用约定 v2 正本，唯一来源）
├── fde.py                     # 平台 SDK（FdeError 等）
├── app/
│   ├── sales/                 # 应用组「sales」——组名 = 一级目录名（不是新实体，纯目录呈现）
│   │   ├── 架构设计.md        # 可选：组级总体设计（构建流水线步骤 2 产出，设计态、不 serve）
│   │   ├── 前端详设/          # 可选：组级页（无后端应用，如 dashboard）的前端设计
│   │   ├── customer/          # 应用「customer」——应用名 = 文件夹名
│   │   │   ├── customer.py    # 主文件（与文件夹同名）：聚合根 Customer
│   │   │   ├── customer.db    # 同名库（平台创建/管理连接）
│   │   │   ├── resource/      # 平台自动创建：import-file（人工上传）/ export-file（Agent 产出）
│   │   │   ├── 应用详设.md    # 可选：后端详细设计（构建流水线步骤 3 产出，设计态、不 serve）
│   │   │   ├── 前端详设.md    # 可选：前端详细设计（构建流水线步骤 7 产出，设计态、不 serve）
│   │   │   ├── view.js        # 可选：前端页面（自描述 PAGE_META + 默认导出工厂，见 design/VIEW_CONVENTION.md）
│   │   │   ├── view.html      # 可选：前端模板片段
│   │   │   └── README.md      # 可选：应用说明（平台喂给该应用的 Agent，见 §11）
│   │   └── sales_org/         # 应用「sales_org」
│   │       ├── sales_org.py   # 聚合根 SalesOrg
│   │       ├── sales_org.db
│   │       ├── resource/
│   │       └── README.md
│   └── todo/                  # 也可直接放在 app/ 下 → 归入「未分组」
│       └── todo.py
└── tests/
    └── smoke.py
```

- **应用名 = 文件夹名**。`app/e2e/member/` 的应用名就是 `member`。
- **应用组 = 一级目录，且只是展示维度**：平台首页按组（系统）展示、点进去看组内应用；组没有配置、没有元数据，
  新建组就是建一个一级目录。判定规则：一级目录含同名主文件 `<名>.py` 视为**应用**（未分组），否则视为**组目录**，
  向下识别一层应用目录（**分组只支持一级**）；不含任何应用的目录被忽略。
- **应用名组内唯一，跨组可重名**：应用以**组限定名 qualname**（`组/名`，未分组为 `名`，如 `sales/customer`、`mes/customer` 可并存）为身份键，注册表按 qualname 登记。跨应用调用的短名按**调用方所在组**解析（§5）；Web/MCP/鉴权亦按 qualname 标识应用。
- **主文件与文件夹同名**：`app/e2e/member/member.py`；其中的聚合根类用 `PascalCase`（`member.py` → `class Member`）。文件夹名用 `snake_case`。
- **同名库放在该应用文件夹内**：`app/e2e/member/member.db`，由平台管理；应用**不需要**也**不应该**自己 `sqlite3.connect`。
- 平台按**文件路径**加载主文件（非 Python 包导入），故应用文件夹**无需** `__init__.py`。
- **可选 `README.md`**：放在应用文件夹内，是该应用写给 Agent 的操作指南（标准工作流 / 注意事项 / 错误处理·Agent 应对策略）。
  平台会把整个 README 喂给**该应用的 Agent**；编写规范见 **§11**。无 README 时 Agent 仅凭内省出的服务签名工作。
- **可选前端视图 `view.js` + `view.html`**：放在应用文件夹内（与后端同文件夹，一次生成、整文件夹交付）。平台自动扫描
  装配进所属组的视图菜单（`/view/<组>/`），经写死端点 `/app/<组>/<名>/view.{js,html}` serve（同目录 `.py`/`.db` 绝不暴露）。
  页面自描述约定（`PAGE_META` + 默认导出工厂 + 绝对路径 import `/view/lib/*`）与生成规范见 **`design/VIEW_CONVENTION.md`**（前端视图约定正本）；
  无 view 文件的应用不进前端菜单（仍可经应用详情页 / Agent / 服务台操作）。
- **可选设计文档 `应用详设.md` / `前端详设.md`**（及组级 `app/<组>/架构设计.md`、`app/<组>/前端详设/`）：构建流水线（九步法，见 `design/工具链使用说明.md`）
  第②/⑥步的设计产出，与代码同文件夹、随应用整夹交付，便于改代码时对照设计、减少漂移。**纯设计态文档：平台不加载、不 serve**
  （同目录仅 `view.{js,html}` 经写死端点暴露，`.py`/`.db`/`.md` 绝不暴露），删除不影响应用运行。
- **资源目录（平台自动创建）**：加载时平台在每个应用文件夹内自动建 `resource/import-file/`（人工上传的待导入文件）与
  `resource/export-file/`（Agent / 服务产出），并配套内置文件工具 `platform_list_files / platform_read_file / platform_write_file`
  （对外工具名 `<应用名>__platform_*`，`import-file` 只读、`write` 只写 `export-file`）。Agent 与 MCP 用其读取导入文件、解析并调用服务入库（见 §10 职责⑩）。

## 2. 一个文件 = 一个聚合根

主文件里定义**一个类**，它就是领域驱动设计中识别出的**聚合根**（销售订单、预测单……）。
这个类的角色更像"该聚合的**应用服务 / 操作面**"：它的实例不代表某一条具体记录，
而是对外提供针对该聚合的各种操作（按 id 操作具体记录）。

```python
# app/e2e/task/task.py
class Task:
    """任务聚合根。"""
    ...
```

## 3. 方法 = 操作（服务）

聚合根的**公共方法**就是它对外暴露的**服务**（操作）：

- **服务名 = 方法名**。`submit(...)` 这个方法，对外就是名为 `submit` 的服务。
- **`_` 前缀的方法是内部辅助**，平台**不**对外暴露（如 `_init_db`、`_row`）。
- 方法的参数与类型标注，即该服务的入参契约（平台据此生成调用表单 / 工具定义）。

## 4. 平台向应用注入的三样东西（核心契约）

应用**无需定义 `__init__`**。平台在实例化聚合根、调用任一公共方法前，
会在实例上注入下列三个属性，应用可直接使用：

| 属性 | 是什么 | 用来做什么 |
|---|---|---|
| `self.ctx` | 身份上下文 `dict` | 读取当前调用人身份 |
| `self.db` | 指向同名 `.db` 的 SQLite 连接 | 读写本应用自己的数据 |
| `self.fde` | 平台网关对象 | 按名调用**其他** FDE 应用的服务 |

### 4.1 `self.ctx` —— 身份上下文（平台权威，应用只读、不可篡改）

平台在每次调用时注入，字段固定：

```python
self.ctx = {
    "userno":       "...",   # 用户编号
    "departmentno": "...",   # 组织编号
    "role":         "...",   # 用户角色
}
```

- 身份由平台负责认证与注入，**应用不实现鉴权**，只读用（如用 `userno` 做数据归属）。
- 跨应用调用时，平台**自动透传**同一份 `ctx`，调用方**无法伪造或覆盖**（沿用 v1 的防伪造原则）。

### 4.2 `self.db` —— 本应用的 SQLite 连接

- 连接由平台创建并注入，指向该应用文件夹内的同名库（如 `app/e2e/member/member.db`），已开启良好默认（`WAL` 日志模式、`busy_timeout`、`foreign_keys`、行工厂）。
- **建表是应用的必选职责**：每个聚合根**必须**定义 `_init_db()` 方法，在其中用幂等纯 SQL（`CREATE TABLE IF NOT EXISTS`）建好本应用的全部表。这是应用声明自身数据结构的唯一地方（见 §6）。
- **事务由平台管理**：公共方法正常返回 → 平台 `commit`；抛出异常 → 平台 `rollback`。应用只管 `execute`，不手动 `commit`。

### 4.3 `self.fde.call(...)` —— 跨应用调用（按名、运行期绑定）

```python
result = self.fde.call("forecast", "latest", month="2026-08")
#                       ↑应用名     ↑服务名   ↑该服务的入参（按名传）
```

详见 §5。

## 5. 跨应用调用约定（本约定的关键创新）

一个方法在执行中，可以调用**其他 FDE 应用**提供的服务。这是一种**基于约定**的耦合：

- **只认名字，不 import**：我们只知道 `forecast` 应用提供一个名为 `latest` 的服务，
  但**不**在本文件里 `import forecast`。
- **运行期绑定**：`self.fde.call("forecast", "latest", ...)` 由平台在**运行时**按名解析目标应用与方法。
  - 若 `app/forecast/forecast.py` **不存在**，或 `Forecast` 类**没有** `latest` 方法 → **运行时报错**；
  - 但本文件的**加载 / 编译完全不受影响**（没有 import，就没有 import 失败）。
- **按调用方所在组解析（跨组可重名）**：`self.fde.call("X", ...)` 的短名 `X` 先按**调用方所在组**解析——本组存在 `本组/X` 即用之；本组没有而 `X` 全局唯一则回退到该唯一应用；多组重名且本组没有 → **运行时报错**，要求用 `组/X` 明确指定。亦可直接写 `self.fde.call("sales/customer", "get")` 显式跨组调用。静态扫描器按同一规则校验（§10.8）。
- **返回值透明**：`call` 直接返回被调服务的返回值；被调服务抛 `FdeError` 时，异常**原样传播**回调用方，调用方可 `try/except`。
- **身份自动透传**：平台把同一份 `self.ctx` 带给被调应用（见 §4.1）。
- **静态扫描器（已提供）**：平台提供静态扫描器（`fde_platform/scanner.py`），在**不运行**的前提下用 AST 检查所有 `self.fde.call`：① 指向的应用/服务是否真实存在；② **调用参数与目标服务签名的契约**（未知参数/缺必传参数/重复传参/位置参数过多）——把运行期错误（含跨应用参数名漂移）左移到开发期。含 `**` 展开的调用仅校验目标。
  结果展示于**平台首页**（接口 `/api/scan`），亦可命令行 `python -m fde_platform.scanner`（存在问题时退出码为 1，可入 CI）。

## 6. 生命周期方法 `_init_db`（必选）

- `_init_db(self)`：**每个聚合根都必须定义**。平台在**加载该应用时调用它**，
  应用在此用幂等 SQL（`CREATE TABLE IF NOT EXISTS ...`）建好本应用所需的全部表。
- 因建表语句幂等，即便重启或重新加载再次调用也安全；应用数据结构的后续演进（加列、建索引）也在此维护。
- `_init_db` 以 `_` 开头，**不是对外服务**，不会被平台当服务暴露。
- **开销**：`_init_db` 只在**加载时**执行（每应用一次并缓存），**不在每次服务调用时执行**。`CREATE TABLE IF NOT EXISTS` 对已有表只是一次元数据存在性检查（微秒级，查 `sqlite_master` 即返回），不扫描、不重建数据；幂等性是重启 / 首次运行 / 重新加载的正确性保险，非热点路径。（运行期每次调用另有微秒级库存在性检查，仅当库被外部删除才触发空库自愈，见 §10.6。）
- **时机辨析**：`import` 应用文件只是**定义**类与方法，**并不会执行** `_init_db`；建表发生在平台**加载该应用**时——平台造一个实例（已注入 `db`）并在其上调用 `_init_db()`，随后缓存该应用。若平台在启动期统一加载所有应用，则建表就发生在**平台初始化阶段**，每个应用一次。

## 7. 返回与错误约定

- **成功**：公共方法**直接返回业务值**（`dict` / `list` / 标量皆可，应可 JSON 序列化）。
- **业务失败**：`raise FdeError("人话错误信息")`。`FdeError` 由平台提供（`from fde import FdeError`）。
  - 平台把它归一为"干净的业务失败"（带可读信息），并让跨应用调用方能捕获。
- **系统异常**：其他未捕获异常由平台归一为"系统错误"（记日志、对调用方屏蔽细节）。

> 说明：v1 用 `{status, message, data}` 信封；v2 改为"返回业务值 + 业务失败抛 `FdeError`"，
> 因为类方法风格下异常更自然，且跨应用错误能靠 `try/except` 天然传播。

## 8. 事务与一致性边界

- **每个应用 = 一个独立 db = 一个独立事务边界**。
- 跨应用调用**不提供分布式事务**：`self.fde.call` 写的是**另一个** db 文件，无法与本应用同进同退。
- 跨应用的一致性由**业务设计**保证：幂等的服务 + 必要的补偿/重试。（这是微服务式设计的固有约束，约定在此如实声明。）

## 9. 应用骨架（示意，非正式样例）

展示全部约定的一次性最小例子：

```python
# app/todo/todo.py —— 示意骨架
from fde import FdeError                 # 平台提供的业务异常基类


class Todo:
    """待办事项聚合根（示意）。公共方法即对外服务，如 todo.create / todo.list。"""

    # ---- 生命周期（必选）：加载时由平台调用，幂等建表 ----
    def _init_db(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS todo (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                title     TEXT    NOT NULL,
                owner_no  TEXT    NOT NULL,
                done      INTEGER NOT NULL DEFAULT 0
            )
        """)

    # ---- 对外服务（公共方法）----
    def create(self, title: str):
        """新建待办，归属当前登录用户。"""
        if not title.strip():
            raise FdeError("标题不能为空")             # 业务失败 → 抛业务异常
        owner = self.ctx["userno"]                    # 平台注入的身份上下文
        cur = self.db.execute(
            "INSERT INTO todo (title, owner_no) VALUES (?, ?)", (title, owner)
        )
        return {"id": cur.lastrowid, "title": title, "owner": owner}

    def list(self):
        """列出当前用户的待办。"""
        rows = self.db.execute(
            "SELECT id, title, done FROM todo WHERE owner_no = ?", (self.ctx["userno"],)
        ).fetchall()
        return [dict(r) for r in rows]

    def remind(self, todo_id: int):
        """跨应用调用示例：请「notify」应用发提醒（按名调用，不 import）。"""
        # 若 app/notify/notify.py 不存在或无 send 方法 → 运行时报错；本文件加载不受影响
        self.fde.call("notify", "send", to=self.ctx["userno"], text=f"待办 #{todo_id} 该处理")
        return {"notified": todo_id}

    # ---- 内部辅助（_ 前缀，不对外暴露）----
    def _row(self, todo_id: int):
        return self.db.execute("SELECT * FROM todo WHERE id = ?", (todo_id,)).fetchone()
```

## 10. 平台职责清单（约定之外，全归平台）

应用只需满足上述约定；以下全部由 FDE 平台承担：

1. **发现与加载**：扫描 `app/` 下的应用文件夹（分组放置 `app/<组>/<名>/` 与直接放置 `app/<名>/` 皆可，见 §1；组即一级目录，首页按组展示），按**唯一模块名**（`fde_app_<组>__<名>`）动态加载其主文件（避免 v1 的 `sys.modules` 撞名竞争），**加载结果缓存、每个应用只加载一次**；应用名**组内唯一、跨组可重名**，注册表以组限定名 qualname（`组/名`）为键；加载后调用其**必选**的 `_init_db()` 完成建表（每次加载至多执行一次，**不计入单次服务调用的开销**）。
2. **实例化与注入**：每次调用构造聚合根实例，注入 `self.ctx` / `self.db` / `self.fde`。
3. **身份与鉴权**：认证调用人、注入权威 `ctx`、跨应用透传、防伪造；**授权维度是"应用下的开放服务"**（`应用.服务`，如 `user.create`）——能否调用某服务取决于是否被授权该服务，能否进入某应用取决于该应用下是否有≥1 被授权服务；admin 全通。该约束在 Web 闸门、MCP、Agent、定时任务四处一致强制。
4. **服务暴露**：把公共方法按 `应用.服务` 对外暴露（应用以 qualname 标识；界面 / API / Agent / 定时任务等多入口）。
5. **跨应用路由**：实现 `self.fde.call` 的按名解析与运行期绑定。
6. **db 连接管理**：在应用文件夹内创建/打开同名库连接、设 WAL/busy_timeout、每操作的事务提交/回滚。**空库自愈**：每次调用若发现库文件被外部删除/清空（SQLite 会自动重建空库 → 无表），自动经幂等 `_init_db` 重建表结构（数据不恢复，服务回到「未初始化/未同步」业务态，而不是抛 OperationalError）。
7. **错误归一与日志**：区分业务失败（`FdeError`）与系统异常，统一记录。
8. **静态调用扫描器**：用 AST 在**不运行**的前提下校验所有 `self.fde.call` 的目标（应用 / 服务）真实存在，且**调用参数符合目标服务签名契约**（未知参数/缺必传/重复/位置过多）；结果展示于平台首页（`/api/scan`），CLI `python -m fde_platform.scanner`（有问题退出码 1）。
9. **Agent 操作指南**：加载应用文件夹内的 `README.md`（若有），整体注入该应用 Agent 的 system prompt（见 §11）；无 README 时 Agent 回落到仅用服务签名。
10. **资源目录与内置文件工具**：加载时自动创建 `resource/import-file`（上传）/ `export-file`（产出）；提供 `platform_list/read/write_file` 内置工具（路径安全防穿越、`import-file` 只读），供 Agent / MCP 做数据导入解析；详情页可上传/下载/删除文件。
11. **定时任务**：以 APScheduler 按计划（cron）调度应用的公共服务，走与手工/Agent/MCP 同一 `platform.call` 调用链（含身份注入、事务）；运行日志落 `config/scheduler.db`；管理页 `/scheduler`（按应用授权可见）。可插拔（`python -m fde_platform.scheduler` 可 CLI 管理）。

---

## 11. 应用 README（Agent 操作指南，强烈推荐）

每个应用**应当**在文件夹内提供 `README.md`（`app/<名>/README.md`）。它不是对外宣传文档，
而是**应用写给 Agent 的操作指南**：平台在构建该应用的 Agent 会话时，会把整个 README **原样注入
system prompt**（见 §10 职责⑨）。Agent 据此理解业务、按「标准工作流」调用工具、按「错误处理·Agent
应对策略」应对失败。

- **可选但强烈推荐**：平台**不强制**——无 README 的应用照样加载运行，Agent 回落到仅凭内省出的
  服务签名工作（能用，但缺业务指引与出错对策）。凡是要经 Agent 操作的应用，都应提供 README。
- **README 是契约，须与代码同步**：其中写的工具名、参数、会抛的错误，必须与公共方法签名一致
  （工具名恒为 `<组>__<应用名>__<公共方法名>`，组限定前缀保证跨组唯一）。代码改了服务，README 要跟着改。

### 推荐章节结构（与样例应用一致）

| 章节 | 写什么 |
|------|--------|
| 一、应用简介 | 聚合根是什么、主键、数据存哪个同名库、是否涉及跨应用调用 |
| 二、对外服务（工具） | 表格列出每个公共方法：工具名（`<组>__<应用名>__<服务名>`，组限定）、参数（类型 / 必填 / 默认）、说明 |
| 三、标准工作流 | Agent 应按什么**顺序**调用哪些工具；给出典型组合流程（可多组） |
| 四、前置条件与注意事项 | 约束（非空 / 唯一 / 取值范围）、跨应用依赖、弱引用 / 删除不级联等易踩的坑 |
| 五、错误处理（Agent 应对策略） | 表格：本应用会抛的每条 `FdeError` 信息 \| 含义 \| **Agent 下一步该怎么做** |

### 写作要求

1. **工具名与参数以代码为准**：用 `<组>__<应用名>__<公共方法名>`（组限定前缀），参数类型 / 必填 / 默认与签名一致。
2. **「标准工作流」要可执行**：写成"先调 A，再调 B"的调用顺序，Agent 会优先照此执行。
3. **「错误处理」逐条覆盖**本应用抛出的 `FdeError`，并给出 Agent 的**具体动作**
   （如索要缺失字段 / 先 `list` 核对编号 / 先建依赖应用的数据 / 改用另一服务），而非泛泛而谈。
4. **用中文，简洁可操作**：面向 Agent，避免与调用无关的铺陈。

> 参考样例：`app/e2e/member/README.md`（最小主数据）、`app/e2e/task/README.md`（单据型：状态机 + 跨应用调用）。

---

## 12. 编码硬性补充（来自构建实现侧，务必遵守）

### 12.1 公共方法禁写返回类型注解 ⚠️
公共方法（服务）**不要**写返回类型注解（如 `def list(self) -> list`、`-> dict`、`-> list[dict]`）。
`list` / `get` 等与内建同名的方法，会在平台内省服务签名时被误当内建类型求值，报
`'function' object is not subscriptable`，导致该服务无法暴露。**参数类型注解可保留，返回注解一律不写。**

### 12.2 外部系统适配器模式
外部系统（SAP / MOM / APS / WMS / TMS / MDM / CTCT 等）**不建聚合**（见 §8 一致性边界）；在自有聚合内
弱引用其标识，并把接口封装为应用内 **`_` 前缀适配器方法**（如 `_load_source`）。取数优先级推荐：
**显式 `source` 入参 > HTTP（环境变量基址，如 `MDM_BASE_URL`）> 本地 stub（`config/stub/*.json`）**。
真实接入时**只换适配器实现**，不动公共方法。

### 12.3 缩进铁律 ⚠️
缩进**只用空格、禁用 Tab**，宽度为 **4 的倍数**：`class` 行顶格（0 空格）；**类内方法定义行
（`def _init_db`、`def create` 等，含 `_` 前缀适配器）恰好缩进 4 个空格**；方法体 8 空格；嵌套逐层 +4。
方法定义行**绝不可顶格**（会被解析为模块级函数、服务无法暴露）或缩进 8 空格（`IndentationError`）。
分段生成续写类内方法时，新段每个 `def` 行必须与上一段的 `_init_db` 保持**完全相同**的 4 空格缩进。

---

## 13. 加载验收清单（违反即加载失败 / 扫描失败）

- [ ] 主文件 `app/<组>/<应用>/<应用>.py` 存在；应用名 snake_case 且**组内唯一**（跨组可重名，注册表按 qualname 登记）
- [ ] 文件顶部 `from fde import FdeError`
- [ ] 聚合根类 `class <应用名PascalCase>`（与文件夹同名推导）
- [ ] `def _init_db(self)` 幂等 `CREATE TABLE IF NOT EXISTS`
- [ ] 公共方法**无**返回类型注解（§12.1）；`_` 前缀方法不暴露
- [ ] 缩进全空格、4 的倍数；类内方法定义行恰好 4 空格（§12.3）
- [ ] 不 `sqlite3.connect`、不 `import` 其它应用（跨应用一律 `self.fde.call`）
- [ ] 业务失败 `raise FdeError("人话")`；成功返回可 JSON 序列化值
- [ ] 不写 `__init__`、不写鉴权（仅读 `self.ctx`）
- [ ] `self.fde.call` 目标存在 + 参数契约通过（`python -m fde_platform.scanner`）
- [ ] `README.md` 五章齐全且与代码同步（§11）
- [ ] 外部系统经 `_` 前缀适配器方法接入（§12.2，不建聚合）

> 注：`<应用>.db` 与 `resource/`（import-file / export-file）**无需手写**——平台加载应用时自动创建（§1 / §10）。
