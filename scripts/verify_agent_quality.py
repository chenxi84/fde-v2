"""与平台智能体**真对话**，校验它在分析/决策场景下给出的结论是否与权威结论一致。

它补的是这段空白
----------------
- `app/psc/tests/verify_chain_psc*.py` 验**算法本身**（分支、公式、状态机）——直调服务；
- `scripts/verify_agent_tools.py` 验**工具面结构**（在不在表里、权限标没标）——不起模型；
- `宣传/agent_tool_eval.py` 验模型**选哪个工具**——直调 provider，不驱真对话；
- **本脚本**验「用户问一句分析题，它答得对不对」——驱真对话（leader/团队/真工具/真数据）。

为什么要这么设计（三条硬约束，都踩过）
--------------------------------------
1. **不能用 `dbguard.isolate_dbs()`**。它靠**移动库文件**实现隔离，要求没有进程持有
   句柄（即必须停服）；可本测试恰恰需要跑着的平台 + `agent_service` + `LLM` 配置，
   而且 dbguard 连 `config/llm.db` 一起隔离（注释写明是为了让"未配置降级"类断言确定）
   ——隔离一进来，模型就没了。所以它跟 `宣传/verify_demo.py` 同类：**对着已就绪的环境跑**。
2. **所以必须防「假绿」**。环境没造好时最坏的失败模式是：agent 说"没有要补货的"、
   ground truth 也是"没有"——两边一致地错，测试照样绿。对策有两层：
     - 全局前置哨兵（LLM / agent_service / 数据非平凡 / 是演示环境）——不过就整体退出码 2；
     - 每条场景自带 `requires`——fixture 里没有这条分支时**明确 SKIP 并说明原因**，
       绝不静默通过。
3. **ground truth 一律现算，且只读**。断言的是「agent 的结论 == 平台服务算出的结论」，
   这样只测 agent、不重复测算法，也不受算法演进牵连。**绝不调用写服务**
   （`refresh_batch` / `scan_alert` / `import_*` 这些会改数据，而且 `demand_pool` 无去重、
   重复调用会重复建补货单）——见 `WRITE_SERVICES`。

三层断言（失败时要能知道错在哪一层）
-----------------------------------
- **L1 工具轨迹**：该查的查了没（`must_call_any`）、不该碰的碰了没（`must_not_call`）、
  是不是真查了而不是凭记忆答（`min_tool_calls`）。L1 绿而 L3 红 → 推理/表达问题；
  L1 红 → 工具面/参数/契约问题。
- **L2 事实**：答案里的关键数字/料号是否对得上现算的权威值（`numbers_must_appear` /
  `gt_set_from`）。抓"漏看"与"编造"。
- **L3 结论**：判定与归因是否正确（`must_include_all/any`、`must_not_match`）。
  本版全部是**确定性**判据，不引入 LLM 裁判（那是下一批 B 类场景的事）。

已知能力边界（如实记录，不假装覆盖）
----------------------------------
- `/api/agent2/sessions/<sid>/messages` 会**丢弃 `role=tool` 的消息**，所以拿不到工具
  返回的原文 → 做不了"答案里的数字必须能在工具返回里找到"这种更硬的防幻觉断言，
  只能与 ground truth 直接比对。
- 智能体**自己可能调写服务**（如 `inventory_projection.refresh_batch`）。本脚本不主动
  触发写，但**会检测并报告**（`read_only: true` 的场景里一旦发现写调用即判失败）。
  若报告里出现写调用，演示数据可能已变化，需要重跑 `宣传/demo_build.py` 还原。

用法
----
    python scripts/verify_agent_quality.py                  # 全部场景
    python scripts/verify_agent_quality.py --scenario A1    # 只跑一条
    python scripts/verify_agent_quality.py --tag 补货判定
    python scripts/verify_agent_quality.py --dry            # 只算 ground truth，不打扰模型
    python scripts/verify_agent_quality.py --repeat 3       # 每条跑 3 次，报告通过率
    python scripts/verify_agent_quality.py --list           # 只列场景

前置（都要在跑之前就绪）：`python main.py`、`python -m fde_platform.agent_service`、
`/llm` 里配好 operator 模型、以及一套造好的 PSC 数据（`宣传/demo_build.py` +
`宣传/demo_prerun.py` + 跑一次产销协同链）。

退出码：`0` 全过 / `1` 有场景失败 / `2` 前置未就绪（**不是**失败，但要显眼）
"""
import argparse
import io
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

try:  # Windows 控制台 UTF-8
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import httpx  # noqa: E402

