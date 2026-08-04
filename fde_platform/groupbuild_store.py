"""FDE v2 平台 —「FDE 应用组构建」功能存储（groups + build_tasks）。

全新轻量功能「应用组构建」的独立持久化，与旧「应用组设计」功能（design_*）**零关联**：
独立 sqlite 库（config/groupbuild.db）、独立表、独立函数。

- groups      应用组登记表：英文名（= app/ 下目录名，唯一）+ 中文名（平台显示名）。
- build_tasks 架构生成任务：状态 / 当前步骤 / 日志 / 断点线程号（LangGraph 续跑）。

可插拔、单向依赖（仅被 groupbuild_admin / groupbuild_runner 使用）。
"""
import sqlite3
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "config" / "groupbuild.db"

# 任务状态机：queued → running → done / failed
STATUSES = ("queued", "running", "done", "failed")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name_en    TEXT NOT NULL UNIQUE,          -- 英文应用组名 = app/<name_en>/ 目录名（snake_case）
    name_cn    TEXT DEFAULT '',               -- 中文应用组名（显示用）
    created_by TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS build_tasks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    group_name    TEXT NOT NULL,              -- 英文应用组名
    kind          TEXT NOT NULL DEFAULT 'arch',  -- 任务类型：arch=第①步生成架构 / detail=第②步应用详设
    business_text TEXT DEFAULT '',            -- 第①步输入的长文本业务描述（来源②）
    target_apps   TEXT DEFAULT '',            -- 第②步：指定聚合根（逗号分隔）；空=总表全部
    status        TEXT NOT NULL DEFAULT 'queued',
    current_step  TEXT,                       -- gather / generate / write / 完成 / 失败
    thread_id     TEXT,                       -- LangGraph 线程号（断点续跑）
    log           TEXT DEFAULT '',
    error         TEXT,
    created_by    TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_gb_task_status ON build_tasks(status);

CREATE TABLE IF NOT EXISTS bugfix_proposals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     INTEGER,                      -- 产生该提案的 bugfix 提案任务
    group_name  TEXT NOT NULL,
    entry_ref   TEXT NOT NULL,                -- 失败用例引用（如「TC-DM-02 同步产品」）
    category    TEXT NOT NULL,                -- app_bug / case_calibration / design_issue
    target_file TEXT DEFAULT '',              -- 相对 app/<组>/ 的路径（design_issue 为空）
    old_text    TEXT DEFAULT '',              -- 精确替换：原文（逐字匹配）
    new_text    TEXT DEFAULT '',              -- 精确替换：新文
    rationale   TEXT DEFAULT '',              -- 根因与方案说明
    risk        TEXT DEFAULT '',              -- 风险注记
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending/approved/rejected/applied/failed/resolved
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    decided_at  TEXT                          -- 批准/驳回/应用等状态变更时间
);
CREATE INDEX IF NOT EXISTS idx_gb_proposal_group ON bugfix_proposals(group_name, status);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    """既有库平滑升级：为 build_tasks 补所需列（已存在则忽略）。"""
    for ddl in ("ALTER TABLE build_tasks ADD COLUMN kind TEXT NOT NULL DEFAULT 'arch'",
                "ALTER TABLE build_tasks ADD COLUMN target_apps TEXT DEFAULT ''",
                "ALTER TABLE build_tasks ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0"):
        try:
            conn.execute(ddl)
        except sqlite3.OperationalError:
            pass  # 列已存在
    conn.commit()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    fresh = not DB_PATH.exists() or DB_PATH.stat().st_size == 0
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    if fresh:
        conn.executescript(_SCHEMA)
        conn.commit()
    return conn


def init_schema() -> None:
    conn = get_conn()
    conn.executescript(_SCHEMA)
    _migrate(conn)
    conn.commit()
    conn.close()


# ── 应用组（groups）──────────────────────────────────────

def create_group(name_en: str, name_cn: str = "", created_by: str | None = None) -> int:
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO groups(name_en, name_cn, created_by) VALUES(?,?,?)",
            (name_en, name_cn, created_by))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_group(name_en: str) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM groups WHERE name_en=?", (name_en,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_groups() -> list:
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM groups ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── 架构生成任务（build_tasks）───────────────────────────

