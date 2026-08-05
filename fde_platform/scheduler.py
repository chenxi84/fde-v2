"""FDE v2 平台 — 定时任务（仿 v1，适配 v2 约定）。

让某应用的某个**公共服务**（聚合根公共方法）按 cron 计划自动运行，每次运行的
成功 / 失败都落库成日志。

设计要点：
- 调度引擎用 APScheduler 的 BackgroundScheduler（后台线程，随平台进程存活；未安装则仅支持手动「立即运行」）
- 执行复用平台运行时 `platform.call(app, service, ctx, **params)`——与页面手工调用、
  Agent、MCP 同一调用链（注入身份、托管事务、跨应用网关）
- 运行身份：任务可指定 run_as_user，到点以该用户身份注入 ctx（users.ctx_for_user）；
  不指定则以平台默认身份运行
- 数据独立存于 config/scheduler.db（jobs / runs 两张表）

可插拔：依赖方向单向（scheduler → runtime/users）；main.py 以 try-import 注册，
删除本模块 + scheduler.html 平台即恢复无定时任务。自带 CLI：python -m fde_platform.scheduler。
"""
import argparse
import json
import logging
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from flask import Blueprint, flash, redirect, render_template, request, url_for

# APScheduler 为可选依赖：缺失时后台调度不可用，但 CRUD / 手动「立即运行」仍可用
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    _HAS_APSCHEDULER = True
except ImportError:  # pragma: no cover
    BackgroundScheduler = None
    CronTrigger = None
    _HAS_APSCHEDULER = False

# ── 常量 ────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "config" / "scheduler.db"
_logger = logging.getLogger(__name__)

MAX_RUNS_PER_JOB = 200   # 每任务保留的运行日志上限
RESULT_TRUNCATE = 20000  # 存入 result_json 的字符上限

