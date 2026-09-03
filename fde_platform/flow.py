"""FDE 工作流编排（DAG：节点 + 依赖边，拓扑分层 + 并行 + 条件分支 + 循环）。

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

节点执行 = 轻量 ReAct 循环（``llm.chat`` + ``bridge.execute``），工具按角色过滤
（``agent_roles.allowed_tools_for_role``）。每步 ``output`` 结果键写入共享 state，
``input`` 依赖的上游结果键用于填充 ``{key}`` 占位符。

进度上报：写入 config/flow_runs.db（只保留最近一次），供 platform_flow_progress /
前端「编排执行」区读取。
"""
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import yaml

from fde_platform import agent_roles
from fde_platform import agentscope_bridge as bridge
from fde_platform import llm

_ROOT = Path(__file__).resolve().parents[1]
_APPS_DIR = _ROOT / "app"
_PROGRESS_DB = _ROOT / "config" / "flow_runs.db"

_MAX_ROUNDS = 10  # 单节点 ReAct 最大轮次（防失控）

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
"""


def _load_flows() -> dict[str, dict]:
    """扫描 app/<组>/_flow_*.yaml，返回 {flow_name: flow_def}。"""
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
            name = (data or {}).get("name") if isinstance(data, dict) else None
            if not name:
                continue
            flows[name] = data
    return flows


def list_flows() -> list[dict]:
    """列出全部已声明 flow（供 platform_list_flows）。"""
    return [
        {"name": n, "description": f.get("description", ""),
         "step_count": len(_normalize_nodes(f))}
        for n, f in sorted(_load_flows().items())
    ]


# ── 进度上报（只保留最近一次执行）────────────────────────

def _report_progress(flow_name: str, status: str, step_index: int,
                     step_total: int, current_role: str, result: str = "") -> None:
    conn = sqlite3.connect(str(_PROGRESS_DB))
    try:
        conn.execute(_SCHEMA)
        conn.execute("DELETE FROM flow_runs")  # 只保留最近一次执行
        conn.execute(
            "INSERT INTO flow_runs (flow_name, status, step_index, step_total, "
            "current_role, result, updated_at) VALUES (?,?,?,?,?,?,?)",
            (flow_name, status, step_index, step_total, current_role, result,
             datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
    finally:
        conn.close()


def get_progress() -> dict | None:
    """读最近一次 flow 执行的进度（无则 None）。"""
    conn = sqlite3.connect(str(_PROGRESS_DB))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(_SCHEMA)
        row = conn.execute("SELECT * FROM flow_runs ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ── 声明归一化 + 条件判断 + 执行 ─────────────────────────

def _normalize_nodes(flow: dict) -> list[dict]:
    """steps（顺序）或 nodes（DAG）统一成 nodes（含 id + depends_on）。"""
    if "nodes" in flow:
        return [dict(n) for n in flow["nodes"] if isinstance(n, dict)]
    nodes = []
    for i, step in enumerate(flow.get("steps", [])):
        if not isinstance(step, dict):
            continue
        node = dict(step)
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


def _node_tools(platform, user, role: str) -> list[dict]:
    """该节点的工具：业务角色按 allowed_tools_for_role 过滤；否则全量。"""
    defs = bridge.tool_schemas(platform, user)
    if role in agent_roles.ROLE_APPS:
        allowed = agent_roles.allowed_tools_for_role(role, defs)
        return [t for t in defs if t["function"]["name"] in allowed]
    return defs


def _run_node(platform, user, role: str, task: str) -> str:
    """轻量 ReAct 循环：带该角色工具的 LLM，多轮调工具，返回最终文本结论。"""
    prov = llm.get_provider("operator")
    if isinstance(prov, llm.NotConfiguredProvider):
        return "（LLM 未配置，无法执行该节点）"
    defs = _node_tools(platform, user, role)
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


def _execute_node(node: dict, state: dict, platform, user):
    """执行单节点：when 不满足返回 None（跳过）；否则执行，until 不满足则循环。"""
    if not _check_condition(node.get("when"), state):
        return None
    output_key = node.get("output")
    max_loop = max(1, int(node.get("max_loop", 1)))
    result = ""
    for _ in range(max_loop):
        task = _fill(str(node.get("task", "")), state, node.get("input"))
        result = _run_node(platform, user, node.get("role", ""), task)
        if output_key:
            state[output_key] = result  # 先写 output，供 until 判断
        until = node.get("until")
        if not until or _check_condition(until, state):
            break
    return result


def _run_ready(nids: list[str], node_by_id: dict, state: dict, platform, user) -> dict:
    """并行执行一批就绪节点，返回 {node_id: result}（result 为 None 表示跳过）。"""
    results: dict = {}
    if not nids:
        return results
    with ThreadPoolExecutor(max_workers=len(nids)) as ex:
        futures = {
            ex.submit(_execute_node, node_by_id[nid], state, platform, user): nid
            for nid in nids
        }
        for fut in as_completed(futures):
            nid = futures[fut]
            try:
                results[nid] = fut.result()
            except Exception as e:  # 单节点失败不影响其他节点
                results[nid] = f"（节点执行失败：{e}）"
    return results


def run_flow(name: str, platform, user) -> dict:
    """按 DAG 执行一个 flow（拓扑分层 + 同层并行 + 条件分支/循环），返回 state。"""
    flow = _load_flows().get(name)
    if flow is None:
        return {"error": f"flow 不存在：{name}"}
    nodes = _normalize_nodes(flow)
    node_by_id = {n.get("id"): n for n in nodes if n.get("id")}
    deps = {nid: set(node_by_id[nid].get("depends_on") or []) for nid in node_by_id}
    total = len(node_by_id)
    state: dict = {}
    done: set = set()
    _report_progress(name, "running", 0, total, "")
    while len(done) < total:
        ready = [nid for nid in deps if nid not in done and deps[nid] <= done]
        if not ready:
            break  # 循环依赖或缺失上游：终止，避免死循环
        for nid, result in _run_ready(ready, node_by_id, state, platform, user).items():
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