CASES = ROOT / "scripts" / "agent_quality" / "cases.jsonl"
BASE = os.environ.get("FDE_BASE", "http://127.0.0.1:4000").rstrip("/")
GROUP = os.environ.get("FDE_AGENT_QUALITY_GROUP", "psc")
ADMIN_PW = os.environ.get("FDE_ADMIN_PW", "admin")
PLANNER_PW = os.environ.get("FDE_AGENT_QUALITY_PLANNER_PW", "")   # 不给 → C1 自动 SKIP
TURN_TIMEOUT = int(os.environ.get("FDE_AGENT_QUALITY_TIMEOUT", "300"))   # 单轮最长等待（秒）
POLL_SECS = 2.0
MIN_IDLE_SECS = 12      # 一个事件都没收到时，至少等这么久才认「跑完了」（防建队期误判）

# 会改数据的业务服务：读问题不该调它们；`read_only` 场景里一出现即判失败
WRITE_SERVICES = {
    "psc__inventory_projection__refresh", "psc__inventory_projection__refresh_batch",
    "psc__inventory_projection__scan_alert",
    "psc__demand_pool__create", "psc__demand_pool__release", "psc__demand_pool__cancel",
    "psc__demand__build_gross", "psc__demand__publish", "psc__demand__calc_net",
    "psc__master_plan__import_plan", "psc__master_plan__import_from_net",
    "psc__strategy_fitting__run", "psc__strategy_fitting__run_batch",
    "psc__strategy_fitting__approve", "psc__strategy_fitting__reject",
    "psc__strategy_fitting__rollback",
    "psc__inventory_strategy__calc", "psc__inventory_strategy__calc_batch",
    "psc__sales_forecast__open_version", "psc__sales_forecast__import_orig_qty",
    "psc__sales_forecast__calc_baseline_batch", "psc__sales_forecast__decide_batch",
    "psc__sales_forecast__summarize", "psc__sales_forecast__set_final",
    "psc__md_material__create", "psc__md_material__update",
    "psc__md_material__import_batch", "psc__md_material__set_fit_params",
    "psc__md_material__sync_external_material",
    "psc__outbound_plan__create", "psc__outbound_plan__update",
    "psc__outbound_plan__delete", "psc__outbound_plan__close_expired",
    "psc__md_monthly_version__create", "psc__md_monthly_version__publish",
    "psc__md_monthly_version__freeze", "psc__md_monthly_version__unfreeze",
}

_C = {"ok": "\033[32m", "bad": "\033[31m", "warn": "\033[33m", "dim": "\033[90m", "0": "\033[0m"}
def _c(k, s):
    return f"{_C.get(k, '')}{s}{_C['0']}" if sys.stdout.isatty() else s


# ── ground truth（只读，现算）─────────────────────────────

_pf = None
_platform_lock = threading.Lock()


_SNAP_FIELDS = ("material_no", "value_class", "prod_days", "logistics_days", "service_level",
                "batch_window", "base_method", "base_params", "predecessor_material_no",
                "sigma_l", "fit_version", "unit_value", "change_risk", "status")


def fingerprint():
    """业务数据指纹（**只读**）：任何写操作都会改变它。

    为什么每条场景都要跑前跑后各取一次：这套测试对着**真实演示数据**跑，而智能体
    有可能自己调写服务（见 `WRITE_SERVICES`）。有了它，两个问题都能被当场回答：
    「这一条有没有弄脏数据」「整个套件跑完数据还是不是原样」。
    它抓到过一次真事：C3 里模型为改一个字段去调 `md_material.import_batch`，
    把该物料十几个字段清成 null（它随后自己恢复了——但那是运气，不是保证）。
    """
    import hashlib
    rows = sorted(_items(call("md_material", "list", size=200)), key=lambda r: r["material_no"])
    blob = "\n".join(json.dumps({k: r.get(k) for k in _SNAP_FIELDS},
                                ensure_ascii=False, sort_keys=True, default=str) for r in rows)
    counts = {}
    for app, svc in (("demand_pool", "list"), ("inventory_projection", "list"),
                     ("strategy_fitting", "list"), ("master_plan", "list"),
                     ("demand", "list"), ("inventory_strategy", "list")):
        try:
            r = call(app, svc, size=1)
            counts[app] = r.get("total") if isinstance(r, dict) else None
        except Exception:
            counts[app] = "?"
    return {"material_hash": hashlib.sha256(blob.encode()).hexdigest()[:16],
            "materials": len(rows), **counts}


def platform():
    """惰性加载平台（只读用途）。多取一次库、与运行中的服务互不影响（WAL 允许并发读）。"""
    global _pf
    with _platform_lock:
        if _pf is None:
            from fde_platform.runtime import FdePlatform
            _pf = FdePlatform()
            _pf.load_all()
    return _pf


def call(app, svc, **kw):
    return platform().call(f"psc/{app}", svc, **kw)


def _items(r):
    if isinstance(r, dict):
        return r.get("items") or []
    return r or []


def x_replenishments(args):
    rows = _items(call("demand_pool", "list", status="待下达", size=200))
    return {
        "materials": [r["material_no"] for r in rows],
        "quantities": [r["replenish_qty"] for r in rows],
        "types": {r["material_no"]: r["replenish_type"] for r in rows},
        "count": len(rows),
        "fb26_qty": next((r["replenish_qty"] for r in rows
                          if r["material_no"] == "BYD-HAN-FB26"), None),
    }


