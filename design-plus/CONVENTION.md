# FDE 应用约定（v2）

> 本文件是 FDE v2 的**唯一约定正本**，置于 `design-plus/CONVENTION.md`（原 `skill/app-convention.md`、`app/CONVENTION.md` 先后迁至此处，旧路径已随 `skill/` 退场）。凡符合本约定的应用（`app/` 下——或其**应用组**子目录下——一个同名文件夹 + 主文件），FDE 平台即可加载、暴露并运行它；
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
├── design-plus/CONVENTION.md             # 本文件（FDE 应用约定 v2 正本，唯一来源）
├── fde.py                     # 平台 SDK（FdeError 等）
├── app/
│   ├── sales/                 # 应用组「sales」——组名 = 一级目录名（不是新实体，纯目录呈现）
│   │   ├── architecture.md    # 可选：组级总体设计（第①步产出，设计态、不 serve；旧名「架构设计.md」平台仍兼容）
│   │   ├── 前端详设/          # 可选：组级页（无后端应用，如 dashboard）的前端设计
│   │   ├── customer/          # 应用「customer」——应用名 = 文件夹名
│   │   │   ├── customer.py    # 主文件（与文件夹同名）：聚合根 Customer
│   │   │   ├── customer.db    # 同名库（平台创建/管理连接）
│   │   │   ├── resource/      # 平台自动创建：import-file（人工上传）/ export-file（Agent 产出）
│   │   │   ├── 应用详设.md    # 可选：后端详细设计（构建流水线步骤 3 产出，设计态、不 serve）
│   │   │   ├── 前端详设.md    # 可选：前端详细设计（构建流水线步骤 7 产出，设计态、不 serve）
│   │   │   ├── view.js        # 可选：前端页面（自描述 PAGE_META + 默认导出工厂，见 design-plus/VIEW_CONVENTION.md）
│   │   │   ├── view.html      # 可选：前端模板片段
│   │   │   ├── HOWTOUSE.md    # 可选但强烈推荐：**常驻注入** Agent 的精简要点（见 §11）
│   │   │   └── README.md      # 可选：完整操作指南，Agent 按需查阅（见 §11）
│   │   └── sales_org/         # 应用「sales_org」
│   │       ├── sales_org.py   # 聚合根 SalesOrg
│   │       ├── sales_org.db
│   │       ├── resource/
│   │       ├── HOWTOUSE.md
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
- **可选 `HOWTOUSE.md` / `README.md`**：都放在应用文件夹内，都是该应用写给 Agent 的。
  **HOWTOUSE 是精简要点（约 300-600 tokens），平台整体注入其对应角色 Agent 的 system prompt**；
  **README 是完整操作指南，不注入，由 Agent 经 `platform_read_app_doc` 按需查阅**。
  两者编写规范见 **§11**；都没有时 Agent 仅凭内省出的服务签名工作。
- **可选前端视图 `view.js` + `view.html`**：放在应用文件夹内（与后端同文件夹，一次生成、整文件夹交付）。平台自动扫描
  装配进所属组的视图菜单（`/view/<组>/`），经写死端点 `/app/<组>/<名>/view.{js,html}` serve（同目录 `.py`/`.db` 绝不暴露）。
  页面自描述约定（`PAGE_META` + 默认导出工厂 + 绝对路径 import `/view/lib/*`）与生成规范见 **`design-plus/VIEW_CONVENTION.md`**（前端视图约定正本）；
  无 view 文件的应用不进前端菜单（仍可经应用详情页 / Agent 操作）。
- **可选设计文档 `应用详设.md` / `前端详设.md`**（及组级 `app/<组>/architecture.md`、`app/<组>/前端详设/`）：构建流水线（九步法，见 `design-plus/工具链使用说明.md`）
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
- **`_` 前缀的方法是内部辅助**，平台**不**对外暴露（如 `_row`、`_clean`）。
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
- **建表由 `schema.sql` 声明**：每个聚合根目录内**必须**放 `schema.sql`（与 `<应用>.py` 同级），用 SQLite 方言 DDL（`CREATE TABLE IF NOT EXISTS` + `CREATE [UNIQUE] INDEX`）声明全部表。这是应用声明自身数据结构的唯一地方（见 §6）。
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

## 6. Schema 声明文件 `schema.sql`（必选）

