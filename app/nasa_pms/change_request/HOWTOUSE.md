# change_request 使用要点

**管什么**：对配置项 / 基线的变更申请——影响范围（`ci_nos` / `req_nos`）、影响分析、CCB 审批意见、实施登记。**本应用不改配置项本身**，版本改动由配置项侧执行。

## 标准工作流（按此顺序）

1. `create` — 提交登记，落 `submitted`；`title` + `requester` 必填，`ci_nos` / `req_nos` **至少一个**（列表或逗号分隔文本皆可，全角逗号认、自动去重）
2. `analyze` — 登记影响分析（`impact_analysis` 必填）→ `analyzing`
3. `submit_review` — 送审 → `reviewing`（**"审批中"的唯一入口**）
4. `approve` / `reject` — 审批意见 `comment` 必填 → `approved` / `rejected`（终态）
5. `implement` — `approved → implemented`（终态），登记实施说明；**真正的改动再调** `configuration_item.bump_version(ci_no, n, cr_no)`
6. `update` 只在第 2 步之前可用（标题 / 申请方 / 影响范围 / 变更说明）

核对用：`list`（按 `status` / `requester` 筛；`ci_no` / `req_no` 是"影响范围含该编号"的成员筛）→ `get`。

## 前置条件与禁忌

- **硬终态 `rejected` / `implemented`**：终态判断是**所有动作的最前置守卫**（排在状态门与参数校验之前），此后修改 / 分析 / 送审 / 审批 / 实施一律报「已处于终态「…」，不能再操作」。
- **禁止跳步**：审批只接受 `reviewing`，对 `submitted` 直接 `approve` → 报「只有审批中的变更请求才能审批（先登记影响分析并提交审批）」——**"先批后分析"在状态机上不可达**，别绕 `analyze` / `submit_review`。
- **内容只在「已提交」可改**：进入 `analyzing` 后内容定型，改范围要**另提一条**。`update` 时只改你传的那一侧、另一侧取当前值，校验的是**改完之后**的整体范围（不能一个都不剩）。
- **影响范围必须真实可用（跨应用只读校验）**：配置项须为 `configuration_item` 里已有且**未归档**（`archived`）、需求须为 `requirement` 里已有且**未废弃**（`obsolete`）。不存在报「请先在配置项台账中登记」；终态对象报「已归档（终态），不能再作为变更的影响范围」—— 这类变更永远无法实施。
- **实施是两步、无分布式事务**：先 `implement`、再 `configuration_item.bump_version(ci_no, n, cr_no)`，靠顺序保证、**不会自动回滚**，别只做一半。
- 编号 `CR-三位序号`不可改；`approve` / `reject` 的审批意见都必填；没有删除服务。

## 出错时

上面的要点没覆盖的细节（完整参数表、错误码含义），用
`platform_read_app_doc(app="nasa_pms/change_request", doc="应用详设")` 读完整详设再处置。