def x_net_demand(args):
    vals = {}
    for rm in ("N+1", "N+2", "N+3"):
        r = call("demand", "get", version_no=args["version_no"],
                 material_no=args["material_no"], rolling_month=rm)
        vals[rm] = (r or {}).get("net_qty") if isinstance(r, dict) else None
    return {"values": [v for v in vals.values() if v is not None], "by_month": vals}


def x_master_plan(args):
    # 注意：`get_latest` 返回的是**列表**（每个滚动月度一行），不是 dict——
    # 取 N+1 那行（主计划只导了 N+1）；当成 dict 取会拿到空值、场景被误判成 SKIP。
    r = call("master_plan", "get_latest", version_no=args["version_no"],
             material_no=args["material_no"])
    rows = r if isinstance(r, list) else ([r] if isinstance(r, dict) else [])
    if not rows:
        return {}
    row = next((x for x in rows if x.get("rolling_month") == "N+1"), rows[0])
    return {"plan_qty": row.get("plan_qty"),
            "latest_inbound_date": row.get("latest_inbound_date"),
            "rolling_month": row.get("rolling_month"), "rows": len(rows)}


def x_water_level(args):
    r = call("inventory_strategy", "get_water_level", version_no=args["version_no"],
             material_no=args["material_no"])
    return dict(r) if isinstance(r, dict) else {}


def x_hedge_groups(args):
    rows = _items(call("inventory_strategy", "list", version_no=args["version_no"], size=200))
    groups = {}
    for r in rows:
        groups.setdefault(r.get("hedge_tool"), []).append(r["material_no"])
    return {"groups": groups, "all_materials": [r["material_no"] for r in rows],
            "count": len(rows)}


def x_fitting_latest(args):
    r = call("strategy_fitting", "get_latest", material_no=args["material_no"])
    return dict(r) if isinstance(r, dict) else {}


def x_unfitted_materials(args):
    """拟合不出预测的物料（pred_method 为空 / 没有拟合行）。"""
    mats = [m["material_no"] for m in _items(call("md_material", "list", size=200))]
    fits = {r["material_no"]: r for r in _items(call("strategy_fitting", "list", size=200))}
    bad = [m for m in mats if not (fits.get(m) or {}).get("pred_method")]
    return {"materials": bad, "all_materials": mats, "count": len(bad)}


def x_history_chain(args):
    r = call("md_material", "history_chain", material_no=args["material_no"])
    chain = r if isinstance(r, list) else (r or {}).get("chain") or []
    return {"chain": chain}


def x_attainment_rank(args):
    rows = _items(call("attainment", "list", size=200))
    rows = [r for r in rows if r.get("mape") is not None]
    rows.sort(key=lambda r: r["mape"], reverse=True)
    return {"worst": rows[0]["material_no"] if rows else None,
            "worst_mape": rows[0]["mape"] if rows else None,
            "ranked": [(r["material_no"], r["mape"], r["bias"]) for r in rows]}


def x_projection_min(args):
    rows = _items(call("inventory_projection", "list", material_no=args["material_no"], size=500))
    if not rows:
        return {}
    lo = min(rows, key=lambda r: r["balance"])
    return {"balance": lo["balance"], "biz_date": lo["biz_date"], "rows": len(rows)}


def x_planner_surface(args):
    """planner01 的**有效授权**集合（与 /agent-admin/permission 同源）+ 未授权应用清单。

    未授权清单在运行期算出来，C1 才能动态断言「没泄漏这些应用」，而不是写死几个名字
    ——写死会随着授权调整失效（还会漏掉别的应用）。
    """
    from fde_platform.agent_admin import permission_view
    pv = permission_view("planner01")
    # 只算**真有可用工具**的组：rows 里也含「整组被打标（usable 为空）」的组，
    # 用 r["app"] 直接收会把它们算成"已授权"——曾经因此让 C1 的泄漏断言变成空断言。
    allowed = {r["app"] for r in pv["rows"] if r["usable"]}
    unauth = [a for a in platform().app_names() if a not in allowed]
    return {"apps": sorted(allowed),
            "unauthorized": sorted(unauth),
            "services": sorted(f"{r['app']}.{s['name']}" for r in pv["rows"] for s in r["usable"])}


def x_none(args):
    return {}


EXTRACTORS = {n[2:]: f for n, f in globals().items() if n.startswith("x_")}


# ── fixture 前置（缺分支就 SKIP，绝不静默通过）──────────────

def r_has_unfitted_material():
    n = x_unfitted_materials({})["count"]
    return (n > 0, f"无「拟合不出预测」的物料（共 {n} 个）——需先导入一个历史为 0 的新料"
                   f"（演示里的 BYD-HAN-FB27 尚未同步进 md_material）")


