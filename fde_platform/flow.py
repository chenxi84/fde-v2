"""FDE 工作流编排（DAG：节点 + 依赖边，拓扑分层 + 并行 + 条件分支 + 循环）。

设计正本：`design-plus/流程编排方案.md`（构建流水线第⑩⑪步，可选增强）。

声明式 flow：`app/<组>/_flow_<名>.yaml`。

两种声明，可混用：
- ``steps``（顺序简写）：按列表顺序执行，前一步结果作为后一步输入。
- ``nodes``（DAG）：每个节点含 ``id`` / ``depends_on``（依赖的节点 id 列表）；
  执行时按依赖拓扑分层，同层无依赖的节点**并行**执行，依赖多个上游的节点自然汇聚。

节点控制流：
- ``when``（条件分支）：执行前判断，不满足则跳过该节点（output 不写 state）。
- ``until`` + ``max_loop``（循环）：执行后判断，不满足则重复执行该节点（最多 max_loop 次）。

条件表达式 ``{key, op, value}``，op 支持 contains / equals / not_empty / empty /
gt / lt / gte / lte（value 可选，缺省视 op 而定）。判断对象是 state 里的值。

节点执行按 ``type`` 分流（缺省 agent，向后兼容）：
- ``agent``：轻量 ReAct 循环（``llm.chat`` + ``bridge.execute``），工具按角色过滤
  （``agent_roles.allowed_tools_for_role``）。
- ``call``：确定性直调应用服务（``bridge.execute``），``call.service``（app.service）
  转 tool 名、``call.args`` 经 ``{key}`` 占位符填充，无 LLM。
- ``skill``：确定性跑已发布技能（``skills.run_skill``），``skill.name`` + ``skill.args``
  作初始 state，无 LLM。

每步 ``output`` 结果键写入共享 state，``input`` 依赖的上游结果键用于填充 ``{key}`` 占位符。

进度上报：写入 config/flow_runs.db（只保留最近一次），供 platform_flow_progress /
前端「编排执行」区读取。
"""
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import yaml

from fde import FdeError
from fde_platform import agent_roles
from fde_platform import agentscope_bridge as bridge
from fde_platform import agent_surface
from fde_platform import builtin_tools
from fde_platform import llm
from fde_platform import users

_ROOT = Path(__file__).resolve().parents[1]
_APPS_DIR = _ROOT / "app"
# 路径**调用时解析**（认 `FDE_CONFIG_ROOT`）：原先这里是模块级常量，环境变量若在 import 后
# 才设（进程内测试的常见顺序）就冻在真 config/ 上了。见 `config_paths.py`。
from fde_platform.config_paths import config_path  # noqa: E402

_MAX_ROUNDS = 10  # 单节点 ReAct 最大轮次（防失控）

_MAX_RUNS = 50  # 运行历史最多保留条数（协同总览时间线用）


class FlowAbort(FdeError):
    """流程级中止：不是"这个节点这次没跑成"，而是"这条流程在当前条件下就不该跑"。

    与普通节点异常**刻意分开**：普通异常记进 state 继续跑（一个节点失败不该拖垮
    整条链，见 `_run_ready`）；而工具面为空这类问题继续跑没有任何意义——下游拿到的
    是零动作的输入，最后产出一段"看着像结论"的东西，还没人看得出它是空的。
    `_run_ready` 只对它放行向上抛。
    """

_SCHEMA = """
CREATE TABLE IF NOT EXISTS flow_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    flow_name TEXT NOT NULL,
    status TEXT NOT NULL,
    step_index INTEGER NOT NULL DEFAULT 0,
    step_total INTEGER NOT NULL DEFAULT 0,
    current_role TEXT DEFAULT '',
    result TEXT DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS flow_run_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    flow_name TEXT NOT NULL,
    status TEXT NOT NULL,
    step_total INTEGER NOT NULL DEFAULT 0,
    result TEXT DEFAULT '',
    updated_at TEXT NOT NULL
);
"""


