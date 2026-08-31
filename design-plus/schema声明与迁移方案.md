# Schema 声明式建表与迁移方案（待执行）

> 状态：**方案待执行**。目标：把建表从「应用内联 SQL + 平台正则改写」升级为
> 「独立 DDL 文件 + 平台结构化解析建表」，并顺势补上 **schema 版本化与迁移机制**。
> 关键决策已定：**DDL=SQL 子集 · 解析器=sqlglot · 一次性迁移不保留回落**。本文只定方案与决策，不含代码。

---

## 一、背景与目标

FDE 的约定「一个聚合根 = 一个应用 = 一个同名 SQLite 库」要求每个应用自述建表。
当前做法是应用在 `_init_db()` 里内联 `CREATE TABLE`，平台在 `fde_platform/db.py`
用正则改写 SQL 来注入审计列、翻译 SQLite→PostgreSQL 方言。

**目标**：

1. 把 schema 从「运行时副作用」提升为「**一等声明式工件**」（DDL 文件）。
2. 应用不再手写建表，`_init_db` **整体删除**；平台统一解析 DDL 建表（SQLite/PG 双兼容）。
3. 顺势补上 **schema 版本号 + diff 补列 + 显式迁移**，替代现在的「try/except 补列」。
4. 让契约扫描器能顺带校验「服务 SQL 里的列名是否存在于 schema」，把列名拼错左移到开发期。

---

## 二、现状与问题

### 现状（`fde_platform/db.py`）

- **幂等建表 + try/except 补列**：应用 `_init_db()` 写 `CREATE TABLE IF NOT EXISTS`，加列写
  `try: ALTER TABLE ADD COLUMN ... except: pass`（如 `md_customer` 补 `credit_code`）。
- **正则注入审计列** `_add_audit_columns`：用 MULTILINE 正则找「第一个表级约束」位置，把
  `created_at/updated_at/created_by/updated_by` 插到约束前。
- **正则方言翻译** `_translate_ddl`：`INTEGER PRIMARY KEY`→`IDENTITY`、`datetime('now')`→`NOW()`、
  `DATETIME`→`TIMESTAMP`；`PRAGMA table_info` 用正则翻成 `information_schema`。
- **正则审计值注入** `_inject_audit`：每次 INSERT/UPDATE 用正则找 `) VALUES (` / ` WHERE ` 拼审计字段。
- **PG 幂等补列**：`ALTER TABLE ADD COLUMN` 包成 `DO $$ ... EXCEPTION WHEN duplicate_column THEN NULL`。

### 问题

1. **无 schema 版本**：无法回答「这个 `.db` 处于哪个版本」，无变更历史。
2. **幂等靠 try/except 吞错 + 正则猜**：真实错误（类型错/语法错/权限）也被 `except: pass` 吞掉。
3. **只能加列，不能改**：无 rename 列、改类型、drop 列、**数据迁移（回填/拆列/清洗）**。
4. **无 down / 回滚**，无迁移顺序，无事务边界。
5. **正则操作 SQL 是正确性隐患**：审计列注入、方言翻译都依赖「DDL 写成特定格式」，
   git 历史已出现 ≥4 个 fix commit（`2d867ff / a24bfa0 / 71a6ec4 / 2e130f6`）专门修正则匹配。
6. **每条 SQL 都过一遍正则**：审计列/审计值注入在每次 `execute()` 上跑，非仅建表时。

---

## 三、关键决策（推荐已给出，需在开工前确认）

### 决策 1：DDL 文件格式

| 方案 | 说明 | 判断 |
|---|---|---|
| **A. SQL DDL 子集（`schema.sql`）** | 文件里是 SQLite 风格 `CREATE TABLE`，与现在 AI 写的一致 | **推荐**：AI 零学习成本、人可读，代价是需要真解析器 |
| B. 声明式 DSL（`schema.json/yaml`） | JSON 描述表/列/约束，平台据此生成 SQL | 解析零风险、diff 极简，但引入新 DSL、丢 SQL 表达力、要维护「DSL→SQL」生成器 |

