# 产销协同看板 前端详设
> 来源：app/psc/architecture.md（主链关系图 · ③）+ app/psc/_contracts.md（冻结契约）；产出供第⑦步编码 / 第⑧步测试用例
> 落位：`view/psc/dashboard.js` + `view/psc/dashboard.html`（组级页，无对应后端应用，key="dashboard"）

## 1. 页面元数据 PAGE_META

| 字段 | 值 | 说明 |
|---|---|---|
| key | `dashboard` | 组级页固定 key；page_id 为 `psc:dashboard` |
| name | 产销协同看板 | 侧栏菜单名 |
| ic | 🏭 | 菜单图标字 |
| title | 产销协同看板 | 主区页面头 |
| crumb | KPI · 主链管道 · 待办队列 | 头部副题 |
| order | 10 | 居首（各应用按 10 步长递增，最小即菜单第 1 项） |

- 页面零鉴权：不做任何权限判断；菜单按页面授权渲染在 shell。**看板对受限用户恒显**——故初始加载一律 `quiet` 探测 + 零值兜底（不喷错误 toast），见 §5。
- 本页**无 create / update / set_* / import_batch**——跨应用只读聚合页，不落任何写操作，无表单、无编辑入口。

## 2. 区块构成

> 区块构成换为：KPI 指标带 / 主链管道（各应用状态分布）/ 待办队列 / 跳转目标（组级看板模板，见 design-plus/前端设计.md 末尾 dashboard 说明）。

### 2.1 KPI 指标带
一排 `.kpi` 卡片行（`.frow`；每卡「数字 + 中文标签」，数字 `.b-link` 点击跳到对应应用页）。全部取各应用 `list` 返回的 `total`：

| 卡片 | 指标 | svc 探测 | 取值 | 跳转 |
|------|------|---------|------|------|
| 待下达补库单 | 需求池待下达数 | `demand_pool.list(status='待下达', page=1, page_size=5)` | `total` | `#/demand_pool` |
| 已下达补库单 | 需求池已下达数 | `demand_pool.list(status='已下达', page=1, page_size=1)` | `total` | `#/demand_pool` |
| 生产中补库单 | 需求池生产中（在途）数 | `demand_pool.list(status='生产中', page=1, page_size=1)` | `total` | `#/demand_pool` |
| 待复核拟合 | 策略拟合待复核数 | `strategy_fitting.list(status='待复核', page=1, page_size=5)` | `total` | `#/strategy_fitting` |
| 草稿版本 | 月度版本草稿数 | `md_monthly_version.list(lock_status='草稿', page=1, page_size=5)` | `total` | `#/md_monthly_version` |
| 缺货预警 | 库存推移表缺货预警行数 | `inventory_projection.list(alert_type='缺货', page=1, page_size=1)` | `total` | `#/inventory_projection` |

- 需求池三态（待下达 / 已下达 / 生产中）与待办队列共用「待下达」那次 `page_size=5` 的返回（`total` 供 KPI、`items` 供待办队列）；「已下达 / 生产中」另起 `page_size=1` 仅取 `total`。
- 无数据时每卡数字显示 `0`（零值兜底），不显示 `—`（数量型指标语义为 0）。

### 2.2 主链管道（各应用状态分布）
七个管道段卡片（`.sec`，主链序固定，取自 architecture.md §③ 关系图粗实线主链）：

**销售预测 → 库存策略 → 毛需求/净需求 → 主计划 → 库存推移表 → 需求池 → 策略拟合**