def create_task(group_name: str, business_text: str = "",
                created_by: str | None = None, kind: str = "arch",
                target_apps: str = "") -> int:
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO build_tasks(group_name, business_text, created_by, kind, target_apps) "
            "VALUES(?,?,?,?,?)",
            (group_name, business_text, created_by, kind, target_apps))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_task(task_id: int) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM build_tasks WHERE id=?", (task_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_tasks(limit: int = 50) -> list:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM build_tasks ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_tasks_by_group(group_name: str, limit: int = 20, kind: str | None = None) -> list:
    conn = get_conn()
    try:
        if kind:
            rows = conn.execute(
                "SELECT * FROM build_tasks WHERE group_name=? AND kind=? ORDER BY id DESC LIMIT ?",
                (group_name, kind, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM build_tasks WHERE group_name=? ORDER BY id DESC LIMIT ?",
                (group_name, limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_task(task_id: int, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = _now()
    assignments = ", ".join(f"{k}=?" for k in fields)
    conn = get_conn()
    try:
        conn.execute(f"UPDATE build_tasks SET {assignments} WHERE id=?",
                     (*fields.values(), task_id))
        conn.commit()
    finally:
        conn.close()


def request_cancel(task_id: int) -> bool:
    """请求终止任务（协作式）：仅对 queued/running 置 cancel_requested 标志。

    返回是否置上了标志（任务已结束 → False）。runner 在各检查点感知后把任务落
    终态 cancelled；重启续跑只捞 queued/running，cancelled 不会被重新执行。"""
    conn = get_conn()
    try:
        cur = conn.execute(
            "UPDATE build_tasks SET cancel_requested=1, updated_at=? "
            "WHERE id=? AND status IN ('queued','running')", (_now(), task_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def append_log(task_id: int, line: str) -> None:
    conn = get_conn()
    try:
        conn.execute("UPDATE build_tasks SET log = log || ?, updated_at=? WHERE id=?",
                     (f"[{datetime.now().strftime('%H:%M:%S')}] {line}\n", _now(), task_id))
        conn.commit()
    finally:
        conn.close()


def public_view(task: dict) -> dict:
    """对外视图：去掉大段 business_text（前端单拉），补充产物路径（按任务类型）。"""
    t = dict(task)
    kind = t.get("kind") or "arch"
    t["kind"] = kind
    if kind == "detail":
        t["artifact"] = f"app/{t.get('group_name')}/<应用名>/应用详设.md（逐聚合根）"
    elif kind == "code":
        t["artifact"] = f"app/{t.get('group_name')}/<应用名>/<应用名>.py + README.md（逐聚合根）"
    elif kind == "testcase":
        t["artifact"] = f"app/{t.get('group_name')}/测试用例.md（整组一份）"
    elif kind == "testexec":
        g = t.get("group_name")
        t["artifact"] = f"app/{g}/tests/verify_chain_{g}.py + app/{g}/tests/测试报告_{g}.md（真实树运行 · 清表初始化）"
    elif kind == "bugfix":
        t["artifact"] = f"app/{t.get('group_name')}/tests/修复提案_{t.get('group_name')}.md（待页面批准）"
    elif kind == "bugfix-apply":
        t["artifact"] = "应用已批准提案（备份于 .bugfix_backup/）+ 派生重测任务"
    elif kind == "contracts":
        t["artifact"] = f"app/{t.get('group_name')}/_contracts.md（契约冻结 · 沙箱 dump）"
    elif kind == "fdesign":
        t["artifact"] = f"app/{t.get('group_name')}/<应用名>/前端详设.md + 前端详设/dashboard.md"
    elif kind == "ftest":
        t["artifact"] = f"app/{t.get('group_name')}/<应用名>/前端测试用例.md + 前端测试用例.md（组级补充）"
    elif kind == "fverify":
        g = t.get("group_name")
        t["artifact"] = f"app/{g}/tests/verify_view_{g}_*.py + app/{g}/tests/前端测试报告.md（dbguard 隔离运行 · 零污染）"
    elif kind == "fcode":
        g = t.get("group_name")
        t["artifact"] = f"app/{g}/<应用名>/view.{{js,html}} + view/{g}/dashboard.*（零接线视图）"
    else:
        t["artifact"] = f"app/{t.get('group_name')}/architecture.md"
    return t


# ── BUG 修复提案（第⑤步回路：提案 → 批准 → 应用 → 重测对账）────

PROPOSAL_STATUSES = ("pending", "approved", "rejected", "applied", "failed", "resolved", "manual")


def add_proposal(task_id: int, group_name: str, entry_ref: str, category: str,
                 target_file: str = "", old_text: str = "", new_text: str = "",
                 rationale: str = "", risk: str = "") -> int:
    """落一条修复提案（status=pending，待人工批准）。返回提案 id。"""
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO bugfix_proposals (task_id, group_name, entry_ref, category, "
            "target_file, old_text, new_text, rationale, risk) VALUES (?,?,?,?,?,?,?,?,?)",
            (task_id, group_name, entry_ref, category, target_file, old_text, new_text,
             rationale, risk))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_proposals(group_name: str, status: str = None) -> list:
    """按组列提案（可过滤状态），新→旧。"""
    conn = get_conn()
    try:
        if status:
            rows = conn.execute(
                "SELECT * FROM bugfix_proposals WHERE group_name=? AND status=? "
                "ORDER BY id DESC", (group_name, status)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM bugfix_proposals WHERE group_name=? ORDER BY id DESC",
                (group_name,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_proposal(proposal_id: int) -> dict | None:
    conn = get_conn()
    try:
        r = conn.execute("SELECT * FROM bugfix_proposals WHERE id=?",
                         (proposal_id,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def set_proposal_status(proposal_id: int, status: str) -> bool:
    """置提案状态（带时间戳）。返回是否存在该提案。"""
    assert status in PROPOSAL_STATUSES, f"非法提案状态：{status}"
    conn = get_conn()
    try:
        cur = conn.execute("UPDATE bugfix_proposals SET status=?, decided_at=? WHERE id=?",
                           (status, _now(), proposal_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def count_open_proposals(group_name: str) -> dict:
    """组的未闭环提案计数（供列表徽章）：pending / approved / 其他未闭环（applied/failed）。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT status, COUNT(*) c FROM bugfix_proposals "
            "WHERE group_name=? AND status NOT IN ('rejected','resolved') "
            "GROUP BY status", (group_name,)).fetchall()
        d = {r["status"]: r["c"] for r in rows}
        return {"pending": d.get("pending", 0), "approved": d.get("approved", 0),
                "open": sum(d.values())}
    finally:
        conn.close()