**结论**：选 A（**已定**）。

### 决策 2：解析器选型

| 方案 | 说明 | 判断 |
|---|---|---|
| **A. 引入 `sqlglot`** | 纯 Python、无原生依赖，原生支持 SQLite↔PG 的 parse/transpile/schema-diff | **推荐**：把 db.py 的正则整体替换为结构化解析，根除正则之痛 |
| B. 自研受限解析器 | 只解析 FDE 需要的 DDL 子集，无依赖 | 无依赖，但本质是重写 SQL 解析，边界一放宽又回到正则泥潭 |

**结论**：选 A（sqlglot，**已定**），作为**正式依赖**（进 requirements.txt，纯 Python 无原生）。
import 失败则平台启动时明确报错（同 PG 模式缺 psycopg2 口径），**不保留正则回落**。

### 决策 3：迁移策略（已定）

**结论**：**一次性迁移，不保留回落**。全部应用在同一次变更里生成 `schema.sql` 并切换引擎，
`_init_db` 与 `db.py` 的正则 DDL 改写**整体删除**，不为兼容老应用保留任何冗余代码路径。
老应用 `_init_db` 里的 `CREATE TABLE` 只是原样抽取到 `schema.sql`，属机械搬迁，风险低。

---

## 四、方案设计

### 4.1 DDL 文件约定（约定优于配置）

- **位置**：`app/<组>/<应用>/schema.sql`，与 `<应用>.py`、`view.js` 同级。**每应用必选**。
- **内容**：受限 SQL DDL 子集（严格白名单，超出即报错）：
  - `CREATE TABLE`（`IF NOT EXISTS` 可选），列定义：`TEXT / INTEGER / REAL / NUMERIC`，
    支持 `PRIMARY KEY`、`NOT NULL`、`DEFAULT`、`CHECK`、`REFERENCES`。
  - 表级约束：`PRIMARY KEY (…)`、`FOREIGN KEY (…) REFERENCES`、`UNIQUE (…)`、`CHECK (…)`。
  - `CREATE [UNIQUE] INDEX`。
  - **明确不在子集内**：触发器、存储过程、`ALTER`（迁移另走 4.4 的显式迁移）、种子数据。
- **审计列**：不再由应用手写，由平台在 AST 层统一注入 `created_at/updated_at/created_by/updated_by`。
- **归属九步法**：`schema.sql` 是第③步编码的一等产物；第④⑤步 scanner / 契约冻结可校验它。

### 4.2 平台 DDL 引擎

平台加载每个应用时统一执行，应用零感知：

```
读 schema.sql → 结构化解析 → 注入审计列（AST 层）→ 按方言生成 DDL（SQLite 原样 / PG transpile）
             → 建表 / 建索引
```

- 对应用：从「写 `_init_db` + 内联 SQL」变成「写 `schema.sql`」，更声明式。
- 平台对外提供如 `platform.create_schema(app)` 的入口；`_init_db` 整体删除。
- `self.db.execute` 的**接口不变**，仍由应用写 `INSERT/UPDATE/SELECT/DELETE`，但内部**不再处理
  CREATE TABLE**。
- **sqlglot 作用域只到 DDL**：只负责 `schema.sql` 的解析、审计列注入、SQLite→PG 方言翻译、schema diff，
  一次应用加载只跑一次，不落在每次服务调用上（无热路径开销）。
- **DML 侧不上 sqlglot**：审计值注入沿用现有轻量正则（稳定路径——现状 4 个 fix commit 全在 DDL，
  DML 从未出过问题），placeholder 翻译保留（`?`→`%s`）。用 sqlglot 解析每条 INSERT/UPDATE 只会
  拖慢每次写操作而无收益。
- **SQLite 特有语义需 FDE 补规则**：`INTEGER PRIMARY KEY`（rowid 别名、自带自增）与 `AUTOINCREMENT`
  是语义级差异，sqlglot 的 transpile（语法级）不会自动映射，需在 AST 层补一条
  `INTEGER PRIMARY KEY` → `GENERATED ALWAYS AS IDENTITY` 规则。