- **`schema.sql`**：每个聚合根目录内**必须**放置的 DDL 文件（与 `<应用>.py` 同级），用 SQLite 方言纯 SQL
  声明本应用的全部表与索引（`CREATE TABLE IF NOT EXISTS ...` + `CREATE [UNIQUE] INDEX ...`）。这是应用声明自身数据结构的唯一地方。
- **平台加载时建表**：平台读取 `schema.sql`，经 DDL 引擎（`fde_platform/ddl.py`）解析——① 注入 `created_at/updated_at/created_by/updated_by` 四个审计列；② 按方言生成 DDL（SQLite 原样 / PostgreSQL transpile）；③ 建表建索引；④ **对账补列**（见下）。
- **加列 ✓ / 删列 ✗（schema 演进）**：`CREATE TABLE IF NOT EXISTS` 只在**表**不存在时生效，表已存在就整句跳过——所以**往 `schema.sql` 里加一列，对已有库毫无作用**，之后读写该列会 `no such column`（且重跑建库脚本也补不上：演示环境的"重置"是清空行、不删库文件）。
  为此加载时会**对账**：读现有表的列 → 与 `schema.sql` 声明比对 → 缺的列 `ALTER TABLE ADD COLUMN`（同时补平台审计列）。补了哪些列会记 `INFO` 日志（不静默）。
  - **只做加法，绝不删列/删表**：少一列报错是显式的，自动删一列丢数据是静默的。
  - **不可补的列直接报错**（如 `NOT NULL` 且无 `DEFAULT`、或主键/唯一约束列）——SQLite 在非空表上加不了这种列。报错信息会说明"给它一个 DEFAULT 或手工迁移"，**不做"悄悄降级成可空"**（那会让库与声明长期不一致）。所以：**新增列请给 `DEFAULT`**。
  - 验收：`python scripts/verify_ddl_reconcile.py`（老库补列、幂等、新库空操作、不可补报错、只加不删）。
- **DDL 子集白名单**：仅支持 `CREATE TABLE`（类型 `TEXT/INTEGER/REAL/DATETIME/TIMESTAMP`，列级/表级 `PRIMARY KEY`、`NOT NULL`、`UNIQUE`、`DEFAULT`、`CHECK`）与 `CREATE [UNIQUE] INDEX`。触发器/视图/存储过程/外键不在子集内。
- **应用不再写 `_init_db`**：建表逻辑从代码抽离到 `schema.sql`，应用类里无 `_init_db` 方法。
- **平台自动审计**：`schema.sql` 里的 `CREATE TABLE`，平台自动追加 4 个审计列；应用 `INSERT`/`UPDATE` 里平台自动注入当前时间与 `self.ctx["userno"]` 到对应审计列——应用零感知。
- **开销**：只在加载时执行（每应用一次并缓存），不在每次服务调用时执行。

## 7. 返回与错误约定

- **成功**：公共方法**直接返回业务值**（`dict` / `list` / 标量皆可，应可 JSON 序列化）。
- ⚠️ **`list` 方法签名与返回格式**：供前端 `pageable()` 消费的 `list` 方法**必须**接受 `page: int = None` 和 `size: int = None` 两个末尾参数（参数名 `size` 与前端 `pageable()` 传参一致），在查询后**先保存 `total = len(rows)`**，再按 `rows[start:start+size]` 做服务端切片，最后返回 `{"items": [...], "total": total}`（`total` 为切片前全量行数，非切片后行数）。`page`/`size` 为 None 时返回全部数据。纯后端内部调用的 `list` 不受此限。
- ⚠️ **`list` 必须返回全字段**：`list` 的 SELECT 与返回项**必须覆盖聚合的全部业务字段**（与 `get` 同口径，完整 `_to_dict`），**不得只 SELECT 关键列子集**。列表「默认只显示关键列」是**视图层**行为（见下条），数据层始终给全字段——列自选、列排序、导出、未来扩展都依赖全字段数据。
- **列表默认只显示关键列（视图层）**：视图把全字段都渲染成列，并在 `PAGE_META` 声明 `col_default_hidden: "列名,列名,…"`（非关键列的表头文本，逗号分隔）；平台列控制在用户**无个人配置**时按它默认隐藏这些列，用户经列设置图标开启后以个人配置（per-user 持久化）覆盖。未声明时默认全显示。范例见 `app/psc/md_material/view.js`。
- **平台级列排序（零应用改动）**：`sort_by` / `sort_dir` 为平台保留参数，**应用无需也不应声明**。REST 调用 `list` 携带它们时由平台在调用层拦截（`fde_platform/listsort.py`）——剥掉 `page/size` 后调应用取全量，在平台进程内做类型感知排序（数字 / ISO 日期 / 字符串，空值恒排末尾），再按请求分页切片返回。不带 `sort_by` 的 `list` 调用路径不变。前端 `pageable()` 的 `sortBy()` 自动携带这两个参数。
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

    # 建表在同目录 schema.sql 声明（平台加载时解析建表，见 §6），应用不再写 _init_db

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

