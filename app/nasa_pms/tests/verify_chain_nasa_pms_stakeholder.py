"""FDE v2 后端主链端到端验证 · nasa_pms（利益相关者 stakeholder · 主数据）

链路形态（**单应用、无状态机、无跨应用调用**，含**一张聚合内子表**与两处语义枢纽）：
  stakeholder(upsert ×N → add_expectation ×N → update_expectation(冻结/解锁))      <- 主链
    · BR-01 编号由**外部来源给定**、落库不可变、upsert 幂等（**没有 create**）
    · BR-02 名称必填
    · BR-03 类型受字典约束（客户 / 承包商 / 内部组织）
    · BR-04 期望必须挂在本聚合内（卡片 I-1）—— 无独立标识、无孤儿期望、**无跨相关方汇总**
    · BR-05 期望的陈述 / 类别 / 来源必填，类别受字典约束
    · BR-06 类别为「度量有效性（MOE）」的期望必须给出度量口径
    · BR-07 已获承诺的期望冻结（**可解锁**：撤回承诺后即可改写）
    · BR-08 upsert 的部分更新语义（None = 不改 / 空串 = 清空）
  形态断言（主数据的"没有"也是规格）：
    · **没有 create** / **没有 delete** —— 服务不存在（不是"调了报错"）
    · **没有状态机** —— 表里没有 status 列、服务里没有流转服务
    · **没有跨应用调用** —— 本应用不发 self.fde.call（卡片 11「跨应用调用：无」）

隔离：`shadow_dbs()` —— 业务库**复制**到临时目录，测试全程只读写副本，
**真库零字节接触，且不用停 dev server**。`shadow_clear(GROUP)` 清的是副本。

运行：python app/nasa_pms/tests/verify_chain_nasa_pms_stakeholder.py
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
APP = "stakeholder"

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


def err_kind(fn):
    """返回 (异常类型名, 消息) —— 用于区分「业务校验(FdeError)」与「契约层(TypeError)」。"""
    try:
        fn()
    except Exception as e:                                          # noqa: BLE001
        return type(e).__name__, str(e)
    return None, ""


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
    step("TC-01 同步一条相关方（upsert 新增：编号由外部来源给定，本系统不生成）")
    r1 = call("upsert", sh_no="SH-001", name="航天科技集团", sh_type="customer",
              duty="用户方", org="航天科技集团", contact="张工 138****",
              project_no="P-2026-01")
    record(r1["sh_no"] == "SH-001" and r1["name"] == "航天科技集团"
           and r1["sh_type"] == "customer" and r1["duty"] == "用户方"
           and r1["org"] == "航天科技集团" and r1["project_no"] == "P-2026-01"
           and r1["expectations"] == [] and r1["expectation_total"] == 0
           and r1["committed_total"] == 0,
           f"sh_no={r1['sh_no']} sh_type={r1['sh_type']} 期望 {r1['expectation_total']}")

    step("TC-02 幂等：同一编号再次同步 = 更新而非新增（BR-01）")
    r2 = call("upsert", sh_no="SH-001", name="航天科技集团（更名）", sh_type="customer")
    lst2 = call("list")
    record(r2["sh_no"] == "SH-001" and r2["name"] == "航天科技集团（更名）"
           and lst2["total"] == 1,
           f"名称已更新={r2['name']} 总数仍为 {lst2['total']}（未产生第二条）")

    step("TC-03 BR-08 部分更新语义：不传的字段**不改**、空串才**清空**")
    record(r2["duty"] == "用户方" and r2["org"] == "航天科技集团"
           and r2["contact"] == "张工 138****" and r2["project_no"] == "P-2026-01",
           f"未传的四个选填字段全部保留：duty={r2['duty']} contact={r2['contact']}")
    r3 = call("upsert", sh_no="SH-001", name="航天科技集团", sh_type="customer",
              contact="")
    record(r3["contact"] == "" and r3["org"] == "航天科技集团" and r3["duty"] == "用户方",
           f"contact 传空串已清空（{r3['contact']!r}），未传的 duty / org 不受影响")

    step("TC-04 类型的三个字典值都能落（客户 / 承包商 / 内部组织）")
    r4a = call("upsert", sh_no="SH-002", name="星辰电子", sh_type="contractor",
               duty="分系统承制", org="星辰电子")
    r4b = call("upsert", sh_no="SH-003", name="总体设计部", sh_type="internal_org",
               duty="总体设计")
    r4c = call("upsert", sh_no="SH-004", name="深空探测中心", sh_type="customer",
               duty="用户方", project_no="P-2026-01")
    record(r4a["sh_type"] == "contractor" and r4b["sh_type"] == "internal_org"
           and r4c["sh_type"] == "customer",
           f"SH-002={r4a['sh_type']} / SH-003={r4b['sh_type']} / SH-004={r4c['sh_type']}")

    step("TC-05 登记期望（聚合内子表：序号本相关方内递增，无独立标识 —— 卡片 I-1）")
    e1 = call("add_expectation", sh_no="SH-001", statement="全任务周期内可靠运行",
              kind="need", source="访谈")
    record(e1["expectation_total"] == 1 and e1["expectations"][0]["seq"] == 1
           and e1["expectations"][0]["kind"] == "need"
           and e1["expectations"][0]["source"] == "访谈"
           and e1["expectations"][0]["committed"] == 0,
           f"seq={e1['expectations'][0]['seq']} kind={e1['expectations'][0]['kind']} "
           "committed=0（缺省未承诺）")
    e2 = call("add_expectation", sh_no="SH-001", statement="2026 年内完成首飞",
              kind="goal", source="SOW")
    record(e2["expectation_total"] == 2 and [x["seq"] for x in e2["expectations"]] == [1, 2],
           f"第二条 seq=2（本相关方内递增）：{[x['seq'] for x in e2['expectations']]}")

    step("TC-06 MOE 类期望带度量口径，并标记已获承诺（材料 §4.1.1.2.6 / §4.1.1.2.8）")
    e3 = call("add_expectation", sh_no="SH-001", statement="数据交付完整率",
              kind="moe", source="SOW", moe=">= 99.9%", committed=True,
              note="已列入验证计划")
    exp3 = e3["expectations"][2]
    record(e3["expectation_total"] == 3 and e3["committed_total"] == 1
           and exp3["seq"] == 3 and exp3["moe"] == ">= 99.9%" and exp3["committed"] == 1,
           f"expectation_total={e3['expectation_total']} committed_total={e3['committed_total']} "
           f"moe={exp3['moe']}")
    call("add_expectation", sh_no="SH-002", statement="单机功耗不高于 45W",
         kind="objective", source="承包商会议")

    step("TC-07 期望随相关方一起返回（get 一次带回，无独立台账 —— 卡片 I-1）")
    g = call("get", sh_no="SH-001")
    record([x["seq"] for x in g["expectations"]] == [1, 2, 3]
           and g["expectations"][0]["statement"] == "全任务周期内可靠运行",
           "期望清单按 seq 升序随 get 返回（3 条）")

    step("TC-08 list 与 get 同字段口径（主档字段逐项对齐 + 两个派生计数）")
    items = call("list")["items"]
    row = [x for x in items if x["sh_no"] == "SH-001"][0]
    record(set(row.keys()) == set(g.keys()) - {"expectations"},
           f"list 行字段数={len(row)} / get 主档字段数={len(g) - 1}")
    record(row["expectation_total"] == 3 and row["committed_total"] == 1,
           f"expectation_total={row['expectation_total']} committed_total={row['committed_total']}")

    step("TC-09 列表缺省：全部、按编号升序（分页契约 {items,total}）")
    lst = call("list")
    record(lst.get("total") == 4 and [x["sh_no"] for x in lst["items"]]
           == ["SH-001", "SH-002", "SH-003", "SH-004"],
           f"total={lst.get('total')} items={[x['sh_no'] for x in lst['items']]}")

    step("TC-10 分页（size=2）")
    paged = call("list", page=1, size=2)
    record(len(paged["items"]) == 2 and paged["total"] == 4,
           f"本页 {len(paged['items'])} 条 / 共 {paged['total']} 条")

    step("TC-11 get 未命中不抛异常（供跨应用探测式调用）")
    # 对照断言（T2 门禁：本步不能只证明「没抛异常」）—— 未命中**不产生副作用**：
    _before = call("list")["total"]
    record(call("get", sh_no="SH-999") is None, "返回 None")
    record(call("list")["total"] == _before,
           f"未命中不产生副作用：列表仍 {_before} 条")
    record(call("get", sh_no="  ") is None, "编号空白 → 返回 None，不抛异常")

    # ── BR-07：承诺冻结与解锁（本聚合的语义枢纽） ──────────
    step("TC-12 BR-07 已获承诺的期望：口径字段不可改写")
    record(True, expect_err(lambda: call("update_expectation", sh_no="SH-001", seq=3,
                                        statement="改成别的"),
                            "已获相关方承诺"))
    record(True, expect_err(lambda: call("update_expectation", sh_no="SH-001", seq=3,
                                        kind="goal"),
                            "不可改写"))
    record(True, expect_err(lambda: call("update_expectation", sh_no="SH-001", seq=3,
                                        moe=">= 99%"),
                            "不可改写"))

    step("TC-13 BR-07 `note` 不受冻结影响（承诺之后还要能留痕）")
    r13 = call("update_expectation", sh_no="SH-001", seq=3, note="已列入验证计划 V-007")
    record(r13["expectations"][2]["note"] == "已列入验证计划 V-007"
           and r13["expectations"][2]["statement"] == "数据交付完整率",
           f"note={r13['expectations'][2]['note']}（陈述未被改动）")

    step("TC-14 BR-07 冻结**可解锁**：撤回承诺（committed=0）后即可改写")
    r14 = call("update_expectation", sh_no="SH-001", seq=3, committed=0)
    record(r14["expectations"][2]["committed"] == 0 and r14["committed_total"] == 0,
           f"committed={r14['expectations'][2]['committed']} committed_total="
           f"{r14['committed_total']}")
    r15 = call("update_expectation", sh_no="SH-001", seq=3, statement="数据交付完整率（修订）")
    record(r15["expectations"][2]["statement"] == "数据交付完整率（修订）",
           "撤回后陈述可改")

    step("TC-15 BR-07 撤回与改写允许在**同一次调用**完成（前端「取消勾选即刻解锁」落的就是这条）")
    call("update_expectation", sh_no="SH-001", seq=3, committed=1)
    r16 = call("update_expectation", sh_no="SH-001", seq=3, committed=0,
               statement="数据交付完整率（再次修订）", note="撤回后重谈")
    exp3 = r16["expectations"][2]
    record(exp3["committed"] == 0 and exp3["statement"] == "数据交付完整率（再次修订）"
           and exp3["note"] == "撤回后重谈",
           f"committed={exp3['committed']} statement={exp3['statement']}")
    call("update_expectation", sh_no="SH-001", seq=3, committed=1)

    step("TC-16 承诺标记的归一与非法值拒绝")
    r17 = call("update_expectation", sh_no="SH-002", seq=1, committed="yes")
    record(r17["expectations"][0]["committed"] == 1, "字符串 'yes' → 1")
    record(True, expect_err(lambda: call("update_expectation", sh_no="SH-002", seq=1,
                                        committed="也许"),
                            "只能是 true / false"))
    r17b = call("update_expectation", sh_no="SH-002", seq=1, committed=False)
    record(r17b["expectations"][0]["committed"] == 0, "布尔 False → 0")

    # ── BR 逐条（负例） ──────────────────────────────────
    step("TC-30 BR-01 编号必填、不存在则新增（同编号永不多出一条）")
    record(True, expect_err(lambda: call("upsert", sh_no="   ", name="无名", sh_type="customer"),
                            "利益相关者编号不能为空"))
    record(True, expect_err(lambda: call("upsert", sh_no="", name="无名", sh_type="customer"),
                            "利益相关者编号不能为空"))
    record(True, expect_err(lambda: call("upsert", sh_no=None, name="无名",
                                        sh_type="customer"),
                            "利益相关者编号不能为空"))
    before = call("list")["total"]
    call("upsert", sh_no="SH-001", name="航天科技集团", sh_type="customer", duty="用户方")
    record(call("list")["total"] == before,
           f"再次同步 SH-001 后总数仍为 {before}（upsert 幂等，不产生第二条）")

    step("TC-31 BR-02 名称必填（空白字符串也要拦下 —— 先 _clean 再 check）")
    record(True, expect_err(lambda: call("upsert", sh_no="SH-900", name="   ",
                                        sh_type="customer"), "利益相关者名称不能为空"))
    record(True, expect_err(lambda: call("upsert", sh_no="SH-900", name=None,
                                        sh_type="customer"), "利益相关者名称不能为空"))

    step("TC-32 BR-03 类型必填且受字典约束")
    record(True, expect_err(lambda: call("upsert", sh_no="SH-900", name="x", sh_type="  "),
                            "相关方类型不能为空"))
    record(True, expect_err(lambda: call("upsert", sh_no="SH-900", name="x", sh_type="partner"),
                            "相关方类型只能是"))
    record(call("get", sh_no="SH-900") is None,
           "三次被拒的 upsert 未落库（get SH-900 仍为 None）")

    step("TC-33 BR-04（卡片 I-1）期望必须挂在本聚合内：相关方不存在则拒绝")
    record(True, expect_err(lambda: call("add_expectation", sh_no="SH-999", statement="x",
                                        kind="goal", source="访谈"),
                            "期望必须挂在本聚合内"))
    record(True, expect_err(lambda: call("add_expectation", sh_no="   ", statement="x",
                                        kind="goal", source="访谈"),
                            "利益相关者编号不能为空"))
    record(True, expect_err(lambda: call("update_expectation", sh_no="SH-999", seq=1,
                                        note="x"), "不存在"))

    step("TC-34 BR-05 期望的陈述 / 类别 / 来源必填，类别受字典约束")
    record(True, expect_err(lambda: call("add_expectation", sh_no="SH-003", statement="   ",
                                        kind="goal", source="访谈"), "期望陈述不能为空"))
    record(True, expect_err(lambda: call("add_expectation", sh_no="SH-003", statement="x",
                                        kind="", source="访谈"), "期望类别不能为空"))
    record(True, expect_err(lambda: call("add_expectation", sh_no="SH-003", statement="x",
                                        kind="wish", source="访谈"), "期望类别只能是"))
    record(True, expect_err(lambda: call("add_expectation", sh_no="SH-003", statement="x",
                                        kind="goal", source="  "), "期望来源不能为空"))
    record(call("get", sh_no="SH-003")["expectation_total"] == 0,
           "四条被拒的 add_expectation 一条都没落库（SH-003 期望数仍为 0）")

    step("TC-35 BR-06 类别为 MOE 时度量口径必填（add 与 update 两条路都要拦）")
    record(True, expect_err(lambda: call("add_expectation", sh_no="SH-003", statement="x",
                                        kind="moe", source="访谈", moe="  "),
                            "必须填写度量口径"))
    ok25 = call("add_expectation", sh_no="SH-003", statement="环控温控裕度",
                kind="goal", source="访谈")
    record(ok25["expectation_total"] == 1, "非 MOE 类别不要求口径（goal 落库成功）")
    record(True, expect_err(lambda: call("update_expectation", sh_no="SH-003", seq=1,
                                        kind="moe"),
                            "必须填写度量口径"))
    ok25b = call("update_expectation", sh_no="SH-003", seq=1, kind="moe", moe=">= 5K")
    record(ok25b["expectations"][0]["kind"] == "moe"
           and ok25b["expectations"][0]["moe"] == ">= 5K",
           "同一次调用里把类别改成 moe 并带上口径 → 接受（BR-06 判的是**合并后**的口径）")

    step("TC-36 BR-04 期望序号必须是正整数且必须命中本相关方的期望")
    record(True, expect_err(lambda: call("update_expectation", sh_no="SH-003", seq="  ",
                                        note="x"), "期望序号不能为空"))
    record(True, expect_err(lambda: call("update_expectation", sh_no="SH-003", seq="abc",
                                        note="x"), "期望序号必须是正整数"))
    record(True, expect_err(lambda: call("update_expectation", sh_no="SH-003", seq=0,
                                        note="x"), "期望序号必须是正整数"))
    record(True, expect_err(lambda: call("update_expectation", sh_no="SH-003", seq=9,
                                        note="x"), "没有序号为 9 的期望"))
    record(call("update_expectation", sh_no="SH-002", seq=1,
                note="跨相关方的同号期望互不影响")["expectations"][0]["note"]
           == "跨相关方的同号期望互不影响",
           "SH-002 的 seq=1 与 SH-003 的 seq=1 互不影响（序号只在相关方内唯一）")

    step("TC-37 无内容修改 → 拒绝；update 的字段白名单里没有编号")
    record(True, expect_err(lambda: call("update_expectation", sh_no="SH-003", seq=1),
                            "没有要修改的内容"))
    # upsert 就是主档的唯一写入口，没有"改名换号"的口子：编号只能原样回来
    r27 = call("upsert", sh_no="SH-003", name="总体设计部（更名）", sh_type="internal_org")
    record(r27["sh_no"] == "SH-003", "编号不可变（落库的仍是 SH-003）")

    step("TC-38 缺传必填参数 → 走契约层（系统错误），负例只能传空白")
    kind28, _ = err_kind(lambda: call("upsert", sh_no="SH-901"))
    record(kind28 == "TypeError", f"缺传 name / sh_type → {kind28}（走契约层，非业务校验）")
    kind28b, _ = err_kind(lambda: call("add_expectation", sh_no="SH-001", statement="x"))
    record(kind28b == "TypeError", f"缺传 kind / source → {kind28b}（走契约层）")

    step("TC-39 主数据形态：**没有 create / 没有 delete / 没有状态流转服务**")
    for svc in ("create", "delete", "remove", "obsolete", "archive", "close", "update_status"):
        kind29, msg29 = err_kind(lambda s=svc: call(s, sh_no="SH-001"))
        record(kind29 == "FdeError" and "无此服务" in msg29,
               f"{svc} 不存在 → {msg29.split('：')[-1]}")
    # 状态机的"没有"落在两个可观测事实上：GET 里没有 status 字段、表里没有 status 列
    record("status" not in call("get", sh_no="SH-001"),
           "get 返回里**没有** status 字段（主数据无状态机 —— 卡片 11）")
    from fde_platform import db as _db
    from fde_platform import ddl as _ddl
    conn = _db.get_connection(qname, pf._apps[qname].db_path)
    # ⚠ 别用 `PRAGMA table_info(...)` 查列：那是 **SQLite 专属**，PG 上直接语法错
    #   （2026-09-27 在测试服务器上用克隆库跑这一片时撞到：`syntax error at or near "PRAGMA"`）。
    #   改用平台的**方言感知内省**（sqlite 走 PRAGMA、PG 走 information_schema）——
    #   与 `ddl.reconcile_columns` 用的是同一个函数，两边口径也就一致了。
    cols = sorted(_ddl._existing_columns(conn, "stakeholder", _db.dialect_of(conn)))
    record("status" not in cols and "sh_no" in cols,
           f"stakeholder 表列={cols} —— 无 status 列")

    step("TC-40 查询筛选（类型精确 / 关键字跨字段模糊 / 所属项目）")
    by_type = call("list", sh_type="customer")
    record(by_type["total"] == 2 and [x["sh_no"] for x in by_type["items"]]
           == ["SH-001", "SH-004"], f"sh_type=customer → {by_type['total']} 条")
    by_org = call("list", keyword="星辰")
    record(by_org["total"] == 1 and by_org["items"][0]["sh_no"] == "SH-002",
           f"keyword=星辰（命中所属机构）→ {by_org['total']} 条")
    by_duty = call("list", keyword="总体设计")
    record(by_duty["total"] == 1 and by_duty["items"][0]["sh_no"] == "SH-003",
           f"keyword=总体设计（命中职责）→ {by_duty['total']} 条")
    by_kw_no = call("list", keyword="SH-00")
    record(by_kw_no["total"] == 4, f"keyword=SH-00（命中编号）→ {by_kw_no['total']} 条")
    by_proj = call("list", project_no="P-2026-01")
    record(by_proj["total"] == 2, f"project_no=P-2026-01 → {by_proj['total']} 条")
    by_none = call("list", sh_type="   ")
    record(by_none["total"] == 4, "空白筛选值 = 不过滤（先 _clean 再拼 WHERE）")
    empty = call("list", keyword="不存在的字串")
    record(empty["total"] == 0 and empty["items"] == [], "无命中 → 空列表（不报错）")

    step("TC-41 被同步过的相关方与期望**都还在**（没有 delete，也就不会级联消失）")
    g31 = call("get", sh_no="SH-001")
    record(g31["sh_no"] == "SH-001" and g31["expectation_total"] == 3,
           f"SH-001 仍在，期望 {g31['expectation_total']} 条（含已承诺的 1 条）")

    step("TC-42 本应用不发任何跨应用调用（卡片 11「跨应用调用：无」）")
    src = (ROOT / "app" / GROUP / APP / f"{APP}.py").read_text(encoding="utf-8")
    record(src.count("self.fde.call") == 0,
           "源码里 self.fde.call 出现 0 次 —— 期望的「来源」是**字段**（source），不是跨应用引用")

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