| 管道段 | svc 探测 | 展示字段（最近 page_size=5 行） | 跳转 |
|--------|---------|-------------------------------|------|
| ① 销售预测 | `sales_forecast.list(version_no=fv, page=1, page_size=5)` | `material_no` + `customer_no` + `rolling_month` + `final_qty`（`abnormal_flag` 徽章） | `#/sales_forecast` |
| ② 库存策略 | `inventory_strategy.list(version_no=fv, page=1, page_size=5)` | `material_no` + `hedge_tool` + `min_level`/`safety_level`/`batch_level` | `#/inventory_strategy` |
| ③ 毛需求/净需求 | `demand.list(version_no=fv, page=1, page_size=5)` | `material_no` + `rolling_month` + `gross_qty`/`net_qty` | `#/demand` |
| ④ 主计划 | `master_plan.list(version_no=fv, page=1, page_size=5)` | `material_no` + `rolling_month` + `plan_version` + `plan_qty` | `#/master_plan` |
| ⑤ 库存推移表 | `inventory_projection.list(page=1, page_size=5)` | `material_no` + `biz_date` + `balance` + `alert_type`（`hue()` 徽章） | `#/inventory_projection` |
| ⑥ 需求池 | `demand_pool.list(page=1, page_size=5)` | `replenish_no` + `material_no` + `replenish_type` + `status`（`hue()` 徽章） | `#/demand_pool` |
| ⑦ 策略拟合 | `strategy_fitting.list(page=1, page_size=5)` | `material_no` + `fit_version` + `pred_method` + `status`（`hue()` 徽章） | `#/strategy_fitting` |

- ①~④ 的 `version_no` 来自 §4 活跃版本 `fv`；⑤~⑦ 不按版本过滤（库存推移 / 补库单 / 拟合以最新状态为准），只按各自 list 默认排序取最近行。
- 每段「最近 5 行」单号 / 物料号列 `.b-link`，点击跳到该应用页；无数据显示「暂无数据」空态（不喷 toast）。

### 2.3 待办队列
三行待办卡片（每行「待办标题 + 数量徽章 + 最近单号列表」，单号 `.b-link`）：

| 待办项 | 状态 | svc 探测 | 展示 | 跳转 |
|--------|------|---------|------|------|
| 需求池「待下达」补库单 | `status='待下达'` | `demand_pool.list(status='待下达', page=1, page_size=5)` | `total` 数量 + 最近 `replenish_no`×5 | `#/demand_pool` |
| 策略拟合「待复核」 | `status='待复核'` | `strategy_fitting.list(status='待复核', page=1, page_size=5)` | `total` 数量 + 最近 `material_no`×5 | `#/strategy_fitting` |
| 月度版本「草稿」 | `lock_status='草稿'` | `md_monthly_version.list(lock_status='草稿', page=1, page_size=5)` | `total` 数量 + 最近 `version_no`×5 | `#/md_monthly_version` |

- 需求池「待下达」与策略拟合「待复核」与 KPI 卡片共用同一 `page_size=5` 返回（§2.1），不重复请求；月度版本「草稿」同理。
- 数量为 0 时仍渲染「0 条」空态，不隐藏卡片（受限用户恒显零值兜底）。

### 2.4 跳转目标
全部跳转用**字面量目标页 key**（= 应用文件夹名），`gotoPage(key)` 写 `window.location.hash = "#/" + key`，不变量拼名：

| 目标页 | 路由 | 入口来源 |
|--------|------|---------|
| 销售预测 | `#/sales_forecast` | 管道① |
| 库存策略 | `#/inventory_strategy` | 管道② |
| 毛需求/净需求 | `#/demand` | 管道③ |
| 主计划 | `#/master_plan` | 管道④ |
| 库存推移表 | `#/inventory_projection` | 管道⑤ / KPI 缺货预警 |
| 需求池 | `#/demand_pool` | 管道⑥ / KPI 三态 / 待办① |
| 策略拟合 | `#/strategy_fitting` | 管道⑦ / KPI 待复核 / 待办② |
| 月度版本 | `#/md_monthly_version` | KPI 草稿 / 待办③ |

> 看板不跳 `attainment`（纯 ERP 冗余回写、无用户操作）与其余 `md_*` 主数据页——待办/管道只覆盖主链 7 应用 + 月度版本。

## 3. svc 字面量清单（授权派生依据——必须字面量 svc("应用","服务")）

