# interface 使用要点

**管什么**：两个系统 / 分系统之间的接口约定（ICD / IRD / IDD / ICP）——两端、约定内容、字母修订版、冻结。**不是代码里的 API 接口**；接口文档本身是配置项，但**改接口 ≠ 改配置项版本**。

## 标准工作流（按此顺序）

1. `create` — 登记接口，落 `defined`（**此时尚无版本**）；`if_name` / `if_type` / `provider` / `consumer` 必填且两端不能相同
2. `update` — 定版前随便改（含**两端**与**约定内容 ICD**）
3. `release` — 首次发布定版为 `A`，**同一事务写两条通知记录**（提供方一条、使用方一条）
4. `revise` — 版本变更：`new_version`（单个大写字母）+ `reason` 必填 → `changing`，**再通知两端**
5. `release` — 变更落到实处后回到 `released`（版本不变），**不重复通知**
6. `freeze` — `released → frozen`（硬终态），可附 `note`

核对用：`get`（主档 + `changes` 通知明细 + `change_total`）→ `list`（按 `if_type` / `status` / `provider` / `consumer` / `ci_no` 筛）→ `list_changes`（跨接口通知台账，按 `party` 筛核验"每次变更两端各收到一条"）。

## 前置条件与禁忌

- **状态闸**：`revise` 只认 `released`（对 `defined` 报「尚未定版，请先发布」，对 `changing` 报「已经在变更中，请先完成本次变更」）；`freeze` 只认 `released`（定义中还没版本可冻、变更中的应先 `release`）；已冻结拒绝 `update` / `release` / `revise` / `freeze` 全部，且**终态守卫排最前**。
- **定版后两端与 ICD 内容锁死**：非 `defined` 时 `update` 传 `provider` / `consumer` 或 `icd_content` 一律拒（「改端等于换一条接口」→ 该新建；「约定内容不能直接改」→ 走 `revise`）；**其余描述性字段（名称 / 类型 / 责任人 / 项目 / 关联配置项）非终态仍可改** —— 与配置项"带变更号即可解锁"的锁法不同，别照搬。
- `update` 传两端时校验的是**改完之后**的两端（只改一端也可能撞成同一个系统）。
- **版本为单个大写字母** `A`..`Z`（`Z` 之后没有两位版本），只能经 `release`（首次定版 `A`）与 `revise` 递增；`update` 的参数表里没有版本与编号（编号 `IF-三位序号`不可改）。
- **`ci_no` 是弱引用（可留空）**：填了必须真实存在且**未归档**（跨应用读 `configuration_item.list`），已归档报「不能作为新的关联」。
- **接口冻结 ≠ 配置项发版**：本应用不改任何配置项的版本或状态；要给配置项发版另走 `configuration_item`（且先要有已批准的变更请求）。
- 通知只落"已通知"、**不落"已确认"**（无回执服务）；没有删除服务。

## 出错时

上面的要点没覆盖的细节（完整参数表、错误码含义），用
`platform_read_app_doc(app="nasa_pms/interface", doc="应用详设")` 读完整详设再处置。