def r_planner_login():
    if not PLANNER_PW:
        return (False, "未提供 planner01 密码（设 FDE_AGENT_QUALITY_PLANNER_PW 后启用）")
    from fde_platform import users
    if not users.get_user_by_name("planner01"):
        return (False, "库中没有用户 planner01")
    return (True, "")


REQUIRES = {n[2:]: f for n, f in globals().items() if n.startswith("r_")}


# ── 全局前置哨兵 ────────────────────────────────────────

def preflight(client):
    """返回 (ok, 问题列表)。任何一条不过 → 整体 ENV_NOT_READY，不把环境问题记成 agent 失败。"""
    problems = []
    try:
        from fde_platform import llm
        src = llm.effective_source("operator")
        if src == "none":
            problems.append("LLM 未配置：去 /llm 配置 operator 模型，或设 LLM_BASE_URL/LLM_API_KEY")
    except Exception as e:
        problems.append(f"LLM 配置读取失败：{e}")

    try:
        r = client.get(f"{BASE}/api/agent2/health")
        if r.status_code == 503:
            problems.append("agent_service 未就绪：请先 `python -m fde_platform.agent_service`")
    except Exception as e:
        problems.append(f"agent_service 探活失败（{type(e).__name__}）："
                        f"请先 `python -m fde_platform.agent_service`")

    try:
        ctx = env_context()
        if ctx["materials"] != 7:
            problems.append(f"不是演示环境：物料 {ctx['materials']} 个（应 7）。"
                            f"请跑 宣传/demo_build.py")
        if ctx["replenishments"] < 1:
            problems.append("没有待下达的补库单：数据未推进到「补库已生成」状态，"
                            "请跑 宣传/demo_prerun.py 并跑一次产销协同链")
    except Exception as e:
        problems.append(f"数据自检失败：{type(e).__name__}: {e}")
    return (not problems), problems


def env_context():
    return {
        "materials": len(_items(call("md_material", "list", size=200))),
        "replenishments": x_replenishments({})["count"],
        "active_version": call("md_monthly_version", "get_active"),
    }


def env_findings():
    """**环境发现**：与 agent 对错无关，但会解释「为什么某几条场景被跳过」，且本身就是信号。"""
    out = []
    try:
        proj = _items(call("inventory_projection", "list", size=2000))
        alerts = {}
        for r in proj:
            alerts[r["alert_type"]] = alerts.get(r["alert_type"], 0) + 1
        neg = [r for r in proj if (r.get("balance") or 0) < 0]
        if proj and neg and set(alerts) == {"无"}:
            lo = min(neg, key=lambda r: r["balance"])
            out.append(
                f"推移表 {len(proj)} 行**全部标「无预警」**，却有 {len(neg)} 行余额为负"
                f"（最差 {lo['material_no']} {lo['biz_date']} 余额 {lo['balance']}）。"
                f"**这是修复前写下的陈旧数据**：这些行是 refresh 按错误的 biz_date"
                f"（缺省当天 → 推出的当月版本没有水位策略）算出来的。该静默降级路径已在"
                f" BR-12 改成 fail-closed（现在会直接报错、一行不写）。"
                f"要让数据自洽：按**版本开库日**重跑一次推演，或重跑 宣传/demo_prerun.py + 产销协同链。")

        hedge = x_hedge_groups({"version_no": "202610"})
        if hedge["count"] and "速度" not in hedge["groups"]:
            hi = [m["material_no"] for m in _items(call("md_material", "list", size=200))
                  if m.get("value_class") == "高"]
            out.append(
                f"7 个物料的水位策略**全是「库存对冲」，没有一个是「速度对冲」**，"
                f"而业务设计里 BYD-HAN-BRK（高价值+2+1 天）应当是速度对冲。"
                f"**同样是陈旧数据**：这些行由修复前的 calc_batch 算得（那时它一律传"
                f" customer_no=None，判定式右边恒为 0）。BR-11 现在会带**主要客户**，"
                f"重跑 inventory_strategy.calc_batch(version_no=...) 即可看到高价值件{hi}转成速度对冲。")

        act = call("md_monthly_version", "get_active")
        if not act:
            out.append("当前**没有活跃版本**（202610 已冻结）——`demand.calc_net` 会把版本推入"
                       "冻结态。所以任何「当前活跃版本是哪个」的问题，正确答案是「没有」，"
                       "版本相关的问题必须显式指定 202610。")

        unf = x_unfitted_materials({})
        if unf["count"] == 0:
            out.append("**没有 pred_method 为空的物料**：演示设计里的反例料 BYD-HAN-FB27"
                       "（历史为 0 → 应留空待人工）还没同步进 md_material（ERP 只有 7 个物料）。"
                       "→ A8「数据不足」场景目前自动 SKIP。")
    except Exception as e:
        out.append(f"环境发现计算失败：{type(e).__name__}: {e}")
    return out