def _load_flows() -> dict[str, dict]:
    """扫描 app/<组>/_flow_*.yaml，返回 {flow_name: flow_def}（def 含 group/key）。"""
    flows: dict[str, dict] = {}
    if not _APPS_DIR.is_dir():
        return flows
    for group_dir in sorted(_APPS_DIR.iterdir()):
        if not group_dir.is_dir() or group_dir.name.startswith((".", "__")):
            continue
        for f in sorted(group_dir.glob("_flow_*.yaml")):
            try:
                data = yaml.safe_load(f.read_text(encoding="utf-8"))
            except Exception:
                continue  # 声明有误：跳过该 flow
            if not isinstance(data, dict):
                continue
            name = data.get("name")
            if not name:
                continue
            # key = 文件名标识（声明里可显式给 key，缺省从文件名推导）
            key = data.get("key") or f.name[len("_flow_"):-len(".yaml")]
            data["group"] = group_dir.name
            data["key"] = key
            flows[name] = data
    return flows


def list_flows() -> list[dict]:
    """列出全部已声明 flow（含 group/key/name/description/nodes，供前端编排页）。"""
    return [
        {"name": n, "key": f.get("key", ""), "group": f.get("group", ""),
         "description": f.get("description", ""),
         "nodes": _normalize_nodes(f)}
        for n, f in sorted(_load_flows().items())
    ]


def get_flow(group: str, key: str) -> dict | None:
    """读单个 flow 的完整定义（按文件名标识 key）。"""
    path = _APPS_DIR / group / f"_flow_{key}.yaml"
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    data = data or {}
    data["group"] = group
    data["key"] = key
    return data


def save_flow(group: str, key: str, name: str, description: str, nodes: list) -> dict:
    """写盘 app/<group>/_flow_<key>.yaml（name 显示名，key 文件名标识）。"""
    if not group or not key:
        return {"error": "group 和 key 不能为空"}
    path = _APPS_DIR / group / f"_flow_{key}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"name": name or key, "key": key, "description": description or "", "nodes": nodes or []}
    try:
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                        encoding="utf-8")
    except Exception as e:
        return {"error": f"保存失败：{e}"}
    return {"saved": key, "name": name or key}


def delete_flow(group: str, key: str) -> dict:
    """删除 app/<group>/_flow_<key>.yaml。"""
    path = _APPS_DIR / group / f"_flow_{key}.yaml"
    if path.is_file():
        try:
            path.unlink()
        except Exception as e:
            return {"error": f"删除失败：{e}"}
    return {"deleted": key}


# ── 进度上报（只保留最近一次执行）────────────────────────

def _report_progress(flow_name: str, status: str, step_index: int,
                     step_total: int, current_role: str, result: str = "") -> None:
    conn = sqlite3.connect(str(config_path("flow_runs.db")))
    try:
        conn.executescript(_SCHEMA)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("DELETE FROM flow_runs")  # 当前进度只留最近一次
        conn.execute(
            "INSERT INTO flow_runs (flow_name, status, step_index, step_total, "
            "current_role, result, updated_at) VALUES (?,?,?,?,?,?,?)",
            (flow_name, status, step_index, step_total, current_role, result, now),
        )
        if status == "done":
            # 运行结束：追加一条历史（裁剪到 _MAX_RUNS 条，供协同总览时间线）
            conn.execute(
                "INSERT INTO flow_run_history (flow_name, status, step_total, result, updated_at) "
                "VALUES (?,?,?,?,?)",
                (flow_name, status, step_total, result, now),
            )
            conn.execute(
                "DELETE FROM flow_run_history WHERE id NOT IN "
                "(SELECT id FROM flow_run_history ORDER BY id DESC LIMIT ?)",
                (_MAX_RUNS,),
            )
        conn.commit()
    finally:
        conn.close()


