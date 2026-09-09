"""FDE v2 平台 — Skill 库（自进化程序性记忆，可插拔）。

把 Agent 在一次成功任务里沉淀的可复用操作流程（"下次同类任务照做即可"）存下来，
走**半自动**生命周期：agent 提议（draft）→ 人工审批（approved 发布）→ 评分/版本/弃用。
**永不无审批直接执行**——只有 approved 的技能才会注入 Agent 的 system prompt 供复用。

设计要点：
- 存储 `config/skills.db`（与 chatstore/llm 同级的独立 SQLite，不占用业务应用库）。
- 一个 skill = name（唯一）+ description + trigger（触发条件，自然语言）+ steps（有序步骤）。
- steps 为 JSON 数组：`[{tool, args, note}]`，args 是参数模板（占位符如 ``{{file_name}}``，
  执行时按实际情况替换）。
- 生命周期：`draft`（agent 提议）→ `approved`（人工审批发布）→ `deprecated`（弃用）。
- `propose` 去重：同名 skill 已存在时更新其 draft（幂等，agent 重复提议不产生垃圾）。

可插拔：删除本模块 + agent_admin 里的引用即无 skill 能力，Agent 照常工作。
"""
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from fde import FdeError

DB_PATH = Path(os.environ.get("SKILL_DB", str(Path("config") / "skills.db")))