# ── 对话驱动 ────────────────────────────────────────────

class Agent:
    """经 Flask 反代驱动真对话：登录 → 建会话 → chat/stream(SSE) → 轮询到跑完 → 读历史。"""

    def __init__(self):
        self.client = httpx.Client(timeout=httpx.Timeout(30.0, read=900.0),
                                   follow_redirects=False, trust_env=False)
        self.user = None

    def login(self, username, password):
        r = self.client.post(f"{BASE}/login", data={"username": username, "password": password})
        if r.status_code not in (301, 302, 303):
            raise RuntimeError(f"登录失败（{username}）：HTTP {r.status_code}")
        self.user = username
        return self

    def new_session(self):
        r = self.client.post(f"{BASE}/api/agent2/sessions", json={}, params={"group": GROUP})
        j = r.json()
        sid = (j.get("data") or {}).get("session_id")
        if not sid:
            raise RuntimeError(f"建会话失败：{json.dumps(j, ensure_ascii=False)[:200]}")
        return sid

    def _state(self, sid):
        """(status, 团队有成员没)——与 web.py `_agent2_turn_finished` 同判据。"""
        try:
            j = self.client.get(f"{BASE}/api/agent2/sessions", params={"group": GROUP}).json()
        except Exception:
            return None, False
        for s in (j.get("data") or []):
            if s.get("session_id") == sid:
                return s.get("status"), bool(((s.get("team") or {}).get("members")))
        return None, False

    def turn(self, sid, message, until="idle", on_poll=None):
        """跑一轮，返回 {events, tool_names, confirm, error, answer, elapsed}。

        收尾判据（照前端 agent_rail.js 的 streamUntilIdle）：**只认 `status == "idle"`
        且团队无成员**；`until="confirm_required"` 时一见到停车信号就收。
        必须一直挂着 SSE——服务端靠 `waitress.client_disconnected` 判断人走了会**掐掉这一轮**。
        """
        events, stop = [], {"v": False, "saw_confirm": False, "err": None, "reader": None}
        holder = {}

        def reader():
            try:
                with self.client.stream(
                        "POST", f"{BASE}/api/agent2/chat/stream",
                        json={"message": message, "session_id": sid},
                        params={"group": GROUP}) as r:
                    holder["r"] = r
                    for line in r.iter_lines():
                        if stop["v"]:
                            break
                        line = (line or "").strip()
                        if not line.startswith("data:"):
                            continue
                        try:
                            evt = json.loads(line[5:].strip())
                        except Exception:
                            continue
                        events.append(evt)
                        if evt.get("event") == "confirm_required":
                            stop["saw_confirm"] = True
                        elif evt.get("event") == "error":
                            stop["err"] = evt.get("data")
            except Exception as e:
                if not stop["v"]:
                    stop["err"] = stop["err"] or f"{type(e).__name__}: {e}"
            finally:
                stop["reader"] = "done"

        t0 = time.time()
        th = threading.Thread(target=reader, daemon=True)
        th.start()

        # 起手先给它一点时间把第一个事件吐出来，避免「还没开始跑就已经 idle」的误判。
        # 只有 events 还不够：leader 思考、建队期间可能十几秒不吐任何事件，
        # 那时 status 仍是 idle → 会被误判成"跑完了"，拿到空回答。
        # 所以**零事件时必须等够 MIN_IDLE_SECS 再认 idle**（连续两次 idle 是第二道闸）。
        idle_streak, started = 0, False
        while time.time() - t0 < TURN_TIMEOUT:
            time.sleep(POLL_SECS)
            elapsed = time.time() - t0
            if any(e.get("event") in ("delta", "tool", "confirm_required") for e in events):
                started = True
            if until == "confirm_required" and stop["saw_confirm"]:
                break
            status, has_team = self._state(sid)
            if on_poll:
                on_poll(round(elapsed), status, len(events))
            if until == "confirm_required" and status == "awaiting_permission":
                break
            if status == "idle" and not has_team:
                idle_streak += 1
                if started or (idle_streak >= 2 and elapsed >= MIN_IDLE_SECS):
                    break
            else:
                idle_streak = 0
            if stop["reader"] == "done":
                break

        stop["v"] = True
        r = holder.get("r")
        if r is not None:
            try:
                r.close()          # 让读线程立刻从 iter_lines 里出来，不必等 30s 心跳
            except Exception:
                pass
        th.join(timeout=8)
        # 流可能被提前掐断，历史才是完整的 —— 与前端 finally 后的对账同理
        msgs = self.history(sid)
        tool_names = [t["name"] for t in _tool_calls(msgs)]
        return {
            "events": events,
            "tool_names": tool_names,
            "tool_calls": _tool_calls(msgs),
            "confirm": stop["saw_confirm"],
            "error": stop["err"],
            "answer": _final_answer(msgs),
            "elapsed": round(time.time() - t0, 1),
        }

    def history(self, sid):
        try:
            j = self.client.get(f"{BASE}/api/agent2/sessions/{sid}/messages",
                                params={"group": GROUP}, timeout=120).json()
            return j.get("data") or []
        except Exception:
            return []


