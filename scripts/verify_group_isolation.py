# -*- coding: utf-8 -*-
"""AI管家三块数据的**应用组隔离**取证（静态门禁用，不起服务、不碰真库）。

## 为什么要有它

2026-09-26 用户报的缺陷：**AI管家里的 SKILL / 告警 / 运转动态没有做应用组隔离** ——
在 A 组的 AI管家里会看到 B 组的数据。根因不是页面忘了传参那么简单：**数据本身就不带组归属**
（`skill` / `agent_alerts` / `flow_run_history` 三张表都没有组字段），其中「库存预警」那条
告警来源还硬编码直调 `psc/inventory_projection`，与当前组毫无关系。

这类缺陷**没有任何测试会红**：端点返回 200、页面渲染正常、数字看着还挺丰富。所以单独对账。

## 口径（与代码同源）

- **组视角** = 本组 ∪ 平台级（`module` 为空的存量与平台级写入）；**平台视角**（不带 group）= 全量。
- 写入路径必须把**当前 agent 的组**落进去（`bridge.execute(..., module=)` ← `agent_service` 的
  闭包按 leader/worker 分别取组）。

## 判据

1. 组视角只含「本组 + 平台级」（不串组）
2. 各组的可见集**并上平台级 == 全量**（平台级不丢数据；存量回填后也不会凭空消失）
3. 平台视角 == 全量（管理页看得到一切）
4. **写入带归属**：`_call_platform_tool` 走一遍 propose_skill / raise_alert，落库的 module 就是传入的组
5. **前端取数带组**（源码级）：`view/pages/*.js` 里对这三个端点的请求必须带 `group=`

全部在**临时 config 根**里跑（`SKILL_DB` + `FDE_CONFIG_ROOT` 指到 tempfile），
真库零接触 —— 注意 `skills.DB_PATH` 是**模块级常量**，所以必须在 import 之前设好环境变量。
"""
import os
import re
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
FAILS = []


