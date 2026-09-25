"""FDE v2 后端主链端到端验证 · nasa_pms（决策 decision）

链路形态（单应用，含**聚合一内两子表**与完整状态机）：
  decision(create → add_criterion×2 → add_option×2 → start → score_option×2
           → conclude(选最高分) → implement)                        ← 主链
  decision(… → conclude(选**非**最高分 + 依据) → 已决策)             ← 选非最高分支路
    · BR-01 准则清单为空不得启动权衡（材料 §6.8.1.2.1：准则先于方案评估）
    · BR-02 备选方案少于两个不得结论（卡片 **I-2**）
    · BR-03 结论必须指向一个有评价得分的备选方案（卡片 **I-1**）
    · BR-04 选中非最高分方案必须给出依据（材料 §6.8.1.2.5）
    · BR-05 编号唯一且不可变（update 的字段白名单里没有 dec_no）
    · BR-06 已决策后内容冻结（结论是快照）；已实施为硬终态
    · BR-07 评价方法受字典约束
    · BR-08 准则权重（正整数）与评价得分（0~100 整数）的取值口径
  备选方案与评价准则都是**聚合内子表**（`architecture.md` 聚合根卡 8 的「备选方案」内部实体）：
  无独立标识（`(dec_no, seq)` 复合主键）、随本聚合同事务维护。

隔离：`shadow_dbs()` —— 业务库**复制**到临时目录，测试全程只读写副本，
**真库零字节接触，且不用停 dev server**。`shadow_clear(GROUP)` 清的是副本。

运行：python app/nasa_pms/tests/verify_chain_nasa_pms_decision.py
"""
import atexit
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent


def _project_root():
    p = HERE
    while not (p / "fde_platform").is_dir():
        if p.parent == p:
            raise RuntimeError("无法定位项目根目录（未找到 fde_platform/）")
        p = p.parent
    return p


ROOT = _project_root()
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from fde_platform.runtime import FdePlatform  # noqa: E402
from fde_platform.shadowdb import shadow_dbs, shadow_clear  # noqa: E402

# 输出编码：控制台代码页在本机默认是 GBK，而断言文案里有 ⇒ / ✓ / ✗ / ⚠ / − 这类**非 GBK 码位** ——
# 不钉住编码的话，print 自己会抛 UnicodeEncodeError（**崩在打印结果那一步**：断言算完了却报不出来，
# 其后用例也不再执行 —— 实测 nasa_pms 的 stakeholder 脚本里有一条断言就这么"消失"过）。与 scripts/run_gates.py 给
# 子进程设 PYTHONIOENCODING 同一根因；由 scripts/verify_test_script_encoding.py 守住别忘这一行。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_shadow = shadow_dbs()
_shadow.__enter__()
atexit.register(_shadow.__exit__, None, None, None)

GROUP = "nasa_pms"
APP = "decision"

RESULTS = []


def step(name):
    print(f"  -> {name}", flush=True)


def record(ok, note=""):
    RESULTS.append((ok, note))
    print(f"    {'[OK]' if ok else '[FAIL]'} {note}" if note else f"    {'[OK]' if ok else '[FAIL]'}",
          flush=True)


def expect_err(fn, substr):
    from fde import FdeError
    try:
        fn()
    except FdeError as e:
        msg = str(e)
        assert substr in msg, f"错误应含『{substr}』，实际: {msg}"
        return msg
    raise AssertionError(f"应抛 FdeError(含『{substr}』)，但未抛出")