def get_progress() -> dict | None:
    """读最近一次 flow 执行的进度（无则 None）。"""
    conn = sqlite3.connect(str(config_path("flow_runs.db")))
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_SCHEMA)
        row = conn.execute("SELECT * FROM flow_runs ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_runs(limit: int = 20) -> list[dict]:
    """读最近 N 条 flow 运行历史（时间线，最新在前）。"""
    conn = sqlite3.connect(str(config_path("flow_runs.db")))
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_SCHEMA)
        rows = conn.execute(
            "SELECT flow_name, status, step_total, result, updated_at "
            "FROM flow_run_history ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limit), _MAX_RUNS)),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── 声明归一化 + 条件判断 + 执行 ─────────────────────────

def _normalize_nodes(flow: dict) -> list[dict]:
    """steps（顺序）或 nodes（DAG）统一成 nodes（含 id + depends_on + type）。

    type 缺省为 agent（智能体 ReAct）；可显式 call（直调服务）/ skill（跑已发布技能）。
    """
    def _with_defaults(n: dict) -> dict:
        node = dict(n)
        node.setdefault("type", "agent")
        return node

    if "nodes" in flow:
        return [_with_defaults(n) for n in flow["nodes"] if isinstance(n, dict)]
    nodes = []
    for i, step in enumerate(flow.get("steps", [])):
        if not isinstance(step, dict):
            continue
        node = _with_defaults(step)
        node.setdefault("id", f"step{i + 1}")
        node.setdefault("depends_on", [] if i == 0 else [f"step{i}"])
        nodes.append(node)
    return nodes


def _fill(task: str, state: dict, inputs: list) -> str:
    """用 state 填充 task 里的 {key} 占位符。"""
    for k in inputs or []:
        task = task.replace("{" + k + "}", str(state.get(k, "")))
    return task


def _check_condition(cond, state: dict) -> bool:
    """判断条件表达式 {key, op, value}（无条件恒真）。"""
    if not isinstance(cond, dict):
        return True
    key = cond.get("key")
    op = cond.get("op", "not_empty")
    value = cond.get("value")
    val = state.get(key, "")
    if op == "contains":
        return str(value) in str(val)
    if op == "equals":
        return str(val) == str(value)
    if op == "not_empty":
        return bool(str(val).strip())
    if op == "empty":
        return not bool(str(val).strip())
    if op in ("gt", "lt", "gte", "lte"):
        try:
            a, b = float(val), float(value)
        except (ValueError, TypeError):
            return False
        return {"gt": a > b, "lt": a < b, "gte": a >= b, "lte": a <= b}[op]
    return True


def _node_tool_usable(user, meta: dict, page_derived=None) -> bool:
    """单个工具对调用者是否可调（口径与 `bridge.execute` 一致）。

    批量场景（`_node_tools`）走 `agent_surface.app_surface` 的**按应用批量版**：
    逐服务调这个函数会退化成 N 次授权查询 + N 次页面注册表扫描（实测把权限视图
    页拖到 60 秒）。这里保留单件判据，供回归测试逐条核对工具面与执行侧同口径。
    """
    app = meta.get("app", "")
    service = meta.get("service", "")
    if app == "__platform__":
        return True  # 平台工具另有下发白名单与 execute 内的 admin 判定
    if builtin_tools.is_builtin_service(service):
        return (user is None or user.get("is_admin")
                or users.has_app_access(user["id"], app))
    return users.is_effectively_granted(user, app, service, page_derived)


def _node_tools(platform, user, role: str, node_id: str = "",
                defs: list | None = None, page_derived=None) -> list[dict]:
    """该节点的工具：先按**角色**收窄，再按调用者**有效授权**收窄。

    两步都是"收窄"，方向一致：节点是脚本化执行者，本就已收窄到该角色的最小可用集，
    不存在「需要看全貌」的场景——所以这里直接过滤，而不是像对话智能体那样
    "保留组、清空工具"。

    收窄到空**必须报错**。从前这里返回空列表，`_run_node` 就拿着一无所有的工具面
    去调 LLM，模型只能回一段文字，节点照样算"成功"——整条流程跑完、一个动作没做、
    不报错。宁可不跑，也不要产出一段零动作的"结论"。

    `defs` 可由调用方预算好传进来（预检、权限视图都要按节点调很多次，
    每次都重建全量工具面会退化成几十秒）。
    """
    if defs is None:
        defs = bridge.tool_schemas(platform, user)
    if role in agent_roles.ROLE_APPS:
        allowed = agent_roles.allowed_tools_for_role(role, defs)
        defs = [t for t in defs if t["function"]["name"] in allowed]

    # 按应用**批量**算可用集：口径与 `_node_tool_usable` 同一份（agent_surface），
    # 但一次查询/一次注册表扫描覆盖整个应用，而不是逐服务各来一遍。
    surface = {r["app"]: set(r["usable"])
               for r in agent_surface.app_surface(defs, user, page_derived)}
    usable = [t for t in defs
              if t["_meta"]["app"] == "__platform__"
              or t["_meta"].get("service", "") in surface.get(t["_meta"]["app"], ())]
    if usable:
        return usable

    apps = sorted({t["_meta"]["app"] for t in defs
                   if t["_meta"].get("app") != "__platform__"})
    who = (user or {}).get("username") or "平台默认身份"
    raise FlowAbort(
        f"节点「{node_id or role}」在角色「{role}」下没有可用工具："
        f"调用者 {who} 缺少这些应用的授权（{'、'.join(apps) or '无'}）。"
        "流程已中止——继续跑只会产出一段零动作的结论。")


def _preflight(nodes: list[dict], platform, user, defs: list | None = None,
               page_derived=None) -> list[str]:
    """预检：**确定会跑**的 agent 节点必须有可用工具。

    只看没有 `when` 的节点：带条件的节点可能本来就会被跳过，不该因为一个
    不会执行的分支把整条流程拦下——那种留到它真跑到时报。

    放在开跑前而不是跑到一半，是为了别让人等几分钟才发现跑不动。
    """
    if defs is None:
        defs = bridge.tool_schemas(platform, user)
    if page_derived is None and user is not None and not user.get("is_admin"):
        page_derived = users.page_derived_services(user["id"])
    problems = []
    for n in nodes:
        if n.get("type", "agent") != "agent" or n.get("when"):
            continue
        try:
            _node_tools(platform, user, n.get("role", ""), n.get("id", ""),
                        defs, page_derived)
        except FdeError as e:
            problems.append(str(e))
    return problems


def _run_node(platform, user, role: str, task: str, node_id: str = "") -> str:
    """轻量 ReAct 循环：带该角色工具的 LLM，多轮调工具，返回最终文本结论。"""
    prov = llm.get_provider("operator")
    if isinstance(prov, llm.NotConfiguredProvider):
        return "（LLM 未配置，无法执行该节点）"
    defs = _node_tools(platform, user, role, node_id)
    tools = [{"type": "function", "function": t["function"]} for t in defs]
    label = agent_roles.role_label(role) or "编排节点"
    messages = [
        {"role": "system",
         "content": f"你是「{label}」。按用户任务调用工具完成，最后用中文给出简明结论。"},
        {"role": "user", "content": task},
    ]
    for _ in range(_MAX_ROUNDS):
        resp = prov.chat(messages, tools=tools or None)
        if not isinstance(resp, dict):
            return str(resp)
        tcs = resp.get("tool_calls")
        if tcs:
            messages.append({"role": "assistant",
                             "content": resp.get("content", ""), "tool_calls": tcs})
            for tc in tcs:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except Exception:
                    args = {}
                result = bridge.execute(platform, user, name, args)
                messages.append({"role": "tool",
                                 "tool_call_id": tc.get("id", ""), "content": result})
        else:
            return resp.get("content", "") or "（节点未产出结论）"
    # 轮次耗尽：返回最后一条 assistant 文本（若有）
    for m in reversed(messages):
        if m.get("role") == "assistant" and m.get("content"):
            return m["content"]
    return "（节点未产出结论）"


def _fill_args(args: dict, state: dict, inputs: list) -> dict:
    """用 state 填充 args 里各字符串值的 {key} 占位符（非字符串值原样保留）。"""
    out = {}
    for k, v in (args or {}).items():
        out[k] = _fill(v, state, inputs) if isinstance(v, str) else v
    return out


def _execute_call_node(node: dict, state: dict, platform, user, group: str = ""):
    """type=call：确定性直调应用服务（bridge.execute），无 LLM。"""
    call = node.get("call") or {}
    service = str(call.get("service", "")).strip()
    if not service:
        raise FdeError("call 节点缺 service（形如 app.service）")
    # app.service → group__app__service（bridge 索引 key；group 由 flow 归属补全）
    tool_name = service.replace(".", "__")
    if group:
        tool_name = f"{group}__{tool_name}"
    args = _fill_args(call.get("args") or {}, state, node.get("input"))
    raw = bridge.execute(platform, user, tool_name, args)
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        data = raw
    if isinstance(data, dict) and data.get("error"):
        raise FdeError(f"call {service} 失败：{data['error']}")
    return data


def _execute_skill_node(node: dict, state: dict, platform, user):
    """type=skill：确定性跑一个已发布技能（skills.run_skill），无 LLM。"""
    from fde_platform import skills

    skill = node.get("skill") or {}
    name = str(skill.get("name", "")).strip()
    if not name:
        raise FdeError("skill 节点缺 name（已发布技能名）")
    init_state = _fill_args(skill.get("args") or {}, state, node.get("input"))
    return skills.run_skill(name, platform, user, init_state=init_state)


def _execute_node(node: dict, state: dict, platform, user, group: str = ""):
    """执行单节点：when 不满足返回 None（跳过）；否则按 type 执行，until 不满足则循环。

    type：call（直调服务）/ skill（跑技能）/ agent（智能体 ReAct，默认）。
    """
    if not _check_condition(node.get("when"), state):
        return None
    output_key = node.get("output")
    max_loop = max(1, int(node.get("max_loop", 1)))
    ntype = node.get("type", "agent")
    result = ""
    for _ in range(max_loop):
        if ntype == "call":
            result = _execute_call_node(node, state, platform, user, group)
        elif ntype == "skill":
            result = _execute_skill_node(node, state, platform, user)
        else:  # agent（默认，向后兼容旧 YAML 无 type）
            task = _fill(str(node.get("task", "")), state, node.get("input"))
            result = _run_node(platform, user, node.get("role", ""), task,
                               node.get("id", ""))
        if output_key:
            state[output_key] = result  # 先写 output，供 until 判断
        until = node.get("until")
        if not until or _check_condition(until, state):
            break
    return result


def _run_ready(nids: list[str], node_by_id: dict, state: dict, platform, user, group: str = "") -> dict:
    """并行执行一批就绪节点，返回 {node_id: result}（result 为 None 表示跳过）。"""
    results: dict = {}
    if not nids:
        return results
    with ThreadPoolExecutor(max_workers=len(nids)) as ex:
        futures = {
            ex.submit(_execute_node, node_by_id[nid], state, platform, user, group): nid
            for nid in nids
        }
        for fut in as_completed(futures):
            nid = futures[fut]
            try:
                results[nid] = fut.result()
            except FlowAbort:
                raise  # 流程级问题：不降级成文本，交给 run_flow 中止整条流程
            except Exception as e:  # 单节点失败不影响其他节点
                results[nid] = f"（节点执行失败：{e}）"
    return results


def run_flow(name: str, platform, user) -> dict:
    """按 DAG 执行一个 flow（拓扑分层 + 同层并行 + 条件分支/循环），返回 state。"""
    flow = _load_flows().get(name)
    if flow is None:
        return {"error": f"flow 不存在：{name}"}
    nodes = _normalize_nodes(flow)
    group = flow.get("group", "")
    node_by_id = {n.get("id"): n for n in nodes if n.get("id")}
    deps = {nid: set(node_by_id[nid].get("depends_on") or []) for nid in node_by_id}
    total = len(node_by_id)

    # 预检放在开跑前：跑不动要立刻知道，别等几分钟后才发现产出是空的
    problems = _preflight(nodes, platform, user)
    if problems:
        msg = "；".join(problems)
        _report_progress(name, "error", 0, total, "", msg[:2000])
        return {"error": "流程预检未通过：" + msg}

    state: dict = {}
    done: set = set()
    _report_progress(name, "running", 0, total, "")
    while len(done) < total:
        ready = [nid for nid in deps if nid not in done and deps[nid] <= done]
        if not ready:
            break  # 循环依赖或缺失上游：终止，避免死循环
        try:
            batch = _run_ready(ready, node_by_id, state, platform, user, group)
        except FlowAbort as e:
            _report_progress(name, "error", len(done), total, "", str(e)[:2000])
            return {"error": f"流程中止：{e}"}
        for nid, result in batch.items():
            node = node_by_id[nid]
            if result is None:
                continue  # when 跳过：output 不写 state
            key = node.get("output")
            if key and result is not None:
                state[key] = result
            done.add(nid)
            _report_progress(name, "running", len(done), total, node.get("role", ""))
    _report_progress(name, "done", len(done), total, "",
                     json.dumps(state, ensure_ascii=False)[:2000])
    return state
