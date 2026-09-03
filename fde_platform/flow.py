"""FDE 工作流编排（阶段 1a：顺序 + 结果传递，节点 = 角色的工具集；+ 进度上报）。

声明式 flow：`app/<组>/_flow_<名>.yaml`，步骤按顺序执行，结果经状态键传递。
节点执行 = 轻量 ReAct 循环（``llm.chat`` + ``bridge.execute``），工具按角色过滤
（``agent_roles.allowed_tools_for_role``），因此「节点=角色」在工具集层面即确定。

进度上报：每次执行把「跑到第几步 / 哪个角色 / 结果摘要」写入 config/flow_runs.db
（只保留最近一次），供 platform_flow_progress / 前端「编排执行」区读取。

约定：
- 一个 flow 一个 YAML，``name`` 全局唯一；``steps`` 有序。
- 每步 ``role``（可选）指定角色（决定工具集）、``task`` 任务文本、``output`` 结果键、
  ``input`` 依赖的上游结果键（用于填充 ``{key}`` 占位符）。
"""
import json
import sqlite3
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
         "step_count": len(f.get("steps", []))}
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


def _fill(task: str, state: dict, inputs: list) -> str:
    """用 state 填充 task 里的 {key} 占位符。"""
    for k in inputs or []:
        task = task.replace("{" + k + "}", str(state.get(k, "")))
    return task


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


def run_flow(name: str, platform, user) -> dict:
    """顺序执行一个 flow，返回 state；执行过程写进度到 flow_runs.db。"""
    flow = _load_flows().get(name)
    if flow is None:
        return {"error": f"flow 不存在：{name}"}
    steps = [s for s in flow.get("steps", []) if isinstance(s, dict)]
    total = len(steps)
    state: dict = {}
    _report_progress(name, "running", 0, total, "")
    for i, step in enumerate(steps, 1):
        role = step.get("role", "")
        task = _fill(str(step.get("task", "")), state, step.get("input"))
        _report_progress(name, "running", i, total, role)
        try:
            result = _run_node(platform, user, role, task)
        except Exception as e:
            _report_progress(name, "error", i, total, role, str(e))
            key = step.get("output")
            if key:
                state[key] = f"（节点执行失败：{e}）"
            continue
        key = step.get("output")
        if key:
            state[key] = result
    _report_progress(name, "done", total, total, "",
                     json.dumps(state, ensure_ascii=False)[:2000])
    return state
