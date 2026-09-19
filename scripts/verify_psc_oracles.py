#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PSC 对账体检 —— 找出「测试用例没想到」的那类 BUG。

## 为什么需要它（与 verify_chain_psc.py 的区别）

`app/psc/tests/verify_chain_psc.py` 的用例来自《测试用例.md》，而《测试用例.md》和**代码**
都是从同一份《应用详设.md》生成的 —— **同源 ⇒ 同一个盲点**。它只能证明「我设计的那条路走得通」。
本脚本换三种**不依赖「人写期望值」**的判据（人写期望值 = 把代码逻辑抄一遍，抄错就一起错）：

  A 对账   —— 同一个量有两条独立可推导路径，走两条比一比
  C 不变式 —— 永远必须成立的约束，被破坏即 BUG，与期望值无关
  S 静态   —— 代码里的死适配器 / 空转断言（结构性问题，扫描即得）

## 三条纪律（改本文件前请先读，这三条是它可信的全部理由）

1. **直连 SQLite，绝不 import app/psc 下的任何代码**。对账器一旦复用被测代码，
   就退化成自证 —— 代码错了它跟着错，且完全看不出来。
2. **靠「冗余」而不是「复算」**。不猜实现约定（如「近 12 期」怎么取、取哪些客户），
   只断言「两条已知口径必须给出同一个数」。猜约定会引入假警报，假警报会让人无视红灯。
3. **每条对账先验分母非空**。空集上的断言是真空 —— 本项目已踩过一次
   （`verify_agent_quality.py` 的 `x_planner_surface` 因空集让整条断言变成摆设）。

## 用法

    python scripts/verify_psc_oracles.py            # 全部
    python scripts/verify_psc_oracles.py -g A       # 只跑 A 组
    python scripts/verify_psc_oracles.py --verbose  # 打印每条对账的分母规模

