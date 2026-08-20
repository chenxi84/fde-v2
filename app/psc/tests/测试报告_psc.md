# psc 组 · 后端联通测试执行报告（第⑤步）

> 产出时间：2026-08-14
> 脚本：`app/psc/tests/verify_chain_psc.py`（编排器）+ `verify_chain_psc_part1.py`（§1 主数据 + §2 主链）+ `verify_chain_psc_part2.py`（§3 分支）
> 设计来源：`app/psc/测试用例.md`（66 条用例，含前置辅助）

---

## 一、Verdict

```
VERIFY_RESULT: PASS
测试结果: 67/67 通过
```

- §1 主数据准备 10 例 ✅
- §2 主业务链 18 例 ✅（预测→库存→毛需求→净需求→主计划→推移表→需求池→拟合 全链联通，含 2 处 ERP 回执模拟）
- §3 分支/异常 38 例 ✅（主数据校验 / 版本与单据状态机 / 三类补库 / 替换件合并 / 断点追溯 / 拟合状态机 / 批量服务）
- 前置辅助 1 例 ✅

---

## 二、执行结果摘要

| 段 | 用例数 | 结果 |
|----|--------|------|
| §1 主数据准备 | 10 | ✅ 全绿 |
| §2 主业务链（happy path + 回执模拟） | 18 | ✅ 全绿 |
| §3 分支 / 异常 | 38 | ✅ 全绿 |
| 前置辅助 | 1 | ✅ |
| **合计** | **67** | **✅ PASS** |

---

## 三、triage 记录（首轮 31/67 → 修复后 67/67）

| 分类 | 数量 | 说明 |
|------|------|------|
| 应用 bug（app_bug） | 3 | attainment `ON CONFLICT` 与审计注入不兼容；sales_forecast.open_version 无历史客户兜底；inventory_strategy.calc 无历史数据兜底 |
| 脚本/用例翻译错（case_calibration） | 7 | 版本号 YYYYMM、import_batch 返回字段、状态机测试数据顺序、关键词「锁定」、rollback 上一版构造、汇总逐行断言 |

详见 `app/psc/tests/BUGS_psc.md`（逐条根因 + 修复）。

---

## 四、契约最终冻结

- 修复 3 处后端代码后，无条件重跑 `python -m fde_platform.contract_dump psc` → 成功（15 应用真实服务签名）。
- `python -m fde_platform.scanner`：**psc 组 33 个跨应用调用 0 issue**（含 open_version 新增 md_customer.list 兜底调用）。
- 契约最终冻结文件时间戳晚于最后一次 `.py` 修改，seed 样例字段形状正常。

---

## 五、结论

- 主链全链真实联通（跨应用 `self.fde.call` 逐段打通），分支/状态机/异常校验全覆盖。
- 三处应用 bug 已修复并回填测试用例；契约已最终冻结。
- **第⑤步门禁通过，后端段（①–⑤）完成**。可进入前端段（第⑥步前端设计，消费最终冻结的 `_contracts.md`）。