1. **发现与加载**：扫描 `app/` 下的应用文件夹（分组放置 `app/<组>/<名>/` 与直接放置 `app/<名>/` 皆可，见 §1；组即一级目录，首页按组展示），按**唯一模块名**（`fde_app_<组>__<名>`）动态加载其主文件（避免 v1 的 `sys.modules` 撞名竞争），**加载结果缓存、每个应用只加载一次**；应用名**组内唯一、跨组可重名**，注册表以组限定名 qualname（`组/名`）为键；加载后读其**必选**的 `schema.sql` 完成建表（每次加载至多执行一次，**不计入单次服务调用的开销**）。
2. **实例化与注入**：每次调用构造聚合根实例，注入 `self.ctx` / `self.db` / `self.fde`。
3. **身份与鉴权**：认证调用人、注入权威 `ctx`、跨应用透传、防伪造；**授权维度是"应用下的开放服务"**（`应用.服务`，如 `user.create`）——能否调用某服务取决于是否被授权该服务，能否进入某应用取决于该应用下是否有≥1 被授权服务；admin 全通。该约束在 Web 闸门、MCP、Agent、定时任务四处一致强制。
4. **服务暴露**：把公共方法按 `应用.服务` 对外暴露（应用以 qualname 标识；界面 / API / Agent / 定时任务等多入口）。
5. **跨应用路由**：实现 `self.fde.call` 的按名解析与运行期绑定。
6. **db 连接管理**：在应用文件夹内创建/打开同名库连接、设 WAL/busy_timeout、每操作的事务提交/回滚。**空库自愈**：每次调用若发现库文件被外部删除/清空（SQLite 会自动重建空库 → 无表），自动经 `schema.sql` 重建表结构（数据不恢复，服务回到「未初始化/未同步」业务态，而不是抛 OperationalError）。
7. **错误归一与日志**：区分业务失败（`FdeError`）与系统异常，统一记录。
8. **静态调用扫描器**：用 AST 在**不运行**的前提下校验所有 `self.fde.call` 的目标（应用 / 服务）真实存在，且**调用参数符合目标服务签名契约**（未知参数/缺必传/重复/位置过多）；结果展示于平台首页（`/api/scan`），CLI `python -m fde_platform.scanner`（有问题退出码 1）。
9. **Agent 使用要点**：加载应用文件夹内的 `HOWTOUSE.md`（若有），整体注入**该应用所属角色** Agent 的 system prompt（见 §11）；完整 `README.md` 不进 prompt，由 Agent 经 `platform_read_app_doc` 按需读取。两者都无时 Agent 回落到仅用服务签名。
10. **资源目录与内置文件工具**：加载时自动创建 `resource/import-file`（上传）/ `export-file`（产出）；提供 `platform_list/read/write_file` 内置工具（路径安全防穿越、`import-file` 只读），供 MCP 与页面使用。**Agent 面只暴露 `read_file`**（读上传的导入文件、图片附件）——`list_files` / `write_file` 对 Agent 边际价值低，却会在工具组内**抢选择**（实测误选里 4 条有 3 条是它），已摘除；开关在 `agent_service._AGENT_HIDDEN_BUILTINS`。
11. **定时任务**：以 APScheduler 按计划（cron）调度应用的公共服务，走与手工/Agent/MCP 同一 `platform.call` 调用链（含身份注入、事务）；运行日志落 `config/scheduler.db`；管理页 `/scheduler`（按应用授权可见）。可插拔（`python -m fde_platform.scheduler` 可 CLI 管理）。

---

## 11. 应用 Agent 文档（HOWTOUSE 常驻 + README 按需）

每个应用**应当**在文件夹内提供两份文档，分工明确：