### 4.3 一次性迁移（不保留回落）

- `schema.sql` 成为**每应用必选**工件（缺则加载失败，与现在缺 `_init_db` 同口径）。
- 平台加载应用时**只走新引擎**：读 `schema.sql` → 解析 → 建表；不存在「否则回落 `_init_db`」分支。
- 全部 19 个应用在同一次变更中一次性迁完；`_init_db` 与 `db.py` 的正则 DDL 改写**整体删除**。
- **补列合并**：`_init_db` 里的 `try: ALTER TABLE ADD COLUMN ...` 补列（如 `md_customer` 补
  `credit_code`），抽取时**合并进 `schema.sql` 的 CREATE TABLE**（变成表内一列），不再保留 ALTER。

### 4.4 schema 版本化与迁移

有了独立 DDL 文件后，迁移有落点：

- **版本记录**：每个应用记一个 schema 版本（DDL 结构 hash 或递增号）到 `_schema_migrations`。
  **应用级**：SQLite 下每应用 `.db` 各一张、PG 下每应用 schema 各一张（与「一应用一库」边界一致）。
- **最终 schema 为准**：diff 与版本 hash 都基于「**注入审计列之后的最终 schema**」，而非原始
  `schema.sql`——否则平台注入的 4 个审计列会被误判为「库中多出的列」。
- **自动 diff（增量变更）**：加载时对比「最终 schema vs 实际库结构」（SQLite `PRAGMA table_info` /
  PG `information_schema`），新增列/索引 → 自动 `ALTER`；新增表 → 自动建；**删表/删列 → 不自动删、
  只告警**（防误删数据）。
- **显式迁移（非增量变更）**：rename 列、改类型、数据回填 → 落到 `app/<组>/<应用>/migrations/NNNN_*.py`
  （每文件一个 `up()`，可带 `down()`），平台按号序执行、记录已应用版本、一条迁移一个事务。
- 目标：加列从「应用手写 try/except 补列」变为「平台自动 diff 补列」，且终于有版本与历史。

### 4.5 契约扫描器扩展（可选，复杂度中等）

现有 `scanner.py` 校验 `self.fde.call` 的服务名/参数。可增加一道：
**校验服务方法里 `self.db.execute("...")` 引用的列名是否存在于 `schema.sql`**，把列名拼错提前到开发期。

> 注意：这需要「从应用 Python 抽 SQL 字符串 → 解析 SQL 取列名 → diff」，本质是个 mini 静态分析器，
> 不是「免费红利」，建议作为**阶段 2 的可选项**单独评估工作量，不与本次 DDL 改造绑定。

### 4.6 `_init_db` 删除与种子数据

`_init_db` **整体删除**，不再是约定。若个别应用有种子数据（插默认行）等非声明式逻辑，
统一落到 `seed.sql`（平台在首次建库后执行一次）；若摸底发现无种子数据，则完全不引入 seed 机制。

### 4.7 design-plus 文档同步（阶段 1 必做，与代码同一变更合入）

改约定必须同步主规格，否则九步法仍驱动 AI 生成 `_init_db`，与引擎冲突。以下文档在阶段 1 一并更新：

| 文档 | 位置 | 改动 |
|---|---|---|
| `CONVENTION.md` | §6 生命周期方法、§10 空库自愈、骨架示例、缩进规范、§13 验收清单 | 删 `_init_db` 约定 → 改「`schema.sql` 必选」；审计列/建表职责描述改到平台侧 |
| `应用编码.md`（③） | 产物清单、字段→建表对应 | 改「写 `schema.sql`」；产物加 `schema.sql` |
| `架构设计.md`（①） | 第③步产物、字段表来源 | 第③步产物改为 `<应用>.py` + `schema.sql` + README |
| `工具链使用说明.md` | 门禁「字段表每列 → `_init_db` 有对应 DDL 列」 | 改成「→ `schema.sql` 有对应列」 |
| `测试执行.md` | AST 抽 `_init_db` 建表字段（数据契约） | 抽取源改为解析 `schema.sql`（更稳更简） |
| `BUG修复.md` | ④ 数据契约静态抽取 `_init_db` | 同上 |
| `CLAUDE.md`（项目根，design-plus 之外） | `self.db` 审计列 / `_init_db` / 方言翻译 | 同步改为 `schema.sql` + 新引擎 |

