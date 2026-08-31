# Schema 摸底结果（阶段 0）

> 扫描 19 个应用（e2e 2 + psc 17）的 `_init_db` 与全文件 SQL，产出本清单，
> 作为「一次性迁移」的依据。结论先行：**迁移工程量很小，DDL 子集比预想更窄、更安全**。

---

## 一、DDL 子集边界（白名单）

### 建表与类型

- 19/19 应用都建表，每应用 **1~2 张**（`md_material`、`sales_forecast` 各 2 张，其余 1 张）。
- **列类型白名单**：`TEXT` / `INTEGER` / `REAL` / `DATETIME` / `TIMESTAMP`。
  未观察到 `NUMERIC / FLOAT / BOOLEAN / BLOB / VARCHAR / DOUBLE`。

### 约束（全为声明式，可进 DDL 子集）

- 列级：`PRIMARY KEY`、`NOT NULL`、`UNIQUE`、`DEFAULT`（字面量 + `CURRENT_TIMESTAMP`）、`CHECK`（枚举 / 比较）。
- 表级：复合 `PRIMARY KEY (a, b)`（如 `md_project_part`）、复合 `UNIQUE (...)`（如 `master_plan` / `md_breakpoint` / `md_part_replace`）。
- **无 `FOREIGN KEY` / `REFERENCES`**：跨表关联全部在应用层做，DB 层零外键 → 子集无需外键。

### 索引

- 多数应用有 `CREATE [UNIQUE] INDEX`（每应用 **1~4 个**）→ 必须进子集。

### SQLite 专属（需 FDE 在 AST 层补规则）

| 项 | 位置 | 处理 |
|---|---|---|
| `INTEGER PRIMARY KEY AUTOINCREMENT` | 仅 `md_breakpoint` 1 处 | PG 需 `GENERATED ALWAYS AS IDENTITY` |
| `CURRENT_TIMESTAMP` | `e2e/member`、`e2e/task` | SQL 标准，SQLite/PG 通用，**无需处理** |
| `PRAGMA table_info` | `md_project_part` `_init_db` | 随 `_init_db` 删除而消失 |

### 明确不在子集内（已确认无）

触发器 / 视图 / 存储过程 / 外键 —— 全部零使用。

---

## 二、迁移工程量

### 补列 ALTER（合并进 CREATE TABLE）

| 应用 | 补列 | 数量 |
|---|---|---|
| `md_customer` | `credit_code` | 1 |
| `md_project` | `veh_model`、`share` | 2 |
| `sales_history` | `forecast_qty` | 1 |

合计 **4 列、3 个应用**。抽取 `schema.sql` 时直接并入各表 `CREATE TABLE`，不再保留 ALTER。

### 非声明式逻辑（转显式迁移，不进 schema.sql）

- **`md_project_part`**：`_init_db` 内含一段**数据迁移**——检测旧列 `veh_model/share` → `DROP TABLE` → 重建 → 逐行回迁 `usage`。这段必须转为阶段 2 的 `migrations/NNNN_*.py` 显式迁移，而非 schema.sql。
- 其余 18 个应用 `_init_db` 均为**纯建表**（无种子数据、无数据迁移）。

---

## 三、DML 方言残留（`_translate_ddl` 移除后 PG 会 break）

- **`md_material`**：DML 里用 SQLite 专属 `datetime('now','localtime')`（**3 处**：2 UPDATE + 1 INSERT，业务字段 `fit_effective_at` / `effective_at`）。
  - 处理：① 保留一个轻量 DML 函数翻译（`datetime('now','localtime')` → `NOW()`）；或 ② 改 `md_material` 用 Python 生成时间戳 + 参数绑定（**推荐**，更干净）。
- Python 层 `datetime.now()/strftime()` 大量使用，但都是 Python 代码，与 SQL 方言无关，**无需处理**。

---

## 四、审计列一致性（新发现）

e2e 与 psc 对审计列的写法**不一致**：

- **e2e/member、e2e/task**：手写 `created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP`、`updated_at DATETIME DEFAULT CURRENT_TIMESTAMP`（平台注入会因列已存在而跳过）。
- **psc 应用**：不写审计列，完全靠平台 `_add_audit_columns` 自动注入。

迁移时应**统一为「平台注入」**：e2e 两个应用手写的 `created_at/updated_at` 列从 `schema.sql` 里删除，交给平台统一注入（`created_at/updated_at/created_by/updated_by` 四列齐整）。

---

## 五、对方案的影响与确认点

1. **DDL 子集可收窄**：类型白名单固定为 `TEXT/INTEGER/REAL/DATETIME/TIMESTAMP`；约束仅列级/表级 `PK/NOT NULL/UNIQUE/DEFAULT/CHECK`；无外键。子集越小，解析器越稳。
2. **迁移量**：4 列合并 + 1 个数据迁移转显式 + 1 处 DML 函数处理 + 2 个应用删手写审计列。整体很小。
3. **需拍板**：`md_material` 的 `datetime('now','localtime')` 用「翻译层」还是「改 Python 参数绑定」——建议后者（少维护一段翻译逻辑）。
4. **`md_project_part` 的数据迁移**：确认它作为显式迁移步骤（阶段 2），不随阶段 1 的 schema.sql 搬迁，阶段 1 可先按「已迁移」处理（即 schema.sql 只写最终表结构，旧数据迁移脚本单独保留到阶段 2）。
