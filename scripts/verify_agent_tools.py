"""智能体工具面回归：守住「工具静默消失」与「工具面膨胀」两类问题。

为什么需要这个脚本
------------------
2026-09 出过一次事故：`platform_run_flow` 等流程编排工具被工厂层一句 `continue`
连坐丢弃，「让数字员工跑工作流」「让大模型创建工作流」两条路都不通——
而工具定义在、middleware 放行，**运行期没有任何报错**，只有真去调才发现工具不在。
这类「静默消失」只有把登记完整性变成断言才守得住。

另一半是「静默膨胀」：加几个应用，单次可见工具数就悄悄爬回塌陷区。
外部证据（arXiv:2605.24660）显示单次呈现超过 ~60 个工具即进入选择塌陷区。

用法：
    python scripts/verify_agent_tools.py
退出码 0 = 全通过；1 = 有失败项。
"""
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

PASS, FAIL = [], []

# 单次呈现预算：常驻（平台工具）+ 一次激活的组。
#
# 目标 25 的由来（见 宣传/工具面收敛方案.md §三）：学术锚点是呈现 ~7 个即达 90%+，
# 塌陷区在 ~60。25 落在「远好于 66 的平铺」与「不强求做到 7」之间，是可达的工程目标。
# 每组 15 里含 3 个按应用隔离的文件工具（platform_read_file 等），
# 所以业务服务实际预算是 12 —— 这也是本文件里两个常数不相等的原因。
VISIBLE_BUDGET = 25        # 常驻 + 最大的一组
GROUP_BUDGET = 15          # 单个应用组（业务服务 + 该应用的 3 个文件工具）

# `_meta` 各键的**消费者登记表**。新增字段必须登记——「标了不用」与「工具静默消失」
# 是同一类失效：静态看不出、运行期不报错。`dangerous` 就曾长期是死字段（18 个 True 无人读）。
META_CONSUMERS = {
    "app":       "工具路由 / 鉴权 / 按组收窄（agent_service、agent_roles）",
    "service":   "服务名过滤与平台工具白名单（agent_service）",
    "app_name":  "流程编排服务下拉（web.py /api/flow-service-options）",
    "dangerous": "HITL 闸门（agent_service._is_dangerous）",
}


def check(label, cond, detail=""):
    (PASS if cond else FAIL).append(label)
    print(f"  [{'OK' if cond else 'FAIL'}] {label:52s} {detail}")
    return cond


def _dup_dict_keys(path):
    """AST 找字典字面量里的重复键。

    Python 对 `{"a": 1, "a": 2}` 是**静默丢弃**前者，不报错也不警告——
    声明文件里写重一个应用，那批服务就会悄无声息地不被摘掉。
    这类「看不出来的失效」正是本脚本存在的理由，所以用 AST 查。
    """
    import ast

    dups = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Dict):
            seen = set()
            for k in node.keys:
                if isinstance(k, ast.Constant):
                    if k.value in seen:
                        dups.append(k.value)
                    seen.add(k.value)
    return dups