def check(ok, note):
    print(f"  {'✓' if ok else '✗'} {note}")
    if not ok:
        FAILS.append(note)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="fde_groupiso_"))
    # ⚠ 顺序要紧：`skills.DB_PATH` 在 **import 时**读 SKILL_DB（模块级常量，后设无效）
    os.environ["SKILL_DB"] = str(tmp / "skills.db")
    os.environ["FDE_CONFIG_ROOT"] = str(tmp)
    sys.path.insert(0, str(ROOT))
    from fde_platform import alerts, flow, skills
    from fde_platform import agentscope_bridge as bridge

    G = "psc"                      # 造数组
    OTHER = "nasa_pms"             # 另一个组（用来验"不串组"）

    print("【1】写入路径带归属")
    r1 = bridge._call_platform_tool(None, None, "propose_skill",
                                    {"name": "组内技能", "description": "d", "trigger": "t",
                                     "steps": [{"tool": "psc__md_material__list", "args": {}}]},
                                    module=G)
    check(r1.get("module") == G, f"propose_skill(module={G}) 落库归属 = {r1.get('module')!r}")
    r2 = bridge._call_platform_tool(None, None, "propose_skill",
                                    {"name": "平台级技能", "description": "d", "trigger": "t",
                                     "steps": [{"tool": "platform_list_flows", "args": {}}]})
    check(r2.get("module") == "", f"propose_skill(不带 module) 落库为平台级 = {r2.get('module')!r}")
    a1 = bridge._call_platform_tool(None, None, "raise_alert",
                                    {"title": "组内告警", "level": "amber"}, module=G)
    check(bool(a1.get("id")), f"raise_alert(module={G}) 落库 id={a1.get('id')}")
    bridge._call_platform_tool(None, None, "raise_alert", {"title": "平台级告警", "level": "red"})

    print("【2】运转动态：写两条（一组一平台级）")
    flow._report_progress("组内流程", "done", 1, 1, "", "{}", G)
    flow._report_progress("平台级流程", "done", 1, 1, "", "{}", "")

    def names(items, key="name"):
        return sorted(re.sub(r"（.*$", "", str(x.get(key) or x.get("title") or "")) for x in items)

    print("【3】三块数据的组视角口径")
    sk_all, sk_g, sk_o = (skills.list_skills(), skills.list_skills(module=G),
                          skills.list_skills(module=OTHER))
    check(set(names(sk_g)) == {"组内技能", "平台级技能"}, f"技能 · {G} 视角 = {names(sk_g)}")
    check(names(sk_o) == ["平台级技能"], f"技能 · {OTHER} 视角 = {names(sk_o)}（不串组）")
    check(set(names(sk_g)) | set(names(sk_o)) == set(names(sk_all)),
          f"技能 · 并集 == 全量（平台级没丢）：{names(sk_all)}")

    al_all = alerts.list_agent_alerts()
    al_g = alerts.list_agent_alerts(module=G)
    al_o = alerts.list_agent_alerts(module=OTHER)
    check(sorted(x["title"] for x in al_g) == ["平台级告警", "组内告警"], f"告警 · {G} 视角枚举")
    check([x["title"] for x in al_o] == ["平台级告警"], f"告警 · {OTHER} 视角 = {[x['title'] for x in al_o]}")
    check(len(al_g) + len(al_o) - 1 == len(al_all), "告警 · 并集 == 全量（平台级只算一次）")
    check(all("module" in x for x in al_all), "告警 · 每条都带 module（页面据此打「平台级」标记）")

    rn_all, rn_g, rn_o = (flow.list_runs(50), flow.list_runs(50, module=G),
                          flow.list_runs(50, module=OTHER))
    check([x["flow_name"] for x in rn_g] == ["平台级流程", "组内流程"], "运转 · psc 视角")
    check([x["flow_name"] for x in rn_o] == ["平台级流程"], "运转 · 另一组视角（不串组）")
    check(len(rn_g) + len(rn_o) - 1 == len(rn_all), "运转 · 并集 == 全量")

    print("【4】注入面也按组收窄（技能步骤里写的是具体工具，别组技能注进去只会撞墙）")
    check(names(skills.published_skills(G)) == [], "未审批的技能谁都拿不到（生命周期没变）")
    skills.approve(r1["id"])
    skills.approve(r2["id"])
    check(set(names(skills.published_skills(G))) == {"平台级技能", "组内技能"},
          f"已发布 · {G} 视角 = {names(skills.published_skills(G))}")
    check(names(skills.published_skills(OTHER)) == ["平台级技能"],
          f"已发布 · {OTHER} 视角 = {names(skills.published_skills(OTHER))}")

    print("【5】前端取数带组（源码级代理判据）")
    # ⚠ 这是**源码级代理**：真正跑起来的行为由上面【3】的 API 口径 + 组级 e2e 保证；
    #   这里只防"页面又忘了传 group"这一类回归（正是用户报的那个缺陷形状）。
    # 取证方式：抓取数表达式，要求它要么自带 `group=`，要么拼的是**本文件里含 `group=` 的变量**
    #   （页面普遍写成 `const qs = g ? "?group=..." : ""` 再 `get(url + qs)`）。
    expr_pat = re.compile(r'get\(\s*("(?:/api/(?:skills|alerts|flow-runs)[^"]*)"'
                          r'(?:\s*\+\s*([A-Za-z_$][\w.$]*))?)')
    var_pat = re.compile(r'(\w+)\s*=\s*[^;\n]*group=')
    for js in sorted((ROOT / "view" / "pages").glob("*.js")):
        src = js.read_text(encoding="utf-8", errors="replace")
        with_group = set(var_pat.findall(src))
        for mm in expr_pat.finditer(src):
            # ⚠ group(1) 是**整段表达式**（`"/api/x" + qs`）；代码注释里提到它的那句
            #   "只抓引号内的路径会假红" —— 别再把 group(1) 与 group(2) 拼一次（拼了会印成 `+ qs + qs`）
            expr, var = mm.group(1), mm.group(2)
            ok = ("group=" in expr) or (var in with_group)
            check(ok, f"{js.name}: {expr} 带组" if ok else
                  f"{js.name}: {expr} **不带组**"
                  f"（本文件里含 group= 的变量：{sorted(with_group)}）")

    print("【6】真库零接触")
    real = ROOT / "config"
    check(not str(tmp).startswith(str(real)), f"全程写在临时根 {tmp.name}/（真 config/ 未参与）")

    print("\n" + "=" * 60)
    if FAILS:
        print(f"  ✗ {len(FAILS)} 条不成立：")
        for f in FAILS:
            print("    ·", f)
        print("  VERIFY_RESULT: FAIL")
        return 1
    print("  ✓ 全部判据成立")
    print("  VERIFY_RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