def _tool_calls(msgs):
    out = []
    for m in msgs:
        for tc in (m.get("tool_calls") or []):
            fn = tc.get("function") or {}
            args = fn.get("arguments")
            try:
                args = json.loads(args) if isinstance(args, str) else args
            except Exception:
                pass
            out.append({"name": fn.get("name"), "args": args})
    return out


def _final_answer(msgs):
    """最后一条**有正文**的 assistant 消息 = 本轮结论（前面的 assistant 消息多是工具轮）。"""
    for m in reversed(msgs):
        if m.get("role") == "assistant" and (m.get("content") or "").strip():
            return m["content"]
    return ""


# ── 断言 ────────────────────────────────────────────────

_NUM = re.compile(r"-?\d+(?:[.,]\d+)?")
# 模型爱用排版减号（U+2212）与全角数字：不归一化就会把 −1357.64 读成 1357.64，
# 于是「答案里有没有这个负数」判成没有 —— 我第一版就是这么冤枉了 A11 的。
_NORM = str.maketrans({**{c: "-" for c in "−－–—"},
                       **{chr(0xFF10 + i): str(i) for i in range(10)}})


def _nums(text):
    vals = []
    for s in _NUM.findall((text or "").translate(_NORM)):
        try:
            vals.append(float(s.replace(",", "")))
        except ValueError:
            pass
    return vals


def num_present(text, value, tol=0.01):
    """数值是否出现在文本里（容忍四舍五入，并接受 ×100 的百分数写法）。"""
    if value is None:
        return True
    v = float(value)
    for cand in (v, v * 100):
        eps = max(abs(cand) * tol, 0.51)
        for n in _nums(text):
            if abs(n - cand) <= eps:
                return True
    return False


def flat_numbers(gt, keys):
    """从 ground truth 里取出待校验的数值（支持 list / 嵌套 dict）。"""
    out = []
    for k in keys:
        v = gt.get(k) if isinstance(gt, dict) else None
        if isinstance(v, (list, tuple)):
            out += [x for x in v if isinstance(x, (int, float))]
        elif isinstance(v, (int, float)):
            out.append(v)
    return out


def check_case(case, gt, run, strict_read_only=True):
    """三层断言 → [(ok, 层, 说明)]。"""
    exp = case.get("expect") or {}
    ans = run["answer"] or ""
    tools = set(run["tool_names"])
    res = []

    # ── L1 工具轨迹 ──
    any_of = exp.get("must_call_any")
    if any_of:
        hit = sorted(tools & set(any_of))
        res.append((bool(hit), "L1", f"调用了预期工具 {hit or '（一个都没有）'}"
                                     f"；实际 {sorted(tools)[:6]}"))
    neg = exp.get("must_not_call")
    if neg:
        bad = sorted(tools & set(neg))
        res.append((not bad, "L1", f"不该调用的工具：{bad}" if bad else "未调用禁调工具"))
    n_min = exp.get("min_tool_calls")
    if n_min is not None:
        res.append((len(run["tool_calls"]) >= n_min, "L1",
                    f"工具调用 {len(run['tool_calls'])} 次（要求 ≥{n_min}）"
                    f"—— 0 次意味着它在凭记忆答，没去查"))
    if strict_read_only:
        w = sorted(tools & WRITE_SERVICES)
        res.append((not w, "L1", f"⚠ 读问题却调用了写服务：{w}（数据可能已变化）" if w
                                 else "未调用任何写服务"))

    # ── L2 事实 ──
    need = exp.get("numbers_must_appear") or []
    if need:
        for v in flat_numbers(gt, need):
            res.append((num_present(ans, v), "L2", f"答案里应出现权威值 {v}"))
    setkey = exp.get("gt_set_from")
    if setkey:
        want = gt.get(setkey) or []
        missing = [m for m in want if m not in ans]
        res.append((not missing, "L2",
                    f"{len(want)} 个料号应全部出现，缺 {missing}" if missing
                    else f"{len(want)} 个料号全部出现"))

    # ── L3 结论 ──
    for pat in (exp.get("must_include_all") or []):
        res.append((bool(re.search(pat, ans)), "L3", f"答案应匹配 /{pat}/"))
    any_pat = exp.get("must_include_any") or []
    if any_pat:
        res.append((any(bool(re.search(p, ans)) for p in any_pat), "L3",
                    f"答案应至少匹配 {any_pat}"))
    for pat in (exp.get("must_not_match") or []):
        res.append((not re.search(pat, ans), "L3", f"答案不得匹配 /{pat}/"))
    for bad in (exp.get("must_not_include") or []):
        res.append((bad not in ans, "L3", f"答案不得出现「{bad}」（越权泄漏）"))
    if exp.get("must_not_leak_apps"):
        # 只看**工具名形态**（组__应用__服务）：那是真的把工具列表吐出来了。
        # 不查「psc/md_customer」这种限定名——"你无权访问 psc/md_customer" 是正确回答，
        # 拿它判泄漏会把好事判成坏事。
        unauth = gt.get("unauthorized") or []
        leaks = [a for a in unauth if f"{a.replace('/', '__')}__" in ans]
        res.append((not leaks, "L3",
                    f"泄漏了未授权应用的工具：{leaks}（该用户未授权 {len(unauth)} 个应用）"
                    if leaks else f"未泄漏任何未授权应用（对照 {len(unauth)} 个未授权）"))

    # 模型反问缺失参数不算答错，但要单独报出来
    if not ans.strip() and not run["confirm"]:
        res.append((False, "L3", "没有拿到任何回答文本（是传输问题还是它没说话？）"))
    return res


