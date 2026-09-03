"""FDE 工作流编排（阶段 1a：顺序 + 结果传递，节点 = 角色的工具集）。

声明式 flow：`app/<组>/_flow_<名>.yaml`，步骤按顺序执行，结果经状态键传递。
节点执行 = 轻量 ReAct 循环（``llm.chat`` + ``bridge.execute``），工具按角色过滤
（``agent_roles.allowed_tools_for_role``），因此「节点=角色」在工具集层面即确定，
不依赖 AgentScope 的 team 内部机制。

约定：
- 一个 flow 一个 YAML，``name`` 全局唯一；``steps`` 有序。
- 每步 ``role``（可选）指定角色（决定工具集）、``task`` 任务文本、``output`` 结果键、
  ``input`` 依赖的上游结果键（用于填充 ``{key}`` 占位符）。
"""
import json

import yaml
from pathlib import Path

from fde_platform import agent_roles
from fde_platform import agentscope_bridge as bridge
from fde_platform import llm

_ROOT = Path(__file__).resolve().parents[1]
_APPS_DIR = _ROOT / "app"

_MAX_ROUNDS = 10  # 单节点 ReAct 最大轮次（防失控）


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
    """顺序执行一个 flow，返回 state（各步骤 output 键的结果）。"""
    flow = _load_flows().get(name)
    if flow is None:
        return {"error": f"flow 不存在：{name}"}
    state: dict = {}
    for step in flow.get("steps", []):
        if not isinstance(step, dict):
            continue
        task = _fill(str(step.get("task", "")), state, step.get("input"))
        result = _run_node(platform, user, step.get("role", ""), task)
        key = step.get("output")
        if key:
            state[key] = result
    return state