def main():
    from fde_platform import agent_roles, agentscope_bridge as bridge, users
    from fde_platform.runtime import FdePlatform
    import fde_platform.agent_service as A

    pf = FdePlatform()
    pf.load_all()
    defs = bridge.tool_schemas(pf, users.get_user_by_name("admin"))

    # ── ① 登记完整性：平台工具一个都不能漏 ─────────────────────
    print("\n① 平台工具登记完整性（防「静默消失」）")
    gaps = A.platform_tool_registry_gaps()
    check("所有平台工具都已登记下发策略", not gaps,
          f"未登记：{sorted(gaps)}" if gaps else "无缺口")
    check("白名单与拒绝名单不重叠",
          not (A._LEADER_PLATFORM_TOOLS & A._LEADER_PLATFORM_DENIED))

    # ── ② leader 到底拿到哪些平台工具 ──────────────────────────
    print("\n② leader 的平台工具（端到端语义，不只看常量）")
    for svc in ("run_flow", "list_flows", "flow_progress", "save_flow"):
        check(f"leader 拿得到 {svc}", A._leader_gets_platform_tool(svc))
    for svc in ("create_user", "set_user_role", "create_job", "save_integration"):
        check(f"leader 拿不到 admin 工具 {svc}",
              not A._leader_gets_platform_tool(svc))

    # ── ③ 剪枝声明必须指向真实存在的服务 ───────────────────────
    # 写错服务名会静默失效（声明了等于没声明），所以要比对真实服务清单。
    print("\n③ 剪枝声明有效性（防「声明写错静默失效」）")
    real = {}
    for t in defs:
        real.setdefault(t["_meta"]["app"], set()).add(t["_meta"].get("service", ""))
    bad = []
    for app, svcs in agent_roles.HIDDEN_FROM_AGENT.items():
        if app not in real:
            bad.append(f"{app}（应用不存在）")
            continue
        for s in svcs:
            if s not in real[app]:
                bad.append(f"{app}.{s}（服务不存在）")
    check("剪枝声明全部指向真实服务", not bad, f"无效声明：{bad}" if bad else "")

    for decl in (ROOT / "app").glob("*/_agent_tools.py"):
        dups = _dup_dict_keys(decl)
        check(f"{decl.parent.name}/_agent_tools.py 无重复键", not dups,
              f"重复：{dups}" if dups else "")

    # ── ④ 剪枝后的实际可见量 ───────────────────────────────────
    print("\n④ 工具面规模（防「静默膨胀」）")
    pruned = [t for t in defs
              if not agent_roles.is_hidden_from_agent(
                  t["_meta"]["app"], t["_meta"].get("service", ""))]
    check("剪枝确实生效", len(pruned) < len(defs),
          f"{len(defs)} → {len(pruned)}")

    basic_n = len(A._WORKER_PLATFORM_TOOLS)
    check("worker 常驻平台工具 ≤ 10", basic_n <= 10, f"{basic_n} 个")

    # 分组口径必须用工厂那个函数，不能在这儿另写一份 ——
    # 初版测试就是自己复刻了一遍分组逻辑，于是漏掉了 leader 按角色分组
    # 导致 sales 一组 58 个工具的问题（工厂与测试对不上，正是这次事故的形态）。
    def _report(who, by_app, basic):
        sizes = sorted((len(v) for v in by_app.values()), reverse=True)
        if not sizes:
            return
        top = sizes[0]
        check(f"{who} 最大组 ≤ {GROUP_BUDGET}", top <= GROUP_BUDGET,
              f"最大 {top} 个（{len(by_app)} 组）")
        check(f"{who} 主路径可见数 ≤ {VISIBLE_BUDGET}",
              basic + top <= VISIBLE_BUDGET,
              f"常驻 {basic} + 最大组 {top} = {basic + top}")
        # 最坏情况（多组同时激活）只报告不设闸：那是模型行为，靠 _GROUP_INSTRUCTIONS
        # 让它在转域前先停用本组来缓解；要结构性解决得做工具合并（方案里的 P4，
        # 已评估为收益不足、暂缓）。给个很松的闸只为发现失控。
        worst = basic + sum(sizes[:2])
        check(f"{who} 最坏可见数（两组）有上界", worst <= 45, f"{worst}")

    # worker 路径：各角色按 allowed 收窄后分组
    for role in ("sales", "planning", "inventory", "delivery"):
        allowed = agent_roles.allowed_tools_for_role(role, pruned)
        keep = [t for t in pruned
                if t["_meta"]["app"] != "__platform__"
                and t["function"]["name"] in allowed]
        _report(f"worker/{role}", A._split_by_app(keep), basic_n)

    # leader 路径：拿本组全部业务工具（此处以 psc 组为例）
    leader_keep = [t for t in pruned
                   if t["_meta"]["app"].startswith("psc/")]
    _report("leader/psc", A._split_by_app(leader_keep), len(A._LEADER_PLATFORM_TOOLS))

    # ── ⑤ 组描述可用（模型靠它决定要不要激活） ─────────────────
    print("\n⑤ 组描述（决定模型能否选对组）")
    sample = ["psc/sales_forecast", "psc/md_material", "psc/strategy_fitting"]
    for app in sample:
        d = A._app_group_desc(app)
        has_cn = any("一" <= ch <= "鿿" for ch in d)
        check(f"{app} 描述含中文职责", has_cn and len(d) > 4, d[:46])

    # ── ⑥ HITL 闸门（哪些工具要人工确认） ─────────────────────
    print("\n⑥ HITL 闸门（防「该拦没拦」与「误伤」）")
    by_name = {t["function"]["name"]: t for t in defs}

    def gated(app: str, svc: str) -> bool:
        t = by_name.get(f"{app.replace('/', '__')}__{svc}")
        return bool(t) and A._is_dangerous(t)

    # 漏网补上的四个：名字里没有关键词，但副作用不可逆（calc_net 会冻结版本！）
    for app, svc, why in (
            ("psc/demand", "calc_net", "会联动冻结月度版本"),
            ("psc/md_monthly_version", "freeze", "冻结版本"),
            ("psc/strategy_fitting", "rollback", "作废已生效拟合"),
            ("psc/outbound_plan", "delete", "真删除"),
    ):
        check(f"{svc} 需人工确认（{why}）", gated(app, svc))

    # 误伤解除：到期自动关闭是惰性结算（读列表时顺带触发），拦它等于每次查询都要点确认
    check("close_expired 不需确认（惰性结算，非危险动作）",
          not gated("psc/outbound_plan", "close_expired"))

    # 平台工具改用它们**自己声明的** _meta.dangerous（原来这个字段从没被读过）
    plat = [t for t in defs if t["_meta"]["app"] == "__platform__"]
    declared = [t for t in plat if t["_meta"].get("dangerous")]
    honored = [t for t in declared if A._is_dangerous(t)]
    check("平台工具的 dangerous 声明被真正使用",
          len(honored) == len(declared),
          f"{len(honored)}/{len(declared)} 个 True 声明的被拦")

    # 清单里的服务名必须真实存在（写错 = 静默不生效，与剪枝同一类坑）
    all_svc = set()
    for t in defs:
        if t["_meta"]["app"] != "__platform__":
            all_svc.add(t["_meta"].get("service", ""))
    ghost = sorted(s for s in A._HITL_SERVICES if s not in all_svc)
    check("HITL 清单里的服务名都真实存在", not ghost,
          f"幽灵条目：{ghost}" if ghost else f"{len(A._HITL_SERVICES)} 条全部命中")

    # ── ⑦ _meta 字段的消费者登记（防死字段） ───────────────────
    # 「标了不用」和「工具静默消失」是同一类失效：静态看不出、运行期没报错。
    # `_meta.dangerous` 就曾标了 18 个 True 却从没被读过——没人问过「这个字段谁来读」。
    # 用登记表而不是自动扫描：grep 判「只写不读」很脆（["key"] 会命中大量无关代码）。
    print("\n⑦ _meta 字段消费者登记（防死字段）")
    produced = {k for t in defs for k in (t.get("_meta") or {})}
    unregistered = sorted(produced - set(META_CONSUMERS))
    check("工具产出的 _meta 字段都已登记消费者", not unregistered,
          f"未登记：{unregistered}（新增字段请登记它由谁读）" if unregistered
          else f"{len(produced)} 个字段全部有登记")
    stale = sorted(set(META_CONSUMERS) - produced)
    check("登记表里没有已消失的字段", not stale,
          f"表中多余：{stale}（字段已删，表要同步）" if stale else "")

    # 角色绑定的应用必须都有 HOWTOUSE.md —— 漏写不会报错、只是静默地不注入，
    # 而「静默地少了一块」正是这类事故的形态（见 CONVENTION §11）。
    missing_howto = agent_roles.apps_missing_howto()
    check("角色绑定的应用都有 HOWTOUSE.md", not missing_howto,
          f"缺：{missing_howto}" if missing_howto else "全部就位")

    # ── 汇总 ──────────────────────────────────────────────────
    print("\n" + "=" * 74)
    print(f"  结果：{len(PASS)} 项通过，{len(FAIL)} 项失败")
    for f in FAIL:
        print(f"    [FAIL] {f}")
    print("=" * 74)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