| # | 区块 | 调用（应用.服务） | 参数 | quiet | 说明 |
|---|------|-------------------|------|-------|------|
| 1 | 版本探测 | `svc("md_monthly_version","get_active")` | `{}` | true | 取活跃版本号（最新非「冻结」版本），驱动管道①~④ 的 version_no |
| 2 | 版本探测 | `svc("md_monthly_version","list")` | `{page:1, page_size:1}` | true | 无活跃版本时回退取最新版本（含已锁定历史版本） |
| 3 | KPI + 待办 | `svc("demand_pool","list")` | `{status:'待下达', page:1, page_size:5}` | true | `total`→KPI 待下达数；`items`→待办① |
| 4 | KPI | `svc("demand_pool","list")` | `{status:'已下达', page:1, page_size:1}` | true | `total`→KPI 已下达数 |
| 5 | KPI | `svc("demand_pool","list")` | `{status:'生产中', page:1, page_size:1}` | true | `total`→KPI 生产中数 |
| 6 | KPI + 待办 | `svc("strategy_fitting","list")` | `{status:'待复核', page:1, page_size:5}` | true | `total`→KPI 待复核数；`items`→待办② |
| 7 | KPI + 待办 | `svc("md_monthly_version","list")` | `{lock_status:'草稿', page:1, page_size:5}` | true | `total`→KPI 草稿数；`items`→待办③ |
| 8 | KPI | `svc("inventory_projection","list")` | `{alert_type:'缺货', page:1, page_size:1}` | true | `total`→KPI 缺货预警数 |
| 9 | 管道① | `svc("sales_forecast","list")` | `{version_no:fv, page:1, page_size:5}` | true | 最近销售预测处理行 |
| 10 | 管道② | `svc("inventory_strategy","list")` | `{version_no:fv, page:1, page_size:5}` | true | 最近库存策略行 |
| 11 | 管道③ | `svc("demand","list")` | `{version_no:fv, page:1, page_size:5}` | true | 最近毛/净需求行 |
| 12 | 管道④ | `svc("master_plan","list")` | `{version_no:fv, page:1, page_size:5}` | true | 最近主计划行 |
| 13 | 管道⑤ | `svc("inventory_projection","list")` | `{page:1, page_size:5}` | true | 最近库存推移行 |
| 14 | 管道⑥ | `svc("demand_pool","list")` | `{page:1, page_size:5}` | true | 最近补库单 |
| 15 | 管道⑦ | `svc("strategy_fitting","list")` | `{page:1, page_size:5}` | true | 最近拟合结果 |

> 以上 15 处必须在 `view/psc/dashboard.js` 中以字面量逐项书写（可包在闭包里），**全部 `quiet:true` 探测**，**勿用变量拼名**——这是页面授权隐式放行派生扫描的唯一来源（pitfalls #8/#10）。

## 4. 数据来源与下拉

**活跃版本号（驱动管道①~④）**：
- 初始化先 `svc("md_monthly_version","get_active")` `{quiet:true}`：命中取返回对象 `version_no` 作为 `fv`；返回 `None`（无未冻结版本）或失败时，回退 `svc("md_monthly_version","list")` `{page:1, page_size:1}` 取最新一条 `version_no`；两者皆空则 `fv=''`，管道①~④ 探测跳过（`Promise.resolve(null)`）并显示「暂无数据」。
- `fv` 只作管道①~④ 的过滤参数，不展示、不进表单。

**契约 payload → 区块字段映射**：

| 来源 | payload 字段 | 去向 |
|------|-------------|------|
| `demand_pool.list` 项 | replenish_no, material_no, replenish_type, replenish_qty, required_inbound, promised_inbound, status | KPI 计数（total）；待办①单号列表；管道⑥行 |
| `strategy_fitting.list` 项 | material_no, fit_version, pred_method, smape, status | KPI 计数（total）；待办②物料列表；管道⑦行 |
| `md_monthly_version.list` 项 | version_no, anchor_period, opening_date, lock_status | KPI 计数（total）；待办③版本列表；活跃版本探测 |
| `inventory_projection.list` 项 | material_no, biz_date, inbound_qty, outbound_qty, balance, alert_type | KPI 缺货计数（total）；管道⑤行 |
| `sales_forecast.list` 项 | version_no, material_no, customer_no, rolling_month, final_qty, abnormal_flag | 管道①行 |
| `inventory_strategy.list` 项 | version_no, material_no, hedge_tool, min_level, safety_level, batch_level | 管道②行 |
| `demand.list` 项 | version_no, material_no, rolling_month, gross_qty, net_qty | 管道③行 |
| `master_plan.list` 项 | material_no, version_no, rolling_month, plan_version, plan_qty, latest_inbound_date | 管道④行 |