CRON_PRESETS = [
    ("每分钟（调试）", "* * * * *"),
    ("每小时整点", "0 * * * *"),
    ("每天 08:00", "0 8 * * *"),
    ("工作日 08:00", "0 8 * * 1-5"),
    ("每周一 08:00", "0 8 * * 1"),
    ("每月 1 日 08:00", "0 8 1 * *"),
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    app_name     TEXT NOT NULL,
    service      TEXT NOT NULL,
    params_json  TEXT NOT NULL DEFAULT '{}',
    cron_expr    TEXT NOT NULL,
    run_as_user  TEXT,
    enabled      INTEGER NOT NULL DEFAULT 1,
    description  TEXT,
    created_by   TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id        INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    duration_ms   INTEGER,
    status        TEXT NOT NULL DEFAULT 'running',
    result_json   TEXT,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_job ON runs(job_id, id DESC);
"""

# 平台运行时实例（register / CLI 时绑定）
_platform = None


def bind_platform(platform) -> None:
    global _platform
    _platform = platform


# ── DB 层 ───────────────────────────────────────────────


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    fresh = not DB_PATH.exists() or DB_PATH.stat().st_size == 0
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if fresh:
        conn.executescript(_SCHEMA)
        conn.commit()
    return conn


def init_schema() -> None:
    conn = get_conn()
    conn.executescript(_SCHEMA)
    conn.commit()
    conn.close()


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ── 校验 ────────────────────────────────────────────────


def validate_service(app_name: str, service: str) -> tuple:
    """校验：应用存在，且 service 是其公共服务（非 _ 前缀）。"""
    if _platform is None:
        return False, "平台运行时未绑定"
    if app_name not in _platform.app_names():
        return False, f"应用不存在：{app_name}"
    names = {s["name"] for s in _platform.services(app_name)}
    if service.startswith("_") or service not in names:
        return False, f"应用 {app_name} 无此公共服务：{service}"
    return True, None


def validate_cron(cron_expr: str) -> tuple:
    if len(cron_expr.split()) != 5:
        return False, "cron 表达式必须是 5 段（分 时 日 月 周），如 0 8 * * 1-5"
    if _HAS_APSCHEDULER:
        try:
            CronTrigger.from_crontab(cron_expr)
        except Exception as e:
            return False, f"cron 表达式无效：{e}"
    return True, None


# ── 任务 CRUD ───────────────────────────────────────────


def create_job(app_name, service, cron_expr, params=None, run_as_user="",
               description="", created_by="", enabled=True) -> tuple:
    app_name = (app_name or "").strip()
    service = (service or "").strip()
    cron_expr = (cron_expr or "").strip()
    run_as_user = (run_as_user or "").strip() or None

    ok, err = validate_service(app_name, service)
    if not ok:
        return False, err, None
    ok, err = validate_cron(cron_expr)
    if not ok:
        return False, err, None
    try:
        params_json = json.dumps(params or {}, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        return False, f"参数必须是合法 JSON 对象：{e}", None

    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO jobs (app_name, service, params_json, cron_expr, run_as_user,"
        " enabled, description, created_by) VALUES (?,?,?,?,?,?,?,?)",
        (app_name, service, params_json, cron_expr, run_as_user,
         1 if enabled else 0, (description or "").strip(), created_by or ""),
    )
    job_id = cur.lastrowid
    conn.commit()
    conn.close()

    if enabled:
        _schedule(get_job(job_id))
    return True, f"已创建定时任务 #{job_id}", job_id


def update_job(job_id, cron_expr, params, run_as_user, description, enabled) -> tuple:
    job = get_job(job_id)
    if not job:
        return False, "任务不存在"
    cron_expr = (cron_expr or "").strip()
    ok, err = validate_cron(cron_expr)
    if not ok:
        return False, err
    run_as_user = (run_as_user or "").strip() or None
    try:
        params_json = json.dumps(params or {}, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        return False, f"参数必须是合法 JSON 对象：{e}"

    conn = get_conn()
    conn.execute(
        "UPDATE jobs SET cron_expr=?, params_json=?, run_as_user=?, description=?,"
        " enabled=? WHERE id=?",
        (cron_expr, params_json, run_as_user, (description or "").strip(),
         1 if enabled else 0, job_id),
    )
    conn.commit()
    conn.close()

    _unschedule(job_id)
    if enabled:
        _schedule(get_job(job_id))
    return True, f"已更新任务 #{job_id}"


def delete_job(job_id: int) -> tuple:
    if not get_job(job_id):
        return False, "任务不存在"
    _unschedule(job_id)
    conn = get_conn()
    conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
    conn.commit()
    conn.close()
    return True, f"已删除任务 #{job_id}"


def set_enabled(job_id: int, enabled: bool) -> tuple:
    job = get_job(job_id)
    if not job:
        return False, "任务不存在"
    conn = get_conn()
    conn.execute("UPDATE jobs SET enabled=? WHERE id=?", (1 if enabled else 0, job_id))
    conn.commit()
    conn.close()
    if enabled:
        _schedule(get_job(job_id))
    else:
        _unschedule(job_id)
    return True, (f"已启用任务 #{job_id}" if enabled else f"已停用任务 #{job_id}")


def get_job(job_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_jobs(enabled_only: bool = False) -> list:
    conn = get_conn()
    sql = "SELECT * FROM jobs" + (" WHERE enabled=1" if enabled_only else "") + " ORDER BY id"
    rows = conn.execute(sql).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── 运行日志 ────────────────────────────────────────────


def _start_run(job_id: int) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO runs (job_id, started_at, status) VALUES (?, ?, 'running')",
        (job_id, _now_str()),
    )
    run_id = cur.lastrowid
    conn.commit()
    conn.close()
    return run_id


def _finish_run(run_id, status, result=None, error_message=None, started_ts=None):
    duration = int((time.time() - started_ts) * 1000) if started_ts else None
    result_json = None
    if result is not None:
        try:
            result_json = json.dumps(result, ensure_ascii=False, default=str)
        except Exception:
            result_json = str(result)
        if len(result_json) > RESULT_TRUNCATE:
            result_json = result_json[:RESULT_TRUNCATE] + " …(截断)"
    conn = get_conn()
    conn.execute(
        "UPDATE runs SET status=?, finished_at=?, duration_ms=?, result_json=?,"
        " error_message=? WHERE id=?",
        (status, _now_str(), duration, result_json, error_message, run_id),
    )
    conn.commit()
    conn.close()


def get_run(run_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_runs(job_id: int, limit: int = 10) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM runs WHERE job_id=? ORDER BY id DESC LIMIT ?", (job_id, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_last_run(job_id: int):
    runs = list_runs(job_id, limit=1)
    return runs[0] if runs else None


def prune_runs(job_id: int) -> None:
    conn = get_conn()
    conn.execute(
        "DELETE FROM runs WHERE job_id=? AND id NOT IN ("
        " SELECT id FROM runs WHERE job_id=? ORDER BY id DESC LIMIT ?)",
        (job_id, job_id, MAX_RUNS_PER_JOB),
    )
    conn.commit()
    conn.close()


# ── 执行 ────────────────────────────────────────────────


def _resolve_ctx(run_as_user: str):
    """解析运行身份为 ctx；失败返回错误（fail-closed）。Returns (ctx|None, err|None)"""
    if not run_as_user:
        return None, None  # 平台默认身份
    from fde_platform import users

    u = users.get_user_by_name(run_as_user)
    if not u:
        return None, f"运行身份不存在：{run_as_user}"
    return users.ctx_for_user(u), None


def run_job_now(job_id: int) -> dict:
    """立即执行一次任务并记录日志（调度回调与手动触发共用）。"""
    from fde import FdeError

    job = get_job(job_id)
    if not job:
        return {"id": None, "status": "error", "error_message": "任务不存在"}

    run_id = _start_run(job_id)
    t0 = time.time()
    try:
        ctx, err = _resolve_ctx(job["run_as_user"])
        if err:
            _finish_run(run_id, "error", error_message=err, started_ts=t0)
        else:
            params = json.loads(job["params_json"] or "{}")
            try:
                result = _platform.call(job["app_name"], job["service"], ctx=ctx, **params)
                _finish_run(run_id, "ok", result=result, started_ts=t0)
            except FdeError as e:
                _finish_run(run_id, "error", error_message=f"业务失败：{e}", started_ts=t0)
    except Exception as e:  # 调度线程绝不能因单次执行崩溃
        _finish_run(run_id, "error", error_message=f"{type(e).__name__}: {e}", started_ts=t0)

    prune_runs(job_id)
    return get_run(run_id)


# ── 调度引擎（APScheduler）─────────────────────────────

_scheduler = None


def _key(job_id: int) -> str:
    return f"fde_job_{job_id}"


def _schedule(job) -> None:
    if not _scheduler or not job or not job["enabled"]:
        return
    try:
        trigger = CronTrigger.from_crontab(job["cron_expr"])
    except Exception as e:
        print(f"[定时任务] 任务 #{job['id']} 的 cron 无效（{job['cron_expr']}）：{e}")
        return
    _scheduler.add_job(
        run_job_now, trigger, id=_key(job["id"]), args=[job["id"]],
        replace_existing=True, misfire_grace_time=600, coalesce=True, max_instances=1,
    )


def _unschedule(job_id: int) -> None:
    if not _scheduler:
        return
    try:
        _scheduler.remove_job(_key(job_id))
    except Exception:
        pass


def load_all_jobs() -> None:
    for job in list_jobs(enabled_only=True):
        _schedule(job)


def start_engine() -> None:
    global _scheduler
    if not _HAS_APSCHEDULER:
        _logger.warning("未安装 APScheduler：后台调度不可用（仅支持手动立即运行）")
        return
    if _scheduler and _scheduler.running:
        return
    _scheduler = BackgroundScheduler()
    _scheduler.start()
    load_all_jobs()
    _logger.info("后台调度引擎已启动 · 已载入 %d 个启用任务", len(list_jobs(enabled_only=True)))


def shutdown_engine() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None


# ── 权限 helper（鉴权可选）──────────────────────────────


def _current_user():
    """取当前登录用户；无认证 / 未登录返回 None（视为不受限管理员）。"""
    try:
        from flask import session

        username = session.get("username")
        if not username:
            return None
        from fde_platform import users

        return users.get_user_by_name(username)
    except Exception:
        return None


def _is_admin(user) -> bool:
    """admin 判定与 users._is_admin_user 同口径：角色带 is_admin 标志；无鉴权模式全通。"""
    return user is None or bool(user.get("is_admin"))


def _can_manage_service(user, app_name: str, service: str) -> bool:
    """能否创建/管理针对该服务的任务：admin 全通，否则须被授权该服务。"""
    if _is_admin(user):
        return True
    from fde_platform import users

    return users.is_service_granted(user["id"], app_name, service)


def _visible_jobs(user) -> list:
    """可见任务：admin 全部；否则仅其被授权服务的任务。"""
    jobs = list_jobs()
    if _is_admin(user):
        return jobs
    from fde_platform import users

    return [j for j in jobs if users.is_service_granted(user["id"], j["app_name"], j["service"])]


def _apps_services(user) -> dict:
    """建任务表单用：{app_name: [可选公共服务]}。admin 全部；普通用户仅被授权服务。"""
    from fde_platform import users

    result = {}
    for name in _platform.app_names():
        if _is_admin(user):
            svcs = _platform.services(name)
        else:
            granted = set(users.granted_services(user["id"], name))
            svcs = [s for s in _platform.services(name) if s["name"] in granted]
        entries = [
            {"name": s["name"], "description": s["description"],
             "params": [p["name"] for p in s["parameters"]]}
            for s in svcs
        ]
        if entries:
            result[name] = entries
    return result


def _user_options(user) -> list:
    """运行身份候选：管理员返回全部用户名，普通用户不给该选项。"""
    if not _is_admin(user):
        return []
    try:
        from fde_platform import users

        return [u["username"] for u in users.list_users()]
    except ImportError:
        return []


# ── 路由 ────────────────────────────────────────────────

bp = Blueprint("scheduler", __name__)  # 路由自带 /scheduler 前缀


def _back():
    return redirect(url_for("scheduler.scheduler_page"))


def _parse_params_form(raw: str):
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        obj = json.loads(raw)
    except Exception as e:
        return None, f"参数不是合法 JSON：{e}"
    if not isinstance(obj, dict):
        return None, "参数必须是 JSON 对象（{...}）"
    return obj


def _job_or_deny(job_id: int):
    user = _current_user()
    job = get_job(job_id)
    if not job:
        flash("任务不存在", "error")
        return None, _back()
    if not _can_manage_service(user, job["app_name"], job["service"]):
        flash("无权操作该任务", "error")
        return None, _back()
    return job, None


@bp.route("/scheduler")
def scheduler_page():
    user = _current_user()
    jobs = _visible_jobs(user)
    for j in jobs:
        j["last_run"] = get_last_run(j["id"])
        j["recent_runs"] = list_runs(j["id"], limit=5)
        try:
            j["params"] = json.loads(j["params_json"] or "{}")
        except Exception:
            j["params"] = {}
    return render_template(
        "scheduler.html",
        jobs=jobs,
        apps_services=_apps_services(user),
        user_options=_user_options(user),
        has_apscheduler=_HAS_APSCHEDULER,
        is_admin=_is_admin(user),
        cron_presets=CRON_PRESETS,
    )


@bp.route("/scheduler/jobs", methods=["POST"])
def jobs_create():
    user = _current_user()
    app_name = request.form.get("app_name", "")
    service = request.form.get("service", "")
    if not _can_manage_service(user, app_name, service):
        flash(f"无权为该服务创建任务：{app_name}.{service}", "error")
        return _back()
    params = _parse_params_form(request.form.get("params", ""))
    if isinstance(params, tuple):
        flash(params[1], "error")
        return _back()
    ok, msg, _ = create_job(
        app_name, request.form.get("service", ""), request.form.get("cron_expr", ""),
        params, request.form.get("run_as_user", ""), request.form.get("description", ""),
        created_by=(user["username"] if user else ""),
    )
    flash(msg, "ok" if ok else "error")
    return _back()


@bp.route("/scheduler/jobs/<int:job_id>/edit", methods=["POST"])
def jobs_edit(job_id):
    job, err = _job_or_deny(job_id)
    if err:
        return err
    params = _parse_params_form(request.form.get("params", ""))
    if isinstance(params, tuple):
        flash(params[1], "error")
        return _back()
    ok, msg = update_job(
        job_id, request.form.get("cron_expr", ""), params,
        request.form.get("run_as_user", ""), request.form.get("description", ""),
        request.form.get("enabled") == "1",
    )
    flash(msg, "ok" if ok else "error")
    return _back()


@bp.route("/scheduler/jobs/<int:job_id>/toggle", methods=["POST"])
def jobs_toggle(job_id):
    job, err = _job_or_deny(job_id)
    if err:
        return err
    ok, msg = set_enabled(job_id, not bool(job["enabled"]))
    flash(msg, "ok" if ok else "error")
    return _back()


@bp.route("/scheduler/jobs/<int:job_id>/run", methods=["POST"])
def jobs_run(job_id):
    job, err = _job_or_deny(job_id)
    if err:
        return err
    run = run_job_now(job_id)
    if run and run["status"] == "ok":
        flash(f"任务 #{job_id} 运行成功（{run.get('duration_ms')} ms）", "ok")
    else:
        flash(f"任务 #{job_id} 运行失败：{(run or {}).get('error_message', '未知错误')}", "error")
    return _back()


@bp.route("/scheduler/jobs/<int:job_id>/delete", methods=["POST"])
def jobs_delete(job_id):
    job, err = _job_or_deny(job_id)
    if err:
        return err
    ok, msg = delete_job(job_id)
    flash(msg, "ok" if ok else "error")
    return _back()


# ── 插件入口 ────────────────────────────────────────────


def register(app, platform) -> None:
    bind_platform(platform)
    init_schema()
    app.register_blueprint(bp)
    start_engine()
    import atexit

    atexit.register(shutdown_engine)
    _logger.info("定时任务已启用 · 任务库 %s", DB_PATH)
    return app


# ── CLI ─────────────────────────────────────────────────


def _cli():
    parser = argparse.ArgumentParser(description="FDE v2 平台定时任务 CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="建表")
    sub.add_parser("list", help="列出任务")

    p = sub.add_parser("add", help="创建任务")
    p.add_argument("app_name")
    p.add_argument("service", help="公共方法名（如 list / create）")
    p.add_argument("cron_expr", help="5 段 cron，如 '0 8 * * 1-5'")
    p.add_argument("--params", default="{}", help="JSON 对象字符串")
    p.add_argument("--run-as", default="", help="运行身份（用户名）")
    p.add_argument("--desc", default="")
    p.add_argument("--by", default="cli")
    p.add_argument("--disabled", action="store_true", help="创建即停用")

    p = sub.add_parser("rm", help="删除任务"); p.add_argument("job_id", type=int)
    p = sub.add_parser("enable", help="启用任务"); p.add_argument("job_id", type=int)
    p = sub.add_parser("disable", help="停用任务"); p.add_argument("job_id", type=int)
    p = sub.add_parser("run", help="立即运行一次"); p.add_argument("job_id", type=int)
    p = sub.add_parser("logs", help="查看运行日志")
    p.add_argument("job_id", type=int); p.add_argument("--limit", type=int, default=10)

    args = parser.parse_args()

    # CLI 自建平台运行时
    from fde_platform.runtime import FdePlatform

    pf = FdePlatform()
    pf.load_all()
    bind_platform(pf)
    init_schema()

    if args.cmd == "init":
        print("定时任务表已就绪")
    elif args.cmd == "list":
        rows = list_jobs()
        if not rows:
            print("（无任务）")
        for j in rows:
            st = "启用" if j["enabled"] else "停用"
            last = get_last_run(j["id"])
            lr = f"{last['status']}@{last['started_at']}" if last else "从未运行"
            print(f"#{j['id']}\t[{st}]\t{j['app_name']}.{j['service']}"
                  f"\tcron={j['cron_expr']}\t身份:{j['run_as_user'] or '默认'}\t上次:{lr}")
    elif args.cmd == "add":
        try:
            params = json.loads(args.params)
        except Exception as e:
            print(f"参数 JSON 无效：{e}")
            return
        print(create_job(args.app_name, args.service, args.cron_expr, params,
                         args.run_as, args.desc, args.by, not args.disabled)[1])
    elif args.cmd == "rm":
        print(delete_job(args.job_id)[1])
    elif args.cmd == "enable":
        print(set_enabled(args.job_id, True)[1])
    elif args.cmd == "disable":
        print(set_enabled(args.job_id, False)[1])
    elif args.cmd == "run":
        print(json.dumps(run_job_now(args.job_id), ensure_ascii=False, indent=2, default=str))
    elif args.cmd == "logs":
        rows = list_runs(args.job_id, args.limit)
        if not rows:
            print("（无运行记录）")
        for r in rows:
            err = f"  {r['error_message']}" if r["error_message"] else ""
            print(f"#{r['id']}\t{r['status']}\t{r['started_at']}\t{r['duration_ms']}ms{err}")


if __name__ == "__main__":
    _cli()