| 文件 | 进 prompt 吗 | 写给谁 | 篇幅 |
|---|---|---|---|
| `HOWTOUSE.md` | ✅ **常驻注入**（该应用所属角色的 system prompt） | Agent 每次动手前要看的 | 300-600 tokens |
| `README.md` | ❌ 不注入，`platform_read_app_doc(app, "README")` 按需查 | Agent 遇到细节时查 | 不限 |

**为什么不把 README 直接注入**：README 是完整指南（3-4k tokens/应用），一个角色 5-6 个应用就是
13k tokens，**每次调用都要重过一遍**——实测每次 LLM 调用约 2 倍延迟；外部研究也显示指令密度
过高会显著降低遵从率（指令数到 ~80 条时，完美遵从率对所有模型归零）。这与 Anthropic 的分层
实践一致：**常驻放正文（L2），大规则表按需加载（L3）**。

### 11.1 `HOWTOUSE.md`（常驻，四段）

| 段落 | 写什么 |
|------|--------|
| 一句话定位 | 这个应用管什么（**一行**） |
| 标准工作流 | **按顺序**该调哪些工具——这是 HOWTOUSE 的核心价值 |
| 前置条件与禁忌 | 影响「能不能调 / 何时能调 / 什么不能做」的硬约束；**被摘除的服务在这里点明**「XX 不在你的工具表里，改用 YY」 |
| 出错时 | 一句指路：`platform_read_app_doc(app="<组>/<应用>", doc="README")` |

**不要写**（这三块占 README 的 60% 以上，且对「选哪个工具」零帮助）：

- ❌ **对外服务表** —— 工具名 / 参数 / 说明**已在每次调用的工具 schema 里**，抄一遍是零信息量的重复
- ❌ **错误处理表** —— 出错时按需读 README
- ❌ 聚合根 / 主键 / 同名库 / 数据来源类型等 background

### 11.2 `README.md`（按需，五章）

章节结构不变——它现在的定位正是「查细节的完整手册」：

| 章节 | 写什么 |
|------|--------|
| 一、应用简介 | 聚合根是什么、主键、数据存哪个同名库、是否涉及跨应用调用 |
| 二、对外服务（工具） | 表格列出每个公共方法：工具名（`<组>__<应用名>__<服务名>`，组限定）、参数（类型 / 必填 / 默认）、说明 |
| 三、标准工作流 | Agent 应按什么**顺序**调用哪些工具；给出典型组合流程（可多组） |
| 四、前置条件与注意事项 | 约束（非空 / 唯一 / 取值范围）、跨应用依赖、弱引用 / 删除不级联等易踩的坑 |
| 五、错误处理（Agent 应对策略） | 表格：本应用会抛的每条 `FdeError` 信息 \| 含义 \| **Agent 下一步该怎么做** |

### 11.3 两份文档共同的写作要求

1. **工具名以代码为准**，恒为 `<组>__<应用名>__<公共方法名>`（组限定前缀保证跨组唯一），
   参数类型 / 必填 / 默认与签名一致。**代码改了服务，文档要跟着改**——文档是契约。
2. **「标准工作流」要可执行**：写成"先调 A，再调 B"的调用顺序，Agent 会优先照此执行。
3. **用中文，简洁可操作**：面向 Agent，避免与调用无关的铺陈。
4. **README 的「错误处理」逐条覆盖**本应用抛出的 `FdeError`，并给出 Agent 的**具体动作**
   （索要缺失字段 / 先 `list` 核对编号 / 先建依赖应用的数据 / 改用另一服务），而非泛泛而谈。

> ⚠️ **两份文档都要遵守「不写没消费者的东西」**：服务藏在工具表里、错误在 README 里，
> 都是为了让 Agent 读到的每一句都有用。写进 HOWTOUSE 的每一行都在**每次调用**上重复付费。

> 参考样例：`app/e2e/member/`、`app/e2e/task/`（两份文档齐全）；`app/psc/sales_forecast/HOWTOUSE.md`
> 是 HOWTOUSE 的典型样例（工作流 + 禁忌 + 出错指路，约 500 tokens）。

> 校验：`scripts/verify_agent_tools.py` 会检查**声明了角色绑定的应用是否都有 `HOWTOUSE.md`**
> （漏写会静默地不注入，属于「静默失效」，必须能被发现）。