- **枚举原值传参，与后端校验值完全一致**：`demand_pool.status` ∈ 待下达/已下达/生产中/已完成/已取消；`strategy_fitting.status` ∈ 待复核/已生效/已否决；`md_monthly_version.lock_status` ∈ 草稿/发布（锁定）/冻结；`inventory_projection.alert_type` ∈ 无/缺货/击穿最低/击穿安全/呆滞/超储（缺货预警取 `'缺货'`）。

## 5. 交互要点

1. **全部 quiet 探测 + 零值兜底**：15 处 svc 全部 `{quiet:true}`；任一失败不喷 toast、不 throw；KPI 数字兜底 `0`，管道/待办列表兜底空数组显示「暂无数据」/「0 条」——受限用户恒显、初始加载无错误 toast。
2. **加载态**：`self.tpl` 先抓模板，`init()` 首个 `await` 前同步建好全部 reactive 状态（`activeVersion=null` / 各管道 `items:[]` / 各 KPI 计数 `0` / `loading=true`），再 `await` 拉数（pitfalls #37——先 await 后建对象会整片报错）；全部探测完成后 `loading=false` 渲染骨架（`.loadbox`）。
3. **并行探测**：版本号先取，其后 KPI/管道/待办用 `Promise.allSettled` 并行发起（依赖 `fv` 的调用在 `fv` 为空时以 `Promise.resolve(null)` 短路），逐项按 `status==='fulfilled'` 取值。
4. **跳转**：KPI 数字 / 管道行单号·物料号 / 待办单号均为 `.b-link`，`gotoPage(key)` 写 `window.location.hash = "#/" + key`；跳转目标见 §2.4，全部字面量 key。
5. **展示工具**：`hue()`（demand_pool.status / inventory_projection.alert_type / strategy_fitting.status / sales_forecast.abnormal_flag 徽章）、`dash()`（空值字段，管道行空字段显示 `—`）、`fmt()`（数量字段，如 final_qty/gross_qty/net_qty/plan_qty/replenish_qty/balance/min_level/safety_level/batch_level）；本页无 `*_json` 需 `tryParse` 展示的字段（`base_params`/`pred_params` 不在看板展示）。
6. **无写操作 / 无模态 / 无表单**：跨应用只读聚合，不调任何 create/update/set_*/import_batch/状态机动作，无详情模态、无编辑入口。

## 6. 验收关注点（供第⑧步）

1. **路由渲染**：`#/dashboard` 挂载出 KPI 指标带（≥6 张 `.kpi`）+ 主链管道 7 段卡 + 待办队列 3 行；菜单「🏭 产销协同看板」按 order=10 居 menu[0]。
2. **看板页有 `.kpi`**（与逐应用页相反——看板有 KPI 卡片，逐应用页 `.kpi` 数恒 0 防挂载粘滞假过）。
3. **quiet 零值兜底**：空库/无版本时 KPI 全 0、管道/待办显示「暂无数据」，全程 0 console error / 0 pageerror / 0 HTTP≥400（受限会话 403 属预期执法，单独豁免）。
4. **受限用户恒显**：播种仅授权一两个应用的 `limited_role` 用户 → 菜单仍含看板（看板对受限用户恒显），直访无授权路由回落看板。
5. **跳转目标字面量**：点 KPI「待下达」数字 → `#/demand_pool`；点待办③「草稿」版本号 → `#/md_monthly_version`；点管道⑦拟合行 → `#/strategy_fitting`（断言 `location.hash` 为字面量目标 key，非变量拼名）。
6. **造数后管道有数据**：造月度版本（草稿/发布）→ 造销售预测/库存策略/毛需求/主计划/推移表/补库单/拟合各行 → 断言各管道段最近 5 行字段非空、状态徽章正确。
7. **KPI 计数真实**：造 N 条「待下达」补库单 → KPI「待下达」数字 = N（取自 `list` 的 `total`，非前端假统计）。