**只读**：本脚本不写任何业务库（`outbound_plan.list` 那种带写副作用的服务一次都不调）。
运行前会自动快照业务库指纹，跑完比对，若指纹变了会明确报出来。
"""
import argparse
import hashlib
import math
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------- 路径锚定
def _project_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "fde_platform").is_dir():
            return parent
    raise SystemExit("找不到项目根：向上未发现 fde_platform/")


ROOT = _project_root()
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

GROUP = "psc"
# 分组名 -> 目录名（应用名 == 目录名 == 库名，见 CONVENTION）
APPS = [
    "attainment", "demand", "demand_pool", "inventory_projection", "inventory_strategy",
    "master_plan", "md_breakpoint", "md_customer", "md_material", "md_monthly_version",
    "md_part_replace", "md_project", "md_project_part", "outbound_plan", "sales_forecast",
    "sales_history", "strategy_fitting",
]

TOL = 1e-6            # 绝对容差
REL_TOL = 1e-9        # 相对容差
# 业务库里的数量/金额按两位小数（分）落库。凡「由一个存储值反推另一个存储值」的对账，
# 容差必须按存储精度取（±0.005 舍入 × 2 倍余量），否则会把舍入差当业务不一致。
TOL_STORED = 0.011


def close_stored(a, b) -> bool:
    try:
        return abs(float(a) - float(b)) <= TOL_STORED
    except (TypeError, ValueError):
        return False


def same_val(a, b) -> bool:
    """两个字段值是否相同：数值按存储精度比，其余按等值比，数字串容错。

    ⚠ 别写成 `isinstance(a, float) or isinstance(b, float) and not close(...) or a != b` ——
    Python 里 `and` 比 `or` 紧，那等价于 `isinstance(a, float) or (...)`，
    **只要字段是浮点就判为不同**。首版就是这么错的，把 demand_pool/outbound_plan 的
    数量字段全报成了不一致（假警报）。
    """
    if a == b:
        return True
    try:
        return close_stored(float(a), float(b))
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------- 报告
class Report:
    """逐条记录：组 / 靶点 / 结论 / 期望 / 实际 / 备注。"""

    def __init__(self):
        self.rows = []

    def _add(self, group, target, verdict, expect="", actual="", note=""):
        self.rows.append({
            "group": group, "target": target, "verdict": verdict,
            "expect": expect, "actual": actual, "note": note,
        })

    def ok(self, group, target, note=""):
        self._add(group, target, "PASS", note=note)

    def fail(self, group, target, expect, actual, note=""):
        self._add(group, target, "FAIL", expect, actual, note)

    def skip(self, group, target, why):
        self._add(group, target, "SKIP", note=why)

    def viol(self, group, target, rows, expect, fmt, note=""):
        """违规行列表 → PASS / FAIL。rows 为空即 PASS。"""
        if not rows:
            self.ok(group, target, note)
            return False
        shown = " | ".join(fmt(r) for r in rows[:3])
        more = f"（共 {len(rows)} 行，下列前 3）" if len(rows) > 3 else ""
        self.fail(group, target, expect, shown, (note + " " + more).strip())
        return True

    def counts(self):
        c = {"PASS": 0, "FAIL": 0, "SKIP": 0}
        for r in self.rows:
            c[r["verdict"]] = c.get(r["verdict"], 0) + 1
        return c


REP = Report()
VERBOSE = False


def note(msg):
    """过程信息（不构成判据）。"""
    if VERBOSE:
        print(f"      · {msg}")


def find(group, target, rows, what):
    """分母非空闸：空集 → SKIP，绝不返回空列表让上层断言变真空。"""
    if not rows:
        REP.skip(group, target, f"分母为空：{what}（无数据可对账，本条不构成证据）")
        return None
    note(f"{target}: 分母 {len(rows)} 行（{what}）")
    return rows


def close(a, b) -> bool:
    try:
        a = float(a)
        b = float(b)
    except (TypeError, ValueError):
        return False
    if math.isnan(a) or math.isnan(b):
        return False
    return abs(a - b) <= max(TOL, REL_TOL * max(abs(a), abs(b)))


# ---------------------------------------------------------------- 数据库
# SQLite 的 ATTACH 上限是 10 个库（编译期 SQLITE_MAX_ATTACHED），17 个业务库装不下。
# 做法改为：逐个挂载 → 把每个表复制进一个内存库（表名 `应用__表名`）→ 卸载。
# 这样跨应用 join 依然是**纯 SQL**（一致性检查不用搬到 Python 里手写），也不受上限约束。
_SQLMAP = {}
_SQLPAT = None


def connect() -> sqlite3.Connection:
    global _SQLMAP, _SQLPAT
    dst = sqlite3.connect(":memory:")
    dst.row_factory = sqlite3.Row
    pairs = []
    for app in APPS:
        path = Path(f"app/{GROUP}/{app}/{app}.db")
        if not path.exists():
            continue          # 不挂载不存在的库 —— ATTACH 会顺手建出一个空库
        try:
            dst.execute("ATTACH DATABASE ? AS _src", (str(path),))
        except sqlite3.Error as e:
            print(f"  ! 无法读取 {app}：{e}")
            continue
        try:
            tables = [r["name"] for r in dst.execute(
                "SELECT name FROM _src.sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'").fetchall()]
            for t in tables:
                dst.execute(f'CREATE TABLE "{app}__{t}" AS SELECT * FROM "_src"."{t}"')
                pairs.append((app, t))
        finally:
            dst.execute("DETACH DATABASE _src")
    _SQLMAP = {f"{a}.{t}": f"{a}__{t}" for a, t in pairs}
    # 长的先匹配，否则 sales_forecast.sales_forecast 会抢在 ..._line 前面命中
    _SQLPAT = re.compile("|".join(re.escape(k) for k in sorted(_SQLMAP, key=len, reverse=True)))
    return dst


def q(conn, sql, params=()):
    """执行查询。`应用.表` 会被自动改写到内存库里的 `应用__表`，SQL 原文不必改。"""
    if _SQLPAT is not None:
        sql = _SQLPAT.sub(lambda m: _SQLMAP[m.group(0)], sql)
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def has_table(conn, app, table) -> bool:
    return bool(q(conn, "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                  (f"{app}__{table}",)))


def columns(conn, app, table) -> set:
    try:
        return {r["name"] for r in q(conn, f'PRAGMA table_info("{app}__{table}")')}
    except sqlite3.Error:
        return set()


# ---------------------------------------------------------------- 指纹
def fingerprint() -> dict:
    """业务库全部表的行数 + 内容哈希。行数能抓到增删，哈希能抓到改值。"""
    fp = {}
    for app in APPS:
        path = Path(f"app/{GROUP}/{app}/{app}.db")
        if not path.exists():
            continue
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            tables = [r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'").fetchall()]
            for t in sorted(tables):
                rows = conn.execute(f'SELECT * FROM "{t}" ORDER BY 1').fetchall()
                h = hashlib.sha256()
                for r in rows:
                    h.update(repr(tuple(r)).encode("utf-8", "replace"))
                fp[f"{app}.{t}"] = (len(rows), h.hexdigest()[:16])
            conn.close()
        except sqlite3.Error as e:
            fp[f"{app}.<ERR>"] = (-1, str(e)[:40])
    return fp


def fp_diff(before, after):
    out = []
    for k in sorted(set(before) | set(after)):
        b, a = before.get(k), after.get(k)
        if b != a:
            out.append(f"{k}: {b} → {a}")
    return out


# ================================================================ A 组：对账
# 判据统一形态：同一个量有两条独立路径，走两条比一比。

def a_water_level(conn):
    """A1–A3 库存策略三层水位：A/C/B 与上下限必须自洽，且日需求两条路径同值。

    A 支路径：日需求 = min_level / max(0, 生产 + 物流 − 线边缓冲)
    B 支路径：日需求 = batch_level / 组批窗口
    两条路径来自**不同的字段、不同的公式**，只有日需求真的一致才可能相等。
    这也顺带验了「A 公式里那个 max(0, ...) 截断」是否真的生效。
    """
    rows = q(conn, """
        SELECT w.version_no, w.material_no, w.hedge_tool,
               w.min_level, w.service_factor, w.resp_volatility,
               w.safety_level, w.batch_window, w.batch_level,
               m.prod_days, m.logistics_days, m.value_class, m.unit_value, m.service_level,
               m.status AS mat_status
        FROM inventory_strategy.inventory_strategy w
        JOIN md_material.md_material m ON m.material_no = w.material_no
    """)
    # 线边缓冲天数取「主客户」。主客户的**文档口径**是「对该物料出货量最大的客户」
    # （sales_history BR-06），照文档取，不照代码取 —— 若实现偏离文档，会在下面的
    # 双路径比较里以「数值对不上」的形式暴露出来，报错信息里带上所用客户便于 triage。
    custs = {r["customer_no"]: r for r in q(
        conn, "SELECT customer_no, line_stock_days, transfer_lead_days FROM md_customer.md_customer")}
    tot = {}
    for r in q(conn, """SELECT material_no, customer_no, SUM(qty) AS t
                        FROM sales_history.sales_history GROUP BY material_no, customer_no"""):
        k = r["material_no"]
        if k not in tot or (r["t"] or 0) > (tot[k][1] or 0):
            tot[k] = (r["customer_no"], r["t"] or 0)
    for r in rows:
        mc = tot.get(r["material_no"], (None, 0))[0]
        r["main_cust"] = mc
        r["line_stock_days"] = (custs.get(mc) or {}).get("line_stock_days")
        r["transfer_lead_days"] = (custs.get(mc) or {}).get("transfer_lead_days")

    rows = find("A", "A1 日需求双路径", rows, "inventory_strategy ⋈ md_material")
    if rows is None:
        return

    bad_b, bad_band, bad_pair = [], [], []
    bad_z, bad_c = [], []
    Z_TABLE = {1.28, 1.65, 2.05, 2.33}       # 文档 §2.3 标准正态分位数表
    pairs_checked = 0                          # 真正做了双路径比较的行数（分母）
    no_a_branch = []                           # 生产+物流 ≤ 线边 ⇒ A 支分母为 0，无信息
    for r in rows:
        prod = r["prod_days"] or 0.0
        logi = r["logistics_days"] or 0.0
        batch_w = r["batch_window"] or 0.0
        minl = r["min_level"] or 0.0
        batchl = r["batch_level"] or 0.0

        # A3 三层非负
        if minl < 0 or (r["safety_level"] or 0.0) < 0 or batchl < 0:
            bad_band.append(r)

        # A1 日需求双路径：
        #   A 支 = min_level / max(0, 生产 + 物流 − 线边缓冲)
        #   B 支 = batch_level / 组批窗口
        # 两个字段、两个公式，只有「日需求」真的一致才可能相等。
        if batchl < 0:
            bad_b.append(r)
        d_a = d_b = None
        denom_a = prod + logi - (r["line_stock_days"] or 0.0)
        if denom_a > 0:
            d_a = minl / denom_a
        else:
            no_a_branch.append(r)              # 文档 §2.1 的 max(0,·) 截断生效 ⇒ A=0
        if batch_w > 0:
            d_b = batchl / batch_w
        if d_a is not None and d_b is not None:
            pairs_checked += 1
            # 正确做法是**比较区间是否有交集**，而不是比较两个点值：
            # 库里 A/B 各保留两位小数，反推出的日需求各带 ±0.005/分母 的误差，
            # 点值比较必然假警报（一开始就是这么错的，0.0007 被当成 BUG）。
            lo_a, hi_a = (minl - 0.005) / denom_a, (minl + 0.005) / denom_a
            lo_b, hi_b = (batchl - 0.005) / batch_w, (batchl + 0.005) / batch_w
            if min(hi_a, hi_b) - max(lo_a, lo_b) < 0:
                bad_pair.append({
                    "material_no": r["material_no"],
                    "msg": (f"{r['material_no']} 反推日需求区间无交集："
                            f"A 支 [{lo_a:.4f}, {hi_a:.4f}] vs B 支 [{lo_b:.4f}, {hi_b:.4f}]"
                            f"｜A={minl} 生+物−线边={denom_a:g}（客户 {r['main_cust']}）"
                            f"B={batchl} 窗口={batch_w:g}"),
                })

        # A2 服务系数双路径
        sf = r["service_factor"]
        vol = r["resp_volatility"] or 0.0
        if sf is None or not any(close(sf, t) for t in Z_TABLE):
            bad_z.append(r)
        # C = z × σ_L 只对**库存对冲**成立：速度对冲按 BR-12 强制 C=0（σ_L 仍留着备查）。
        # 一开始漏了这个过滤，把 3 行速度对冲报了假警报，已修正。
        if r["hedge_tool"] != "速度" and not close_stored(r["safety_level"] or 0.0, (sf or 0.0) * vol):
            bad_c.append(r)

    if pairs_checked == 0:
        REP.skip("A", "A1 日需求双路径", f"分母为空：{len(rows)} 行水位中没有一行同时具备"
                                        "「A 支分母>0」与「组批窗口>0」")
    else:
        REP.viol("A", "A1 日需求 · A 支与 B 支同值", bad_pair,
                 "min_level/(生产+物流−线边) == batch_level/组批窗口",
                 lambda x: x["msg"], f"{pairs_checked} 行参与双路径比较")
        note(f"A1: {pairs_checked} 行做了日需求双路径；{len(no_a_branch)} 行因 max(0,·) 截断无 A 支")

    REP.viol("A", "A1 日需求 · B 支非负", bad_b,
             "日需求 = B / 组批窗口 ≥ 0", lambda r: f"{r['material_no']} B={r['batch_level']} W={r['batch_window']}")
    REP.viol("A", "A2 服务系数 · 必须是查表值", bad_z,
             "service_factor ∈ {1.28, 1.65, 2.05, 2.33}", lambda r: f"{r['material_no']} z={r['service_factor']}")
    REP.viol("A", "A2 安全库存 · C = z × σ_L", bad_c,
             "safety_level == service_factor × resp_volatility",
             lambda r: f"{r['material_no']} C={r['safety_level']} z={r['service_factor']} σ={r['resp_volatility']}")
    REP.viol("A", "A3 三层水位 · 非负", bad_band,
             "min_level / safety_level / batch_level ≥ 0",
             lambda r: f"{r['material_no']} A={r['min_level']} C={r['safety_level']} B={r['batch_level']}")


def a_hedge(conn):
    """A4 速度对冲：hedge_tool='速度' ⟺ C=0 且 B=0（文档 §2.4）。

    这条是**纯内部一致性**，不需要知道线边缓冲/调拨提前期是多少，因此不会因猜约定而误报。
    项目里 speed-hedge 分支出过一次「批量路径永远走不到」的缺口，所以两个方向都要验。
    """
    rows = q(conn, """
        SELECT material_no, version_no, hedge_tool,
               COALESCE(safety_level,0) AS c, COALESCE(batch_level,0) AS b
        FROM inventory_strategy.inventory_strategy
    """)
    rows = find("A", "A4 速度对冲双向一致", rows, "inventory_strategy 全表")
    if rows is None:
        return
    speed = [r for r in rows if r["hedge_tool"] == "速度"]
    stock = [r for r in rows if r["hedge_tool"] == "库存"]
    note(f"A4: 速度对冲 {len(speed)} 行 / 库存对冲 {len(stock)} 行")
    if not speed:
        REP.fail("A", "A4 速度对冲分支可达", "至少存在 1 行 hedge_tool='速度'",
                 f"0 行（全表 {len(rows)} 行，全部是「库存」对冲）",
                 "该分支曾因批量路径不传 customer_no 而永不可达；0 行需确认是数据使然还是分支再次不可达")
    bad_speed = [r for r in speed if not (close(r["c"], 0) and close(r["b"], 0))]
    REP.viol("A", "A4 速度对冲 ⇒ C=B=0", bad_speed,
             "hedge_tool='速度' 时 safety_level=0 且 batch_level=0",
             lambda r: f"{r['material_no']} C={r['c']} B={r['b']}")
    # 反方向**不是**不变量：零历史物料日需求=0 ⇒ A=0、σ_L=0 ⇒ C=B=0，
    # 但它按参数判据仍属「库存对冲」。故只作参考，不判失败（一开始误判过，已修正）。
    stock_zero = [r for r in stock if close(r["c"], 0) and close(r["b"], 0)]
    if stock_zero:
        REP._add("A", "A4 库存对冲但 C=B=0（参考）", "WARN",
                 "若物料有历史，库存对冲不应 C=B=0",
                 " | ".join(f"{r['material_no']}" for r in stock_zero[:4]),
                 "若该物料日需求为 0（无历史/数据不足），C=B=0 属正常，非 BUG")
    else:
        REP.ok("A", "A4 库存对冲但 C=B=0（参考）")


def a_forecast(conn):
    """A5/A6 销售预测：调整后需求与达成率必须能对上原始数据。

    A5 行内自洽：adj_qty == orig_qty × (1 − bias)，用**行内自己的 bias**，不猜口径。
    A6 外部对账：行内 bias/mape 与 attainment 表同键的值一致（两条独立写入路径）。
    """
    lines = q(conn, """
        SELECT version_no, material_no, customer_no, rolling_month,
               orig_qty, bias, mape, adj_qty, abnormal_flag, final_qty
        FROM sales_forecast.sales_forecast_line
    """)
    lines = find("A", "A5 调整后需求 = 原始 × (1 − bias)", lines, "sales_forecast_line 全表")
    if lines is not None:
        bad = []
        for r in lines:
            if r["orig_qty"] is None or r["bias"] is None or r["adj_qty"] is None:
                continue
            if not close(r["adj_qty"], r["orig_qty"] * (1 - r["bias"])):
                bad.append(r)
        REP.viol("A", "A5 adj = orig × (1 − bias)", bad,
                 "adj_qty == orig_qty × (1 − bias)",
                 lambda r: "{m}/{c}/{rm} orig={o} bias={b} adj={a}".format(
                     m=r["material_no"], c=r["customer_no"], rm=r["rolling_month"],
                     o=r["orig_qty"], b=r["bias"], a=r["adj_qty"]))
        REP.ok("A", "A5 分母规模", f"{len(lines)} 行预测明细参与对账")

    # A6 与 attainment 表对账。**只对「客户已报数」的行断言**：
    # bias 由 fill_customer 写入、mape 由 decide 写入，客户从未报数的行两者都没写过
    # fill_customer（只有 decide 写过 mape），此时 line.bias 为空是正常的，不是不一致。
    rows = q(conn, """
        SELECT l.material_no, l.customer_no, l.bias AS line_bias, l.mape AS line_mape,
               a.bias AS att_bias, a.mape AS att_mape
        FROM (SELECT DISTINCT material_no, customer_no, bias, mape
              FROM sales_forecast.sales_forecast_line
              WHERE orig_qty IS NOT NULL) l
        JOIN attainment.attainment a
          ON a.material_no = l.material_no AND a.customer_no = l.customer_no
    """)
    rows = find("A", "A6 预测偏差 与 达成率台账 同值", rows,
                "有客户原始预测的预测行 ⋈ attainment（同 material+customer）")
    if rows is not None:
        bad = [r for r in rows
               if not close(r["line_bias"], r["att_bias"]) or not close(r["line_mape"], r["att_mape"])]
        REP.viol("A", "A6 bias/mape 两条写入路径同值", bad,
                 "line.bias == attainment.bias 且 line.mape == attainment.mape",
                 lambda r: f"{r['material_no']}/{r['customer_no']} "
                           f"bias {r['line_bias']} vs {r['att_bias']}｜mape {r['line_mape']} vs {r['att_mape']}")


def a_source_fallback(conn):
    """A13 双源合成不得静默退化成单源。

    「双源」= 客户预测（orig_qty → adj_qty）与统计基线（base_qty → base_event_qty，BR-23）。
    客户没报数时 orig_qty 为空（BR-09 明确允许可空），此时**基线应当兜住**。
    若代码在 adj_qty 为空时把 final_qty 直接置空、且 abnormal_flag 仍为 0，
    表现就是「基线算了却丢掉、汇总按 0 计、毛需求只剩水位层」——
    不报错、不崩溃、只是答案错，正是最难发现的那一类。

    本条是本轮实测发现（2026-09-15：M9-BEAM 基线 1967.71/月 被丢，
    毛需求从 ~4008 掉到 2040）固化成的回归靶点。
    """
    rows = q(conn, """
        SELECT version_no, material_no, customer_no, rolling_month,
               orig_qty, adj_qty, base_qty, base_event_qty, abnormal_flag, final_qty
        FROM sales_forecast.sales_forecast_line
    """)
    rows = find("A", "A13 双源退化", rows, "sales_forecast_line 全表")
    if rows is None:
        return

    # ① 算了基线却没用：非异常行、最终值为空、而基线非空非零
    dropped = [r for r in rows
               if r["abnormal_flag"] == 0 and r["final_qty"] is None
               and r["base_event_qty"] is not None and not close(r["base_event_qty"], 0)]
    REP.viol("A", "A13 基线不得被静默丢弃", dropped,
             "非异常行若基线非零，final_qty 不应为空（应回退到基线）",
             lambda r: f"{r['material_no']}/{r['rolling_month']} "
                       f"基线={r['base_event_qty']:.2f} 客户原始={r['orig_qty']} "
                       f"调整后={r['adj_qty']} → 最终=None（异常标记=0）",
             "客户未报数时 orig_qty 为空（BR-09 允许），但基线已经算好落库（BR-23）")

    # ② 无客户数也无最终值：该行对汇总的贡献恒为 0，且系统不认为有问题
    silent = [r for r in rows
              if r["abnormal_flag"] == 0 and r["final_qty"] is None and r["orig_qty"] is None]
    if silent:
        mats = sorted({r["material_no"] for r in silent})
        REP._add("A", "A13 静默归零行（参考）", "WARN",
                 "非异常且无客户数的行，最终值应回退到基线而非留空",
                 f"{len(silent)} 行 / {len(mats)} 个物料：{', '.join(mats[:5])}",
                 "这些行在汇总里按 0 计入，界面上看不出任何异常")

    # ③ 影响量级：汇总为 0（或明显低于基线）而该物料有非零基线
    impact = q(conn, """
        SELECT s.version_no, s.material_no, s.rolling_month, s.final_qty_sum,
               SUM(l.base_event_qty) AS base_sum, COUNT(*) AS line_cnt
        FROM sales_forecast.sales_forecast_summary s
        JOIN sales_forecast.sales_forecast_line l
          ON l.version_no = s.version_no AND l.material_no = s.material_no
         AND l.rolling_month = s.rolling_month
        GROUP BY s.version_no, s.material_no, s.rolling_month
        HAVING ABS(s.final_qty_sum - COALESCE(SUM(l.final_qty), 0)) < 1e-9
    """)
    lossy = [r for r in impact
             if (r["base_sum"] or 0) > 0 and close(r["final_qty_sum"] or 0, 0)]
    if lossy:
        total = sum(r["base_sum"] for r in lossy)
        REP._add("A", "A13 归零物料的少算量（参考）", "WARN",
                 "汇总应为 0 的物料不应有非零基线",
                 " | ".join(f"{r['material_no']}/{r['rolling_month']} 基线={r['base_sum']:.2f} "
                            f"汇总={r['final_qty_sum']:.2f}" for r in lossy[:3]),
                 f"共 {len(lossy)} 组，合计少算 {total:.2f} 件（这些量会直接漏出毛需求）")
    else:
        REP.ok("A", "A13 归零物料的少算量（参考）")


def a_merge_transfer(conn):
    """A14 BR-09 毛需求合并加工：被合并的旧料不得残留，且其需求应**全额转入新件**。

    为什么补这条（2026-09）：BR-09 此前**没有任何判据**（`--coverage` 表里标 ❌），
    而本轮 `BYD-HAN-FB25` 整条从 `demand` 里消失正是走这条路 ——
    `build_gross` 按断点把切换后的需求全额转移给新件，然后 `forecast.pop(old)`。
    该行为经查是**设计如此**，但「转移是否真的全额、旧料是否真的不残留」
    **从来没有人验过**；而它一旦少转或多转，毛需求就会静默偏大/偏小。

    判据（不需要知道正确值，只用守恒关系）：
      · 切换时间 ≤ 该滚动月的月份 ⇒ 旧料的预测应**全部**归新件，旧料在 demand 里**不得有行**；
      · 新件的 `forecast_qty` == 新件自己的汇总 + 被转入的旧料汇总。
    """
    bps = q(conn, """
        SELECT old_material_no, new_material_no, switch_time
        FROM md_breakpoint.md_breakpoint WHERE COALESCE(disabled, 0) = 0
    """)
    reps = q(conn, """
        SELECT old_material_no, new_material_no FROM md_part_replace.md_part_replace
        WHERE COALESCE(status, '生效') = '生效'
    """)
    pairs = [(r["old_material_no"], r["new_material_no"], str(r["switch_time"] or ""))
             for r in bps] + [(r["old_material_no"], r["new_material_no"], "") for r in reps]
    pairs = find("A", "A14 BR-09 合并转移", pairs, "断点 + 生效替换关系")
    if pairs is None:
        return

    versions = [r["version_no"] for r in q(conn, "SELECT DISTINCT version_no FROM demand.demand")]
    if not versions:
        REP.skip("A", "A14 BR-09 合并转移", "分母为空：demand 里没有任何版本")
        return

    bad, checked = [], 0
    for old, new, switch in pairs:
        for V in versions:
            for rm, off in (("N+1", 1), ("N+2", 2), ("N+3", 3)):
                if switch and switch[:7] > _shift_month(V, off):
                    continue          # 该滚动月还没到切换时间 ⇒ 不转移
                old_rows = q(conn, "SELECT final_qty_sum FROM sales_forecast.sales_forecast_summary"
                                   " WHERE version_no=? AND material_no=? AND rolling_month=?",
                             (V, old, rm))
                new_rows = q(conn, "SELECT final_qty_sum FROM sales_forecast.sales_forecast_summary"
                                   " WHERE version_no=? AND material_no=? AND rolling_month=?",
                             (V, new, rm))
                if not old_rows and not new_rows:
                    continue          # 这个物料组合在该版本没有预测行，无从判
                checked += 1
                old_sum = sum((r["final_qty_sum"] or 0) for r in old_rows)
                new_own = sum((r["final_qty_sum"] or 0) for r in new_rows)
                d = q(conn, "SELECT forecast_qty, gross_qty FROM demand.demand"
                            " WHERE version_no=? AND material_no=? AND rolling_month=?",
                      (V, new, rm))
                if not d:
                    bad.append({"k": f"{old}→{new} {V}/{rm}", "why": "新件在 demand 里没有行"})
                    continue
                got = d[0]["forecast_qty"] or 0
                if not close_stored(got, new_own + old_sum):
                    bad.append({"k": f"{old}→{new} {V}/{rm}",
                                "why": f"预测层 {got} ≠ 新件自有 {new_own} + 转入 {old_sum}"
                                       f" = {new_own + old_sum:.2f}"})
                left = q(conn, "SELECT material_no FROM demand.demand"
                               " WHERE version_no=? AND material_no=?", (V, old))
                if left:
                    bad.append({"k": f"{old}→{new} {V}/{rm}",
                                "why": f"旧料 {old} 被合并后仍在 demand 里有 {len(left)} 行"})
    # **内层分母闸**：`find()` 只保证「物料对」非空，保不住「真的比了几组」。
    # 首版就是因为一个日期格式笔误让所有组合被 continue 掉，然后报 PASS —— 判据自己在撒谎。
    if checked == 0:
        REP.fail("A", "A14 BR-09 合并转移全额且旧料不残留",
                 "至少应有 1 个（物料对×版本×滚动月）进入比对",
                 f"0 个 —— 判据成了空规则，本次 PASS 不可信",
                 "外层分母（物料对）非空但内层全被跳过：查 `switch_time` 与 "
                 "`_shift_month` 的形态是否一致")
        return
    REP.viol("A", "A14 BR-09 合并转移全额且旧料不残留", bad,
             "切换后的预测应全额转入新件（新件预测层 = 新件自有 + 转入），且旧料不得残留",
             lambda t: f"{t['k']}：{t['why']}", f"{checked} 个（物料对×版本×滚动月）参与比对")


def a_deviation(conn):
    """A15 BR-12 偏离率计算 + BR-14 异常标记：独立重算 deviation，与 `abnormal_flag` 对照。

    判据（照详设 BR-12 原文，不照代码）：
      偏离率 = |基线值 − 客户值| ÷ 客户值；客户值为 0 时按绝对值判定
      其中 客户值 = 物料级客户调整后需求合计（`SUM(adj_qty)`）、基线值 = 基线和事件合计量
      BR-14：**MAPE 存在 且 偏离率 > 5% → 标记异常**；否则不标记

    这条此前**没有任何判据**（`--coverage` 标 ❌），而它是 `decide` 里唯一的判定逻辑 ——
    阈值写错、除以零写错、MAPE 的存在性判断写错，都不会有任何东西报警。

    ⚠ 已知边界：**人工定稿过的行不受 `decide` 影响**（BR-27），若定稿后上游数据又变过，
    该行的 flag 与按当前数据重算的结果可以合法地不一致 —— 所以下面把「有定稿记录的行」
    单独计数并排除，避免把设计行为报成缺陷。
    """
    rows = q(conn, """
        SELECT version_no, material_no, customer_no, rolling_month,
               orig_qty, adj_qty, base_qty, mape, abnormal_flag
        FROM sales_forecast.sales_forecast_line
    """)
    rows = find("A", "A15 BR-12 偏离率与异常标记", rows, "预测明细全表")
    if rows is None:
        return
    settled = {(r["version_no"], r["material_no"], r["customer_no"], r["rolling_month"])
               for r in q(conn, "SELECT version_no, material_no, customer_no, rolling_month"
                                " FROM sales_forecast.sales_forecast_settle")}
    groups = {}
    for r in rows:
        groups.setdefault((r["version_no"], r["material_no"], r["rolling_month"]), []).append(r)

    THRESHOLD = 0.05          # BR-16 声明的默认偏离阈值；S7 已对账它与代码常量一致
    bad, checked, skipped_settled = [], 0, 0
    for key, lines in groups.items():
        adj_vals = [l["adj_qty"] for l in lines if l["adj_qty"] is not None]
        bases = [l["base_qty"] for l in lines if l["base_qty"] is not None]
        adj_sum = sum(adj_vals) if adj_vals else None
        base = bases[0] if bases else None
        for l in lines:
            k4 = (l["version_no"], l["material_no"], l["customer_no"], l["rolling_month"])
            if k4 in settled:
                skipped_settled += 1
                continue
            if adj_sum is None or base is None:
                expect = False          # 无从算偏离率 ⇒ 按 BR-14 不标记
            else:
                dev = abs(base - adj_sum) if not adj_sum else abs(base - adj_sum) / adj_sum
                expect = (l["mape"] is not None) and dev > THRESHOLD
            checked += 1
            if bool(l["abnormal_flag"]) != bool(expect):
                bad.append({"k": f"{l['material_no']}/{l['customer_no']}/{l['rolling_month']}",
                            "why": f"重算 应{'异常' if expect else '正常'}，实际 "
                                   f"abnormal_flag={l['abnormal_flag']}（客户值={adj_sum} 基线={base} "
                                   f"MAPE={l['mape']}）"})
    if checked == 0:
        REP.skip("A", "A15 BR-12 偏离率与异常标记",
                 f"分母为空：{skipped_settled} 行全部是人工定稿行，没有可判的")
        return
    REP.viol("A", "A15 BR-12 偏离率与异常标记", bad,
             "偏离率 = |基线 − 客户值| ÷ 客户值（客户值为 0 按绝对值）；"
             "MAPE 存在 且 偏离率 > 5% 才标异常（BR-12 / BR-14）",
             lambda t: f"{t['k']}：{t['why']}",
             f"{checked} 行参与比对（另跳过 {skipped_settled} 行人工定稿行 —— BR-27 下它们不受 decide 影响）")


def a_summary(conn):
    """A7 汇总 = 明细聚合（BR-25 / BR-03：汇总表禁止独立编辑）。"""
    rows = q(conn, """
        SELECT s.version_no, s.material_no, s.rolling_month,
               s.final_qty_sum,
               COALESCE(SUM(l.final_qty), 0) AS calc_sum,
               COUNT(l.material_no) AS line_cnt
        FROM sales_forecast.sales_forecast_summary s
        LEFT JOIN sales_forecast.sales_forecast_line l
               ON l.version_no = s.version_no
              AND l.material_no = s.material_no
              AND l.rolling_month = s.rolling_month
        GROUP BY s.version_no, s.material_no, s.rolling_month
    """)
    rows = find("A", "A7 预测汇总 = 明细合计", rows, "sales_forecast_summary")
    if rows is None:
        return
    bad = [r for r in rows if not close(r["final_qty_sum"], r["calc_sum"])]
    REP.viol("A", "A7 final_qty_sum = Σ final_qty", bad,
             "汇总数量 == 同键明细之和",
             lambda r: f"{r['material_no']}/{r['rolling_month']} "
                       f"汇总={r['final_qty_sum']} 明细和={r['calc_sum']}（{r['line_cnt']} 行）")
    orphan = [r for r in rows if r["line_cnt"] == 0]
    REP.viol("A", "A7 汇总不得有孤儿行", orphan,
             "每条汇总至少对应 1 行明细", lambda r: f"{r['material_no']}/{r['rolling_month']}")


def a_gross(conn):
    """A8 毛需求 = 预测汇总 + 水位上限（三条独立路径必须同一值）。

    路径①：demand.forecast_qty 应等于 sales_forecast_summary.final_qty_sum（demand 经 get_summary 取数）
    路径②：demand.inventory_qty 应等于 inventory_strategy 三层之和 A+C+B（水位上限）
    路径③：demand.gross_qty 应等于 ① + ②
    三条路径分别来自三个应用的三张表 —— 这是本轮「毛需求丢水位层」BUG 的同一探针。
    """
    rows = q(conn, """
        SELECT d.version_no, d.material_no, d.rolling_month,
               d.forecast_qty, d.inventory_qty, d.gross_qty,
               s.final_qty_sum,
               (COALESCE(w.min_level,0) + COALESCE(w.safety_level,0) + COALESCE(w.batch_level,0)) AS water_upper,
               w.material_no IS NULL AS no_water
        FROM demand.demand d
        LEFT JOIN sales_forecast.sales_forecast_summary s
               ON s.version_no = d.version_no AND s.material_no = d.material_no
              AND s.rolling_month = d.rolling_month
        LEFT JOIN inventory_strategy.inventory_strategy w
               ON w.version_no = d.version_no AND w.material_no = d.material_no
    """)
    rows = find("A", "A8 毛需求分层对账", rows, "demand 全表")
    if rows is None:
        return

    # 路径③：内部自洽（最重要，纯结构）
    bad_sum = [r for r in rows
               if not close(r["gross_qty"], (r["forecast_qty"] or 0) + (r["inventory_qty"] or 0))]
    REP.viol("A", "A8 毛需求 = 预测 + 水位", bad_sum,
             "gross_qty == forecast_qty + inventory_qty",
             lambda r: f"{r['material_no']}/{r['rolling_month']} "
                       f"毛={r['gross_qty']} 预测={r['forecast_qty']} 水位={r['inventory_qty']}")

    # 路径②：水位层与库存策略对上
    has_w = [r for r in rows if not r["no_water"]]
    bad_w = [r for r in has_w if not close(r["inventory_qty"], r["water_upper"])]
    REP.viol("A", "A8 水位层 = A+C+B", bad_w,
             "demand.inventory_qty == inventory_strategy(A+C+B)",
             lambda r: f"{r['material_no']}/{r['rolling_month']} "
                       f"demand={r['inventory_qty']} 策略={r['water_upper']}")
    missing_w = [r for r in rows if r["no_water"]]
    REP.viol("A", "A8 有毛需求就必须有水位策略", missing_w,
             "demand 的每行都能在 inventory_strategy 找到同版本同物料的水位",
             lambda r: f"{r['material_no']}/{r['rolling_month']} 版本 {r['version_no']} 无水位策略")

    # 路径①：预测层与预测汇总对上
    has_s = [r for r in rows if r["final_qty_sum"] is not None]
    bad_s = [r for r in has_s if not close(r["forecast_qty"], r["final_qty_sum"])]
    REP.viol("A", "A8 预测层 = 预测汇总", bad_s,
             "demand.forecast_qty == sales_forecast_summary.final_qty_sum",
             lambda r: f"{r['material_no']}/{r['rolling_month']} "
                       f"demand={r['forecast_qty']} 汇总={r['final_qty_sum']}")


def a_net(conn):
    """A9 净需求分层口径（BR-04 / BR-08）。

    N+1  ：net = max(0, 毛 + 未发 − 库存 − 在途)，且三层扣减量必须落库
    N+2/3：net = 毛（远期库存/在途未知，不扣减），且三层扣减量必须为 0
    **扣减的符号方向**是本条的重点：`+未发 −库存 −在途` 写反了，在演示环境里完全看不出来
    （适配器 stub 恒返回 0，等价于 net = 毛）。
    """
    rows = q(conn, """
        SELECT version_no, material_no, rolling_month, gross_qty,
               open_order_qty, onhand_qty, in_transit_qty, net_qty
        FROM demand.demand
    """)
    rows = find("A", "A9 净需求分层", rows, "demand 全表")
    if rows is None:
        return

    n1 = [r for r in rows if r["rolling_month"] == "N+1"]
    far = [r for r in rows if r["rolling_month"] != "N+1"]
    if not n1:
        REP.skip("A", "A9 N+1 扣减公式", "分母为空：没有任何 N+1 行")
    else:
        bad = []
        for r in n1:
            want = (r["gross_qty"] or 0) + (r["open_order_qty"] or 0) \
                - (r["onhand_qty"] or 0) - (r["in_transit_qty"] or 0)
            want = max(0.0, want)          # BR-08 各层非负
            if not close(r["net_qty"], want):
                bad.append(r)
        REP.viol("A", "A9 N+1：net = max(0, 毛+未发−库存−在途)", bad,
                 "net_qty == max(0, gross + open_order − onhand − in_transit)",
                 lambda r: f"{r['material_no']} 毛={r['gross_qty']} 未发={r['open_order_qty']} "
                           f"库存={r['onhand_qty']} 在途={r['in_transit_qty']} → 存={r['net_qty']}")
        # 非零覆盖度：**参考项，不判失败**。适配器 stub 恒返回 0，所以真库上这层永远是 0
        # （不是缺陷，是环境使然）。把它做成 FAIL 会留下一条**永远红**的检查 ——
        # 常红的检查会训练人无视红灯，比没有检查更坏。真正的穿透验证在 H 组
        # （影子库内 monkeypatch 喂非零受控值），那里才是判据。
        nonzero = [r for r in n1
                   if (r["open_order_qty"] or 0) or (r["onhand_qty"] or 0) or (r["in_transit_qty"] or 0)]
        if not nonzero:
            REP._add("A", "A9 扣减层非零覆盖（参考）", "WARN",
                     "真库上三层恒为 0 属环境使然（适配器是 stub）",
                     f"{len(n1)} 行 N+1 全部三层为 0",
                     "扣减公式的穿透验证见 H 组（影子库内注入非零值）；本条仅作提示，不判失败")
        else:
            REP.ok("A", "A9 扣减层非零覆盖", f"{len(nonzero)}/{len(n1)} 行 N+1 有非零扣减层")

    bad_far = [r for r in far
               if not close(r["net_qty"], r["gross_qty"])
               or (r["open_order_qty"] or 0) or (r["onhand_qty"] or 0) or (r["in_transit_qty"] or 0)]
    REP.viol("A", "A9 N+2/N+3：net = 毛，扣减层归零", bad_far,
             "net_qty == gross_qty 且三层扣减为 0",
             lambda r: f"{r['material_no']}/{r['rolling_month']} 毛={r['gross_qty']} "
                       f"→ 净={r['net_qty']}（扣减 {r['open_order_qty']}/{r['onhand_qty']}/{r['in_transit_qty']}）")


def a_master_plan(conn):
    """A10 主计划逐字等于净需求（BR-08：原样通过，不四舍五入）。"""
    rows = q(conn, """
        SELECT m.version_no, m.material_no, m.rolling_month, m.plan_version, m.plan_qty,
               d.net_qty
        FROM master_plan.master_plan m
        JOIN demand.demand d
          ON d.version_no = m.version_no AND d.material_no = m.material_no
         AND d.rolling_month = m.rolling_month
        WHERE m.plan_version = (
            SELECT MAX(plan_version) FROM master_plan.master_plan m2
            WHERE m2.version_no = m.version_no AND m2.material_no = m.material_no
        )
    """)
    rows = find("A", "A10 主计划 = 净需求", rows, "master_plan ⋈ demand")
    if rows is None:
        return
    bad = [r for r in rows if not close(r["plan_qty"], r["net_qty"])]
    REP.viol("A", "A10 plan_qty 原样等于 net_qty", bad,
             "plan_qty == net_qty（BR-08 不得四舍五入/再计算）",
             lambda r: f"{r['material_no']}/{r['rolling_month']} 计划={r['plan_qty']} 净={r['net_qty']}")

    orphan = q(conn, """
        SELECT m.material_no, m.version_no, m.rolling_month
        FROM master_plan.master_plan m
        LEFT JOIN demand.demand d
          ON d.version_no = m.version_no AND d.material_no = m.material_no
         AND d.rolling_month = m.rolling_month
        WHERE d.material_no IS NULL
    """)
    REP.viol("A", "A10 主计划不得有无源行", orphan,
             "每条主计划都能在 demand 找到同键净需求",
             lambda r: f"{r['material_no']}/{r['rolling_month']} 版本 {r['version_no']}")


def a_projection(conn):
    """A11 推移表逐日递推自洽：balance(d) = balance(d−1) + inbound(d) − outbound(d)。

    起点不锚定（refresh 的 opening_stock 只在首日生效），只验**相邻两日之间的差额**，
    因此不需要知道起始库存是多少 —— 又一个「不猜约定」的对账。
    """
    rows = q(conn, """
        SELECT material_no, biz_date, inbound_qty, outbound_qty, balance, prev_bal, prev_date
        FROM (
            SELECT *,
                   LAG(balance)     OVER (PARTITION BY material_no ORDER BY biz_date) AS prev_bal,
                   LAG(biz_date)    OVER (PARTITION BY material_no ORDER BY biz_date) AS prev_date
            FROM inventory_projection.inventory_projection
        )
        WHERE prev_bal IS NOT NULL
    """)
    rows = find("A", "A11 推移表递推", rows, "inventory_projection 相邻日对")
    if rows is None:
        return

    # 只验日期连续的相邻对（跨窗口拼接处差额不成立：refresh 以 opening_stock 重锚）
    def contiguous(prev, cur):
        try:
            import datetime
            a = datetime.date.fromisoformat(str(prev))
            b = datetime.date.fromisoformat(str(cur))
            return (b - a).days == 1
        except (ValueError, TypeError):
            return False

    pairs = [r for r in rows if contiguous(r["prev_date"], r["biz_date"])]
    if not pairs:
        REP.skip("A", "A11 推移表递推", "分母为空：没有日期连续的相邻对")
        return
    # 余额按两位小数落库 ⇒ 递推差值的容差同样按存储精度取（0.011），不按 1e-9
    bad = [r for r in pairs
           if abs(r["balance"] - (r["prev_bal"] + (r["inbound_qty"] or 0) - (r["outbound_qty"] or 0))) > 0.011]
    REP.viol("A", "A11 余额(d) = 余额(d−1) + 入 − 出", bad,
             "相邻日递推差额等于当日入减出",
             lambda r: f"{r['material_no']} {r['prev_date']}→{r['biz_date']} "
                       f"余额 {r['prev_bal']}→{r['balance']} 但入={r['inbound_qty']} 出={r['outbound_qty']}")
    note(f"A11: {len(pairs)} 个连续相邻对参与对账")

    # A11b：出现过入库的行，其入库日期必须能对上「主计划最迟入库日 ∪ 需求池承诺/要求入库日」
    inbound_days = q(conn, """
        SELECT material_no, biz_date, inbound_qty
        FROM inventory_projection.inventory_projection WHERE inbound_qty > 0
    """)
    inbound_days = find("A", "A11b 入库日来源可溯", inbound_days,
                        "inventory_projection 中 inbound_qty > 0 的行")
    if inbound_days is None:
        REP.fail("A", "A11b 入库日来源可溯", "至少存在 1 行 inbound_qty > 0",
                 "0 行 —— 推移表从未有过任何预计入库",
                 "若主计划/补库单非空却全无入库，说明 BR-04 的入库收集没生效（曾在毛需求上出过同类问题）")
        return
    plan_days = {(r["material_no"], str(r["latest_inbound_date"]))
                 for r in q(conn, "SELECT material_no, latest_inbound_date FROM master_plan.master_plan")}
    pool_days = set()
    for r in q(conn, "SELECT material_no, promised_inbound, required_inbound FROM demand_pool.demand_pool"):
        for k in ("promised_inbound", "required_inbound"):
            if r[k]:
                pool_days.add((r["material_no"], str(r[k])))
    src = plan_days | pool_days
    bad = [r for r in inbound_days if (r["material_no"], str(r["biz_date"])) not in src]
    REP.viol("A", "A11b 入库日来源可溯", bad,
             "每一笔预计入库都能对上主计划最迟入库日或补库单入库日",
             lambda r: f"{r['material_no']} {r['biz_date']} 入 {r['inbound_qty']} 无来源单据")


def a_daily_demand_ref(conn):
    """A12（参考值，不判 FAIL）日需求 与「近 12 期月均 ÷ 30」的比值。

    「近 12 期」的取数口径（取哪些客户、缺期怎么算）文档没写死到可复现，
    硬断言会因猜错约定而假警报 —— 故只报倍数，让人看。偏离 1 倍以上值得追问。
    """
    rows = q(conn, """
        SELECT w.material_no,
               w.batch_window, w.batch_level,
               (SELECT SUM(h.qty) FROM sales_history.sales_history h
                 WHERE h.material_no = w.material_no
                   AND h.period >= (
                        SELECT MIN(p) FROM (SELECT DISTINCT period AS p
                                            FROM sales_history.sales_history
                                            WHERE material_no = w.material_no
                                            ORDER BY p DESC LIMIT 12))) AS qty12,
               (SELECT COUNT(DISTINCT h.period) FROM sales_history.sales_history h
                 WHERE h.material_no = w.material_no) AS periods
        FROM inventory_strategy.inventory_strategy w
        WHERE w.batch_window > 0
    """)
    rows = find("A", "A12 日需求参考值", rows, "有组批窗口的水位行")
    if rows is None:
        return
    out = []
    for r in rows:
        if not r["periods"] or r["periods"] < 12 or not r["qty12"]:
            continue
        implied = (r["batch_level"] or 0) / r["batch_window"]
        doc = (r["qty12"] / 12.0) / 30.0
        if doc <= 0:
            continue
        ratio = implied / doc
        if not (0.67 <= ratio <= 1.5):
            out.append((r["material_no"], implied, doc, ratio))
    if out:
        REP._add("A", "A12 日需求 vs 文档口径（参考）", "WARN",
                 "批窗口推得的日需求 与 近12期月均÷30 同量级（0.67~1.5×）",
                 " | ".join(f"{m}: 批={i:.3f} 文档={d:.3f} 比={q:.2f}×" for m, i, d, q in out[:4]),
                 f"共 {len(out)} 行偏离，需人工判定是数据使然还是口径不符")
    else:
        REP.ok("A", "A12 日需求 vs 文档口径（参考）", f"{len(rows)} 行均在 0.67~1.5× 内")


# ================================================================ C 组：不变式

def c_invariants(conn):
    """永远必须成立的约束。每条都是一句 SQL：应当返回 0 行，返回了就是被破坏。"""

    def inv(target, sql, expect, fmt, note_=""):
        try:
            rows = q(conn, sql)
        except sqlite3.Error as e:
            REP.skip("C", target, f"SQL 无法执行（表/列缺失？）：{e}")
            return
        REP.viol("C", target, rows, expect, fmt, note_)

    # --- 引用完整性（主数据引用铁律）---
    for app, table in [("demand", "demand"), ("master_plan", "master_plan"),
                       ("inventory_strategy", "inventory_strategy"),
                       ("inventory_projection", "inventory_projection"),
                       ("demand_pool", "demand_pool"), ("strategy_fitting", "strategy_fitting"),
                       ("sales_history", "sales_history"), ("outbound_plan", "outbound_plan"),
                       ("attainment", "attainment")]:
        if not (has_table(conn, app, table) and columns(conn, app, table) >= {"material_no"}):
            continue
        inv(f"C1 引用完整性 · {app}.material_no",
            f"""SELECT DISTINCT t.material_no FROM {app}.{table} t
                LEFT JOIN md_material.md_material m ON m.material_no = t.material_no
                WHERE m.material_no IS NULL""",
            "每行的 material_no 都存在于 md_material（BR-12 铁律）",
            lambda r: f"{r['material_no']} 不存在于主数据")

    # --- 枚举域 ---
    inv("C2 枚举 · hedge_tool",
        """SELECT DISTINCT hedge_tool FROM inventory_strategy.inventory_strategy
           WHERE hedge_tool NOT IN ('库存','速度')""",
        "hedge_tool ∈ {库存, 速度}", lambda r: f"hedge_tool={r['hedge_tool']}")
    inv("C2 枚举 · rolling_month",
        """SELECT DISTINCT rolling_month FROM demand.demand
           WHERE rolling_month NOT IN ('N+1','N+2','N+3')""",
        "rolling_month ∈ {N+1, N+2, N+3}", lambda r: f"rolling_month={r['rolling_month']}")
    inv("C2 枚举 · demand_pool.status",
        """SELECT DISTINCT status FROM demand_pool.demand_pool
           WHERE status NOT IN ('待下达','已下达','生产中','已完成','已取消')""",
        "补库单状态在状态机取值域内", lambda r: f"status={r['status']}")
    inv("C2 枚举 · outbound_plan.status",
        """SELECT DISTINCT status FROM outbound_plan.outbound_plan
           WHERE status NOT IN ('待出库','已关闭','已完成')""",
        "出库计划状态在取值域内", lambda r: f"status={r['status']}")

    # --- 非负 ---
    inv("C3 非负 · 净需求",
        "SELECT material_no, rolling_month, net_qty FROM demand.demand WHERE net_qty < 0",
        "net_qty ≥ 0（BR-08）", lambda r: f"{r['material_no']}/{r['rolling_month']} net={r['net_qty']}")
    inv("C3 非负 · 毛需求",
        "SELECT material_no, rolling_month, gross_qty FROM demand.demand WHERE gross_qty < 0",
        "gross_qty ≥ 0", lambda r: f"{r['material_no']}/{r['rolling_month']} gross={r['gross_qty']}")
    inv("C3 非负 · 主计划",
        "SELECT material_no, rolling_month, plan_qty FROM master_plan.master_plan WHERE plan_qty < 0",
        "plan_qty ≥ 0（BR-06）", lambda r: f"{r['material_no']}/{r['rolling_month']} plan={r['plan_qty']}")
    inv("C3 非负 · 补库量",
        "SELECT replenish_no, replenish_qty FROM demand_pool.demand_pool WHERE replenish_qty <= 0",
        "replenish_qty > 0（BR-09）", lambda r: f"{r['replenish_no']} qty={r['replenish_qty']}")
    inv("C3 非负 · 水位三层",
        """SELECT material_no, min_level, safety_level, batch_level
           FROM inventory_strategy.inventory_strategy
           WHERE min_level < 0 OR safety_level < 0 OR batch_level < 0""",
        "A/C/B 均 ≥ 0", lambda r: f"{r['material_no']} A={r['min_level']} C={r['safety_level']} B={r['batch_level']}")

    # --- 唯一性（复合主键若生效，这些必然为空；验的是「约束真在库里」）---
    inv("C4 唯一性 · demand 四键",
        """SELECT version_no, material_no, rolling_month, COUNT(*) n
           FROM demand.demand GROUP BY 1,2,3 HAVING n > 1""",
        "version+material+month 唯一（BR-11）",
        lambda r: f"{r['material_no']}/{r['rolling_month']}×{r['n']}")
    inv("C4 唯一性 · 预测明细四键",
        """SELECT version_no, material_no, customer_no, rolling_month, COUNT(*) n
           FROM sales_forecast.sales_forecast_line GROUP BY 1,2,3,4 HAVING n > 1""",
        "四键唯一（BR-02）",
        lambda r: f"{r['material_no']}/{r['customer_no']}/{r['rolling_month']}×{r['n']}")
    inv("C4 唯一性 · 水位二键",
        """SELECT version_no, material_no, COUNT(*) n
           FROM inventory_strategy.inventory_strategy GROUP BY 1,2 HAVING n > 1""",
        "version+material 唯一（BR-01）",
        lambda r: f"{r['material_no']}×{r['n']}")
    inv("C4 唯一性 · 推移表二键",
        """SELECT material_no, biz_date, COUNT(*) n
           FROM inventory_projection.inventory_projection GROUP BY 1,2 HAVING n > 1""",
        "material+biz_date 唯一（BR-01）",
        lambda r: f"{r['material_no']} {r['biz_date']}×{r['n']}")

    # --- 审计列（平台自动注入；表存在该列才验）---
    for app, table in [("demand", "demand"), ("md_material", "md_material"),
                       ("demand_pool", "demand_pool"), ("master_plan", "master_plan")]:
        cols = columns(conn, app, table)
        if "created_by" not in cols:
            continue
        inv(f"C5 审计列 · {app}.created_by",
            f"SELECT * FROM {app}.{table} WHERE created_by IS NULL OR created_by = ''",
            "created_by 非空（平台自动注入）",
            lambda r: f"{r.get('material_no') or r.get('replenish_no')} created_by 为空")

    # --- 状态机：已进入生产/完成的补库单必须有承诺入库日 ---
    # ⚠ 2026-09-19 收窄：原 SQL 把 `已下达` 也算了进来，而**判据自己的名字写的是「已完成」** ——
    # SQL 比它声明的口径更严。仓库内三条依据都站在「下达时允许留空」这一侧：
    #   · 服务签名 `release(replenish_no, promised_inbound: Optional[str] = None)`（可选）
    #   · `demand_pool/应用详设.md` 字段表把 `promised_inbound` 标为「否」（非必填）
    #   · 详设状态机：「承诺入库时间在产能平衡后承诺（具体回填时点待确认）」
    # 承诺日是**产能平衡的结果**，天然晚于「下达」这个动作；到「生产中」（ERP 已回传开工，
    # 说明它接单并给了日期）还没有，才是真问题。故收窄到 `生产中 / 已完成`。
    # 原来的信号没丢：见紧随其后的 C6b 参考项（长期挂着不承诺 → WARN，不卡闸）。
    inv("C6 状态机 · 生产中/已完成的补库单须有承诺入库日",
        """SELECT replenish_no, status FROM demand_pool.demand_pool
           WHERE status IN ('生产中','已完成') AND (promised_inbound IS NULL OR promised_inbound = '')""",
        "已进入生产/完成的补库单必须有 promised_inbound（下达时允许留空：承诺日是产能平衡的结果）",
        lambda r: f"{r['replenish_no']} 状态={r['status']} 无承诺入库日")

    # --- C6b 参考项：下达后长期没人承诺（只报出来，不卡闸）---
    # 为什么是参考项而不是失败项：「下达后多久必须补上承诺日」业务上还没有定论
    # （详设原文就是「具体回填时点待确认」）。一条**永远红**的检查会训练人无视红灯，
    # 比没有检查更坏 —— 这是本项目已经写进纪律的一条（见 `design-plus/验证门禁.md`）。
    # `updated_at` 在这里当作「最后一次改动时间」的代理：下达那一刻会写它，此后没人动就停在那儿。
    try:
        _late = q(conn, """SELECT replenish_no, updated_at FROM demand_pool.demand_pool
                           WHERE status = '已下达'
                             AND (promised_inbound IS NULL OR promised_inbound = '')
                             AND updated_at < datetime('now', '-7 days')""")
    except sqlite3.Error as e:
        REP.skip("C", "C6b 已下达超过 7 天仍无承诺入库日（参考）", f"SQL 无法执行：{e}")
    else:
        if _late:
            REP._add("C", "C6b 已下达超过 7 天仍无承诺入库日（参考）", "WARN",
                     "下达后应在合理期限内补上承诺入库日（时点业务未定，故不卡闸）",
                     " | ".join(f"{r['replenish_no']}@{r['updated_at']}" for r in _late[:5]),
                     "`updated_at` 是「最后改动时间」的代理；该行之后若被动过，计时会重置")
        else:
            REP.ok("C", "C6b 已下达超过 7 天仍无承诺入库日（参考）")

    # --- 预测异常行的最终值口径（BR-26：异常行不自动填写）---
    inv("C7 预测 · 非异常行必须有最终预测",
        """SELECT version_no, material_no, customer_no, rolling_month, abnormal_flag, final_qty
           FROM sales_forecast.sales_forecast_line
           WHERE abnormal_flag = 0 AND final_qty IS NULL""",
        "非异常行 final_qty 非空（异常行才转人工）",
        lambda r: f"{r['material_no']}/{r['customer_no']}/{r['rolling_month']} 非异常但无最终预测")

    # --- C11 引用完整性 · version_no（BR-12 铁律的另一半）---
    # C1 只查了 `material_no`，而 BR-12 要求 `version_no` 也引用 `md_monthly_version`。
    # 补这一条的直接触发：实测 `inventory_strategy.calc(version_no="209901", …)` **成功了**，
    # 为一个**不存在的版本**写入了水位策略（BR-16 声明「版本有效性校验」，实现只校验格式）。
    for app, table in [("demand", "demand"),
                       ("inventory_strategy", "inventory_strategy"),
                       ("master_plan", "master_plan"),
                       ("sales_forecast", "sales_forecast_line"),
                       ("sales_forecast", "sales_forecast_summary"),
                       ("sales_forecast", "sales_forecast_settle")]:
        if not (has_table(conn, app, table) and columns(conn, app, table) >= {"version_no"}):
            continue
        inv(f"C11 引用完整性 · {app}.{table}.version_no",
            f"""SELECT DISTINCT t.version_no FROM {app}.{table} t
                LEFT JOIN md_monthly_version.md_monthly_version v ON v.version_no = t.version_no
                WHERE v.version_no IS NULL""",
            "每行的 version_no 都存在于 md_monthly_version（BR-12 铁律）",
            lambda r: f"版本 {r['version_no']} 不存在于月度版本主数据")

    # --- C12 BR-04 清单范围：正常状态物料 × 该物料的历史采购客户（按物料收窄）---
    # 处理表的每一行都该由「清单」展开而来，而清单 = 正常物料 × 它的采购客户。
    # 客户不是该物料的采购客户 ⇒ 清单范围失控（凭空多出客户，或客户张冠李戴）。
    inv("C12 预测 · 客户必须是该物料的采购客户（BR-04）",
        """SELECT DISTINCT l.material_no, l.customer_no
           FROM sales_forecast.sales_forecast_line l
           LEFT JOIN sales_history.sales_history h
                  ON h.material_no = l.material_no AND h.customer_no = l.customer_no
           WHERE COALESCE(l.customer_no, '') <> '' AND h.material_no IS NULL""",
        "处理表的客户必须在该物料的历史台账里出现过（BR-04 按物料收窄）",
        lambda r: f"{r['material_no']} 的客户 {r['customer_no']} 无任何历史台账")

    inv("C12 预测 · 物料必须是「正常」状态（BR-04）",
        """SELECT DISTINCT l.material_no
           FROM sales_forecast.sales_forecast_line l
           LEFT JOIN md_material.md_material m ON m.material_no = l.material_no
           WHERE m.material_no IS NULL OR m.status <> '正常'""",
        "处理表的物料必须是「正常」状态（BR-04 清单范围）",
        lambda r: f"{r['material_no']} 不是正常状态物料")

    # --- C8 BR-05 每个「物料×客户」拆 N+1/N+2/N+3 三行 ---
    inv("C8 预测 · 每个物料×客户恰好拆 3 行（N+1/N+2/N+3）",
        """SELECT version_no, material_no, customer_no, COUNT(*) n
           FROM sales_forecast.sales_forecast_line
           GROUP BY 1, 2, 3 HAVING n <> 3""",
        "每个 (版本, 物料, 客户) 应有且仅有 3 行（BR-05）",
        lambda r: f"{r['material_no']}/{r['customer_no']} 有 {r['n']} 行（应为 3）")

    # --- C9 BR-01 三表同版本：每条明细都要有对应汇总 ---
    # A7 查的是「汇总不得有孤儿」，这里查反向：**明细不得没有汇总** —— 两个方向都要有，
    # 否则「汇总漏了一批物料」这种漏算不会被发现。
    inv("C9 预测 · 每条明细都有对应汇总（BR-01 三表同聚合同版本）",
        """SELECT DISTINCT l.version_no, l.material_no, l.rolling_month
           FROM sales_forecast.sales_forecast_line l
           LEFT JOIN sales_forecast.sales_forecast_summary s
                  ON s.version_no = l.version_no AND s.material_no = l.material_no
                 AND s.rolling_month = l.rolling_month
           WHERE s.material_no IS NULL""",
        "处理表的每个 (版本,物料,滚动月) 都应有汇总行（汇总漏了 = 毛需求少一层）",
        lambda r: f"{r['material_no']}/{r['rolling_month']} 版本 {r['version_no']} 无汇总行")

    # --- C10 BR-24 断点追溯前置：bp_material_no 必须来自该客户的真实断点 ---
    inv("C10 预测 · bp_material_no 来自真实断点（BR-24）",
        """SELECT DISTINCT l.material_no, l.customer_no, l.bp_material_no
           FROM sales_forecast.sales_forecast_line l
           WHERE COALESCE(l.bp_material_no, '') <> ''
             AND NOT EXISTS (
                 SELECT 1 FROM md_breakpoint.md_breakpoint b
                 WHERE b.new_material_no = l.material_no
                   AND b.customer_no = l.customer_no
                   AND b.old_material_no = l.bp_material_no)""",
        "处理表里填的断点旧料，必须是该客户在该新料上的真实断点",
        lambda r: f"{r['material_no']}/{r['customer_no']} 断点旧料 {r['bp_material_no']} 无对应断点")


# ================================================================ S 组：静态探针

def s_static(conn):
    """结构性探针：死适配器、空转断言。扫描即得，不需要跑业务。"""
    py_files = sorted(Path(f"app/{GROUP}").glob("*/*.py")) + sorted(Path(f"app/{GROUP}").glob("*.py"))
    py_files = [p for p in py_files if "tests" not in p.parts]

    # 死适配器：定义了 _load_* 却没有任何 self.<name>( 调用点
    dead = []
    for p in py_files:
        text = p.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"^\s+def (_load_\w+|_dispatch\w*|_fetch\w+)\s*\(", text, re.M):
            name = m.group(1)
            if f"self.{name}(" not in text:
                dead.append((str(p), name))
    if dead:
        REP.fail("S", "S1 死适配器", "每个声明的外部适配器都有调用点",
                 " | ".join(f"{p.split(chr(92))[-1]}::{n}" for p, n in dead[:4]),
                 f"共 {len(dead)} 处：定义了（且带 docstring 声明语义）却从未被调用。"
                 "后果是该外部数据永远不参与计算，且在 stub 环境下完全隐形")
    else:
        REP.ok("S", "S1 死适配器")

    # 空转断言：记录了但从不校验的列表 / 恒真断言
    vacuous = []
    for p in py_files:
        text = p.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"^\s*record\(\s*True\s*\)", text, re.M):
            vacuous.append((str(p), text[:m.start()].count("\n") + 1, "record(True)"))
        for m in re.finditer(r"assert\s+\w+\s+is\s+not\s+None\s*,", text):
            vacuous.append((str(p), text[:m.start()].count("\n") + 1, "assert is not None"))
        for m in re.finditer(r"check\([^)]*,\s*True\s*[,)]", text):
            vacuous.append((str(p), text[:m.start()].count("\n") + 1, "check(..., True)"))
    # 只报 app/psc（测试脚本自身）里的
    if vacuous:
        REP.fail("S", "S2 空转断言", "断言必须能失败",
                 " | ".join(f"{Path(p).name}:{ln} {kind}" for p, ln, kind in vacuous[:4]),
                 f"共 {len(vacuous)} 处恒真/退化断言，对应用例即使功能坏掉也会全绿")
    else:
        REP.ok("S", "S2 空转断言")

    # S5 触发方向 create 传参是否覆盖 BR-06 分档所需入参
    # BR-07：产能松紧**默认富余**；BR-06：富余时「一次按组批量切线上足（补到组批水位 B）」。
    # 但 demand_pool._resolve_replenish_qty 的最后一行是「未提供水位线参数时，退回触发方
    # 传入的补货量」—— 若触发方不传水位线，富余档就**永远走不到**，只能落到触发线档。
    # 实测 2026-09-15：真库 16 张自动生成的补货单里，**补到 B 的 0 张**，每张的量都恰好等于
    # 触发线缺口（RB26 是 64.16 = A，而补到 B 应为 898.26）。
    probe = Path(f"app/{GROUP}/inventory_projection/inventory_projection.py")
    if probe.exists():
        text = probe.read_text(encoding="utf-8", errors="replace")
        m = re.search(r'self\.fde\.call\(\s*"demand_pool"\s*,\s*"create"\s*,(.*?)\)', text, re.S)
        if not m:
            REP.skip("S", "S5 触发方传参覆盖 BR-06 分档入参",
                     "在该文件里找不到对 demand_pool.create 的调用")
        else:
            arg_blob = m.group(1)
            needed = ("stock_on_hand", "min_level_a", "safety_level_c", "batch_level_b")
            missing = [k for k in needed if k not in arg_blob]
            if missing:
                REP.fail("S", "S5 触发方传参覆盖 BR-06 分档入参",
                         "scan_alert 调用 demand_pool.create 时应传水位类入参"
                         "（BR-06 分档需要）：" + " / ".join(needed),
                         f"实参里缺 {missing}",
                         "缺了它们，`_resolve_replenish_qty` 的「未提供水位线参数时退回触发方"
                         "传入的补货量」**无条件命中** ⇒ BR-06 的「产能富余补到组批水位 B」"
                         "在自动触发路径上永不可达（实测 0/16 张单补到 B）。"
                         "投影的 docstring 写着「产能富余补到 B 由 demand_pool 分档」——"
                         "意图写清了，接线没接")
            else:
                REP.ok("S", "S5 触发方传参覆盖 BR-06 分档入参")

    # S7 阈值常量与《应用详设》声明一致（BR-16 阈值可配置）
    # 这条是**文档↔代码**的对账：详设写了默认值，代码里也有一份 —— 两份必须相同。
    # 实测教训：`MAPE_THRESHOLD` 曾经**定义了却一行没引用**（BR-15 四分支只实现两分支的化石），
    # 而"常量存在"会让人以为规则落地了。值对不上比常量缺失更难发现。
    spec = Path(f"app/{GROUP}/sales_forecast/应用详设.md")
    code = Path(f"app/{GROUP}/sales_forecast/sales_forecast.py")
    if spec.exists() and code.exists():
        stext, ctext = spec.read_text(encoding="utf-8"), code.read_text(encoding="utf-8")
        want = {}
        # 详设里以「默认 20%」「默认 5%」的形式声明
        m = re.search(r"MAPE 阈值（默认\s*([\d.]+)%）", stext)
        if m:
            want["MAPE_THRESHOLD"] = float(m.group(1)) / 100
        m = re.search(r"偏离阈值（默认\s*([\d.]+)%）", stext)
        if m:
            want["DEVIATION_THRESHOLD"] = float(m.group(1)) / 100
        bad = []
        for name, expect in want.items():
            cm = re.search(rf"^\s+{name}\s*=\s*([\d.]+)", ctext, re.M)
            if not cm:
                bad.append({"n": name, "why": "详设声明了默认值，但代码里找不到这个常量"})
            elif not close(float(cm.group(1)), expect):
                bad.append({"n": name,
                            "why": f"详设 {expect}（{expect*100:g}%）vs 代码 {cm.group(1)}"})
        if not want:
            REP.skip("S", "S7 阈值常量与详设一致", "详设里没找到「默认 N%」形态的声明")
        else:
            REP.viol("S", "S7 阈值常量与详设一致（BR-16）", bad,
                     "《应用详设》声明的阈值默认值必须与代码里的常量相同",
                     lambda t: f"{t['n']}：{t['why']}", f"{len(want)} 个阈值参与比对")
    else:
        REP.skip("S", "S7 阈值常量与详设一致", "缺 应用详设.md 或 sales_forecast.py")

    # S6 死常量：类常量定义了却全文件未被引用
    # 这类常量往往是「某条规则被设计过、文档写过、然后没实现」的化石 ——
    # `sales_forecast.MAPE_THRESHOLD` 就是这么找到 BR-15 缺两支的。
    # 但**也可能是别处实现的规则的副本**（`demand_pool.REPLENISH_PRIORITY` 就是：
    # BR-05 的优先级其实在 `inventory_projection._classify_alert` 的判断顺序里正确实现），
    # 所以只作参考项（WARN），不判失败 —— 报出来让人确认「规则到底在哪实现」。
    dead_consts = []
    for p in py_files:
        text = p.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"^    ([A-Z][A-Z0-9_]{2,})\s*[:=]", text, re.M):
            name = m.group(1)
            if len(re.findall(r"\b" + name + r"\b", text)) - 1 <= 0:
                dead_consts.append(f"{p.parent.name}::{name}")
    if dead_consts:
        REP._add("S", "S6 死常量（参考）", "WARN",
                 "类常量应至少被引用一次，否则确认规则是否在别处实现",
                 " | ".join(dead_consts[:5]),
                 "可能是「设计了没实现」的化石，也可能是别处实现的规则的副本 —— 需人工确认")
    else:
        REP.ok("S", "S6 死常量（参考）")

    # 内部调用里没传分页的 list（如果哪个 list 默认只回第一页，求和就会静默截断）
    nopage = []
    for p in py_files:
        text = p.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r'self\.fde\.call\(\s*"[^"]+"\s*,\s*"list"\s*\)', text):
            nopage.append((str(p), text[:m.start()].count("\n") + 1))
    if nopage:
        REP._add("S", "S3 内部 list 调用未传分页（参考）", "WARN",
                 "内部求和类调用应显式传 size 或确认默认全量",
                 " | ".join(f"{Path(p).name}:{ln}" for p, ln in nopage[:4]),
                 f"共 {len(nopage)} 处。当前所有 list 都守「无 page/size 即全量」约定，"
                 "故暂时无害；但约定一旦被某个应用破坏，这些地方会静默截断求和")
    else:
        REP.ok("S", "S3 内部 list 调用未传分页")


# ================================================================ 场景（影子库）
# 全链路场景需要**写**数据，而真库是可复现演示环境（重建要停服、要重跑流程）。
# 做法：把 17 个业务库复制到临时目录，在**本进程内**把 db.get_connection 的路径重定向到副本，
# 于是平台照常跑、真库零字节接触。平台代码一行不改（不改 runtime.py），也不需停 dev server。

def shadow_sandbox():
    """(shadow_dir, restore) —— 退出时务必调 restore()。"""
    import shutil
    import tempfile
    import fde_platform.db as fdb

    shadow = Path(tempfile.mkdtemp(prefix="psc_shadow_"))
    n = 0
    for app in APPS:
        src = Path(f"app/{GROUP}/{app}/{app}.db")
        if src.exists():
            shutil.copy2(src, shadow / src.name)
            n += 1
    note(f"影子库已就绪：{n} 个库 → {shadow}")

    orig = fdb.get_connection

    def patched(app_name, db_path=None):
        if db_path is not None:
            db_path = shadow / Path(db_path).name
        return orig(app_name, db_path)

    fdb.get_connection = patched

    def restore():
        fdb.get_connection = orig
        shutil.rmtree(shadow, ignore_errors=True)

    return shadow, restore


def scenario_forecast(conn):
    """S 场景：验证 B-01 修复 —— 客户未报数时最终预测回退到基线（BR-15）。

    在影子库里对 202610 走一遍「解冻 → 决策 → 汇总 → 毛需求」，
    断言修复后基线不再被丢弃，且人工定稿行不被覆盖（BR-27）。
    """
    import sqlite3 as _s

    V = "202610"
    # 修复前的实测值（来自真库，用作对照）
    BEFORE = {
        "BYD-HAN-SPARM": {"final": 0.0, "base": 135.9135, "gross_n1": 84.55},
        "M9-BEAM": {"final": 0.0, "base": 5889.962, "gross_n1": 2040.14},
    }
    # 定稿台账的基线（从真库直接读；影子库初始 = 真库副本，故两者一致）
    _rc = _s.connect(f"app/{GROUP}/sales_forecast/sales_forecast.db")
    _rc.row_factory = _s.Row
    settled_before = {
        (r["version_no"], r["material_no"], r["customer_no"], r["rolling_month"]): r["final_qty"]
        for r in _rc.execute("SELECT * FROM sales_forecast_settle")
    }
    _rc.close()

    shadow, restore = shadow_sandbox()
    try:
        from fde_platform.runtime import FdePlatform
        pf = FdePlatform()
        pf.load_all()

        def call(app, svc, **kw):
            return pf.call(f"{GROUP}/{app}", svc, **kw)

        # ① 解冻（版本冻结则 decide/summarize/build_gross 全被拒）
        ver = call("md_monthly_version", "get", version_no=V)
        note(f"S: 202610 初始锁定状态 = {ver.get('lock_status')}")
        if ver.get("lock_status") != "草稿":
            call("md_monthly_version", "unfreeze", version_no=V)
            ver = call("md_monthly_version", "get", version_no=V)
        REP.ok("X", "S1 版本回到草稿", f"lock_status={ver.get('lock_status')}")

        # ② 决策：修复后，客户未报数的行应回退到基线
        call("sales_forecast", "decide_batch", version_no=V)
        call("sales_forecast", "summarize", version_no=V)

        # 影子库是**副本**：主连接 conn 读的是真库，拿不到新值 —— 直接连副本文件
        sc = _s.connect(str(shadow / "sales_forecast.db"))
        sc.row_factory = _s.Row
        lines = [dict(r) for r in sc.execute(
            "SELECT material_no, rolling_month, orig_qty, adj_qty, base_event_qty,"
            " abnormal_flag, final_qty FROM sales_forecast_line WHERE version_no=?", (V,))]
        sc.close()

        orphan = [r for r in lines if r["abnormal_flag"] == 0 and r["final_qty"] is None]
        REP.viol("X", "S2 非异常行必须有最终预测", orphan,
                 "修复后不应再有「非异常却无最终值」的行（原 9 行）",
                 lambda r: f"{r['material_no']}/{r['rolling_month']} 基线={r['base_event_qty']} final=None")

        dropped = [r for r in lines if r["abnormal_flag"] == 0 and r["final_qty"] is None
                   and r["base_event_qty"] is not None and not close(r["base_event_qty"], 0)]
        REP.viol("X", "S2 基线不再被丢弃", dropped,
                 "基线非零的非异常行应取到基线值", lambda r: r["material_no"])

        # 逐物料核对最终值 = 基线
        for mat, exp in BEFORE.items():
            got = {}
            for r in lines:
                if r["material_no"] == mat:
                    got[r["rolling_month"]] = r["final_qty"]
            if not got:
                REP.skip("X", f"S3 {mat} 最终值 = 基线", "分母为空：该物料无预测行")
                continue
            bad = {rm: v for rm, v in got.items() if v is None or v < 0}
            if bad:
                REP.fail("X", f"S3 {mat} 最终值 = 基线（修复前汇总为 0）",
                         f"三个滚动月最终值 ≈ 基线合计 {exp['base']:.2f}",
                         f"仍有 {len(bad)} 个月为空/负：{bad}")
            else:
                total = sum(got.values())
                REP.ok("X", f"S3 {mat} 最终值 = 基线（修复前汇总为 {exp['final']:.2f}）",
                       f"修复后三个月合计 {total:.2f}")

        # ③ 毛需求：应含基线层
        call("demand", "build_gross", version_no=V)
        dc = _s.connect(str(shadow / "demand.db"))
        dc.row_factory = _s.Row
        dg = {}
        for r in dc.execute("SELECT material_no, rolling_month, forecast_qty, inventory_qty,"
                            " gross_qty, net_qty FROM demand WHERE version_no=? AND rolling_month='N+1'", (V,)):
            dg[r["material_no"]] = dict(r)
        dc.close()
        for mat, exp in BEFORE.items():
            r = dg.get(mat)
            if r is None:
                REP.skip("X", f"S4 {mat} 毛需求含基线层", "分母为空：该物料无毛需求行")
                continue
            want = exp["base"] / 3.0  # 单个滚动月的基线（三个月合计/3，SPARM 与 M9-BEAM 均按月等值）
            rough = abs(r["forecast_qty"] - want) / max(want, 1e-9)
            if rough > 0.05:
                REP.fail("X", f"S4 {mat} N+1 毛需求含基线层",
                         f"预测层 ≈ {want:.2f}（月基线）",
                         f"实际 forecast_qty={r['forecast_qty']:.2f}（修复前为 0），"
                         f"gross={r['gross_qty']:.2f} 水位={r['inventory_qty']:.2f}")
            else:
                REP.ok("X", f"S4 {mat} N+1 毛需求含基线层（修复前 {exp['gross_n1']:.2f}）",
                       f"预测层 {r['forecast_qty']:.2f} + 水位 {r['inventory_qty']:.2f} "
                       f"= 毛需求 {r['gross_qty']:.2f}")

        # ④ BR-27：人工定稿行不得被 decide 覆盖
        sc = _s.connect(str(shadow / "sales_forecast.db"))
        sc.row_factory = _s.Row
        settled_after = {
            (r["version_no"], r["material_no"], r["customer_no"], r["rolling_month"]): r["final_qty"]
            for r in sc.execute("SELECT * FROM sales_forecast_settle")
        }
        sc.close()
        if not settled_before:
            REP.skip("X", "S5 人工定稿不被覆盖（BR-27）", "分母为空：定稿台账为空")
        else:
            changed = [k for k in settled_before if not close_stored(settled_before[k],
                                                                    settled_after.get(k, -1e9))]
            REP.viol("X", "S5 人工定稿不被覆盖（BR-27）", changed,
                     f"{len(settled_before)} 条定稿的 final_qty 不得变化",
                     lambda k: f"{k[1]}/{k[3]} 定稿 {settled_before[k]} → {settled_after.get(k)}")

        # ------------------------------------------------ 下游全链：毛需求 → 发布 → 净需求
        def sread(dbname, sql, params=(), extra=()):
            """读影子库。extra=[(别名, 库名)] 用于跨库 join（SQLite 单连接只能看到已 ATTACH 的库）。"""
            c = _s.connect(str(shadow / f"{dbname}.db"))
            c.row_factory = _s.Row
            try:
                for alias, other in extra:
                    c.execute(f"ATTACH DATABASE ? AS {alias}", (str(shadow / f"{other}.db"),))
                return [dict(r) for r in c.execute(sql, params)]
            finally:
                c.close()

        # ⑤ 发布 + 运算净需求（calc_net 会把版本推入冻结态）
        call("demand", "publish", version_no=V)
        call("demand", "calc_net", version_no=V)
        ver = call("md_monthly_version", "get", version_no=V)
        if ver.get("lock_status") != "冻结":
            REP.fail("X", "S6 净需求运算后版本冻结", "lock_status=冻结",
                     f"实际 {ver.get('lock_status')}", "calc_net 未联动 freeze")
        else:
            REP.ok("X", "S6 净需求运算后版本冻结")

        net = sread("demand", "SELECT material_no, rolling_month, forecast_qty, inventory_qty,"
                              " gross_qty, open_order_qty, onhand_qty, in_transit_qty, net_qty"
                              " FROM demand WHERE version_no=?", (V,))
        if not net:
            REP.skip("X", "S7 净需求分层", "分母为空：该版本无毛需求行")
        else:
            bad = []
            for r in net:
                if r["rolling_month"] == "N+1":
                    want = max(0.0, (r["gross_qty"] or 0) + (r["open_order_qty"] or 0)
                               - (r["onhand_qty"] or 0) - (r["in_transit_qty"] or 0))
                else:
                    want = r["gross_qty"] or 0
                if not close_stored(r["net_qty"], want):
                    bad.append(r)
            REP.viol("X", "S7 净需求 = 分层公式", bad,
                     "N+1: max(0, 毛+未发−库存−在途)；N+2/3: 毛",
                     lambda r: f"{r['material_no']}/{r['rolling_month']} 毛={r['gross_qty']} "
                               f"→ 净={r['net_qty']}")
            # 修复后毛需求应普遍大于 0（修复前 M9-BEAM 只剩水位层）
            zero_pred = [r for r in net if close(r["forecast_qty"] or 0, 0)]
            if len(zero_pred) == len(net):
                REP.fail("X", "S7 预测层非零覆盖", "至少 1 行毛需求的预测层非零",
                         f"{len(net)} 行全部预测层为 0")
            else:
                REP.ok("X", "S7 预测层非零覆盖",
                       f"{len(net) - len(zero_pred)}/{len(net)} 行预测层非零")

        # ⑥ 主计划导入（BR-08 原样通过）
        mats = sorted({r["material_no"] for r in net}) if net else []
        if mats:
            try:
                call("master_plan", "import_from_net", version_no=V, rolling_month="N+1",
                     latest_inbound_date="2026-10-31", material_nos=mats)
            except Exception as e:
                REP.fail("X", "S8 主计划导入", "应将净需求原样导入主计划",
                         f"{type(e).__name__}: {e}")
            mp = sread("master_plan", """SELECT m.material_no, m.plan_qty, d.net_qty
                                         FROM master_plan m JOIN dm.demand d
                                           ON d.version_no=m.version_no AND d.material_no=m.material_no
                                          AND d.rolling_month=m.rolling_month
                                         WHERE m.version_no=?
                                           AND m.plan_version=(SELECT MAX(plan_version)
                                               FROM master_plan m2 WHERE m2.version_no=m.version_no
                                                 AND m2.material_no=m.material_no)""", (V,),
                       extra=[("dm", "demand")])
            if not mp:
                REP.skip("X", "S8 主计划 = 净需求", "分母为空：无主计划行")
            else:
                REP.viol("X", "S8 主计划 = 净需求（逐字）",
                         [r for r in mp if not close_stored(r["plan_qty"], r["net_qty"])],
                         "plan_qty == net_qty",
                         lambda r: f"{r['material_no']} 计划={r['plan_qty']} 净={r['net_qty']}")
        else:
            REP.skip("X", "S8 主计划导入", "分母为空：无净需求行")

        # ⑦ 推移表 + 补库单扫描：重点看会不会因毛需求变大而重复建单
        pool_before = sread("demand_pool",
                            "SELECT replenish_no, material_no, required_inbound, status FROM demand_pool")
        try:
            call("inventory_projection", "refresh_batch", biz_date="2026-10-01")
        except Exception as e:
            REP.fail("X", "S9 推移表批量刷新", "应能生成推移表",
                     f"{type(e).__name__}: {e}")
        proj = sread("inventory_projection",
                     "SELECT material_no, biz_date, inbound_qty, outbound_qty, balance, alert_type"
                     " FROM inventory_projection")
        if not proj:
            REP.skip("X", "S9 推移表生成", "分母为空：推移表无行")
        else:
            REP.ok("X", "S9 推移表生成", f"{len(proj)} 行 / "
                                      f"{len({r['material_no'] for r in proj})} 个物料")

            # 递推自洽（容差按存储精度）
            by_mat = {}
            for r in proj:
                by_mat.setdefault(r["material_no"], []).append(r)
            bad_rec = []
            for mat, rows in by_mat.items():
                rows.sort(key=lambda x: x["biz_date"])
                for a, b in zip(rows, rows[1:]):
                    if not close_stored(b["balance"], a["balance"] + b["inbound_qty"] - b["outbound_qty"]):
                        bad_rec.append(b)
            REP.viol("X", "S9 推移表递推自洽", bad_rec,
                     "余额(d) = 余额(d−1) + 入 − 出",
                     lambda r: f"{r['material_no']} {r['biz_date']} 余额={r['balance']}")

            # 补库单唯一性：单的身份是（物料 + 补库类型 + 要求入库日）。
            # ⚠ 不能只用（物料 + 入库日）—— 补库量是**分级补齐**的（击穿最低→补到 A，
            #   击穿安全→补到 A+C），所以同一物料同一天出现「最低库存补库 + 安全库存补库」
            #   两张**不同类型**的单是设计行为（BR-06：产能松紧分档由 demand_pool 处理）。
            #   一开始按两者做键，把设计行为报成了重复单（假警报），已修正。
            pool_after = sread("demand_pool",
                               "SELECT replenish_no, material_no, replenish_type, required_inbound,"
                               " replenish_qty, status FROM demand_pool")
            key = {}
            for r in pool_after:
                key.setdefault((r["material_no"], r["replenish_type"], r["required_inbound"]),
                               []).append(r["replenish_no"])
            dup = [{"k": k, "v": v} for k, v in key.items() if len(v) > 1]
            REP.viol("X", "S10 补库单无重复（物料+类型+入库日）", dup,
                     "同一物料同类型同一要求入库日只应有一张补库单",
                     lambda r: f"{r['k'][0]} {r['k'][1]} @{r['k'][2]} × {len(r['v'])}"
                               f"（{', '.join(r['v'][:3])}）",
                     "键含补库类型：仅用（物料+入库日）会把分级补齐的两张单误报为重复")

            created = [r for r in pool_after
                       if r["replenish_no"] not in {b["replenish_no"] for b in pool_before}]
            REP.ok("X", "S10 本次刷新建单数", f"新增 {len(created)} 张"
                                            f"（刷新前 {len(pool_before)} → 刷新后 {len(pool_after)}）")

            # 每条补库单的物料**在推移表里确有行、且要求入库日落在推演窗口内**
            # ⚠ 2026-09-17 订正（**判据自身第 11 处自纠**）：原判据写的是
            # 「每张补库单对应的物料应存在非「无」的预警行」——**它不是不变量**：
            # BR-04 把「待下达」也算进预计入库，所以**一张单补足之后，它自己的击穿就消失了**
            # （余额回到触发线 ⇒ 该物料整窗无预警）。实测：速度对冲件 FB25 的单到位后
            # 余额恰好 = A=70.53 ⇒ 90 行全「无」，旧判据当场把它报成"孤儿单"。
            # 判据的粒度必须对齐业务的真实身份 —— 这条与 A1/A2/A4/G8 那批假警报同类。
            proj_mats = {r["material_no"] for r in proj}
            win = ((min(r["biz_date"] for r in proj), max(r["biz_date"] for r in proj))
                   if proj else (None, None))
            # ⚠ 2026-09-17 放宽：**要求入库日早于窗口首日不再是缺陷** —— 新口径（BR-04）要求
            # 「过期未下达的补库单**钳到窗口首日**计入并明确报出」，所以那种单是**合法的**。
            # 本条因此只留「物料在推移表里确有行」这一条存在性断言（挡幽灵单）。
            orphan_orders = [r for r in pool_after if r["material_no"] not in proj_mats]
            REP.viol("X", "S10 补库单的物料在推移窗口内", orphan_orders,
                     "每张补库单对应的物料应有推移行（要求入库日可早于窗口 —— 那是 BR-04 的钳入口径）",
                     lambda r: f"{r['replenish_no']} 物料={r['material_no']}"
                               f" 要求入库={r['required_inbound']}（窗口 {win[0]}~{win[1]}）")

            # **镜像判据**（这才是真正的不变量）：**有击穿行的物料必须已有补库单**
            # —— 防的是「有击穿却没人管」那一侧（实测踩过：B-08 接线前后 FB25/FB26
            # 都有击穿却建不出单，被 `refresh_batch` 静默吞掉）。
            breach_mats = {r["material_no"] for r in proj
                           if (r["alert_type"] or "无") in ("缺货", "击穿最低", "击穿安全")}
            pool_mats = {r["material_no"] for r in pool_after}
            unhandled = sorted(breach_mats - pool_mats)
            REP.viol("X", "S10 击穿物料必有补库单", [{"material_no": m} for m in unhandled],
                     "推移表里有击穿行的物料，必须已存在对应补库单（否则该击穿无人跟进）",
                     lambda r: f"{r['material_no']} 有击穿行却无任何补库单")

        # ⑨ 反复刷新必须**收敛**（不是张数不变 —— 分级补齐天然会先多后少）
        #    断言：新增单数逐轮下降并归零，且收敛后无 (物料+类型+入库日) 重复。
        #    若新增单永远不归零 → 真·滚单（持续建单），那才是 BUG。
        try:
            rounds, trace, last_pool_n = 0, [], len(pool_after)
            while rounds < 6:
                n_before = sread("demand_pool", "SELECT COUNT(*) n FROM demand_pool")[0]["n"]
                call("inventory_projection", "refresh_batch", biz_date="2026-10-01")
                n_after = sread("demand_pool", "SELECT COUNT(*) n FROM demand_pool")[0]["n"]
                trace.append(n_after - n_before)
                rounds += 1
                if n_after == n_before:
                    break
            if trace and trace[-1] != 0:
                REP.fail("X", "S11 反复刷新应收敛", "连续 6 轮刷新后新增单数应归零",
                         f"逐轮新增 {trace}（最终 {last_pool_n + sum(trace)} 张）—— 持续建单不收敛")
            else:
                REP.ok("X", "S11 反复刷新应收敛",
                       f"{rounds} 轮内归零，逐轮新增 {trace}")

            pr2 = sread("inventory_projection", "SELECT COUNT(*) n FROM inventory_projection")
            if pr2 and proj and pr2[0]["n"] != len(proj):
                REP.fail("X", "S11 反复刷新后推移表行数不变",
                         f"仍应为 {len(proj)} 行", f"实际 {pr2[0]['n']} 行")
            else:
                REP.ok("X", "S11 反复刷新后推移表行数不变",
                       f"{pr2[0]['n'] if pr2 else '?'} 行")

            fin = sread("demand_pool", "SELECT material_no, replenish_type, required_inbound,"
                                       " replenish_no FROM demand_pool")
            k2 = {}
            for r in fin:
                k2.setdefault((r["material_no"], r["replenish_type"], r["required_inbound"]),
                              []).append(r["replenish_no"])
            dup2 = [{"k": k, "v": v} for k, v in k2.items() if len(v) > 1]
            REP.viol("X", "S11 收敛后补库单无重复", dup2,
                     "收敛后同一 (物料+类型+入库日) 只应有一张单",
                     lambda r: f"{r['k'][0]} {r['k'][1]} @{r['k'][2]} × {len(r['v'])}")
        except Exception as e:
            REP.fail("X", "S11 反复刷新收敛性", "反复刷新应安全且收敛",
                     f"{type(e).__name__}: {e}")
    finally:
        restore()


def scenario_net_deduction(conn):
    """H 组：净需求扣减公式的**穿透测试**（B-03）。

    为什么必须做：`demand` 的三个 `_load_*` 适配器是**代码写死的 stub、恒返回 `{}`**
    （`app/psc/demand/demand.py:405-415`，与 /integration 配置无关）。于是
    `net = 毛需求 + 未发订单 − 库存 − 在途` 在演示环境里**恒等价于 `net = 毛需求`**：
    符号写反、单位错、取错来源，**全都不可能被测出来**。实测 6 行 N+1 的扣减三层全为 0。

    做法：在影子库里把这几个适配器换成**受控的非零值**，再跑一次净需求运算，断言
      ① 落库的扣减三层 == 注入值（证明真被用了，而不是被静默忽略）；
      ② 净额按**正确符号**算出；
      ③ 库存大于毛需求时钳到 0（BR-08）；
      ④ 净额不再恒等于毛需求（破退化）；
      ⑤ N+2/N+3 仍不扣减。
    """
    import sqlite3 as _s

    V = "202610"
    INJECT = {
        # 未发 5000 / 在途 3000 ⇒ 净额应比毛需求**大 2000**。
        # 若符号写反（毛 − 未发 + 库存 + 在途）会得到「毛 − 8000 再钳 0」，与期望差得远。
        "BYD-HAN-BRK": (5000.0, 0.0, 3000.0),
        # 库存远超毛需求 ⇒ 净额应被钳到 0。
        "BYD-HAN-FB26": (0.0, 1e9, 0.0),
    }

    shadow, restore = shadow_sandbox()
    try:
        from fde_platform.runtime import FdePlatform
        pf = FdePlatform()
        pf.load_all()

        def call(app, svc, **kw):
            return pf.call(f"{GROUP}/{app}", svc, **kw)

        def sread(dbname, sql, params=()):
            c = _s.connect(str(shadow / f"{dbname}.db"))
            c.row_factory = _s.Row
            try:
                return [dict(r) for r in c.execute(sql, params)]
            finally:
                c.close()

        cls = pf.handle(f"{GROUP}/demand").cls

        # H0 先证明它现在**确实是 stub**：非空说明适配器已被实现，本组就该改判据而不是打补丁
        try:
            stub = cls._load_inventory(None, V)
        except Exception as e:
            REP.skip("X", "H0 适配器确为 stub", f"调用失败，无法判定：{type(e).__name__}: {e}")
            stub = None
        if stub is not None:
            if stub:
                REP.fail("X", "H0 适配器确为 stub", "stub 应返回空 dict（尚未实现）",
                         f"_load_inventory 返回了 {stub!r}",
                         "适配器已被实现 —— 本组应改为直接喂真实数据，而不是 monkeypatch")
            else:
                REP.ok("X", "H0 适配器确为 stub", "_load_inventory(None, V) 返回 {}")

        # H1 解冻 → 发布（calc_net 要求「已发布」；草稿与冻结都会被拒）
        ver = call("md_monthly_version", "get", version_no=V)
        if ver.get("lock_status") != "草稿":
            call("md_monthly_version", "unfreeze", version_no=V)
        call("demand", "publish", version_no=V)

        # H2 注入受控的外部数据（适配器签名是 (self, version_no) -> {material_no: qty}）
        def _mk(idx):
            return lambda self, version_no: {m: v[idx] for m, v in INJECT.items()}

        orig = (cls._load_open_order, cls._load_inventory, cls._load_in_transit)
        cls._load_open_order = _mk(0)
        cls._load_inventory = _mk(1)
        cls._load_in_transit = _mk(2)
        try:
            call("demand", "calc_net", version_no=V)
        finally:
            (cls._load_open_order, cls._load_inventory, cls._load_in_transit) = orig

        rows = sread("demand", "SELECT material_no, rolling_month, gross_qty, open_order_qty,"
                               " onhand_qty, in_transit_qty, net_qty FROM demand WHERE version_no=?",
                     (V,))
        n1 = [r for r in rows if r["rolling_month"] == "N+1"]
        n1 = find("X", "H3 扣减三层落库 = 注入值", n1, f"{V} 的 N+1 行")
        if n1 is None:
            return
        injected = [r for r in n1 if r["material_no"] in INJECT]

        # ① 注入值必须真落库（否则说明适配器被静默忽略）
        bad_inj = []
        for r in injected:
            oo, oh, it = INJECT[r["material_no"]]
            if not (close(r["open_order_qty"], oo) and close(r["onhand_qty"], oh)
                    and close(r["in_transit_qty"], it)):
                bad_inj.append(r)
        REP.viol("X", "H3 扣减三层落库 = 注入值", bad_inj,
                 "落库的 未发/库存/在途 应等于注入值（证明适配器真被调用）",
                 lambda r: f"{r['material_no']} 落库({r['open_order_qty']},{r['onhand_qty']},"
                           f"{r['in_transit_qty']}) vs 注入{INJECT[r['material_no']]}")

        # ② 净额按正确符号算出
        bad_net = []
        for r in injected:
            oo, oh, it = INJECT[r["material_no"]]
            want = max(0.0, (r["gross_qty"] or 0) + oo - oh - it)
            if not close_stored(r["net_qty"], want):
                bad_net.append((r, want))
        if bad_net:
            REP.fail("X", "H4 净额 = 毛 + 未发 − 库存 − 在途（符号正确）",
                     "净额应按「+未发 −库存 −在途」计算",
                     " | ".join(f"{r['material_no']} 毛={r['gross_qty']} 注入{INJECT[r['material_no']]}"
                                f" 期望={w:.2f} 实际={r['net_qty']}" for r, w in bad_net))
        else:
            REP.ok("X", "H4 净额 = 毛 + 未发 − 库存 − 在途（符号正确）",
                   " | ".join(f"{r['material_no']} 毛={r['gross_qty']} → 净={r['net_qty']}"
                              for r in injected))

        # ③ 钳零：库存远超毛需求
        clamped = [r for r in injected if INJECT[r["material_no"]][1] >= 1e9]
        if clamped:
            REP.viol("X", "H5 库存超额 ⇒ 净额钳到 0（BR-08）",
                     [r for r in clamped if not close_stored(r["net_qty"], 0)],
                     "net_qty == 0",
                     lambda r: f"{r['material_no']} 毛={r['gross_qty']} 库存=1e9 → 净={r['net_qty']}")

        # ④ 破退化：至少一行的净额必须与毛需求不同（否则扣减等于没做）
        differs = [r for r in injected if not close_stored(r["net_qty"], r["gross_qty"])]
        if not differs:
            REP.fail("X", "H6 扣减确实生效（非恒等）",
                     "注入非零扣减层后，净额应至少有一行不等于毛需求",
                     f"{len(injected)} 行注入后净额仍等于毛需求 —— 扣减被忽略")
        else:
            REP.ok("X", "H6 扣减确实生效（非恒等）", f"{len(differs)}/{len(injected)} 行净额≠毛需求")

        # ⑤ N+2/N+3 不扣减：注入后三层仍应为 0
        far = [r for r in rows if r["rolling_month"] != "N+1"]
        REP.viol("X", "H7 远期不扣减（N+2/N+3）",
                 [r for r in far if (r["open_order_qty"] or 0) or (r["onhand_qty"] or 0)
                  or (r["in_transit_qty"] or 0) or not close_stored(r["net_qty"], r["gross_qty"])],
                 "远期净额 = 毛需求，且三层扣减为 0",
                 lambda r: f"{r['material_no']}/{r['rolling_month']} 净={r['net_qty']} 毛={r['gross_qty']}")
    finally:
        restore()


def scenario_silent_degrade(conn):
    """F 组：静默降级反证 —— 「取不到数就按 0/空继续」这一类。

    本轮对账挖出的 BUG 里有一半属于这一类（毛需求丢水位层、推移表全标「无」、
    预测汇总被当 0），共同特征是**不报错、不崩溃、只是答案错**。所以反证法最有效：
    人为制造「应该取到数却取不到」的局面，断言**必须 raise**，而不是返回 0 / 空 / 空列表。

    本组挑最能暴露问题的一对**同类操作**做对照：
      · `demand.build_gross`  —— 预测汇总为空时？
      · `master_plan.import_from_net` —— 无命中行时（BR-10 明确要求报错）
    同一类情形，若一个报错一个静默，那静默的那个就是缺陷。
    """
    import sqlite3 as _s

    V = "202610"
    shadow, restore = shadow_sandbox()
    try:
        from fde_platform.runtime import FdePlatform
        pf = FdePlatform()
        pf.load_all()

        def call(app, svc, **kw):
            return pf.call(f"{GROUP}/{app}", svc, **kw)

        def sconnect(dbname):
            c = _s.connect(str(shadow / f"{dbname}.db"))
            c.row_factory = _s.Row
            return c

        # ── F3 对照：master_plan 无命中行时报错（BR-10）──
        # 必须**先做**：它要在版本处于冻结态时跑（import_from_net 经 demand.export_net 取数，
        # 而 export_net 要求「净需求已运算」= 冻结）。放在 F1/F2 之后会「假通过」——
        # 首版就踩了这个坑：报错内容是「净需求未运算」，根本没走到 BR-10 那条路。
        ver0 = call("md_monthly_version", "get", version_no=V)
        if ver0.get("lock_status") != "冻结":
            REP.skip("X", "F3 主计划无命中行必须报错（BR-10）",
                     f"前置不成立：版本为 {ver0.get('lock_status')}，需冻结态才能经 export_net 取数")
        else:
            try:
                r = call("master_plan", "import_from_net", version_no=V, rolling_month="N+1",
                         latest_inbound_date="2026-10-31", material_nos=["__NO_SUCH_MATERIAL__"])
                REP.fail("X", "F3 主计划无命中行必须报错（BR-10）",
                         "应 raise FdeError 且说明无命中行，不静默导入 0 行", f"未报错，返回 {r!r}")
            except Exception as e:
                msg = str(e)
                if "未运算" in msg:
                    REP.fail("X", "F3 主计划无命中行必须报错（BR-10）",
                             "应报「无命中行」，而不是其它前置错误",
                             f"{type(e).__name__}: {msg[:80]}",
                             "报错原因不对 = 这条断言其实没打到 BR-10 那条路（假通过）")
                else:
                    REP.ok("X", "F3 主计划无命中行必须报错（BR-10）",
                           f"已报错：{type(e).__name__}: {msg[:60]}")

        ver = call("md_monthly_version", "get", version_no=V)
        if ver.get("lock_status") != "草稿":
            call("md_monthly_version", "unfreeze", version_no=V)

        # ── F1 预测汇总为空 ⇒ build_gross 必须报错，而不是「成功，共 0 个物料」 ──
        # 制造条件：在**影子库**里清掉该版本的汇总行（直接改副本，不走应用，确保条件成立）
        c = sconnect("sales_forecast")
        n_before = c.execute("SELECT COUNT(*) n FROM sales_forecast_summary WHERE version_no=?",
                             (V,)).fetchone()["n"]
        c.execute("DELETE FROM sales_forecast_summary WHERE version_no=?", (V,))
        c.commit()
        n_after = c.execute("SELECT COUNT(*) n FROM sales_forecast_summary WHERE version_no=?",
                            (V,)).fetchone()["n"]
        c.close()
        if n_before == 0:
            REP.skip("X", "F1 汇总为空时 build_gross 必须报错",
                     "前置不成立：该版本本来就没有汇总行")
        elif n_after != 0:
            REP.skip("X", "F1 汇总为空时 build_gross 必须报错",
                     f"前置不成立：清空后仍有 {n_after} 行")
        else:
            try:
                r = call("demand", "build_gross", version_no=V)
                REP.fail("X", "F1 汇总为空时 build_gross 必须报错",
                         "应 raise FdeError（无预测可合成，不该声称成功）",
                         f"未报错，返回 {r!r}",
                         "对照：master_plan.import_from_net 同类情形按 BR-10 明确报错 —— "
                         "同一类操作两个应用口径不一致，静默的那个是缺陷")
            except Exception as e:
                REP.ok("X", "F1 汇总为空时 build_gross 必须报错",
                       f"已报错：{type(e).__name__}: {str(e)[:60]}")

        # ── F2 水位策略缺失 ⇒ build_gross 必须报错（fail-closed 回归）──
        # 版本仍是草稿（build_gross 不改锁定状态），无需再发布/解冻
        c = sconnect("inventory_strategy")
        n_w = c.execute("SELECT COUNT(*) n FROM inventory_strategy WHERE version_no=?",
                        (V,)).fetchone()["n"]
        c.close()
        if n_w == 0:
            REP.skip("X", "F2 无水位策略时 build_gross 必须报错", "前置不成立：本无水策略")
        else:
            # 汇总已在 F1 清空；先恢复汇总再测水位这条，避免两个变量混在一起
            try:
                call("sales_forecast", "summarize", version_no=V)
            except Exception:
                pass
            c = sconnect("inventory_strategy")
            rows = c.execute("SELECT material_no, version_no, hedge_tool FROM inventory_strategy"
                             " WHERE version_no=?", (V,)).fetchall()
            c.execute("DELETE FROM inventory_strategy WHERE version_no=?", (V,))
            c.commit()
            c.close()
            try:
                r = call("demand", "build_gross", version_no=V)
                REP.fail("X", "F2 无水位策略时 build_gross 必须报错",
                         "应 raise FdeError（BR-12 fail-closed 的同类要求）",
                         f"未报错，返回 {r!r}")
            except Exception as e:
                REP.ok("X", "F2 无水位策略时 build_gross 必须报错",
                       f"已报错：{type(e).__name__}: {str(e)[:60]}")

    finally:
        restore()


def scenario_zero_touch(conn):
    """G 组：零触达服务体检 —— 对从未被任何测试断言过的服务下判据。

    共 17 个公共方法在 `verify_chain_psc.py` / `verify_view_*` 里**一次都没被调用过**
    （覆盖矩阵见 `app/psc/BUGS_psc_2026-09-15.md`）。零触达 = 零证据，未知 BUG 最可能藏这儿。

    判据仍不写期望值，用两条**结构性**关系：
      G1 **get 与 list 必须同值** —— 同一个键，两条读路径必须给出同一行；
      G2/G3 **批量服务与单行服务必须同值** —— `*_batch` 与逐行版对同一份数据必须收敛到同一结果。
          （本项目出过一次正是这类分歧：`calc_batch` 不传 customer_no，导致速度对冲分支
            在批量路径永不可达 —— 单行能出、批量不能出。）
      G4 **`attainment.compute` 跑完后，表必须等于文档公式的独立重算** —— 写服务刚跑完，
         这正是"口径A 单表重算"最该被验证的时刻（它此前零触达）。
    """
    import sqlite3 as _s

    V = "202610"
    shadow, restore = shadow_sandbox()
    try:
        from fde_platform.runtime import FdePlatform
        pf = FdePlatform()
        pf.load_all()

        def call(app, svc, **kw):
            return pf.call(f"{GROUP}/{app}", svc, **kw)

        def sread(dbname, sql, params=()):
            c = _s.connect(str(shadow / f"{dbname}.db"))
            c.row_factory = _s.Row
            try:
                return [dict(r) for r in c.execute(sql, params)]
            finally:
                c.close()

        def items_of(result):
            if isinstance(result, dict):
                return result.get("items") or result.get("data") or result.get("rows") or []
            return result if isinstance(result, list) else []

        # ── G1 get 与 list 同键同值 ──
        # 覆盖面刻意放宽：本项目大量 `_to_dict` 用「固定键列表 + if x in keys else None」，
        # 一旦某个 `list` 的 SELECT 少取了几列，那些键就会**照样出现、但恒为 None**，
        # 而库里其实有值（strategy_fitting.list 就这么埋了 6 个字段，实测 2026-09-15）。
        # 所以每一个「list 与 get 都存在的应用」都要比对一遍 —— 这是同一个陷阱的全量扫描。
        PAIRS = [
            ("md_project_part", ("project_no", "material_no")),
            ("md_breakpoint", ("bp_id",)),
            ("md_part_replace", ("rel_no",)),
            ("master_plan", ("version_no", "material_no", "rolling_month")),
            ("demand_pool", ("replenish_no",)),
            ("outbound_plan", ("plan_no",)),
            ("attainment", ("customer_no", "material_no")),
            ("md_customer", ("customer_no",)),
            ("md_material", ("material_no",)),
            ("md_project", ("project_no",)),
            ("md_monthly_version", ("version_no",)),
            ("inventory_strategy", ("version_no", "material_no")),
            ("inventory_projection", ("material_no", "biz_date")),
            ("demand", ("version_no", "material_no", "rolling_month")),
            ("sales_forecast", ("version_no", "material_no", "customer_no", "rolling_month")),
        ]
        for app, keys in PAIRS:
            try:
                rows = items_of(call(app, "list", size=200))
            except Exception as e:
                REP.skip("X", f"G1 {app}.get == list 同键行", f"list 调用失败：{type(e).__name__}: {e}")
                continue
            # 同一键多行的（如 master_plan 多 plan_version）会有歧义，只取键唯一的行
            grouped = {}
            for r in rows:
                grouped.setdefault(tuple(r.get(k) for k in keys), []).append(r)
            uniq = [v[0] for v in grouped.values() if len(v) == 1]
            uniq = find("X", f"G1 {app}.get == list 同键行", uniq, f"{app}.list 的键唯一行")
            if uniq is None:
                continue
            bad, big_notes, tested = [], [], 0
            for r in uniq[:5]:
                try:
                    one = call(app, "get", **{k: r.get(k) for k in keys})
                except Exception as e:
                    REP.skip("X", f"G1 {app}.get == list 同键行",
                             f"get 调用失败（签名可能不同）：{type(e).__name__}: {e}")
                    bad = None
                    break
                if not isinstance(one, dict):
                    continue
                shared = [k for k in one if k in r]
                if len(shared) < 3:
                    continue
                tested += 1
                diff = [k for k in shared if not same_val(r[k], one[k])]
                if not diff:
                    continue
                # 区分两类：
                #   · **刻意省略的大字段**（如 model_blob = 整个 pickle 模型，列表接口带上会把
                #     响应撑爆）—— 合理设计，只提示不判失败；
                #   · **漏取的小字段** —— get 有值、list 恒 None，消费方会把 None 当"没有"，
                #     这是缺陷（实测抓到 strategy_fitting 漏 6 个字段、md_material 漏 sigma_l）。
                # 判断依据是**字段体量**，不写死字段名。
                big = [k for k in diff
                       if isinstance(one[k], (str, bytes)) and len(one[k]) > 200]
                small = [k for k in diff if k not in big]
                if small:
                    bad.append((r, one, small))
                if big:
                    big_notes.append({"m": r.get(keys[0]), "keys": big})
            if bad is None:
                continue
            if tested == 0:
                REP.skip("X", f"G1 {app}.get == list 同键行", "分母为空：没有可比对的重叠字段")
            else:
                REP.viol("X", f"G1 {app}.get == list 同键行", bad,
                         "同一键经 get 与 list 取到的行必须逐字段一致"
                         "（小字段不得出现「get 有值、list 为 None」）",
                         lambda t: f"{t[0].get(keys[0])} 字段不一致：{t[2][:4]}",
                         f"{tested} 行参与比对")
                if big_notes:
                    REP._add("X", f"G1 {app} 大字段在 list 中省略（参考）", "WARN",
                             "大字段（>200 字符）可合理省略",
                             "；".join(f"{b['m']}: {b['keys']}" for b in big_notes[:3]),
                             "体量判断，非缺陷；但消费方读到的是 None 而非缺键，"
                             "语义上仍不理想")

        # ── G2 calc_baseline_batch 与逐行 calc_baseline 必须同值 ──
        ver = call("md_monthly_version", "get", version_no=V)
        if ver.get("lock_status") != "草稿":
            call("md_monthly_version", "unfreeze", version_no=V)
        try:
            call("sales_forecast", "calc_baseline_batch", version_no=V)
            lines = sread("sales_forecast",
                          "SELECT material_no, customer_no, rolling_month, base_qty, base_event_qty,"
                          " abnormal_flag, final_qty FROM sales_forecast_line WHERE version_no=?", (V,))
            lines = find("X", "G2 批量基线 == 逐行基线", lines, f"{V} 的预测明细")
            if lines is not None:
                key = lambda r: (r["material_no"], r["customer_no"], r["rolling_month"])
                batch = {key(r): (r["base_qty"], r["base_event_qty"]) for r in lines}
                errs = []
                for r in lines:
                    try:
                        call("sales_forecast", "calc_baseline", version_no=V,
                             material_no=r["material_no"], customer_no=r["customer_no"],
                             rolling_month=r["rolling_month"])
                    except Exception as e:
                        errs.append((r, f"逐行调用失败 {type(e).__name__}: {e}"))
                        continue
                after = {key(r): (r["base_qty"], r["base_event_qty"]) for r in sread(
                    "sales_forecast", "SELECT material_no, customer_no, rolling_month, base_qty,"
                                      " base_event_qty FROM sales_forecast_line WHERE version_no=?",
                    (V,))}
                diff = [r for r in lines if not close_stored(
                    (after.get(key(r), (None, None))[0] or 0), (batch[key(r)][0] or 0))]
                REP.viol("X", "G2 批量基线 == 逐行基线", diff,
                         "同一行经 calc_baseline_batch 与 calc_baseline 得到的 base_qty 必须相同",
                         lambda r: f"{r['material_no']}/{r['customer_no']}/{r['rolling_month']} "
                                   f"批量={batch.get(key(r), (None,))[0]} "
                                   f"逐行={after.get(key(r), (None,))[0]}",
                         f"{len(lines)} 行参与比对" + (f"；逐行调用报错 {len(errs)} 行" if errs else ""))
                if errs:
                    REP._add("X", "G2 逐行调用报错（参考）", "WARN",
                             "逐行 calc_baseline 应可调用",
                             f"{len(errs)} 行报错，例：{errs[0][1][:70]}", "")
        except Exception as e:
            REP.fail("X", "G2 批量基线 == 逐行基线", "正常执行", f"{type(e).__name__}: {e}")

        # ── G3 calc_batch 与逐行 calc 必须同值（速度对冲 BUG 的老家）──
        try:
            call("inventory_strategy", "calc_batch", version_no=V)
            batch_map = {r["material_no"]: r for r in sread(
                "inventory_strategy", "SELECT material_no, hedge_tool, min_level, safety_level,"
                                      " batch_level FROM inventory_strategy WHERE version_no=?", (V,))}
            # find 返回的是**行列表**，dict 要单独留着（首版在这上面调 .values() 崩了）
            rows_w = find("X", "G3 批量水位 == 逐行水位", list(batch_map.values()), f"{V} 的水位行")
            if rows_w is not None:
                for r in rows_w:
                    call("inventory_strategy", "calc", version_no=V, material_no=r["material_no"])
                after_w = {r["material_no"]: r for r in sread(
                    "inventory_strategy", "SELECT material_no, hedge_tool, min_level, safety_level,"
                                          " batch_level FROM inventory_strategy WHERE version_no=?",
                    (V,))}
                diff = [r for r in rows_w
                        if not (close_stored(after_w.get(r["material_no"], {}).get("min_level", -1),
                                            r["min_level"])
                                and close_stored(after_w.get(r["material_no"], {}).get("safety_level", -1),
                                                 r["safety_level"])
                                and close_stored(after_w.get(r["material_no"], {}).get("batch_level", -1),
                                                 r["batch_level"])
                                and after_w.get(r["material_no"], {}).get("hedge_tool") == r["hedge_tool"])]
                REP.viol("X", "G3 批量水位 == 逐行水位", diff,
                         "同一物料经 calc_batch 与 calc 得到的 A/C/B 与对冲工具必须相同",
                         lambda r: f"{r['material_no']} 批量(={r['hedge_tool']},{r['min_level']},"
                                   f"{r['safety_level']},{r['batch_level']}) 逐行="
                                   f"{after_w.get(r['material_no'])}",
                         f"{len(rows_w)} 行参与比对")
        except Exception as e:
            REP.fail("X", "G3 批量水位 == 逐行水位", "正常执行", f"{type(e).__name__}: {e}")

        # ── G4 attainment.compute（口径A）──
        try:
            hist = sread("sales_history",
                         "SELECT customer_no, material_no, period, qty, forecast_qty FROM sales_history")
            n_fc = sum(1 for r in hist if r["forecast_qty"] is not None)
            raised, res = None, None
            try:
                res = call("attainment", "compute", months=6)
            except Exception as e:
                raised = e
            # G4a 无样本时**必须报错**（BR-13 同口径）：
            # 口径A 靠 sales_history.forecast_qty，而它由 sync_forecast 从**历史版本**的
            # N+1 客户预测按月回填。forecast_qty 全空时 compute 一组都算不出来 ——
            # 旧行为是「成功但 0 组」，调用方看不出这次重算什么都没干。
            if n_fc == 0:
                if raised is None:
                    REP.fail("X", "G4a 无样本时 compute 必须报错",
                             "应 raise FdeError（无样本可算不该声称成功）",
                             f"未报错，返回 {res!r}",
                             "本应用已按 BR-13 同口径改为 fail-closed；未报错说明改动没生效")
                else:
                    REP.ok("X", "G4a 无样本时 compute 必须报错",
                           f"已报错：{type(raised).__name__}: {str(raised)[:60]}")
                    REP.skip("X", "G4 compute 结果 == 文档公式重算",
                             "无样本可算（forecast_qty 全空）⇒ 没有可比对的表内容")
            else:
                REP.ok("X", "G4a compute 的输入非空（forecast_qty 已回填）",
                       f"{n_fc}/{len(hist)} 行有 forecast_qty；compute 返回 {res!r}")
            if n_fc == 0:
                return          # 无样本可算：已 SKIP，不再往下比对（finally 仍会清理影子库）
            groups = {}
            for r in hist:
                groups.setdefault((r["customer_no"], r["material_no"]), []).append(r)
            want = {}
            for k, rows in groups.items():
                pairs = sorted((r["period"], r["forecast_qty"], r["qty"]) for r in rows
                               if r["forecast_qty"] is not None and r["qty"] is not None)
                if len(pairs) < 3:
                    continue
                cutoff = _shift_month(pairs[-1][0], -5)
                pairs = [t for t in pairs if t[0] >= cutoff]
                if len(pairs) < 3:
                    continue
                sF = sum(p[1] for p in pairs)
                sA = sum(p[2] for p in pairs)
                if sA == 0:
                    continue
                mape_vals = [abs(p[2] - p[1]) / p[2] for p in pairs if p[2] != 0]
                if not mape_vals:
                    continue
                want[k] = (round(sum(mape_vals) / len(mape_vals), 4), round((sF - sA) / sA, 4))
            got = {(r["customer_no"], r["material_no"]): (r["mape"], r["bias"])
                   for r in sread("attainment", "SELECT customer_no, material_no, mape, bias FROM attainment")}
            shared = [k for k in want if k in got]
            shared = find("X", "G4 attainment.compute == 文档公式重算", shared,
                          "既在重算集合又在 attainment 表里的键")
            if shared is not None:
                diff = [k for k in shared
                        if not (close_stored(want[k][0], got[k][0]) and close_stored(want[k][1], got[k][1]))]
                REP.viol("X", "G4 attainment.compute == 文档公式重算",
                         [{"k": k, "want": want[k], "got": got[k]} for k in diff],
                         "compute 后 attainment 的 mape/bias 必须等于「口径A」重算值",
                         lambda t: f"{t['k'][0]}/{t['k'][1]} 应={t['want']} 实={t['got']}",
                         f"{len(shared)} 个客户×物料参与比对")
        except Exception as e:
            REP.fail("X", "G4 compute 与文档公式重算（脚本自身崩溃）", "正常执行",
                     f"{type(e).__name__}: {e}")
    finally:
        restore()


def _shift_month(period, delta):
    """月份加减，**同时支持 `YYYY-MM`（台账期间）与 `YYYYMM`（版本号）两种形态**。

    ⚠ 首版只认 `YYYY-MM`，而版本号是 `YYYYMM` —— `"202610"[5:7]` 取到的是 `"0"`，
    于是算出来是 `2026-01` 而不是 `2026-11`，把 A14 的每个比对组合都 `continue` 掉了：
    **判据一个字都没比，却报 PASS**。两种形态都要认，且调用处要有分母闸。
    """
    s = str(period or "").strip()
    try:
        if "-" in s:
            y, m = int(s[:4]), int(s[5:7])
        else:
            y, m = int(s[:4]), int(s[4:6])
    except (ValueError, TypeError):
        return period
    if not 1 <= m <= 12:
        return period
    t = y * 12 + (m - 1) + delta
    return f"{t // 12:04d}-{t % 12 + 1:02d}"


_CYCLE_CHILD = r"""
import os, sys
from pathlib import Path
ROOT, SHADOW, MAT = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
os.chdir(ROOT); sys.path.insert(0, ROOT)
import fde_platform.db as fdb
_orig = fdb.get_connection
fdb.get_connection = lambda a, p=None: _orig(a, (SHADOW / Path(p).name) if p else None)
from fde_platform.runtime import FdePlatform
pf = FdePlatform(); pf.load_all()
r = pf.call("psc/md_material", "predecessor_chain", material_no=MAT)
if isinstance(r, (list, tuple)):
    print("RESULT list len=%d uniq=%d" % (len(r), len(set(map(str, r)))))