---

## 12. 编码硬性补充（来自构建实现侧，务必遵守）

### 12.1 公共方法禁写返回类型注解 ⚠️
公共方法（服务）**不要**写返回类型注解（如 `def list(self) -> list`、`-> dict`、`-> list[dict]`）。
`list` / `get` 等与内建同名的方法，会在平台内省服务签名时被误当内建类型求值，报
`'function' object is not subscriptable`，导致该服务无法暴露。**参数类型注解可保留，返回注解一律不写。**

### 12.2 外部系统适配器模式
外部系统（SAP / MOM / APS / WMS / TMS / MDM / CTCT 等）**不建聚合**（见 §8 一致性边界）；在自有聚合内
弱引用其标识，并把接口封装为应用内 **`_` 前缀适配器方法**（在类里显式声明 `_EXTERNAL_ADAPTERS`，如
`_http_fetch_xxx` / `_erp_sync_xxx`）。HTTP 接入走 **`/integration` 集成配置**（url / 鉴权 / Mock，
凭证加密落库），不硬编码环境变量基址。真实接入时**只换适配器实现**，不动公共方法。

> 完整落地步骤（适配器声明、集成配置流程、对外服务包装、响应解析、方法探测、字段映射、定时任务调用）
> 见 `design-plus/接口适配器开发.md`。

### 12.3 缩进铁律 ⚠️
缩进**只用空格、禁用 Tab**，宽度为 **4 的倍数**：`class` 行顶格（0 空格）；**类内方法定义行
（`def create`、`def list` 等，含 `_` 前缀适配器）恰好缩进 4 个空格**；方法体 8 空格；嵌套逐层 +4。
方法定义行**绝不可顶格**（会被解析为模块级函数、服务无法暴露）或缩进 8 空格（`IndentationError`）。
分段生成续写类内方法时，新段每个 `def` 行必须与上一段的 `def` 行保持**完全相同**的 4 空格缩进。

---

## 13. 加载验收清单（违反即加载失败 / 扫描失败）

- [ ] 主文件 `app/<组>/<应用>/<应用>.py` 存在；应用名 snake_case 且**组内唯一**（跨组可重名，注册表按 qualname 登记）
- [ ] 文件顶部 `from __future__ import annotations`（置于最前，避免 `list` 等方法名遮蔽内置类型注解）
- [ ] 文件顶部 `from fde import FdeError`
- [ ] 聚合根类 `class <应用名PascalCase>`（与文件夹同名推导）
- [ ] `schema.sql` 存在且含 `CREATE TABLE IF NOT EXISTS`（§6）
- [ ] 公共方法**无**返回类型注解（§12.1）；`_` 前缀方法不暴露
- [ ] 缩进全空格、4 的倍数；类内方法定义行恰好 4 空格（§12.3）
- [ ] 不 `sqlite3.connect`、不 `import` 其它应用（跨应用一律 `self.fde.call`）
- [ ] 业务失败 `raise FdeError("人话")`；成功返回可 JSON 序列化值
- [ ] 不写 `__init__`、不写鉴权（仅读 `self.ctx`）
- [ ] `self.fde.call` 目标存在 + 参数契约通过（`python -m fde_platform.scanner`）
- [ ] `README.md` 五章齐全且与代码同步（§11）
- [ ] 外部系统经 `_` 前缀适配器方法接入（§12.2，不建聚合）

> 注：`<应用>.db` 与 `resource/`（import-file / export-file）**无需手写**——平台加载应用时自动创建（§1 / §10）。

---

## 14. 附：数据层双模与 DML 编译层（**平台内部决策**，应用侧不受影响）

> 本节记录"为什么这么做"，以及**还没做完的那一步**。应用开发者不需要读它 ——
> 应用侧看到的一切（`self.db.execute(裸 SQL, ?)`、`schema.sql` 是唯一真相源）都没有变。

### 14.1 三条决策（各自的**触发条件**写在一起，将来要重议时看条件，不看结论）