def main():
    # ⚠ 必须显式清表：影子库的副本**带着真库的数据**，不清会撞主键（清的是副本）
    shadow_clear(GROUP)
    pf = FdePlatform()
    pf.load_all()

    qname = f"{GROUP}/{APP}"
    if qname not in pf.app_names():
        print(f"  ⚠ 应用未加载: {qname}", flush=True)
        return 1
    print(f"  [OK] {qname}", flush=True)

    def call(svc, **kw):
        return pf.call(qname, svc, **kw)

    # ── 主链（正向） ──────────────────────────────────────
    step("TC-01 新建决策（提出态，编号 DC-001，两个子表都空）")
    r1 = call("create", topic="飞控计算机选用", measure_no="TPM-001",
              issue="任务要求双余度，需在自研与货架产品之间取舍", owner="张三")
    record(r1["dec_no"] == "DC-001" and r1["status"] == "proposed"
           and r1["criteria"] == [] and r1["options"] == []
           and r1["criterion_total"] == 0 and r1["option_total"] == 0
           and r1["top_seq"] is None and r1["eval_method"] == "weighted_matrix",
           f"dec_no={r1['dec_no']} status={r1['status']} method={r1['eval_method']}")

    step("TC-02 编号递增")
    r2 = call("create", topic="推进方案选用", eval_method="trade_study", owner="李四")
    record(r2["dec_no"] == "DC-002", f"dec_no={r2['dec_no']}")

    step("TC-03 加评价准则（聚合内子表，seq 本决策内递增；权重正整数）")
    call("add_criterion", dec_no="DC-001", criterion="成本", weight=3)
    i3 = call("add_criterion", dec_no="DC-001", criterion="进度", weight=2)
    record([x["seq"] for x in i3["criteria"]] == [1, 2]
           and i3["criteria"][0]["criterion"] == "成本" and i3["criteria"][0]["weight"] == 3
           and i3["criterion_total"] == 2,
           f"criteria={[(x['seq'], x['weight']) for x in i3['criteria']]}")

    step("TC-04 加备选方案（提出态即可加；seq 本决策内递增）")
    call("add_option", dec_no="DC-001", name="方案A：自研", description="自研飞控计算机")
    o4 = call("add_option", dec_no="DC-001", name="方案B：货架产品", description="采购货架产品并适配")
    record([x["seq"] for x in o4["options"]] == [1, 2]
           and o4["options"][1]["name"] == "方案B：货架产品"
           and o4["options"][0]["score"] is None and o4["scored_total"] == 0,
           f"options={[(x['seq'], x['score']) for x in o4['options']]}")

    step("TC-05 启动权衡（提出 → 权衡中）")
    record(call("start", dec_no="DC-001")["status"] == "weighing", "status=weighing")

    step("TC-06 给备选方案打分（仅权衡中；可反复改分）")
    r6 = call("score_option", dec_no="DC-001", seq=1, score=70, note="成本优、进度慢")
    record(r6["options"][0]["score"] == 70 and r6["options"][0]["note"] == "成本优、进度慢"
           and r6["scored_total"] == 1 and r6["top_seq"] == 1 and r6["top_score"] == 70,
           f"seq=1 → {r6['options'][0]['score']} 分，top_seq={r6['top_seq']}")

    step("TC-07 打第二分 → 最高分方案随之切换")
    r7 = call("score_option", dec_no="DC-001", seq=2, score=88, note="总分最高")
    record(r7["options"][1]["score"] == 88 and r7["scored_total"] == 2
           and r7["top_seq"] == 2 and r7["top_score"] == 88,
           f"top_seq={r7['top_seq']} top_score={r7['top_score']}")

    step("TC-08 作决策：选中最高分方案（依据选填）→ 已决策")
    r8 = call("conclude", dec_no="DC-001", chosen_seq=2, risk_note="货架产品需做环境适应性验证")
    record(r8["status"] == "decided" and r8["chosen_seq"] == 2
           and r8["chosen_name"] == "方案B：货架产品" and r8["risk_note"].startswith("货架产品"),
           f"status={r8['status']} chosen={r8['chosen_name']}")

    step("TC-09 实施（已决策 → 已实施，硬终态）")
    r9 = call("implement", dec_no="DC-001", note="已签采购合同")
    record(r9["status"] == "implemented" and r9["implement_note"] == "已签采购合同",
           f"status={r9['status']}")

    step("TC-10 支路：选**非**最高分方案 + 给出依据 → 已决策")
    call("add_criterion", dec_no="DC-002", criterion="成本", weight=2)
    call("add_criterion", dec_no="DC-002", criterion="风险", weight=3)
    call("add_option", dec_no="DC-002", name="方案甲：液氧煤油")
    call("add_option", dec_no="DC-002", name="方案乙：固液混合")
    call("start", dec_no="DC-002")
    call("score_option", dec_no="DC-002", seq=1, score=90)
    call("score_option", dec_no="DC-002", seq=2, score=75)
    r10 = call("conclude", dec_no="DC-002", chosen_seq=2,
               rationale="方案乙风险低，成本略高但在可承受区间内")
    record(r10["status"] == "decided" and r10["chosen_seq"] == 2
           and r10["rationale"].startswith("方案乙风险低")
           and r10["top_seq"] == 1 and r10["top_score"] == 90,
           f"status={r10['status']} chosen={r10['chosen_name']}（最高分是 seq={r10['top_seq']}）")

    step("TC-11 造第三条：停在「权衡中」（2 个方案只打了 1 分）")
    call("create", topic="测控链路方案", eval_method="cost_benefit", owner="王五")
    call("add_criterion", dec_no="DC-003", criterion="支持性", weight=1)
    call("add_option", dec_no="DC-003", name="S 频段链路")
    call("add_option", dec_no="DC-003", name="Ka 频段链路")
    call("start", dec_no="DC-003")
    call("score_option", dec_no="DC-003", seq=1, score=60)
    r11 = call("get", dec_no="DC-003")
    record(r11["status"] == "weighing" and r11["scored_total"] == 1
           and r11["options"][1]["score"] is None,
           f"DC-003 权衡中，已打分 {r11['scored_total']}/{r11['option_total']}")

    step("TC-12 造第四条：停在「提出」（有准则、无方案）")
    call("create", topic="地面站部署方式", owner="赵六")
    call("add_criterion", dec_no="DC-004", criterion="任务成功", weight=5)
    record(call("get", dec_no="DC-004")["status"] == "proposed", "DC-004 提出")

    step("TC-13 查询列表（缺省：全部，按编号升序）")
    lst = call("list")
    # ⚠ list 契约是 {items, total}（前端 pageable 依赖它）；返回裸数组会让页面静默显示空态
    items = lst.get("items") or []
    record(lst.get("total") == 4 and [x["dec_no"] for x in items]
           == ["DC-001", "DC-002", "DC-003", "DC-004"],
           f"total={lst.get('total')} items={[x['dec_no'] for x in items]}")

    step("TC-14 list 与 get 同字段口径（主档字段逐项对齐 + 派生计数）")
    one = call("get", dec_no="DC-001")
    row = [x for x in items if x["dec_no"] == "DC-001"][0]
    record(set(row.keys()) == set(one.keys()) - {"criteria", "options"},
           f"list 行字段数={len(row)} / get 主档字段数={len(one) - 2}")
    record(row["criterion_total"] == 2 and row["option_total"] == 2
           and row["scored_total"] == 2 and row["top_seq"] == 2 and row["top_score"] == 88,
           f"派生计数 准则 {row['criterion_total']} / 方案 {row['option_total']} / "
           f"已打分 {row['scored_total']} / top {row['top_seq']}@{row['top_score']}")

    step("TC-15 分页（size=2，total 是切片前全量）")
    paged = call("list", page=1, size=2)
    record(len(paged["items"]) == 2 and paged["total"] == 4,
           f"本页 {len(paged['items'])} 条 / 共 {paged['total']} 条")

    step("TC-16 查询详情：主档 + 准则清单 + 方案清单（子表随聚合一起返回）")
    one = call("get", dec_no="DC-002")
    record(one["topic"] == "推进方案选用" and len(one["criteria"]) == 2
           and len(one["options"]) == 2 and one["options"][1]["score"] == 75
           and one["dissent"] == "",
           "字段完整（准则 2 / 方案 2 / 依据已落库）")

    step("TC-17 get 未命中 / 空编号不抛异常")
    # 对照断言（T2 门禁：本步不能只证明「没抛异常」）—— 未命中**不产生副作用**：
    _before = call("list")["total"]
    record(call("get", dec_no="DC-999") is None and call("get", dec_no="") is None,
           "返回 None")
    record(call("list")["total"] == _before,
           f"未命中不产生副作用：列表仍 {_before} 条")

    # ── BR 逐条（负例） ──────────────────────────────────
    step("TC-21 BR-01 准则清单为空不得启动权衡")
    call("create", topic="无准则议题", owner="孙七")
    record(True, expect_err(lambda: call("start", dec_no="DC-005"),
                            "还没有评价准则"))
    rec21 = call("get", dec_no="DC-005")
    record(rec21["status"] == "proposed" and rec21["criterion_total"] == 0,
           "被拒后仍是提出态（无副作用）")

    step("TC-22 BR-02 备选方案少于两个不得结论（卡片 I-2）")
    call("create", topic="单一方案议题", eval_method="decision_tree", owner="孙七")
    call("add_criterion", dec_no="DC-006", criterion="成本", weight=1)
    call("add_option", dec_no="DC-006", name="唯一可行方案")
    call("start", dec_no="DC-006")
    call("score_option", dec_no="DC-006", seq=1, score=80)
    record(True, expect_err(lambda: call("conclude", dec_no="DC-006", chosen_seq=1),
                            "少于两个不允许作结论"))

    step("TC-23 BR-03 结论必须指向一个有评价得分的备选方案（卡片 I-1）")
    record(True, expect_err(lambda: call("conclude", dec_no="DC-003", chosen_seq=2),
                            "还没有评价得分"))
    record(True, expect_err(lambda: call("conclude", dec_no="DC-003", chosen_seq=2,
                                         rationale="哪怕给了依据也不行"),
                            "还没有评价得分"))
    record(True, expect_err(lambda: call("conclude", dec_no="DC-003", chosen_seq=9),
                            "没有序号为 9 的备选方案"))

    step("TC-24 BR-08 得分 0 是**有效的分**（与「未打分」不是一回事）")
    call("create", topic="同分与零分议题", eval_method="ahp", owner="周八")
    call("add_criterion", dec_no="DC-007", criterion="风险", weight=1)
    call("add_option", dec_no="DC-007", name="零分方案")
    call("add_option", dec_no="DC-007", name="满分方案")
    call("start", dec_no="DC-007")
    r24 = call("score_option", dec_no="DC-007", seq=1, score=0)
    record(r24["options"][0]["score"] == 0 and r24["scored_total"] == 1
           and r24["top_seq"] == 1 and r24["top_score"] == 0,
           f"score=0 落库为 0（top_seq={r24['top_seq']}），scored_total=1")
    r24b = call("score_option", dec_no="DC-007", seq=2, score=100)
    record(r24b["top_seq"] == 2 and r24b["top_score"] == 100, "100 分 → top 切到 seq=2")

    step("TC-25 BR-04 选中非最高分方案必须给出依据（材料 §6.8.1.2.5）")
    record(True, expect_err(lambda: call("conclude", dec_no="DC-007", chosen_seq=1),
                            "必须给出依据"))
    record(True, expect_err(lambda: call("conclude", dec_no="DC-007", chosen_seq=1,
                                         rationale="   "), "必须给出依据"))
    still = call("get", dec_no="DC-007")
    record(still["status"] == "weighing" and still["chosen_seq"] is None,
           "被拒后仍是权衡中、未写选中方案（无副作用）")
    # 选**最高分**方案则依据选填（对照：DC-001 的 TC-08 已证）
    same = call("score_option", dec_no="DC-006", seq=1, score=80, note="复核维持 80")
    call("add_option", dec_no="DC-006", name="备选方案（同分）")
    tie = call("score_option", dec_no="DC-006", seq=2, score=80)
    record(tie["top_seq"] == 1 and tie["top_score"] == 80,
           "同分时 top_seq 取序号小者（口径唯一）")

    step("TC-26 BR-05 编号唯一且不可变（update 字段白名单里没有编号）")
    r26 = call("update", dec_no="DC-004", topic="地面站部署方式（改名）")
    record(r26["dec_no"] == "DC-004" and r26["topic"] == "地面站部署方式（改名）",
           "编号不可改，议题可改")

    step("TC-27 BR-06 已决策后内容冻结（改 / 加准则 / 加方案 / 打分全拒）")
    record(True, expect_err(lambda: call("update", dec_no="DC-002", topic="偷改"),
                            "已作出决策"))
    record(True, expect_err(lambda: call("add_criterion", dec_no="DC-002", criterion="补一条"),
                            "已作出决策"))
    record(True, expect_err(lambda: call("add_option", dec_no="DC-002", name="补一个方案"),
                            "已作出决策"))
    record(True, expect_err(lambda: call("score_option", dec_no="DC-002", seq=1, score=99),
                            "已作出决策"))
    record(True, expect_err(lambda: call("start", dec_no="DC-002"),
                            "不能回到权衡中"))
    record(True, expect_err(lambda: call("conclude", dec_no="DC-002", chosen_seq=1),
                            "不能重复决策"))
    record(True, expect_err(lambda: call("implement", dec_no="DC-003"),
                            "只有已决策的议题才能实施"))

    step("TC-28 BR-06 已实施为硬终态（改 / 加 / 打分 / 决策 / 启动 / 再实施全拒）")
    record(True, expect_err(lambda: call("update", dec_no="DC-001", topic="偷改"),
                            "已实施（终态）"))
    record(True, expect_err(lambda: call("add_criterion", dec_no="DC-001", criterion="补一条"),
                            "已实施（终态）"))
    record(True, expect_err(lambda: call("add_option", dec_no="DC-001", name="补一个"),
                            "已实施（终态）"))
    record(True, expect_err(lambda: call("score_option", dec_no="DC-001", seq=1, score=1),
                            "已实施（终态）"))
    record(True, expect_err(lambda: call("conclude", dec_no="DC-001", chosen_seq=1),
                            "已实施（终态）"))
    record(True, expect_err(lambda: call("start", dec_no="DC-001"), "已实施（终态）"))
    record(True, expect_err(lambda: call("implement", dec_no="DC-001"),
                            "已经是实施状态"))

    step("TC-29 BR-07 评价方法受字典约束（创建 / 修改两处）")
    record(True, expect_err(lambda: call("create", topic="x", eval_method="其它"),
                            "评价方法只能是"))
    record(True, expect_err(lambda: call("create", topic="x", eval_method="  "),
                            "评价方法不能为空"))
    record(True, expect_err(lambda: call("update", dec_no="DC-004", eval_method="expert"),
                            "评价方法只能是"))
    record(call("update", dec_no="DC-005", eval_method="borda")["eval_method"] == "borda",
           "字典内的方法可改（borda）")

    step("TC-30 BR-08 得分 / 权重取值口径")
    record(True, expect_err(lambda: call("score_option", dec_no="DC-003", seq=1, score="八十"),
                            "评价得分必须是 0~100 的整数"))
    record(True, expect_err(lambda: call("score_option", dec_no="DC-003", seq=1, score=101),
                            "评价得分必须是 0~100 的整数"))
    record(True, expect_err(lambda: call("score_option", dec_no="DC-003", seq=1, score=-5),
                            "评价得分必须是 0~100 的整数"))
    record(True, expect_err(lambda: call("add_criterion", dec_no="DC-004", criterion="x",
                                         weight=0), "准则权重必须大于 0"))
    record(True, expect_err(lambda: call("add_criterion", dec_no="DC-004", criterion="x",
                                         weight="二"), "准则权重必须是正整数"))

    step("TC-31 议题 / 准则名 / 方案名 / 议题改名 非空校验")
    record(True, expect_err(lambda: call("create", topic="   "), "决策议题不能为空"))
    record(True, expect_err(lambda: call("add_criterion", dec_no="DC-004", criterion="  "),
                            "评价准则不能为空"))
    record(True, expect_err(lambda: call("add_option", dec_no="DC-004", name="  "),
                            "备选方案名称不能为空"))
    record(True, expect_err(lambda: call("update", dec_no="DC-004", topic="  "),
                            "决策议题不能为空"))

    step("TC-32 提出态不能直接决策 / 打分（须先启动权衡）")
    record(True, expect_err(lambda: call("conclude", dec_no="DC-004", chosen_seq=1),
                            "须先启动权衡"))
    record(True, expect_err(lambda: call("score_option", dec_no="DC-004", seq=1, score=80),
                            "须先启动权衡"))
    record(True, expect_err(lambda: call("conclude", dec_no="DC-005", chosen_seq=1),
                            "须先启动权衡"))

    step("TC-33 序号非法 / 不存在（守卫顺序：状态 → 序号格式 → 存在性）")
    # ⚠ 序号校验在**状态守卫之后**，故这些负例都拿「权衡中」的 DC-003 跑
    record(True, expect_err(lambda: call("score_option", dec_no="DC-003", seq="一", score=1),
                            "备选方案序号必须是正整数"))
    record(True, expect_err(lambda: call("score_option", dec_no="DC-003", seq=0, score=1),
                            "备选方案序号必须大于 0"))
    record(True, expect_err(lambda: call("score_option", dec_no="DC-003", seq=9, score=1),
                            "没有序号为 9 的备选方案"))
    record(True, expect_err(lambda: call("conclude", dec_no="DC-003", chosen_seq="甲"),
                            "备选方案序号必须是正整数"))

    step("TC-34 重复状态动作（守卫顺序逐条对齐）")
    record(True, expect_err(lambda: call("start", dec_no="DC-003"), "已经处于权衡中"))
    record(True, expect_err(lambda: call("implement", dec_no="DC-006"),
                            "只有已决策的议题才能实施"))
    # ⚠ DC-006 是「权衡中」：再启动会撞「已经处于权衡中」，再决策则因只有 2 个方案已可决策
    #   —— 故这里只断「不能从权衡中直接实施」
    record(True, expect_err(lambda: call("start", dec_no="DC-006"), "已经处于权衡中"))

    step("TC-35 编号为空 / 不存在 → 拒绝")
    record(True, expect_err(lambda: call("start", dec_no=""), "决策编号不能为空"))
    record(True, expect_err(lambda: call("update", dec_no="  ", topic="x"),
                            "决策编号不能为空"))
    record(True, expect_err(lambda: call("add_option", dec_no="DC-999", name="x"), "不存在"))
    record(True, expect_err(lambda: call("add_criterion", dec_no="DC-999", criterion="x"),
                            "不存在"))
    record(True, expect_err(lambda: call("start", dec_no="DC-999"), "不存在"))
    record(True, expect_err(lambda: call("score_option", dec_no="DC-999", seq=1, score=1),
                            "不存在"))
    record(True, expect_err(lambda: call("conclude", dec_no="DC-999", chosen_seq=1),
                            "不存在"))
    record(True, expect_err(lambda: call("implement", dec_no="DC-999"), "不存在"))

    step("TC-36 无内容修改 → 拒绝")
    record(True, expect_err(lambda: call("update", dec_no="DC-004"), "没有要修改的内容"))

    step("TC-37 列表筛选（评价方法 / 状态 / 责任人）")
    # ⚠ 期望值按**实际动作序列**重算（同源用例最易错的一处）：
    #   DC-001 已实施 / DC-002 已决策 / DC-003・006・007 权衡中 / DC-004・005 提出
    #   评价方法：DC-001 缺省 weighted_matrix / DC-002 trade_study / DC-003 cost_benefit /
    #            DC-004 weighted_matrix / DC-005 被 TC-29 改成 borda / DC-006 decision_tree / DC-007 ahp
    by_method = call("list", eval_method="trade_study")
    record(by_method["total"] == 1 and by_method["items"][0]["dec_no"] == "DC-002",
           f"method=trade_study -> {by_method['total']} 条")
    by_default = call("list", eval_method="weighted_matrix")
    record(by_default["total"] == 2
           and [x["dec_no"] for x in by_default["items"]]
           == ["DC-001", "DC-004"],
           f"method=weighted_matrix（含缺省取值）-> {by_default['total']} 条")
    by_status = call("list", status="weighing")
    record(by_status["total"] == 3
           and [x["dec_no"] for x in by_status["items"]]
           == ["DC-003", "DC-006", "DC-007"],
           f"status=weighing -> {by_status['total']} 条")
    by_impl = call("list", status="implemented")
    record(by_impl["total"] == 1 and by_impl["items"][0]["dec_no"] == "DC-001",
           f"status=implemented -> {by_impl['total']} 条")
    by_owner = call("list", owner="王五")
    record(by_owner["total"] == 1 and by_owner["items"][0]["dec_no"] == "DC-003",
           f"owner=王五 -> {by_owner['total']} 条")
    blank = call("list", status="  ", owner="")
    record(blank["total"] == 7, f"空白筛选条件被忽略 -> {blank['total']} 条")

    step("TC-38 决策与它的两条子表都**不删除**（历史可追溯）")
    trace = call("get", dec_no="DC-001")
    record(trace["status"] == "implemented" and len(trace["criteria"]) == 2
           and len(trace["options"]) == 2 and trace["options"][1]["score"] == 88
           and trace["chosen_name"] == "方案B：货架产品",
           "已实施后准则 / 方案 / 得分 / 选中方案仍在（同事务子表，不级联删）")

    # ── 汇总 ─────────────────────────────────────────────
    bad = [r for r in RESULTS if not r[0]]
    print(f"\n{'='*60}")
    print(f"  用例 {len(RESULTS)} 项 · 通过 {len(RESULTS)-len(bad)} · 失败 {len(bad)}")
    print(f"  {'VERIFY_RESULT: PASS' if not bad else 'VERIFY_RESULT: FAIL'}")
    for ok, note in bad:
        print(f"    [X] {note}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