STATUSES = ("draft", "approved", "deprecated")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS skill (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE,
    description  TEXT NOT NULL DEFAULT '',
    trigger      TEXT NOT NULL DEFAULT '',
    steps_json   TEXT NOT NULL DEFAULT '[]',
    status       TEXT NOT NULL DEFAULT 'draft',
    version      INTEGER NOT NULL DEFAULT 1,
    score        REAL NOT NULL DEFAULT 0,
    rating_count INTEGER NOT NULL DEFAULT 0,
    usage_count  INTEGER NOT NULL DEFAULT 0,
    created_by   TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_skill_status ON skill(status);
"""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(_SCHEMA)
    return conn


def init_schema() -> None:
    _conn().close()


def _row_to_skill(r: sqlite3.Row) -> dict:
    s = dict(r)
    try:
        s["steps"] = json.loads(s.pop("steps_json") or "[]")
    except (ValueError, TypeError):
        s["steps"] = []
    return s


def _validate_steps(steps) -> list:
    """校验 steps 并归一为 [{tool, args, output, note}]；非法即抛 FdeError。

    output 可选：该步结果写入的 state 键，供后续步骤的 args 占位符 {{key}} 填充
    （run_skill 确定性执行时用）。
    """
    if not isinstance(steps, list):
        raise FdeError("steps 必须是数组")
    out = []
    for i, st in enumerate(steps):
        if not isinstance(st, dict):
            raise FdeError(f"steps[{i}] 必须是对象")
        tool = (st.get("tool") or "").strip()
        if not tool:
            raise FdeError(f"steps[{i}] 缺少 tool")
        args = st.get("args") or {}
        if not isinstance(args, dict):
            raise FdeError(f"steps[{i}].args 必须是对象")
        out.append({
            "tool": tool,
            "args": args,
            "output": (st.get("output") or "").strip(),
            "note": (st.get("note") or "").strip(),
        })
    if not out:
        raise FdeError("steps 不能为空")
    return out


# ── 生命周期 ────────────────────────────────────────────

def propose(name, description, trigger, steps, created_by="agent") -> dict:
    """agent 提议沉淀一个 skill（draft）；同名已存在则更新 draft（幂等）。"""
    name = (name or "").strip()
    if not name:
        raise FdeError("skill 名不能为空")
    steps = _validate_steps(steps)
    conn = _conn()
    try:
        row = conn.execute("SELECT id FROM skill WHERE name = ?", (name,)).fetchone()
        if row:
            conn.execute(
                "UPDATE skill SET description=?, trigger=?, steps_json=?, status='draft', "
                "version=version+1, updated_at=? WHERE id=?",
                ((description or "").strip(), (trigger or "").strip(),
                 json.dumps(steps, ensure_ascii=False), _now(), row["id"]),
            )
            sid = row["id"]
        else:
            cur = conn.execute(
                "INSERT INTO skill (name, description, trigger, steps_json, status, "
                "created_by, created_at, updated_at) VALUES (?,?,?,?, 'draft', ?,?,?)",
                ((name), (description or "").strip(), (trigger or "").strip(),
                 json.dumps(steps, ensure_ascii=False), created_by, _now(), _now()),
            )
            sid = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    return get_skill(sid)


def approve(skill_id, approver="") -> dict:
    skill = get_skill(skill_id)
    if skill is None:
        raise FdeError(f"skill 不存在：{skill_id}")
    conn = _conn()
    conn.execute("UPDATE skill SET status='approved', updated_at=? WHERE id=?",
                 (_now(), skill_id))
    conn.commit()
    conn.close()
    return get_skill(skill_id)


def reject(skill_id) -> None:
    """否决 draft：直接删除（草稿不保留）。"""
    conn = _conn()
    conn.execute("DELETE FROM skill WHERE id=? AND status='draft'", (skill_id,))
    conn.commit()
    conn.close()


def deprecate(skill_id) -> dict:
    skill = get_skill(skill_id)
    if skill is None:
        raise FdeError(f"skill 不存在：{skill_id}")
    conn = _conn()
    conn.execute("UPDATE skill SET status='deprecated', updated_at=? WHERE id=?",
                 (_now(), skill_id))
    conn.commit()
    conn.close()
    return get_skill(skill_id)


def rate(skill_id, score) -> dict:
    """评分（0~5，累计平均）。"""
    skill = get_skill(skill_id)
    if skill is None:
        raise FdeError(f"skill 不存在：{skill_id}")
    try:
        score = float(score)
    except (ValueError, TypeError):
        raise FdeError("评分必须是数值")
    if not 0 <= score <= 5:
        raise FdeError("评分须在 0~5 之间")
    conn = _conn()
    conn.execute(
        "UPDATE skill SET score=(score*rating_count+?)/(rating_count+1), "
        "rating_count=rating_count+1, updated_at=? WHERE id=?",
        (score, _now(), skill_id),
    )
    conn.commit()
    conn.close()
    return get_skill(skill_id)


def mark_used(skill_id) -> None:
    """一次成功复用后 usage_count+1。"""
    conn = _conn()
    conn.execute("UPDATE skill SET usage_count=usage_count+1, updated_at=? WHERE id=?",
                 (_now(), skill_id))
    conn.commit()
    conn.close()


def _is_subsequence(seq, haystack) -> bool:
    """seq 是否按序出现在 haystack 中（子序列匹配）。"""
    it = iter(haystack)
    return all(x in it for x in seq)


def note_usage(tool_names) -> int:
    """按 Agent 本轮工具名序列匹配已发布技能，命中则 usage_count+1（复用计数）。返回命中数。"""
    names = list(tool_names or [])
    if not names:
        return 0
    hit = 0
    for s in published_skills():
        step_tools = [st["tool"] for st in s["steps"]]
        if step_tools and _is_subsequence(step_tools, names):
            mark_used(s["id"])
            hit += 1
    return hit


# ── 查询 ────────────────────────────────────────────────

def get_skill(skill_id) -> dict | None:
    conn = _conn()
    try:
        row = conn.execute("SELECT * FROM skill WHERE id=?", (skill_id,)).fetchone()
        return _row_to_skill(row) if row else None
    finally:
        conn.close()


def get_skill_by_name(name) -> dict | None:
    conn = _conn()
    try:
        row = conn.execute("SELECT * FROM skill WHERE name=?", (name,)).fetchone()
        return _row_to_skill(row) if row else None
    finally:
        conn.close()


def list_skills(status=None) -> list:
    conn = _conn()
    try:
        if status:
            rows = conn.execute("SELECT * FROM skill WHERE status=? ORDER BY id", (status,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM skill ORDER BY status, id").fetchall()
        return [_row_to_skill(r) for r in rows]
    finally:
        conn.close()


def published_skills() -> list:
    """已发布（approved）的 skill，按评分 × 使用次数排序，供注入 system prompt。"""
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT * FROM skill WHERE status='approved' "
            "ORDER BY usage_count DESC, score DESC, id"
        ).fetchall()
        return [_row_to_skill(r) for r in rows]
    finally:
        conn.close()


def run_skill(name: str, platform, user, init_state: dict = None) -> dict:
    """确定性执行一个已发布 skill：按 steps 顺序调 tool，占位符从 state 填充。

    与「注入 prompt 让 leader 自由执行」不同，这里是**确定性**的：不经过 LLM，
    直接按固定步骤顺序调工具，前一步的 output 结果填后一步 args 里的 {{key}} 占位符。
    init_state 作为初始 state（供第一步 args 的 {{key}} 占位符填充外部输入）。
    供 Flow 编排的 skill 节点调用。
    """
    from fde import FdeError
    from fde_platform import agentscope_bridge as bridge

    skill = get_skill_by_name(name)
    if not skill:
        raise FdeError(f"skill 不存在：{name}")
    if skill.get("status") != "approved":
        raise FdeError(f"skill 未发布（当前 {skill.get('status')}）：{name}")
    state: dict = dict(init_state or {})
    for st in skill["steps"]:
        args = {}
        for k, v in (st.get("args") or {}).items():
            if isinstance(v, str):
                for key, val in state.items():
                    v = v.replace("{{" + key + "}}", str(val))
            args[k] = v
        raw = bridge.execute(platform, user, st["tool"], args)
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (ValueError, TypeError):
            data = raw
        if isinstance(data, dict) and data.get("error"):
            raise FdeError(f"步骤 {st['tool']} 失败：{data['error']}")
        if st.get("output"):
            state[st["output"]] = data
    return state


PROPOSE_INSTRUCTION = (
    "操作规则（skill 沉淀）：任务完成后，若形成了可复用的通用流程（下次同类任务可直接照做），"
    "调用平台工具 platform_propose_skill 将其沉淀为 skill 草稿、提交人工审批；"
    "已发布的技能会出现在「已沉淀技能库」中，匹配时优先遵循其步骤。"
)


def agent_prompt() -> str:
    """注入 Agent system prompt 的 skill 片段：沉淀指令（恒在）+ 已发布技能清单（若有）。"""
    block = published_prompt_block()
    return (block + "\n\n" + PROPOSE_INSTRUCTION) if block else ("\n\n" + PROPOSE_INSTRUCTION)


def published_prompt_block() -> str:
    """已发布 skill 的 system prompt 注入片段（无 skill 返回空串）。"""
    skills = published_skills()
    if not skills:
        return ""
    lines = ["", "## 已沉淀技能库（可复用的操作流程，经人工审批发布）", "",
             "下面是历史任务中沉淀并经审批发布的可复用流程。当用户请求与某技能的「触发条件」匹配时，",
             "优先按该技能的步骤执行（参数按实际情况替换占位符）；完成后可继续用 platform_propose_skill 提议新流程。",
             ""]
    for s in skills:
        head = f"### 技能：{s['name']}（v{s['version']} · 已用 {s['usage_count']} 次"
        if s.get("rating_count"):
            head += f" · 评分 {s['score']:.1f}/{s['rating_count']}人"
        head += "）"
        lines.append(head)
        if s.get("trigger"):
            lines.append(f"触发条件：{s['trigger']}")
        for i, st in enumerate(s["steps"], 1):
            args = json.dumps(st["args"], ensure_ascii=False) if st.get("args") else ""
            note = f" — {st['note']}" if st.get("note") else ""
            lines.append(f"  {i}. {st['tool']}({args}){note}")
        lines.append("")
    return "\n".join(lines)