| 决策 | 理由 | 什么情况下重新评估 |
|---|---|---|
| **不整体换 SQLAlchemy / Alembic 接管数据层** | 「裸 SQL + `?` 占位符 + `schema.sql` 单一真相源」是**产品属性**（应用由 AI 按规范批量生成、要给人看）。SQLAlchemy Core 的中性绑定风格是 `:name` ⇒ 换它等于改全仓 **336 处 `self.db.execute` 调用点**的写法（⚠ 口径 = **调用点**、不是「语句数」：`grep -rn "self\.db\.execute(" app --include=*.py | grep -v /tests/ | wc -l` ⇒ 336）
+ 九步法第③步的规范与提示词；ORM 更会推翻"一个聚合根 = 一个文件 = 一个事务边界"的心智 | 若哪天**不再要求应用 SQL 保持这个形状**（例如产品定位变了），则技术最优会变成 SQLAlchemy Core |
| **SQLite 刻意不池化**（开发底座：标准库 `sqlite3`、每次调用开/关；**部署侧** PG/MySQL 才用 Engine 池） | ① SQLite 只是 Windows 本地开发底座，商业部署走服务器 PG（容器化）；② 池对 SQLite **没有并发收益**（单文件单写者）；③ 保住"clone 下来 `python main.py` 就能跑、零数据库依赖"；④ 风险最小化：影子库隔离靠"复制文件 + 环境变量换根"，每次新开连接让它天然正确 | 不需要（这是定位问题，不是权衡问题） |
| **不引 Alembic** | 应用库的加列演进**已有机制**：`ddl.execute_schema` 在加载时把已有表**对账补齐**到 `schema.sql` 声明（只加列、绝不删，有 `verify_ddl_reconcile` 门禁守着）；平台自有库（`config/*.db`）用手写幂等迁移（`skills`/`flow` 是 `_migrate()`，`alerts`/`integration`/`users` 是内联的幂等 `ALTER TABLE ADD COLUMN`）。Alembic 与"`schema.sql` 是唯一真相源"天然打架（会变成第二份真相） | 平台自有库需要**非常规**结构演进（改类型 / 拆表 / 需要 downgrade）时再评估 |

### 14.2 DML 编译层（`fde_platform/sqlc.py`，2026-09-26 落地，默认启用）

应用照旧写 SQLite 方言裸 SQL + `?`；平台在 **AST 层**（sqlglot）做方言翻译：
审计列注入（INSERT 每一行 / `INSERT…SELECT` 投影 / UPDATE 的 SET）、占位符按**词法顺序**命名化、
字面量 `%` 按驱动转义、时间函数归一（与 DDL 共用 `ddl._time_funcs`）、transpile 到目标方言。
**只有一条路**（2026-09-27 起）：原来那个 `FDE_SQL_COMPILER=legacy` 的退回开关（走 `db.py` 内联的
字符串手术）已随灰度结束删除；**回退手段改为 git**（见 §14.3）。判据在门禁「SQL 方言编译层」
（`scripts/verify_pg_translate.py`），断言的是**编译产物**。

**部署侧取连接**走 SQLAlchemy Engine（等待超时 / pre-ping / recycle / 溢出；未装 SQLAlchemy 自动回落
psycopg2 原生池），池参数 `FDE_PG_POOL_MIN/MAX/TIMEOUT/RECYCLE`。

### 14.3 legacy 已删除（2026-09-27）· 回退方式与历史边界

**删了什么**：`_inject_audit`（正则审计注入）、`_PgConnection.execute` 的 legacy 内联块（`%`/`?` 字符串替换）、
`_pg_seq_pk` + `_resolve_lastrowid` + `currval` 兜底、`FDE_SQL_COMPILER` 开关与 `sqlc.enabled()`、
门禁的 A 段（它的意图已由 B 段 ⑥~⑮ 覆盖）、探针里"按路径分辨"的分支与**差分 oracle**（差分需要两条路）。

**回退方式 = git**（不再是环境变量）：legacy 的代码在本仓历史里，真要回退就
`git revert <删它的提交>`（或 `git checkout <删它之前的提交> -- fde_platform/db.py fde_platform/sqlc.py`）
**+ 重新部署**（`fde_platform/` 是烤进镜像的）。

**凭什么可以删（判据，不是感觉）**：原定条件是"灰度过一个工作周期 + 出现过新的 SQL 形态而两条路不打架"。
第二条我用**主动造形态**替代等待 —— 造了 7 类"新应用可能用到"的 SQLite 形态去撞编译层，结果：