> **数据契约抽取**（测试执行.md / BUG修复.md）是最隐蔽的一处：删 `_init_db` 后，AST 抽取
> 改为解析 `schema.sql`，反而更稳更简单，但必须一并改，否则第④⑤步找不到数据契约。

---

## 五、分阶段落地路径

| 阶段 | 内容 | 产出 / 门禁 |
|---|---|---|
| **0 摸底** | 扫 19 个应用 `_init_db`，统计「纯建表 / 含种子 / 含索引 / 含补列 ALTER」分布；并查应用 DML 是否用了 SQLite 专属函数（如 `datetime('now')`） | 一份「DDL 子集边界 + 种子/补列/DML 方言 分布」清单 |
| **1 一次性迁移** | ① 引入 sqlglot 替换 db.py 正则 DDL 改写；② 为全部应用生成 `schema.sql`（`_init_db` 的 `CREATE TABLE` 原样抽取、补列合并）；③ 删除 `_init_db` 建表与回落；④ 同步 design-plus 文档（见 4.7） | `scanner` + `verify_chain` + `verify_view` 全绿 + **PG 模式冒烟**（`DATABASE_URL` 起一次、跑建表/增删查）才合入 |
| **2 迁移挂钩** | `_schema_migrations` 版本 + diff 补列 + 显式迁移步骤 + 契约列名校验 | 加列可自动补、有版本历史 |

> 阶段 1 是「大爆炸」：一次变更完成引擎替换 + 全量搬迁，无逐应用回滚点。缓解手段见「六、风险 6」。

---

## 六、风险与注意

1. **DDL 子集边界要严格**：一旦允许任意 SQL，解析器又被拖回正则时代；子集外即报错。
2. **索引/约束进 DDL，触发器/存储过程不进**：保持子集纯声明。
3. **种子数据归属**：先摸底 `_init_db` 除了建表还干了什么，再定是否引入 `seed.sql`。
4. **新依赖 sqlglot**：确认覆盖 FDE 用到的 SQLite DDL 语法（`AUTOINCREMENT`、`INTEGER PRIMARY KEY`
   rowid 语义等，见 4.2）；作为正式依赖进 requirements.txt，import 失败则启动报错（不保留正则回落）。
5. **多环境契约对齐**：schema 版本号需与 `_contracts.md` 契约版本、代码版本绑定记录，
   启动时校验「契约声明的 schema 版本 == 库的 `_schema_migrations` 版本」，不一致即告警。
6. **一次性迁移的风险**：单次大变更、无逐应用回滚点。缓解：迁移是机械搬迁（`_init_db` 的
   `CREATE TABLE` 原样抽到 `schema.sql`），且以 `scanner` + `verify_chain` + `verify_view`
   全绿 + **PG 冒烟** 为合入门禁，配合 dbguard 的测试库隔离，风险可控。
7. **DML 方言残留**：`_translate_ddl` 移除后，应用 DML 里的 SQLite 专属函数（如 `datetime('now')`）
   若存在，PG 下会报错。阶段 0 摸底若发现此类用法，需补一个轻量 DML 函数翻译，或改造应用 DML
   为可移植写法。

---

## 七、待确认清单（开工前需拍板）

- [x] 决策 1：DDL 格式 = **SQL 子集**（已定）
- [x] 决策 2：解析器 = **sqlglot**（已定，正式依赖）
- [x] 决策 3：迁移策略 = **一次性迁移，不保留回落**（已定）
- [ ] 种子数据归属：`seed.sql` 还是完全无种子（以阶段 0 摸底为准）
- [ ] 是否做 4.5 契约列名校验（可选，阶段 2 单独评估工作量）
