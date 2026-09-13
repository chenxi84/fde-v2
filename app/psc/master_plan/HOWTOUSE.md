# master_plan 使用要点

**管什么**：主计划——线下产能平衡后导回的**已排定产量**与最迟入库日期，按计划版本号版本化。回答「计划排产了多少、什么时候到货」用它；问「需求是多少」去毛需求与净需求。

## 标准工作流（按此顺序）

1. `import_from_net` — **产能平衡「照单全收」时走它**：只给 `version_no` / `material_nos` / `rolling_month` / `latest_inbound_date`，净需求多少就排多少，取数换算由服务自己做。**别自己去读净需求再手抄数字拼 rows**——抄错一位就是一个错的主计划
2. `import_plan` — 线下平衡**动过数量**时才用它：传 `version_no` 与 `rows`，每行含 `material_no` / `rolling_month` / `plan_qty` / `latest_inbound_date`。**用户拿一份线下平衡结果要你导进去是完全正常的请求**，直接导
3. `list` — 按 `version_no` / `material_no` 精确筛选浏览（`plan_version` 降序）
4. `get` — 用返回的 `plan_version + material_no + rolling_month` 核对单行
5. `get_latest` — 取该物料在每个滚动月度的**最新版本**行；这是下游库存推移表「预计入库量」的取数口径

## 前置条件与禁忌

- **`plan_version` 由系统生成，不要传也不该传**：每次导入按「物料 × 滚动月度」取当前最大值 +1，调用方只给 `version_no` 和行数据。
- **导入只增不改**：`plan_version` 严格递增（v1 → v2 → v3…），旧版本永远保留，本应用不可删除或覆盖历史版本。读当前口径一律用 `get_latest`，别拿旧版本行当现状。
- **逐行校验，不做整批回滚**：非法行进 `errors`，合法行照常入库。导入后**必须看**返回的 `success` / `fail` / `errors`，不要只回一句「导入成功」。
- `rolling_month` 只认 `N+1` / `N+2` / `N+3`；`plan_qty` 必须 ≥ 0；`latest_inbound_date` 必填且为 `YYYY-MM-DD`。
- `import_plan` 内部会先调 `demand.export_net` 导出净需求供参考，**它失败（如「净需求未运算」）不阻断导入**——不必先跑一遍净需求，也不要因此改用别的入口。

## 出错时

上面的要点没覆盖的细节（完整参数表、错误码含义），用
`platform_read_app_doc(app="psc/master_plan", doc="README")` 读完整操作指南再处置。