- 撞出**三个真缺陷**，都已修 + 已固化进门禁（⑳㉑ 两组）：
  ① `ON CONFLICT(a)` 被渲染成 `ON CONFLICT(a NULLS FIRST)` ⇒ **PG 语法错**；
  ② `datetime(列, '-7 days')` 被翻成 `CURRENT_TIMESTAMP` ⇒ **静默错值**（根因：我复用 DDL 的 `_time_funcs`，
     它只认 `datetime('now',…)` 一种用法）；
  ③ `strftime` 被翻成 `TO_CHAR(d, '%YYYY-%MM')` ⇒ **静默错值**（根因：**我的转义跑在渲染之前**，
     把 `%Y` 搞成 `%%Y` 再交给 sqlglot 翻译；顺序修正后它翻得忠实）；
- 其余形态要么**忠实**（`INSERT OR REPLACE` / `WITH … UPDATE` / `substr` / `IFNULL` / `random`），
  要么**响亮失败**（`DEFAULT VALUES` → 明确 `FdeError`；`PRAGMA` / `julianday` / `printf` → 运行时报错）
  —— **没有第三类**（"静默错值"这一类已被上面三条堵掉）。

**历史上的边界**（现在已不可能出现，留作对照 —— 它们曾是"legacy 严格更差"的证据）：

| 形态 | 当年 legacy 的表现 | 现在的编译层 |
|---|---|---|
| 多行 `VALUES (…),(…)` | 审计值只补**最后一个** tuple ⇒ PG 报 `more target columns than expressions` | 每个 tuple 都补 ✓ |
| `INSERT … SELECT` | 审计列没注入但参数多塞 ⇒ `not all arguments converted` | 补在投影里 ✓ |
| 参数个数与占位符不匹配 | 驱动层 `IndexError: tuple index out of range` | 可读的 `FdeError` ✓ |

⚠ 删除的**代价**（如实记）：失去"一个环境变量就能退回"的即时手段，回退要多花一次重新部署。
换来的是：审计语义只有一份实现、不存在一条"已知会静默出错"的退路、探针与门禁不必再带两套分支。
应用侧只有 1 处读 `lastrowid`（`app/psc/md_breakpoint/md_breakpoint.py:29`，其表是自增主键 ⇒ 走 `RETURNING` ✓）。

### 14.4 接**下一种数据库**时的清单（按边际代价排序，越靠前越便宜）

| 项 | 内容 |
|---|---|
| 驱动 paramstyle | 选驱动 + 一行改写规则（⚠ sqlglot 给 mysql 的是 `:name`，而 pymysql 只认 `%(name)s`） |
| 主键取回策略 | MySQL **没有** `RETURNING` ⇒ 用驱动 `lastrowid`；PG 必须 `RETURNING` |
| 内省适配 | **要补的是 `ddl._existing_columns`**（建表对账用）：它只认 sqlite(`PRAGMA`) 与 pg(`information_schema`)，mysql 会落到 `PRAGMA` 分支。`sqlc.pk_column` **已有** mysql 分支（`information_schema` + `auto_increment`）；`runtime._load` 本身不做方言相关内省（委托给 `ddl`） |
| schema 语义 | pg 是 `CREATE SCHEMA` + `search_path`；**mysql 的 schema 就是 database**，要 `USE` 或全限定 |
| **读数归一** | bool：pg 回 `True/False`、mysql/sqlite 回 `0/1`；date/decimal 各驱动返回类型也不同 ⇒ JSON 契约层要按方言归一（**不报错、是读数漂移**，最易漏） |
| **真实服务器暴露周期** | 静态渲染便宜；真行为必须真库跑。**每加一个方言 = 一轮暴露**（2026-09-20 一天在真 PG 上撞四个就是这么来的） |

⚠ 相关坑：**SQLAlchemy 2.1 起 `postgresql://` 默认解析到 psycopg (v3)**，而本项目装的是 psycopg2
⇒ 平台在 `db.sa_url()` 里显式补 `+psycopg2`（用户仍只写 `postgresql://`，承诺不变）。

### 14.5 在 PG 部署上跑测试

`shadowdb`（影子库）复制的是 **SQLite 文件**，**PG 上没有等价物** ⇒ 用**克隆空库**：
配方与三条要点见《验证门禁》§四之二，脚本 `scripts/verify_pg_clone.sh`；
真 PG 上的编译层/连接层现场验证用 `scripts/verify_pg_live.py`（含**差分 oracle**：legacy 与编译层逐行比对）。