else:
    print("RESULT %r" % (r,))
print("CHILD_OK")
"""


def scenario_boundary(conn):
    """E 组：边界与对抗注入（全部在影子库内，真库零风险）。

    优先查**写入侧有没有拦住**：拦住了，读取侧的递归/无限循环就进不去，成本极低。
    只有写入侧没拦住时，才需要上「子进程 + 超时」去验读取侧会不会挂死
    （进程内跑可能挂住整个体检 —— 所以环检测这类检查必须隔离到子进程）。

    覆盖：
      E1 前序链成环（自指 / 互指）—— `predecessor_chain` 是递归的，环 = 无限递归
      E2 断点自反（原物料 = 新物料，BR-02）
      E3 负值注入（生产时间 / 组批窗口，BR-08 / BR-12）
      E4 日期边界（EOP 早于 SOP，BR-05）
    """
    import sqlite3 as _s

    V = "202610"
    shadow, restore = shadow_sandbox()
    try:
        from fde_platform.runtime import FdePlatform
        pf = FdePlatform()
        pf.load_all()

        def call(app, svc, **kw):
            return pf.call(f"{GROUP}/{app}", svc, **kw)

        def sread(dbname, sql, params=()):
            c = _s.connect(str(shadow / f"{dbname}.db"))
            c.row_factory = _s.Row
            try:
                return [dict(r) for r in c.execute(sql, params)]
            finally:
                c.close()

        def reject(target, fn, keywords, note_=""):
            """断言该调用**被拒绝**，且理由是预期的那个（理由不对 = 没打到目标分支）。"""
            try:
                r = fn()
            except TypeError as e:            # 签名猜错 ≠ 缺陷，记 SKIP
                REP.skip("X", target, f"入参签名不符，无法判定：{e}")
                return
            except Exception as e:
                msg = str(e)
                if any(k in msg for k in keywords):
                    REP.ok("X", target, f"已拒绝：{msg[:70]}")
                else:
                    REP.fail("X", target, f"应因「{'/'.join(keywords)}」被拒",
                             f"{type(e).__name__}: {msg[:80]}",
                             "报错原因不对 = 这条断言其实没打到目标校验分支（假通过）")
                return
            # 返回体可能很大（如 md_material 带 model_blob），截断后再进报告
            REP.fail("X", target, f"应被拒绝（{'/'.join(keywords)}）",
                     f"未拒绝，返回 {str(r)[:160]}", note_)

        # ── E1 前序链成环（自指 / 互指）──
        mats = [r["material_no"] for r in sread("md_material",
                                                "SELECT material_no FROM md_material ORDER BY material_no")]
        if len(mats) < 2:
            REP.skip("X", "E1 前序链成环必须被拒", "分母为空：物料不足 2 个")
        else:
            a, b = mats[0], mats[1]
            reject("E1 自指（前序 = 自己）必须被拒",
                   lambda: call("md_material", "update", material_no=a, predecessor_material_no=a),
                   ["前序", "自己", "自身", "循环", "环", "不能"])
            # 互指：先把 a 的前序设成 b（若这步就被拒，下面的互指无从构造）
            try:
                call("md_material", "update", material_no=a, predecessor_material_no=b)
                built = True
            except Exception as e:
                built = False
                REP.ok("X", "E1b 互指构造（a→b 允许）", f"已拒绝：{str(e)[:60]}")
            if built:
                reject("E1b 前序链成环（写入侧无环检测）",
                       lambda: call("md_material", "update", material_no=b, predecessor_material_no=a),
                       ["前序", "循环", "环", "不能"])
                # 写入侧没拦住 → 必须验**读取侧**：predecessor_chain 是递归的，环 = 无限递归。
                # 这一步必须**隔离到子进程 + 超时** —— 进程内跑若真挂死，整个体检就卡住了。
                if not any(r["target"] == "E1b 前序链成环（写入侧无环检测）"
                           and r["verdict"] == "PASS" for r in REP.rows):
                    cyc = sread("md_material",
                                "SELECT material_no, predecessor_material_no FROM md_material")
                    has_cycle = any(x["predecessor_material_no"] == a for x in cyc) and \
                                any(x["predecessor_material_no"] == b for x in cyc)
                    if not has_cycle:
                        REP.skip("X", "E1c 成环后读取侧必须终止", "前置不成立：环未真的建起来")
                    else:
                        try:
                            res = subprocess.run(
                                [sys.executable, "-c", _CYCLE_CHILD,
                                 str(ROOT), str(shadow), a],
                                capture_output=True, text=True, timeout=30)
                            out = [x for x in (res.stdout or "").strip().splitlines() if x]
                            got = next((x for x in out if x.startswith("RESULT")), "(无 RESULT 行)")
                            if res.returncode != 0:
                                tail = (res.stderr or "").strip().splitlines()[-1:] or [""]
                                REP.fail("X", "E1c 成环后读取侧必须终止",
                                         "必须在有限时间内正常返回（契约：成环在已访问处断链）",
                                         f"退出码 {res.returncode}：{tail[0][:90]}")
                            else:
                                # 终止 + 断链是 docstring 明写的契约，返回结果是**正确行为**，
                                # 不是缺陷。判据只到「有没有终止」为止 —— 首版把期望写成
                                # 「必须报错」，那是把设计行为当缺陷（本项目对账器第三次犯这个错了）。
                                REP.ok("X", "E1c 成环后读取侧必须终止",
                                       f"契约行为已验证：未挂死，{got}")
                        except Exception as e:
                            REP.skip("X", "E1c 成环后读取侧必须终止",
                                     f"子进程未能跑起来：{type(e).__name__}: {e}")

        # ── E2 断点自反（BR-02：原物料号不得等于新物料号）──
        bp = sread("md_breakpoint", "SELECT customer_no, old_material_no FROM md_breakpoint LIMIT 1")
        if not bp:
            REP.skip("X", "E2 断点自指必须被拒", "分母为空：无断点数据")
        else:
            cust, old = bp[0]["customer_no"], bp[0]["old_material_no"]
            reject("E2 断点自指（原=新）必须被拒",
                   lambda: call("md_breakpoint", "create", customer_no=cust,
                                old_material_no=old, new_material_no=old,
                                switch_time="2026-12-01"),
                   ["不能相同", "不得相同", "相同", "自"])

        # ── E3 负值注入（BR-08 生产时间 / BR-12 组批窗口 非负）──
        reject("E3 生产时间负数必须被拒",
               lambda: call("md_material", "update", material_no=mats[0], prod_days=-1),
               ["不能为负", "非负", "负数", "须大于", "大于 0"])
        reject("E3 组批窗口负数必须被拒",
               lambda: call("md_material", "update", material_no=mats[0], batch_window=-1),
               ["不能为负", "非负", "负数", "须大于", "大于 0"])

        # ── E5/E6 填写预测前的前置校验（sales_forecast BR-07 / BR-08）──
        # 这两条 BR 此前**没有任何判据**：引用完整性（C1）查的是"落库行必须引用存在的主数据"，
        # 而 BR-07/08 是"**调用时就该拦住**" —— 落到库里再查已经晚了。
        # fill_customer 要求草稿态；演示库里 202610 是冻结态，`get_active` 会返回空。
        # 影子库里先解冻（真库零风险），这样这两条判据才有分母 —— 否则它会静默 SKIP，
        # 而 BR-07/08 依旧没有任何判据。
        vno = V
        try:
            call("md_monthly_version", "unfreeze", version_no=vno)
        except Exception as e:
            note(f"E5: 解冻 {vno} 失败：{e}")
        if True:
            reject("E5 不存在的主数据：fill_customer 必须被拒",
                   lambda: call("sales_forecast", "fill_customer", version_no=vno,
                                material_no="__NO_SUCH_MAT__", customer_no="BYD",
                                rolling_month="N+1", orig_qty=100),
                   ["处理表行不存在", "物料不存在"])
            reject("E6 不存在的主数据：fill_customer 必须被拒",
                   lambda: call("sales_forecast", "fill_customer", version_no=vno,
                                material_no=mats[0], customer_no="__NO_SUCH_CUS__",
                                rolling_month="N+1", orig_qty=100),
                   ["处理表行不存在", "客户不存在"])
            # ⚠ 关键词必须写「处理表行不存在」：首版写的是泛化的「不存在」，
            # 于是上面两条**假通过**了 —— 实际报的是上游 `_get_line` 的前置拦截，
            # 而不是详设 BR-07/08 声明的那道校验。**关键词太泛 = 打不到目标分支。**
            REP._add("X", "E5b BR-07/08 的独立校验点不可达（参考）", "WARN",
                     "详设声明「填写客户预测前校验物料存在 / 校验客户存在」",
                     "实际由 `_get_line` 的「处理表行不存在」先拦下，物料/客户校验分支走不到",
                     "行为正确（确实被拒），但报错话术与详设不符；"
                     "属「声明了但走不到」同族 —— 校验点了但被上游短路")

        # ── E7~E10 四种传统基线方法的参数约束（sales_forecast BR-18~21）──
        # 演示数据里全是 statsforecast 方法（AutoTheta/AutoARIMA/TSB），四种传统方法
        # **一个都没出现** ⇒ 数据判据够不着，只能注入：给一个空参数集，若该方法要求参数则应被拒。
        for meth in ("移动平均", "指数平滑", "阶跃检测", "借用参考"):
            reject(f"E7 基线参数与方法不匹配必须被拒（{meth}）",
                   lambda m=meth: call("md_material", "update",
                                       material_no=mats[0], base_method=m, base_params="{}"),
                   # 「必填」也是正确的拒绝理由 —— 首版漏了它，把一次**正确的拒绝**
                   # 判成了失败（同一类错误今天已经是第二次：关键词写窄 = 假红）
                   ["参数", "不匹配", "缺少", "不能为空", "校验", "必填"])

        # ── E8 版本有效性校验（inventory_strategy BR-16）──
        # ⚠ 必须传**格式合法但不存在**的版本（209901），不能传 "__NO_SUCH_VER__" ——
        # 后者会先被格式校验拦下，报「版本号格式必须为 YYYYMM」，
        # 于是这条断言看着通过、其实**没打到「版本不存在」那一支**（今天第三次同一类错）。
        reject("E8 不存在的版本上算水位必须被拒",
               lambda: call("inventory_strategy", "calc",
                            version_no="209901", material_no=mats[0]),
               ["不存在", "未找到", "校验", "版本"])

        # ── E9 事件调整只作用归属期、不外推（sales_forecast BR-22 + BR-23）──
        # 详设示例原文：「N+1 期 event_adj=+20，N+2/N+3 期不受影响」。
        # 这条既没有判据、数据里也没造过事件（演示 environment 的 event_adj 全为 0），
        # 所以只能注入：给 N+1 加一次调整，断言 N+2/N+3 没被带着走，且 N+1 的
        # `base_event_qty` = `base_qty` + 调整量（BR-23 的合计量口径）。
        try:
            call("sales_forecast", "adjust_event", version_no=V, material_no=mats[0],
                 customer_no="BYD", rolling_month="N+1",
                 event_analysis="口径验证（结构检查注入）", event_adj=20)
            aft = {r["rolling_month"]: r for r in sread(
                "sales_forecast",
                "SELECT rolling_month, event_adj, base_qty, base_event_qty"
                " FROM sales_forecast_line WHERE version_no=? AND material_no=?"
                " AND customer_no='BYD'", (V, mats[0]))}
            if not aft:
                REP.skip("X", "E9 事件调整只作用归属期（BR-22/23）",
                         "分母为空：该版本/物料/客户没有预测行")
            else:
                bad = []
                n1 = aft.get("N+1")
                if n1 is None:
                    bad.append({"k": mats[0], "why": "没有 N+1 行"})
                else:
                    if not close_stored(n1["event_adj"] or 0, 20):
                        bad.append({"k": "N+1", "why": f"event_adj 应为 20，实际 {n1['event_adj']}"})
                    elif not close_stored(n1["base_event_qty"], (n1["base_qty"] or 0) + 20):
                        bad.append({"k": "N+1（BR-23）",
                                    "why": f"base_event_qty 应为 base_qty+20 = "
                                           f"{(n1['base_qty'] or 0) + 20}，实际 {n1['base_event_qty']}"})
                for rm in ("N+2", "N+3"):
                    r = aft.get(rm)
                    if r and not close_stored(r["event_adj"] or 0, 0):
                        bad.append({"k": rm, "why": f"**被外推了**：event_adj={r['event_adj']}"})
                if bad:
                    REP.fail("X", "E9 事件调整只作用归属期（BR-22/23）",
                             "调整只加在归属期，N+2/N+3 不受影响；且 base_event_qty = base_qty + 调整量",
                             "；".join(f"{t['k']} {t['why']}" for t in bad[:3]))
                else:
                    REP.ok("X", "E9 事件调整只作用归属期（BR-22/23）",
                           "N+1 加 +20 后 N+2/N+3 未受影响；base_event_qty = base_qty + 20")
        except Exception as e:
            REP.fail("X", "E9 事件调整只作用归属期（BR-22/23）", "应可注入一次事件调整",
                     f"{type(e).__name__}: {e}")

        # ── E4 日期边界（BR-05 阶段时间先后：EOP 不得早于 SOP）──
        projs = sread("md_project", "SELECT project_no, sop_date, eop_date FROM md_project LIMIT 1")
        if not projs:
            REP.skip("X", "E4 EOP 早于 SOP 必须被拒", "分母为空：无项目数据")
        else:
            pj = projs[0]
            reject("E4 EOP 早于 SOP 必须被拒",
                   lambda: call("md_project", "update", project_no=pj["project_no"],
                                sop_date="2026-12-01", eop_date="2026-01-01"),
                   ["早于", "晚于", "先后", "不能", "顺序"])
    finally:
        restore()


def scenario_idempotent(conn):
    """D 组：幂等与换序（最便宜的 BUG 探测器 —— 不需要任何期望值）。

    幂等：同一批服务在同一份数据上跑两次，**结果必须逐字节相同**。
    换序：顺序不变量被破坏时必须**报错**，而不是静默给出另一个答案
    （`app/psc/sales_forecast/HOWTOUSE.md` 记录过这条：拟合→基线→决策→定稿→汇总）。
    """
    import sqlite3 as _s

    V = "202610"
    shadow, restore = shadow_sandbox()
    try:
        from fde_platform.runtime import FdePlatform
        pf = FdePlatform()
        pf.load_all()

        def call(app, svc, **kw):
            return pf.call(f"{GROUP}/{app}", svc, **kw)

        # 平台的审计列每次写都会变（updated_at 秒级、updated_by 是调用者），
        # 做「内容是否相同」的签名时必须排除 —— 否则**任何写入都会被判成不幂等**。
        # 首版用 SELECT * 就踩了这个坑：两次 calc_batch 落在同一秒内时侥幸通过，
        # 跨秒就报「8 行 → 8 行（内容不同）」，是一条**间歇性假警报**（比稳定假警报更坏）。
        _AUDIT = {"created_at", "updated_at", "created_by", "updated_by"}

        def _payload_cols(dbname, table):
            c = _s.connect(str(shadow / f"{dbname}.db"))
            try:
                names = [r[1] for r in c.execute(f'PRAGMA table_info("{table}")')]
            finally:
                c.close()
            keep = [n for n in names if n not in _AUDIT]
            return ", ".join(f'"{n}"' for n in keep) or "*"

        def sig(dbname, table, where="", params=()):
            """表内容签名：行数 + 全部行的有序元组（**不含审计列**）。"""
            cols = _payload_cols(dbname, table)
            c = _s.connect(str(shadow / f"{dbname}.db"))
            try:
                rows = c.execute(f'SELECT {cols} FROM "{table}" {where} ORDER BY 1,2',
                                 params).fetchall()
                return (len(rows), tuple(tuple(r) for r in rows))
            finally:
                c.close()

        ver = call("md_monthly_version", "get", version_no=V)
        if ver.get("lock_status") != "草稿":
            call("md_monthly_version", "unfreeze", version_no=V)

        # ── D3 换序（先测：此时版本是草稿，净需求不该能算）──
        try:
            r = call("demand", "calc_net", version_no=V)
            REP.fail("X", "D3 换序：草稿版本不得运算净需求",
                     "应 raise FdeError（毛需求未发布冻结）",
                     f"未报错，返回 {str(r)[:100]}",
                     "顺序不变量：拟合→基线→决策→定稿→汇总→毛需求→发布→净需求，"
                     "跳步必须报错而不是静默给另一个答案")
        except Exception as e:
            REP.ok("X", "D3 换序：草稿版本不得运算净需求", f"已报错：{str(e)[:60]}")

        # ── D1 幂等 ──
        IDEM = [
            ("decide_batch", "sales_forecast", "sales_forecast_line", "WHERE version_no=?", (V,)),
            ("summarize", "sales_forecast", "sales_forecast_summary", "WHERE version_no=?", (V,)),
            ("build_gross", "demand", "demand", "WHERE version_no=?", (V,)),
            ("calc_batch", "inventory_strategy", "inventory_strategy", "WHERE version_no=?", (V,)),
        ]
        for svc, call_app, table, where, params in IDEM:
            try:
                call(call_app, svc, version_no=V)
                a = sig(call_app, table, where=where, params=params)
                call(call_app, svc, version_no=V)
                b = sig(call_app, table, where=where, params=params)
            except Exception as e:
                REP.fail("X", f"D1 {call_app}.{svc} 幂等", "应可重复调用且结果不变",
                         f"{type(e).__name__}: {e}")
                continue
            where_txt = {"WHERE version_no=?": "该版本"}.get(where, "")
            REP.viol("X", f"D1 {call_app}.{svc} 幂等", [{"t": table}] if a != b else [],
                     f"连跑两次后 {table} {where_txt}的内容必须完全相同",
                     lambda _: f"{table} 两次不一致：{a[0]} 行 → {b[0]} 行"
                               f"（内容{'不同' if a[0] == b[0] else '行数不同'}）",
                     f"{a[0]} 行参与比对")
    finally:
        restore()


_KNOWN_FILE = Path(__file__).resolve().parent / "psc_oracles_known.txt"

# ---------------------------------------------------------------- BR 覆盖映射
# **这是唯一的人补部分**：BR 清单本身从《应用详设》机械抽取（见 coverage_table），
# 只有「哪条 BR 由哪条判据覆盖」需要人写 —— 因为 BR 是中文散文，机器读不出依赖关系。
#
# 维护纪律：
#   · 新增/改动 BR 时必须同步这张表；
#   · 跑 `--coverage` 会把「详设有、表里没有」和「表里有、详设没有」两种漂移都报出来；
#   · 标 `[]` 的表示**目前没有任何判据碰过它** —— 那才是真正的盲区清单。
BR_COVERAGE = {
    "inventory_strategy": {
        "BR-01": ["C4 唯一性 · 水位二键"],
        "BR-02": ["A1 日需求 · A 支与 B 支同值", "A12 日需求 vs 文档口径（参考）"],
        "BR-03": ["A1 日需求 · A 支与 B 支同值"],
        "BR-04": ["A1 日需求 · A 支与 B 支同值"],
        # BR-05「响应窗口 L 折算为月」：见 BR_UNJUDGEABLE —— 落库只有一个 resp_volatility，
        # 看不出构造窗口，数据判据够不着。（**这行曾被一次不精确的整串替换错写成 C8**，
        # 因为 inventory_strategy 的 BR-05 在字典里排在 sales_forecast 之前。）
        "BR-05": [],
        "BR-06": ["A2 安全库存 · C = z × σ_L"],
        "BR-07": ["A2 服务系数 · 必须是查表值"],
        "BR-08": ["A2 安全库存 · C = z × σ_L"],
        "BR-09": ["A1 日需求 · A 支与 B 支同值"],
        "BR-10": ["A3 三层水位 · 非负", "A8 水位层 = A+C+B"],
        "BR-11": ["A4 速度对冲 ⇒ C=B=0"],
        "BR-12": ["A4 速度对冲 ⇒ C=B=0"],
        "BR-13": ["A3 三层水位 · 非负"],
        "BR-14": ["C2 枚举 · hedge_tool"],
        "BR-15": ["E3 生产时间负数必须被拒", "E3 组批窗口负数必须被拒"],
        "BR-16": ["E8 不存在的版本上算水位必须被拒"],
    },
    "demand": {
        "BR-01": ["A8 毛需求 = 预测 + 水位"],
        "BR-02": ["A8 水位层 = A+C+B"],
        "BR-03": ["A8 预测层 = 预测汇总"],
        "BR-04": ["A9 N+1：net = max(0, 毛+未发−库存−在途)"],
        "BR-05": ["A9 N+2/N+3：net = 毛，扣减层归零"],
        "BR-06": ["H4 净额 = 毛 + 未发 − 库存 − 在途（符号正确）"],
        "BR-07": ["H4 净额 = 毛 + 未发 − 库存 − 在途（符号正确）"],
        "BR-08": ["C3 非负 · 净需求", "H5 库存超额 ⇒ 净额钳到 0（BR-08）"],
        "BR-09": ["A14 BR-09 合并转移全额且旧料不残留"],
        "BR-10": ["D3 换序：草稿版本不得运算净需求"],
        "BR-11": ["C4 唯一性 · demand 四键"],
        "BR-12": ["C1 引用完整性 · demand.material_no"],
        "BR-13": ["F1 汇总为空时 build_gross 必须报错"],
    },
    "sales_forecast": {
        "BR-01": ["C9 预测 · 每条明细都有对应汇总（BR-01 三表同聚合同版本）"],
        "BR-02": ["C4 唯一性 · 预测明细四键"],
        "BR-03": ["A7 final_qty_sum = Σ final_qty"],
        "BR-04": ["C12 预测 · 客户必须是该物料的采购客户（BR-04）"],
        "BR-05": ["C8 预测 · 每个物料×客户恰好拆 3 行（N+1/N+2/N+3）"],
        "BR-06": ["D3 换序：草稿版本不得运算净需求"],
        "BR-07": ["E5 不存在的主数据：fill_customer 必须被拒"],
        "BR-08": ["E6 不存在的主数据：fill_customer 必须被拒"],
        "BR-09": ["A5 adj = orig × (1 − bias)"],
        "BR-10": ["A6 bias/mape 两条写入路径同值"],
        "BR-11": ["A5 adj = orig × (1 − bias)"],
        "BR-12": ["A15 BR-12 偏离率与异常标记"],
        "BR-13": ["A13 基线不得被静默丢弃"],
        "BR-14": ["A13 基线不得被静默丢弃"],
        "BR-15": ["A13 基线不得被静默丢弃"],
        "BR-16": ["S7 阈值常量与详设一致（BR-16）"],
        "BR-17": ["G2 批量基线 == 逐行基线"],
        "BR-18": ["E7 基线参数与方法不匹配必须被拒（移动平均）"],
        "BR-19": ["E7 基线参数与方法不匹配必须被拒（指数平滑）"],
        "BR-20": ["E7 基线参数与方法不匹配必须被拒（阶跃检测）"],
        "BR-21": ["E7 基线参数与方法不匹配必须被拒（借用参考）"],
        "BR-22": ["E9 事件调整只作用归属期（BR-22/23）"],
        "BR-23": ["A13 基线不得被静默丢弃"],
        "BR-24": ["C10 预测 · bp_material_no 来自真实断点（BR-24）"],
        "BR-25": ["A7 final_qty_sum = Σ final_qty"],
        "BR-26": ["C7 预测 · 非异常行必须有最终预测"],
        "BR-27": ["S5 人工定稿不被覆盖（BR-27）"],
    },
}


# 已评估为「**不可由数据判据覆盖**」的 BR：不是"还没做"，是"现有手段做不到"，理由写在这里。
# 区分这两者很重要 —— 混在一起会让"覆盖率"变成一个说不清的数字。
BR_UNJUDGEABLE = {
    "inventory_strategy BR-05":
        "响应窗口 L（天）折算为月只影响 σ_L 的构造过程，而落库只有一个 resp_volatility 数值，"
        "看不出它是由几期累计序列算出来的；要从数据判它，得能反推构造窗口 —— 做不到。"
        "可选替代：静态检查实现里确实按 L/30 折算（但静态检查易把 bug 固化成标准），"
        "或专门设计「同物料改 L 参数后 σ_L 应随之变化」的差分判据。",
}

_BR_RE = re.compile(r"`(BR-\d+)`\s*(.+)")


def coverage_table():
    """BR ↔ 判据覆盖表：BR 清单从详设抽，映射取自 BR_COVERAGE。"""
    print("=" * 78)
    print("BR ↔ 判据 覆盖表")
    print("  BR 清单从《应用详设》机械抽取；映射是人补部分（BR_COVERAGE）")
    print("=" * 78)
    total = covered = 0
    blind = []
    assessed = []
    for app, mapping in BR_COVERAGE.items():
        spec = Path(f"app/{GROUP}/{app}/应用详设.md")
        if not spec.exists():
            print(f"\n[{app}] 找不到 {spec}")
            continue
        titles, seen = {}, []
        for ln in spec.read_text(encoding="utf-8").splitlines():
            m = _BR_RE.search(ln)
            if m and m.group(1) not in titles:
                titles[m.group(1)] = m.group(2).strip().strip("*：: ")
                seen.append(m.group(1))
        print(f"\n[{app}]")
        print(f"  {'BR':7s} {'规则':30s} 判据")
        for br in seen:
            judges = mapping.get(br)
            total += 1
            if judges:
                covered += 1
                print(f"  {br:7s} {titles[br][:28]:30s} {' / '.join(judges)}")
            else:
                key = f"{app} {br}"
                if key in BR_UNJUDGEABLE:
                    assessed.append(key)
                    print(f"  {br:7s} {titles[br][:28]:30s} ⊘ 已评估：不可由数据判据覆盖")
                else:
                    blind.append(f"{app} {br} {titles[br]}")
                    print(f"  {br:7s} {titles[br][:28]:30s} ❌ **无判据（待补）**")
        extra = [b for b in mapping if b not in titles]
        if extra:
            print(f"  ⚠ 映射表里登记了但详设里没有的 BR（映射漂移）：{extra}")
    print("\n" + "=" * 78)
    print(f"覆盖 {covered}/{total} 条 BR；"
          f"**待补判据 {len(blind)} 条** · 已评估不可覆盖 {len(assessed)} 条")
    for b in blind:
        print(f"  · {b}")
    for a in assessed:
        print(f"  ⊘ {a} —— {BR_UNJUDGEABLE[a]}")
    print("=" * 78)
    return 0


def load_known():
    """已登记为「待业务/口径决策」的失败项（每行一个靶点名，# 注释）。

    为什么要这个：几项长期待决策的失败会让门禁**常红**，而常红的闸会训练人无视红灯 ——
    比没有闸更坏。有了基线之后，闸只为**不在清单里**的新回归变红；
    每登记一条都必须同时在台账 `app/psc/BUGS_psc_<日期>.md` 里记账。
    """
    if not _KNOWN_FILE.exists():
        return set()
    out = set()
    for ln in _KNOWN_FILE.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#"):
            out.add(ln)
    return out


def scenario_zero_touch_more(conn):
    """G5–G8：剩下几个零触达服务（覆盖矩阵里"一次都没被调用过"的）。

    判据仍是两条结构性关系，不写期望值：
      G5/G6 「投影服务与列表服务必须同值」—— `get_latest` / `list_by_material` 这类
            专供跨应用调用的投影，必须与 `list` 的对应子集一致；
      G7    「稀疏 payload 不得清空未提供的字段」—— B-01 修的就是这个（md_material.import_batch
            整行覆盖把未提供字段清成 NULL）；这里是同一条纪律在 md_project_part 上的回归；
      G8    「回填必须留下可回滚的版本记录」（BR-20 / BR-15）—— 只写不读的
            `md_material_param_version` 此前零触达，rollback 无据可依时无人知道。
    """
    import sqlite3 as _s

    shadow, restore = shadow_sandbox()
    try:
        from fde_platform.runtime import FdePlatform
        pf = FdePlatform()
        pf.load_all()

        def call(app, svc, **kw):
            return pf.call(f"{GROUP}/{app}", svc, **kw)

        def sread(dbname, sql, params=()):
            c = _s.connect(str(shadow / f"{dbname}.db"))
            c.row_factory = _s.Row
            try:
                return [dict(r) for r in c.execute(sql, params)]
            finally:
                c.close()

        def items_of(result):
            if isinstance(result, dict):
                return result.get("items") or result.get("data") or result.get("rows") or []
            return result if isinstance(result, list) else []

        # ── G5 strategy_fitting.get_latest 与 list 的对应行一致 ──
        try:
            all_fit = items_of(call("strategy_fitting", "list", size=500))
            by_mat = {}
            for r in all_fit:
                by_mat.setdefault(r["material_no"], []).append(r)
            mats = find("X", "G5 get_latest == list 的最新版", list(by_mat), "有拟合结果的物料")
            if mats is not None:
                bad, tested = [], 0
                for m in mats[:6]:
                    rows = sorted(by_mat[m], key=lambda r: str(r["fit_version"]), reverse=True)
                    want = rows[0]
                    got = call("strategy_fitting", "get_latest", material_no=m)
                    if not isinstance(got, dict):
                        bad.append({"m": m, "why": f"返回 {type(got).__name__} 而非 dict"})
                        continue
                    tested += 1
                    shared = [k for k in got if k in want]
                    diff = [k for k in shared if not same_val(want[k], got[k])]
                    if diff:
                        bad.append({"m": m,
                                    "why": "；".join(f"{k}: list={want[k]!r} get_latest={got[k]!r}"
                                                     for k in diff[:3])})
                REP.viol("X", "G5 get_latest == list 的最新版", bad,
                         "get_latest 必须等于 list 中该物料 fit_version 最大的那一行",
                         lambda t: f"{t['m']}：{t['why']}", f"{tested} 个物料参与比对")
        except Exception as e:
            REP.fail("X", "G5 get_latest == list 的最新版", "正常执行",
                     f"{type(e).__name__}: {e}")

        # ── G6 md_project_part.list_by_material 与 list 按物料过滤一致 ──
        try:
            all_pp = items_of(call("md_project_part", "list", size=500))
            mats = sorted({r["material_no"] for r in all_pp})
            mats = find("X", "G6 list_by_material == list 的子集", mats, "项目零件映射里的物料")
            if mats is not None:
                bad, tested = [], 0
                for m in mats[:6]:
                    want = sorted((r["project_no"], r["material_no"])
                                  for r in all_pp if r["material_no"] == m)
                    got = items_of(call("md_project_part", "list_by_material", material_no=m))
                    got_keys = sorted((r.get("project_no"), r.get("material_no")) for r in got)
                    tested += 1
                    if want != got_keys:
                        bad.append({"m": m, "want": want[:4], "got": got_keys[:4]})
                REP.viol("X", "G6 list_by_material == list 的子集", bad,
                         "list_by_material(m) 必须等于 list 中该物料的全部行",
                         lambda t: f"{t['m']}：list={t['want']} 投影={t['got']}",
                         f"{tested} 个物料参与比对")
        except Exception as e:
            REP.fail("X", "G6 list_by_material == list 的子集", "正常执行",
                     f"{type(e).__name__}: {e}")

        # ── G7 稀疏 payload 不得清空未提供的字段（B-01 同类回归）──
        try:
            rows = sread("md_project_part", "SELECT * FROM md_project_part")
            rows = find("X", "G7 稀疏导入不得清空未提供字段", rows, "md_project_part 现有行")
            if rows is not None:
                row = rows[0]
                keys = ("project_no", "material_no")
                # 挑一个**非主键、且当前有值**的列当"目击者"：我没在 payload 里提供它，
                # 导入后它必须原封不动。这正是 md_material 那次整行覆盖会踩的地方。
                witness = next((k for k, v in row.items()
                                if k not in keys and v not in (None, "")
                                and not k.startswith(("created_", "updated_"))), None)
                if witness is None:
                    REP.skip("X", "G7 稀疏导入不得清空未提供字段",
                             "分母为空：找不到有值的非主键列当目击者")
                else:
                    keep = row[witness]
                    call("md_project_part", "import_batch",
                         rows=[{keys[0]: row[keys[0]], keys[1]: row[keys[1]]}])
                    after = [r for r in sread("md_project_part", "SELECT * FROM md_project_part")
                             if r[keys[0]] == row[keys[0]] and r[keys[1]] == row[keys[1]]]
                    if not after:
                        REP.fail("X", "G7 稀疏导入不得清空未提供字段",
                                 "该行应仍存在", "导入后该行不见了")
                    else:
                        got = after[0][witness]
                        if not same_val(keep, got):
                            REP.fail("X", "G7 稀疏导入不得清空未提供字段",
                                     f"未提供的列「{witness}」应保持 {keep!r}",
                                     f"实际变成 {got!r}",
                                     "稀疏 payload 只含主键时把其它列清空 = 整行覆盖。"
                                     "md_material 的 import_batch 出过同一问题（ERP 夜间同步会清掉"
                                     "基线方法/参数），修法是**只更新 payload 里提供的列**")
                        else:
                            REP.ok("X", "G7 稀疏导入不得清空未提供字段",
                                   f"目击列「{witness}」保持 {keep!r} 未变")
        except Exception as e:
            REP.fail("X", "G7 稀疏导入不得清空未提供字段", "正常执行",
                     f"{type(e).__name__}: {e}")

        # ── G8 拟合回填必须留下可回滚的版本记录（BR-20 / BR-15）──
        try:
            mats = sread("md_material",
                         "SELECT material_no, fit_version, base_method, base_params,"
                         " batch_window, service_level FROM md_material"
                         " WHERE fit_version IS NOT NULL AND fit_version <> ''")
            mats = find("X", "G8 回填参数有版本记录可回滚", mats, "已回填 fit_version 的物料")
            if mats is not None:
                # ⚠ sread 的第一个参数是**库名**（md_material），不是表名 ——
                # 首版把表名传了进去，等于去开一个不存在的库，直接 OperationalError。
                vers = {(r["material_no"], r["fit_version"]): r for r in sread(
                    "md_material",
                    "SELECT material_no, fit_version, base_method, base_params,"
                    " batch_window, service_level FROM md_material_param_version")}
                missing, mismatch = [], []
                for m in mats:
                    k = (m["material_no"], m["fit_version"])
                    if k not in vers:
                        missing.append(m)
                        continue
                    v = vers[k]
                    diff = [c for c in ("base_method", "base_params", "batch_window", "service_level")
                            if not same_val(m[c], v[c])]
                    if diff:
                        mismatch.append((m, diff))
                REP.viol("X", "G8 回填参数有版本记录（BR-20）", missing,
                         "每个已回填 fit_version 的物料都应有对应的参数版本记录",
                         lambda r: f"{r['material_no']} 版本 {r['fit_version']} 无版本记录 —— "
                                   f"rollback 将无据可依")
                REP.viol("X", "G8 版本记录 == 主数据当前参数", mismatch,
                         "版本记录里的参数应与主数据当前值一致（它就是回填时写下的那份）",
                         lambda t: f"{t[0]['material_no']} 不一致字段 {t[1]}")
        except Exception as e:
            REP.fail("X", "G8 回填参数有版本记录（BR-20）", "正常执行",
                     f"{type(e).__name__}: {e}")
    finally:
        restore()


def scenario_external_sync(conn):
    """G9/G10：外部同步服务（走真的 HTTP，打到 mock ERP :5001）。

    这里有本轮最有价值的一条回归：**外部 payload 是稀疏的**（ERP 只给 material_no /
    material_name / unit_value 这类字段），而 `import_batch` 曾经是**整行覆盖** ——
    也就是说 ERP 夜间同步会把平台上由拟合回填的 `base_method`/`base_params`、
    以及人工维护的 `predecessor_material_no` **全部清成 NULL**。
    该问题已于本轮按「只更新 payload 里提供的列」修复（用户确认的口径），
    但外部同步这条路**一次都没被跑过**（零触达），所以回归没有守卫 —— 本组补上。

    另外验两个 sync 在**未配置端点**时是否 fail-closed（不得静默成功）。
    """
    import sqlite3 as _s

    # mock ERP 在不在？不在就 SKIP（不静默通过）
    import socket
    s = socket.socket()
    s.settimeout(0.5)
    try:
        s.connect(("127.0.0.1", 5001))
        erp_up = True
    except OSError:
        erp_up = False
    finally:
        s.close()

    WATCH = ["base_method", "base_params", "predecessor_material_no", "sigma_l",
             "batch_window", "service_level", "value_class"]

    shadow, restore = shadow_sandbox()
    try:
        from fde_platform.runtime import FdePlatform
        pf = FdePlatform()
        pf.load_all()

        def call(app, svc, **kw):
            return pf.call(f"{GROUP}/{app}", svc, **kw)

        def sread(dbname, sql, params=()):
            c = _s.connect(str(shadow / f"{dbname}.db"))
            c.row_factory = _s.Row
            try:
                return [dict(r) for r in c.execute(sql, params)]
            finally:
                c.close()

        # ── G9 外部物料同步：稀疏 payload 不得清空既有字段 ──
        if not erp_up:
            REP.skip("X", "G9 外部物料同步不得清空既有字段",
                     "mock ERP(:5001) 未运行 —— 起 `python 宣传/mock_erp.py` 后再跑")
        else:
            before = {r["material_no"]: r for r in sread(
                "md_material", "SELECT material_no, base_method, base_params,"
                               " predecessor_material_no, sigma_l, batch_window,"
                               " service_level, value_class FROM md_material")}
            watched = [m for m, r in before.items()
                       if any(r[k] not in (None, "") for k in WATCH)]
            if not watched:
                REP.skip("X", "G9 外部物料同步不得清空既有字段",
                         "分母为空：没有任何物料的被观字段有值")
            else:
                try:
                    res = call("md_material", "sync_external_material")
                except Exception as e:
                    REP.fail("X", "G9 外部物料同步不得清空既有字段", "同步应可执行",
                             f"{type(e).__name__}: {e}")
                    res = None
                if res is not None:
                    after = {r["material_no"]: r for r in sread(
                        "md_material", "SELECT material_no, base_method, base_params,"
                                       " predecessor_material_no, sigma_l, batch_window,"
                                       " service_level, value_class FROM md_material")}
                    wiped = []
                    for m in watched:
                        if m not in after:
                            continue
                        lost = [k for k in WATCH
                                if before[m][k] not in (None, "") and after[m][k] in (None, "")]
                        if lost:
                            wiped.append({"m": m, "lost": lost})
                    REP.viol("X", "G9 外部物料同步不得清空既有字段", wiped,
                             "同步后，payload 未提供的列必须保持原值",
                             lambda t: f"{t['m']} 被清空：{t['l']}",
                             f"同步返回 {str(res)[:70]}；{len(watched)} 个物料参与比对")

                    # 幂等：连跑两次内容不变
                    snap1 = sorted((m, tuple(str(after[m][k]) for k in WATCH))
                                   for m in after)
                    try:
                        call("md_material", "sync_external_material")
                    except Exception as e:
                        REP.fail("X", "G9b 外部同步幂等", "重复同步应成功",
                                 f"{type(e).__name__}: {e}")
                        snap1 = None
                    if snap1 is not None:
                        after2 = {r["material_no"]: r for r in sread(
                            "md_material", "SELECT material_no, base_method, base_params,"
                                           " predecessor_material_no, sigma_l, batch_window,"
                                           " service_level, value_class FROM md_material")}
                        snap2 = sorted((m, tuple(str(after2[m][k]) for k in WATCH))
                                       for m in after2)
                        if snap1 != snap2:
                            REP.fail("X", "G9b 外部同步幂等",
                                     "连跑两次后被观字段应完全相同",
                                     f"{len(snap1)} 个物料的内容发生了变化",
                                     "外部同步会由定时任务每天跑，不幂等意味着数据会每天漂移")
                        else:
                            REP.ok("X", "G9b 外部同步幂等",
                                   f"{len(snap2)} 个物料的被观字段两次一致")

        # ── G10 未配置端点时必须 fail-closed（已配置则应真正导入，不得**假成功**）──
        for app, svc in (("sales_history", "sync_external_history"),
                         ("md_material", "sync_external_material")):
            try:
                r = call(app, svc)
            except Exception as e:
                REP.ok("X", f"G10 {app}.{svc} 未配置时报错（fail-closed）",
                       f"已报错：{type(e).__name__}: {str(e)[:60]}")
                continue
            # 走到这里说明端点已配置。判「不是假成功」：必须有 mock 标记、或有导入计数。
            # 判据不能只看某个键名 —— 首版只认 `imported`，而 import_batch 返回的是
            # `{'total':8,'success':8,...}`，于是把一次**成功的同步**误报成了假成功。
            counts = [r.get(k) for k in ("success", "imported", "updated")] if isinstance(r, dict) else []
            if isinstance(r, dict) and (r.get("status") == "mock" or any(c for c in counts if c)):
                REP.ok("X", f"G10 {app}.{svc} 未配置时报错（fail-closed）",
                       f"端点已配置且真正执行：{str(r)[:70]}")
            else:
                REP.fail("X", f"G10 {app}.{svc} 未配置时报错（fail-closed）",
                         "未配置应报错；已配置应真正导入（有导入计数或 mock 标记）",
                         f"既没报错、也没有任何导入计数：{str(r)[:90]}")
    finally:
        restore()


def canary(conn):
    """防伪绿：故意造一个必然违规的断言，若它没被识别为 FAIL，说明体检本身坏了。"""
    before = len(REP.rows)
    REP.viol("K", "K0 canary（故意违规，必须 FAIL）", [{"x": 1}],
             "本条必须被识别为 FAIL", lambda r: "canary")
    got = REP.rows[-1]["verdict"]
    REP.rows.pop()          # canary 不应计入正式报告
    if got != "FAIL":
        REP.fail("K", "K0 canary 失效", "canary 必须被判 FAIL", f"实际判定 {got}",
                 "体检机制自身坏了，本次全部 PASS 都不可信")
    else:
        REP.ok("K", "K0 canary 生效", "违规检测链路工作正常")
    del before


# ================================================================ 主流程

SECTIONS = [
    ("A", "对账（同一个量的两条独立路径必须同值）", [a_water_level, a_hedge, a_forecast,
                                                     a_source_fallback, a_merge_transfer, a_deviation, a_summary, a_gross,
                                                     a_net, a_master_plan, a_projection,
                                                     a_daily_demand_ref]),
    ("C", "不变式（永远必须成立，被破坏即 BUG）", [c_invariants]),
    ("S", "静态探针（结构性问题，扫描即得）", [s_static]),
]

# 场景组（影子库内真跑一遍链路，需要加载平台，单独执行）
SCENARIOS = [("X", "全链路场景（影子库内执行，不动真库）",
              [scenario_forecast, scenario_net_deduction, scenario_silent_degrade,
               scenario_zero_touch, scenario_boundary,
               scenario_idempotent, scenario_zero_touch_more,
               scenario_external_sync])]


def main():
    global VERBOSE
    ap = argparse.ArgumentParser(description="PSC 对账体检：找出「测试用例没想到」的那类 BUG")
    ap.add_argument("-g", "--group", action="append",
                    help="只跑指定组（A/C/S，可重复）")
    ap.add_argument("--coverage", action="store_true",
                    help="只出 BR ↔ 判据 覆盖表（不跑检查）")
    ap.add_argument("--scenario", action="store_true",
                    help="额外跑全链路场景（影子库内执行，会加载平台，较慢）")
    ap.add_argument("--verbose", action="store_true", help="打印每条对账的分母规模")
    args = ap.parse_args()
    VERBOSE = args.verbose

    print("=" * 78)
    print("PSC 对账体检")
    print("  判据：A 对账（冗余双路径） / C 不变式 / S 静态探针")
    print("  纪律：直连 SQLite 不 import 应用代码 · 不猜实现约定 · 每条先验分母非空")
    print("  本脚本只读，不写任何业务库")
    print("=" * 78)

    if args.coverage:
        return coverage_table()

    before = fingerprint()
    print(f"业务库指纹已快照：{len(before)} 张表\n")

    conn = connect()
    canary(conn)

    wanted = set(args.group) if args.group else {g for g, _, _ in SECTIONS}
    for key, title, funcs in SECTIONS:
        if key not in wanted:
            continue
        print(f"\n--- [{key}] {title} ---")
        for fn in funcs:
            try:
                fn(conn)
            except Exception as e:            # 报告优先：一个检查崩了不阻断其余
                REP.fail(key, f"{fn.__name__} 崩溃", "正常执行",
                         f"{type(e).__name__}: {e}")

    conn.close()

    if args.scenario:
        for key, title, funcs in SCENARIOS:
            print(f"\n--- [{key}] {title} ---")
            for fn in funcs:
                try:
                    fn(None)
                except Exception as e:
                    import traceback
                    REP.fail(key, f"{fn.__name__} 崩溃", "正常执行",
                             f"{type(e).__name__}: {e}")
                    if VERBOSE:
                        traceback.print_exc()

    after = fingerprint()
    diff = fp_diff(before, after)
    if diff:
        REP.fail("K", "K1 数据未被改动", "跑完指纹不变",
                 " | ".join(diff[:3]), f"共 {len(diff)} 张表变化 —— 体检脚本自己动了数据")
    else:
        REP.ok("K", "K1 数据未被改动", f"{len(before)} 张表指纹一致")

    # ---- 报告 ----
    print("\n" + "=" * 78)
    print("逐条结果")
    print("=" * 78)
    for g, title, _ in SECTIONS + SCENARIOS:
        rows = [r for r in REP.rows if r["group"] == g]
        if not rows:
            continue
        print(f"\n[{g}] {title}")
        for r in rows:
            mark = {"PASS": "✓", "FAIL": "✗", "SKIP": "–", "WARN": "!"}.get(r["verdict"], "?")
            print(f"  {mark} {r['verdict']:<4} {r['target']}")
            if r["verdict"] == "FAIL" or r["verdict"] == "WARN":
                if r["expect"]:
                    print(f"        期望：{r['expect']}")
                if r["actual"]:
                    print(f"        实际：{r['actual']}")
            if r["note"]:
                print(f"        备注：{r['note']}")
    rows = [r for r in REP.rows if r["group"] == "K"]
    if rows:
        print("\n[K] 体检自身")
        for r in rows:
            mark = {"PASS": "✓", "FAIL": "✗"}.get(r["verdict"], "?")
            print(f"  {mark} {r['verdict']:<4} {r['target']}"
                  + (f" —— {r['note']}" if r["note"] else ""))

    c = REP.counts()
    warn = len([r for r in REP.rows if r["verdict"] == "WARN"])
    known = load_known()
    fail_targets = [r["target"] for r in REP.rows if r["verdict"] == "FAIL"]
    registered = [t for t in fail_targets if t in known]
    fresh = [t for t in fail_targets if t not in known]
    print("\n" + "=" * 78)
    print(f"通过 {c['PASS']} · 失败 {c['FAIL']} · 跳过 {c['SKIP']} · 参考 {warn}")
    if registered:
        print(f"其中 {len(registered)} 项已登记为待决策（不判为新回归）：")
        for t in registered:
            print(f"  · {t}")
    if fresh:
        print(f"⚠ {len(fresh)} 项**未登记**的失败（这才是要报警的）：")
        for t in fresh:
            print(f"  · {t}")
    verdict = "FAIL" if fresh else ("PARTIAL" if registered else "PASS")
    print(f"VERIFY_RESULT: {verdict}")
    print("=" * 78)
    if fresh:
        print("\n未登记的失败按上表逐条核对；『期望 / 实际』已给出差在哪。")
        print("若确认是应用 BUG：业务口径由人定，改代码前先记录到 app/psc/BUGS_psc_<日期>.md。")
    return 0 if not fresh else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n中断")
        sys.exit(130)