# ── 主流程 ──────────────────────────────────────────────

def _model_name():
    try:
        from fde_platform import llm
        return (llm.load_profile("operator") or {}).get("model") or "?"
    except Exception:
        return "?"


def load_cases():
    out = []
    for line in CASES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def run_one(case, verbose=True):
    """跑一条场景 → 结果 dict。SKIP 与 FAIL 严格分开。"""
    cid, tag = case["id"], case.get("tag", "")
    turns = case.get("turns") or [case["question"]]

    # ① fixture 前置：缺分支就 SKIP（绝不静默通过）
    req = case.get("requires")
    if req:
        ok, why = REQUIRES[req]()
        if not ok:
            return {"id": cid, "tag": tag, "status": "SKIP", "why": why, "question": turns[0]}

    # ② ground truth（只读现算）
    try:
        gt = EXTRACTORS[case["gt"]["extract"]](case["gt"].get("args") or {})
    except Exception as e:
        return {"id": cid, "tag": tag, "status": "SKIP", "question": turns[0],
                "why": f"ground truth 取数失败（{type(e).__name__}: {e}）"}

    if not gt and case["gt"]["extract"] != "none":
        return {"id": cid, "tag": tag, "status": "SKIP", "question": turns[0],
                "why": "ground truth 为空 —— 数据里没有这条分支"}

    before = fingerprint()          # 跑前指纹（写操作会改变它）

    # ③ 真对话
    try:
        ag = Agent().login(case.get("login_as") or "admin",
                           PLANNER_PW if case.get("login_as") else ADMIN_PW)
        sid = ag.new_session()
        run = None
        for i, q in enumerate(turns):
            until = "confirm_required" if (case.get("until") == "confirm_required"
                                           and i == len(turns) - 1) else "idle"
            if verbose:
                print(f"    turn {i + 1}/{len(turns)} “{q[:34]}…”", flush=True)
            run = ag.turn(sid, q, until=until)
            if run["error"]:
                break
    except Exception as e:
        return {"id": cid, "tag": tag, "status": "FAIL", "question": turns[0], "gt": gt,
                "why": f"驱动对话失败：{type(e).__name__}: {e}",
                "checks": [], "answer": "", "tool_names": [], "elapsed": 0}

    checks = check_case(case, gt, run, strict_read_only=case.get("read_only", True))

    after = fingerprint()
    changed = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
    if changed:
        warn_only = not case.get("read_only", True)
        note = "；".join(f"{k}: {v[0]} → {v[1]}" for k, v in changed.items())
        checks.append((warn_only, "L0", f"业务数据被改动：{note}"
                       + ("" if warn_only else "（本场景声明 read_only，不该写）")))
    else:
        checks.append((True, "L0", f"业务数据指纹未变（{before['materials']} 物料/"
                                   f"{before['demand_pool']} 补库单）"))

    bad = [c for c in checks if not c[0]]
    return {"id": cid, "tag": tag, "status": "PASS" if not bad else "FAIL",
            "question": turns[0], "gt": gt, "checks": checks, "failed": bad,
            "answer": run["answer"], "tool_names": run["tool_names"],
            "tool_calls": run["tool_calls"], "confirm": run["confirm"],
            "error": run["error"], "elapsed": run["elapsed"], "events": len(run["events"])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", action="append", help="只跑指定 id（可多次）")
    ap.add_argument("--tag", help="只跑该标签的场景")
    ap.add_argument("--skip-tag", action="append",
                    help="跳过该标签（如 --skip-tag 越权写入被挡住：它会故意诱使智能体尝试写）")
    ap.add_argument("--repeat", type=int, default=1, help="每条重复次数（只用于报告通过率）")
    ap.add_argument("--dry", action="store_true", help="只算 ground truth，不打扰模型")
    ap.add_argument("--list", action="store_true", help="只列场景")
    ap.add_argument("--no-env-findings", action="store_true")
    ap.add_argument("--show-answer", action="store_true", help="打印每条场景的原始回答与工具轨迹")
    args = ap.parse_args()

    cases = load_cases()
    if args.scenario:
        cases = [c for c in cases if c["id"] in set(args.scenario)]
    if args.tag:
        cases = [c for c in cases if args.tag in (c.get("tag") or "")]
    for st in (args.skip_tag or []):
        cases = [c for c in cases if st not in (c.get("tag") or "")]
    if args.list:
        for c in cases:
            print(f"  {c['id']:4s} [{c.get('tag', '')}] {(c.get('question') or (c.get('turns') or [''])[0])}")
        return 0
    if not cases:
        print("没有匹配的场景。")
        return 2

    print("=" * 78)
    print(f"智能体输出质量验收 · {len(cases)} 条场景 · group={GROUP} · {BASE}")
    print("=" * 78)

    if args.dry:
        for c in cases:
            gt = EXTRACTORS[c["gt"]["extract"]](c["gt"].get("args") or {})
            print(f"\n[{c['id']}] {c.get('tag', '')}")
            print(f"  问：{(c.get('question') or (c.get('turns') or [''])[0])}")
            print(f"  权威值：{json.dumps(gt, ensure_ascii=False, default=str)[:400]}")
        return 0

    client = httpx.Client(timeout=60, trust_env=False)
    try:
        client.post(f"{BASE}/login", data={"username": "admin", "password": ADMIN_PW})
    except Exception as e:
        print(_c("bad", f"\n连不上平台（{BASE}）：{type(e).__name__}: {e}"))
        print("→ 请先 `python main.py`")
        return 2

    ok, problems = preflight(client)
    if not ok:
        print(_c("warn", "\n前置未就绪（ENV_NOT_READY）——这是环境问题，不是 agent 答错："))
        for p in problems:
            print(f"  · {p}")
        print("\nVERIFY_RESULT: ENV_NOT_READY")
        return 2

    results = []
    for c in cases:
        for k in range(max(1, args.repeat)):
            tag = f" (第 {k + 1}/{args.repeat} 次)" if args.repeat > 1 else ""
            print(f"\n[{c['id']}] {c.get('tag', '')}{tag}")
            r = run_one(c)
            results.append(r)
            mark = {"PASS": _c("ok", "✓ PASS"), "FAIL": _c("bad", "✗ FAIL"),
                    "SKIP": _c("warn", "— SKIP")}[r["status"]]
            print(f"  {mark}  {r.get('elapsed', 0)}s  {r.get('question', '')[:40]}")
            if r["status"] == "SKIP":
                print(f"        skipped: {r['why']}")
            for okc, layer, note in r.get("checks", []):
                if not okc:
                    print(_c("bad", f"        ✗ [{layer}] {note}"))
            if args.show_answer or r["status"] == "FAIL":
                if r.get("tool_names"):
                    print(f"        工具轨迹: {r['tool_names']}")
                if r.get("answer"):
                    lim = 1200 if args.show_answer else 400
                    print(f"        回答摘录: {r['answer'][:lim].replace(chr(10), ' ')}")
                if r.get("checks"):
                    print("        断言: " + " · ".join(
                        f"{'✓' if ok else '✗'}[{ly}] {nt}" for ok, ly, nt in r["checks"]))

    # ── 汇总 ──
    passed = [r for r in results if r["status"] == "PASS"]
    failed = [r for r in results if r["status"] == "FAIL"]
    skipped = [r for r in results if r["status"] == "SKIP"]
    print("\n" + "=" * 78)
    print(f"通过 {len(passed)} · 失败 {len(failed)} · 跳过 {len(skipped)}"
          f"（共 {len(results)} 条；总耗时 {sum(r.get('elapsed', 0) for r in results):.0f}s）"
          f"  [模型 {_model_name()}]")
    if args.repeat > 1:
        by_id = {}
        for r in results:
            by_id.setdefault(r["id"], []).append(r["status"])
        print("  稳定性（--repeat 仅用于报告，不用于放行）：")
        for cid, sts in by_id.items():
            print(f"    {cid}: {sts.count('PASS')}/{len(sts)} 次通过 {sts}")
    if skipped:
        print("\n  跳过（fixture 缺该分支，不是通过）：")
        for r in skipped:
            print(f"    {r['id']} {r.get('tag', '')}: {r['why']}")
    if failed:
        print("\n  失败明细（期望 → 实际）：")
        for r in failed:
            print(f"    {r['id']} {r.get('tag', '')}")
            for okc, layer, note in r["failed"]:
                print(f"      [{layer}] {note}")

    if not args.no_env_findings:
        print("\n" + "-" * 78)
        print("环境发现（与 agent 对错无关，但会解释上面的跳过，且本身就是信号）：")
        for f in env_findings():
            print(f"  ! {f}")

    print("=" * 78)
    if failed:
        print(f"VERIFY_RESULT: PARTIAL {len(passed)}/{len(passed) + len(failed)}")
        return 1
    print("VERIFY_RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
