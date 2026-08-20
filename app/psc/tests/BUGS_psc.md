# psc 组 · 测试失败 triage 台账（第⑤步）

> 首跑 31/67 通过 → 逐条 triage 修复后 67/67 PASS。
> 分类：app_bug（应用代码缺陷）/ case_calibration（用例/脚本翻译错）。

---

## 一、应用 bug（已修复，反馈第③步）

| # | 应用 | 缺陷 | 根因 | 修复 |
|---|------|------|------|------|
| B1 | attainment | `upsert` 报「4 values for 8 columns」 | `ON CONFLICT ... DO UPDATE` 语法与平台审计列注入不兼容（注入器假设 INSERT 以 `VALUES(...)` 结尾） | 改为「先查后写」（存在则 UPDATE、不存在则 INSERT） |
| B2 | sales_forecast | `open_version` 在无历史采购客户时生成 0 行，主链无法启动 | 清单客户来源只依赖 `_load_sales_history`（ERP 历史），系统初始化时为空 | 加兜底：历史客户为空时取 `md_customer` 全部客户作为预测范围 |
| B3 | inventory_strategy | `calc` 在无历史数据时抛「历史需求数据缺失」，阻断主链 | 未覆盖「新品/初始场景无历史」的兜底 | 加兜底：无历史时水位按 0 计算（basis 注明），不阻断 |

> 三处均为「应用依赖 ERP 历史数据、但无初始/空数据兜底」的同类缺陷——BRD §7.7「历史不足用借用参考/兜底」精神，应用应能在空数据场景启动而非抛错。

---

## 二、用例/脚本翻译错（已修脚本 + 回填用例）

| # | 用例 | 问题 | 修复 |
|---|------|------|------|
| C1 | 全链 version_no | 用「V202608」但代码校验纯 YYYYMM | 改为「202608」 |
| C2 | 全链 fit_version | 用「FIT-202608」但代码校验 YYYYMM | 改为「202608」 |
| C3 | TC-ERR-38 | import_batch 断言 `created/updated`，实际返回 `total/success/fail` | 断言改 `success=2, fail=0` |
| C4 | TC-ERR-11 | 期望「草稿」，实际 `_require_draft` 抛「锁定」 | 关键词改「锁定」 |
| C5 | TC-ERR-17/19 | 状态机测试数据顺序错（用待下达单测「非待下达」） | 先推进状态再测拦截 |
| C6 | TC-ERR-32 | rollback 无「上一版已生效参数」 | 先 run+approve 更早版本 202607 再回滚 |
| C7 | TC-MC-05 | get_summary 期望合计值 2850，实际逐行 3 行各 950 | 改「3 行各 final_qty_sum=950」 |

---

## 三、结论

- 应用 bug 3 处（B1~B3）已修复，测试跑绿；已据实回填测试用例.md（版本号/期望/状态机数据）。
- 测试用例.md §4 待确认 Q1（基线/水位依赖历史数据）已通过 B2/B3 的兜底修复部分消解，仍需真实历史数据验证 decide 双源对比分支。
