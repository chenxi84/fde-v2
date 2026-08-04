"""FDE v2 平台 —「FDE 应用组构建」功能（Web 层，可插拔 Blueprint）。

提供「应用组构建」页（/groupbuild）与 /api/groupbuild/* 接口，三步能力：
  1. 建组（中文名 + 英文名 → app/<英文名>/ 与 app/<英文名>/brd/）
  2. 上传 / 删除业务设计文件（存入 brd/）
  3. 架构创建（长文本业务描述 → 后台 groupbuild_runner，LangGraph → app/<组>/architecture.md）

与旧「应用组设计」功能（design_* / builder）**零关联**：独立模块、独立存储、独立 agent。
仅 admin 可用（与 /design、/llm 同口径）。可插拔：删本模块 + main.py 注册块即移除。
"""
import io
import os
import re
import zipfile
from pathlib import Path

from flask import Blueprint, jsonify, redirect, render_template, request, send_file

from fde_platform import builtin_tools, groupbuild_runner, groupbuild_store, users

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APPS_DIR = PROJECT_ROOT / "app"
VIEW_DIR = PROJECT_ROOT / "view"          # 组级看板根（view/<组>/dashboard.*；⑩前端编码的第二棵落点根）

bp = Blueprint("groupbuild", __name__)

# 英文应用组名：snake_case，首字母小写，仅小写字母 / 数字 / 下划线（拒绝中文 / 路径字符）
_NAME_EN_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _is_admin(user) -> bool:
    return user is None or bool(user.get("is_admin"))


def _current_user():
    try:
        return users.session_user()
    except Exception:
        return None


def _valid_name_en(name_en: str) -> bool:
    return bool(_NAME_EN_RE.match(name_en or ""))


def _brd_dir(name_en: str) -> Path:
    return APPS_DIR / name_en / "brd"


def _file_tree(base: Path, root: Path | None = None) -> list:
    """递归列出 base 下的目录与文件，组装为树（目录在前、文件在后）。

    root 为顶层 brd/ 目录（首次调用时=base）；文件的 relpath **始终相对 root**，
    保证嵌套文件（如 images/x.svg）的删除接口能正确定位。
    节点：目录 {type:'dir', name, children:[...]}；
          文件 {type:'file', name, relpath(相对 root 的 POSIX 路径), size, mtime}。
    """
    root = root or base
    nodes = []
    if not base.is_dir():
        return nodes
    for p in sorted(base.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
        if p.name.startswith("."):
            continue
        if p.is_dir():
            nodes.append({"type": "dir", "name": p.name, "children": _file_tree(p, root)})
        else:
            st = p.stat()
            nodes.append({"type": "file", "name": p.name,
                          "relpath": p.relative_to(root).as_posix(),
                          "size": st.st_size, "mtime": int(st.st_mtime)})
    return nodes


def _count_files(base: Path) -> int:
    """递归统计 base 下（不含隐藏文件）的文件总数。"""
    if not base.is_dir():
        return 0
    return sum(1 for f in base.rglob("*") if f.is_file() and not f.name.startswith("."))


def _design_files(name_en: str) -> list:
    """列出 app/<组>/<应用名>/应用详设.md（排除 brd），返回 [{app,size,mtime}]。"""
    base = APPS_DIR / name_en
    out = []
    if not base.is_dir():
        return out
    for d in sorted(p for p in base.iterdir()
                    if p.is_dir() and p.name != "brd" and not p.name.startswith(".")):
        f = d / "应用详设.md"
        if f.is_file():
            st = f.stat()
            out.append({"app": d.name, "size": st.st_size, "mtime": int(st.st_mtime)})
    return out


def _code_files(name_en: str) -> list:
    """列出已编码应用 app/<组>/<应用名>/<应用名>.py（排除 brd），返回 [{app,size,mtime,has_readme}]。"""
    base = APPS_DIR / name_en
    out = []
    if not base.is_dir():
        return out
    for d in sorted(p for p in base.iterdir()
                    if p.is_dir() and p.name != "brd" and not p.name.startswith(".")):
        f = d / f"{d.name}.py"
        if f.is_file():
            st = f.stat()
            out.append({"app": d.name, "size": st.st_size, "mtime": int(st.st_mtime),
                        "has_readme": (d / "README.md").is_file()})
    return out


# ── 页面 ────────────────────────────────────────────────

@bp.route("/groupbuild")
def page():
    if not _is_admin(_current_user()):
        return redirect("/")
    return render_template("groupbuild.html")


# ── 第 1 步：应用组 ─────────────────────────────────────

@bp.route("/api/groupbuild/groups", methods=["GET"])
def api_list_groups():
    if not _is_admin(_current_user()):
        return jsonify({"status": "error", "message": "无权限"}), 403
    out = []
    for g in groupbuild_store.list_groups():
        name_en = g["name_en"]
        out.append({
            "name_en": name_en,
            "name_cn": g.get("name_cn") or "",
            "created_by": g.get("created_by"),
            "created_at": g.get("created_at"),
            "brd_count": _count_files(_brd_dir(name_en)),
            "has_architecture": (APPS_DIR / name_en / "architecture.md").is_file(),
            "dir_exists": (APPS_DIR / name_en).is_dir(),
            "aggregate_count": len(groupbuild_runner.arch_app_names(name_en)),
            "design_count": len(_design_files(name_en)),
            "code_count": len(_code_files(name_en)),
            "has_testcase": (APPS_DIR / name_en / "测试用例.md").is_file(),
            "has_testexec": (APPS_DIR / name_en / "tests" / f"verify_chain_{name_en}.py").is_file(),
            "has_contracts": (APPS_DIR / name_en / "_contracts.md").is_file(),
            "fdesign_count": len(_fdesign_files(name_en)),
            "has_fdesign_dashboard": (APPS_DIR / name_en / "前端详设" / "dashboard.md").is_file(),
            "fcode_count": len(_fcode_files(name_en)),
            "has_fcode_dashboard": (VIEW_DIR / name_en / "dashboard.js").is_file(),
            "ftest_count": len(_ftest_files(name_en)),
            "has_ftest_group": (APPS_DIR / name_en / "前端测试用例.md").is_file(),
            "fverify_count": len(_fverify_files(name_en)),
            "has_fverify_group": (APPS_DIR / name_en / "tests" / f"verify_view_{name_en}.py").is_file(),
            "has_fverify_report": (APPS_DIR / name_en / "tests" / "前端测试报告.md").is_file(),
            "has_bugfix_doc": (APPS_DIR / name_en / "tests" / f"修复提案_{name_en}.md").is_file(),
            "bugfix": groupbuild_store.count_open_proposals(name_en),
        })
    return jsonify({"status": "ok", "data": out})


@bp.route("/api/groupbuild/groups", methods=["POST"])
def api_create_group():
    user = _current_user()
    if not _is_admin(user):
        return jsonify({"status": "error", "message": "无权限"}), 403
    d = request.get_json(silent=True) or {}
    name_cn = (d.get("name_cn") or "").strip()
    name_en = (d.get("name_en") or "").strip()
    if not name_cn:
        return jsonify({"status": "error", "message": "中文应用组名不能为空"}), 400
    if not name_en:
        return jsonify({"status": "error", "message": "英文应用组名不能为空"}), 400
    if not _valid_name_en(name_en):
        return jsonify({"status": "error",
                        "message": "英文名须为 snake_case（小写字母开头，仅含小写字母 / 数字 / 下划线）"}), 400
    if groupbuild_store.get_group(name_en):
        return jsonify({"status": "error", "message": f"应用组 {name_en} 已存在"}), 400
    if (APPS_DIR / name_en).exists():
        return jsonify({"status": "error", "message": f"目录 app/{name_en}/ 已存在，请换名"}), 400
    # 建目录：app/<name_en>/ 与 app/<name_en>/brd/
    (APPS_DIR / name_en).mkdir(parents=True, exist_ok=True)
    _brd_dir(name_en).mkdir(parents=True, exist_ok=True)
    groupbuild_store.create_group(name_en, name_cn=name_cn,
                                  created_by=(user or {}).get("username"))
    return jsonify({"status": "ok", "data": {"name_en": name_en, "name_cn": name_cn}})


# ── 第 2 步：业务设计文件（brd/）────────────────────────

@bp.route("/api/groupbuild/groups/<name_en>/files", methods=["GET"])
def api_list_files(name_en):
    if not _is_admin(_current_user()):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    brd = _brd_dir(name_en)
    tree = _file_tree(brd)
    return jsonify({"status": "ok", "data": {"group": name_en,
                                              "count": _count_files(brd), "tree": tree}})


@bp.route("/api/groupbuild/groups/<name_en>/files", methods=["POST"])
def api_upload_files(name_en):
    if not _is_admin(_current_user()):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    if not (APPS_DIR / name_en).is_dir():
        return jsonify({"status": "error", "message": f"应用组 {name_en} 不存在，请先创建"}), 404
    brd = _brd_dir(name_en)
    brd.mkdir(parents=True, exist_ok=True)
    uploads = request.files.getlist("files")
    if not uploads:
        return jsonify({"status": "error", "message": "未收到文件（字段名 files）"}), 400
    saved, skipped = [], []
    for up in uploads:
        name = builtin_tools.safe_filename(up.filename or "")
        if not name:
            skipped.append(up.filename or "(空名)")
            continue
        target = (brd / name).resolve()
        if target.parent != brd.resolve():   # 穿越防护：必须直接落在 brd/ 下
            skipped.append(up.filename or name)
            continue
        up.save(str(target))
        saved.append(name)
    return jsonify({"status": "ok", "data": {"saved": saved, "skipped": skipped}})


@bp.route("/api/groupbuild/groups/<name_en>/files/<path:filename>", methods=["DELETE"])
def api_delete_file(name_en, filename):
    """删除 brd/ 下文件；filename 可为子目录内文件的相对路径（如 images/x.svg）。"""
    if not _is_admin(_current_user()):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    brd = _brd_dir(name_en).resolve()
    target = (brd / filename).resolve()
    # 穿越防护：目标必须仍位于 brd/ 之内（兼容子目录内文件，拒绝 ../ 越界）
    if not (target == brd or target.is_relative_to(brd)):
        return jsonify({"status": "error", "message": "非法文件路径"}), 400
    if not target.is_file():
        return jsonify({"status": "error", "message": "文件不存在"}), 404
    rel = target.relative_to(brd).as_posix()
    try:
        target.unlink()
    except OSError as e:                     # Windows 下文件被占用（如编辑器打开）
        return jsonify({"status": "error", "message": f"删除失败：文件可能被占用，请关闭占用程序后重试（{e}）"}), 500
    return jsonify({"status": "ok", "data": {"deleted": rel}})


# ── 第 3 步：架构创建 ───────────────────────────────────

@bp.route("/api/groupbuild/groups/<name_en>/architecture", methods=["POST"])
def api_create_architecture(name_en):
    user = _current_user()
    if not _is_admin(user):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    if not (APPS_DIR / name_en).is_dir():
        return jsonify({"status": "error", "message": f"应用组 {name_en} 不存在，请先创建"}), 404
    d = request.get_json(silent=True) or {}
    business_text = (d.get("business_text") or "").strip()
    # 输入完备性预检（不臆造）：brd/ 为空 且 无文字 → 直接失败，不调 LLM
    brd = _brd_dir(name_en)
    brd_has = brd.is_dir() and any(f.is_file() and not f.name.startswith(".") for f in brd.iterdir())
    if not brd_has and not business_text:
        return jsonify({"status": "error",
                        "message": "无业务输入：请先上传 BRD 文件，或填写业务描述"}), 400
    tid = groupbuild_store.create_task(name_en, business_text=business_text,
                                       created_by=(user or {}).get("username"))
    groupbuild_runner.enqueue(tid)
    return jsonify({"status": "ok", "id": tid})


@bp.route("/api/groupbuild/groups/<name_en>/architecture", methods=["GET"])
def api_download_architecture(name_en):
    """下载已生成的 architecture.md（as_attachment 强制下载）。"""
    if not _is_admin(_current_user()):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    path = APPS_DIR / name_en / "architecture.md"
    if not path.is_file():
        return jsonify({"status": "error", "message": "架构文件尚未生成"}), 404
    return send_file(str(path), as_attachment=True, download_name="architecture.md")


@bp.route("/api/groupbuild/groups/<name_en>/architecture", methods=["DELETE"])
def api_delete_architecture(name_en):
    """删除已生成的 architecture.md（可随后重新「生成架构」）。"""
    if not _is_admin(_current_user()):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    path = APPS_DIR / name_en / "architecture.md"
    if not path.is_file():
        return jsonify({"status": "error", "message": "架构文件不存在"}), 404
    try:
        path.unlink()
    except OSError as e:                     # Windows 下文件被占用（如编辑器打开）
        return jsonify({"status": "error", "message": f"删除失败：文件可能被占用，请关闭占用程序后重试（{e}）"}), 500
    return jsonify({"status": "ok", "data": {"deleted": f"app/{name_en}/architecture.md"}})


# ── 第 4 步：应用详设（逐聚合根，第②步）─────────────────

@bp.route("/api/groupbuild/groups/<name_en>/design", methods=["POST"])
def api_create_design(name_en):
    """建第②步任务：body {app_names?: []}（缺省=总表全部聚合根）。"""
    user = _current_user()
    if not _is_admin(user):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    arch = APPS_DIR / name_en / "architecture.md"
    if not arch.is_file():
        return jsonify({"status": "error",
                        "message": "缺少 architecture.md，请先运行『生成架构』（第①步）"}), 400
    d = request.get_json(silent=True) or {}
    app_names = d.get("app_names") or []
    all_apps = groupbuild_runner.arch_app_names(name_en)
    if not all_apps:
        return jsonify({"status": "error", "message": "architecture.md 总表未解析到聚合根"}), 400
    if app_names:
        bad = [a for a in app_names if a not in all_apps]
        if bad:
            return jsonify({"status": "error", "message": f"聚合根不在总表中：{', '.join(bad)}"}), 400
        target = [a for a in all_apps if a in app_names]   # 按总表序
    else:
        target = all_apps
    tid = groupbuild_store.create_task(name_en, created_by=(user or {}).get("username"),
                                       kind="detail", target_apps=",".join(target))
    groupbuild_runner.enqueue(tid)
    return jsonify({"status": "ok", "id": tid, "count": len(target)})


@bp.route("/api/groupbuild/groups/<name_en>/design", methods=["GET"])
def api_list_design(name_en):
    """列已生成的应用详设；?zip=1 时打包全部详设下载。"""
    if not _is_admin(_current_user()):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    if request.args.get("zip") == "1":
        files = _design_files(name_en)
        if not files:
            return jsonify({"status": "error", "message": "尚无可打包的应用详设"}), 404
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for it in files:
                zf.write(str(APPS_DIR / name_en / it["app"] / "应用详设.md"),
                         arcname=f"{name_en}/{it['app']}/应用详设.md")
        buf.seek(0)
        return send_file(buf, as_attachment=True, download_name=f"{name_en}_应用详设.zip",
                         mimetype="application/zip")
    files = _design_files(name_en)
    all_apps = groupbuild_runner.arch_app_names(name_en)
    return jsonify({"status": "ok", "data": {"group": name_en, "count": len(files),
                                              "aggregate_count": len(all_apps),
                                              "aggregate_apps": all_apps, "items": files}})


@bp.route("/api/groupbuild/groups/<name_en>/design/<app_name>", methods=["GET"])
def api_download_design(name_en, app_name):
    """下载某聚合根的 应用详设.md。"""
    if not _is_admin(_current_user()):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en) or not _valid_name_en(app_name):
        return jsonify({"status": "error", "message": "非法应用组名/应用名"}), 400
    path = APPS_DIR / name_en / app_name / "应用详设.md"
    if not path.is_file():
        return jsonify({"status": "error", "message": "该聚合根的应用详设尚未生成"}), 404
    return send_file(str(path), as_attachment=True, download_name="应用详设.md")


@bp.route("/api/groupbuild/groups/<name_en>/design/<app_name>", methods=["DELETE"])
def api_delete_design(name_en, app_name):
    """删除某聚合根的 应用详设.md（可随后重新生成）。"""
    if not _is_admin(_current_user()):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en) or not _valid_name_en(app_name):
        return jsonify({"status": "error", "message": "非法应用组名/应用名"}), 400
    path = APPS_DIR / name_en / app_name / "应用详设.md"
    if not path.is_file():
        return jsonify({"status": "error", "message": "应用详设不存在"}), 404
    try:
        path.unlink()
    except OSError as e:                     # Windows 下文件被占用（如编辑器打开）
        return jsonify({"status": "error",
                        "message": f"删除失败：文件可能被占用，请关闭占用程序后重试（{e}）"}), 500
    return jsonify({"status": "ok", "data": {"deleted": f"app/{name_en}/{app_name}/应用详设.md"}})


# ── 第 5 步：应用编码（逐聚合根，第③步）─────────────────

@bp.route("/api/groupbuild/groups/<name_en>/code", methods=["POST"])
def api_create_code(name_en):
    """建第③步任务：body {app_names?: []}（缺省=总表全部）。要求对应聚合根已有应用详设。"""
    user = _current_user()
    if not _is_admin(user):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    arch = APPS_DIR / name_en / "architecture.md"
    if not arch.is_file():
        return jsonify({"status": "error",
                        "message": "缺少 architecture.md，请先运行『生成架构』（第①步）"}), 400
    d = request.get_json(silent=True) or {}
    app_names = d.get("app_names") or []
    all_apps = groupbuild_runner.arch_app_names(name_en)
    if not all_apps:
        return jsonify({"status": "error", "message": "architecture.md 总表未解析到聚合根"}), 400
    if app_names:
        bad = [a for a in app_names if a not in all_apps]
        if bad:
            return jsonify({"status": "error", "message": f"聚合根不在总表中：{', '.join(bad)}"}), 400
        target = [a for a in all_apps if a in app_names]   # 按总表序
    else:
        target = all_apps
    # 主输入预检：每个目标聚合根须已有 应用详设.md（第②步产出）
    no_detail = [a for a in target
                 if not (APPS_DIR / name_en / a / "应用详设.md").is_file()]
    if no_detail:
        return jsonify({"status": "error",
                        "message": "以下聚合根缺 应用详设.md，请先生成应用详设（第②步）："
                                   + ", ".join(no_detail)}), 400
    tid = groupbuild_store.create_task(name_en, created_by=(user or {}).get("username"),
                                       kind="code", target_apps=",".join(target))
    groupbuild_runner.enqueue(tid)
    return jsonify({"status": "ok", "id": tid, "count": len(target)})


@bp.route("/api/groupbuild/groups/<name_en>/code", methods=["GET"])
def api_list_code(name_en):
    """列已编码应用；?zip=1 时打包全部 <应用>.py + README.md 下载。"""
    if not _is_admin(_current_user()):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    if request.args.get("zip") == "1":
        files = _code_files(name_en)
        if not files:
            return jsonify({"status": "error", "message": "尚无可打包的应用代码"}), 404
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for it in files:
                d = APPS_DIR / name_en / it["app"]
                zf.write(str(d / f"{it['app']}.py"), arcname=f"{name_en}/{it['app']}/{it['app']}.py")
                if it["has_readme"]:
                    zf.write(str(d / "README.md"), arcname=f"{name_en}/{it['app']}/README.md")
        buf.seek(0)
        return send_file(buf, as_attachment=True, download_name=f"{name_en}_应用代码.zip",
                         mimetype="application/zip")
    files = _code_files(name_en)
    design_count = len(_design_files(name_en))
    return jsonify({"status": "ok", "data": {"group": name_en, "count": len(files),
                                              "design_count": design_count, "items": files}})


@bp.route("/api/groupbuild/groups/<name_en>/code/<app_name>", methods=["GET"])
def api_download_code(name_en, app_name):
    """下载某应用的 <应用>.py；?readme=1 时下载 README.md。"""
    if not _is_admin(_current_user()):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en) or not _valid_name_en(app_name):
        return jsonify({"status": "error", "message": "非法应用组名/应用名"}), 400
    if request.args.get("readme") == "1":
        path = APPS_DIR / name_en / app_name / "README.md"
        dl = "README.md"
        miss = "该应用 README.md 尚未生成"
    else:
        path = APPS_DIR / name_en / app_name / f"{app_name}.py"
        dl = f"{app_name}.py"
        miss = "该应用代码尚未生成"
    if not path.is_file():
        return jsonify({"status": "error", "message": miss}), 404
    return send_file(str(path), as_attachment=True, download_name=dl)


@bp.route("/api/groupbuild/groups/<name_en>/code/<app_name>", methods=["DELETE"])
def api_delete_code(name_en, app_name):
    """删除某应用的 <应用>.py 与 README.md（可随后重新生成；不删 .db / resource/）。"""
    if not _is_admin(_current_user()):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en) or not _valid_name_en(app_name):
        return jsonify({"status": "error", "message": "非法应用组名/应用名"}), 400
    d = APPS_DIR / name_en / app_name
    py = d / f"{app_name}.py"
    if not py.is_file():
        return jsonify({"status": "error", "message": "应用代码不存在"}), 404
    try:
        py.unlink()
        readme = d / "README.md"
        if readme.is_file():
            readme.unlink()
    except OSError as e:                     # Windows 下文件被占用（如编辑器打开）
        return jsonify({"status": "error",
                        "message": f"删除失败：文件可能被占用，请关闭占用程序后重试（{e}）"}), 500
    return jsonify({"status": "ok", "data": {"deleted": f"app/{name_en}/{app_name}/{app_name}.py"}})


# ── 第 6 步：测试用例生成（整组一份，第④步）─────────────

@bp.route("/api/groupbuild/groups/<name_en>/testcase", methods=["POST"])
def api_create_testcase(name_en):
    """建第④步任务：整组生成一份 测试用例.md（覆盖主链 + 分支 + 回执模拟，含测试数据）。"""
    user = _current_user()
    if not _is_admin(user):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    if not (APPS_DIR / name_en / "architecture.md").is_file():
        return jsonify({"status": "error",
                        "message": "缺少 architecture.md，请先运行『生成架构』（第①步）"}), 400
    all_apps = groupbuild_runner.arch_app_names(name_en)
    if not all_apps:
        return jsonify({"status": "error", "message": "architecture.md 总表未解析到聚合根"}), 400
    # 主输入预检：每个聚合根须已有 应用详设.md（第②步产出），否则即时报错（不异步失败）
    no_detail = [a for a in all_apps
                 if not (APPS_DIR / name_en / a / "应用详设.md").is_file()]
    if no_detail:
        return jsonify({"status": "error",
                        "message": "以下聚合根缺 应用详设.md，请先生成应用详设（第②步）："
                                   + ", ".join(no_detail)}), 400
    tid = groupbuild_store.create_task(name_en, created_by=(user or {}).get("username"),
                                       kind="testcase")
    groupbuild_runner.enqueue(tid)
    return jsonify({"status": "ok", "id": tid, "count": len(all_apps)})


@bp.route("/api/groupbuild/groups/<name_en>/testcase", methods=["GET"])
def api_download_testcase(name_en):
    """下载已生成的 测试用例.md。"""
    if not _is_admin(_current_user()):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    path = APPS_DIR / name_en / "测试用例.md"
    if not path.is_file():
        return jsonify({"status": "error", "message": "测试用例尚未生成"}), 404
    return send_file(str(path), as_attachment=True, download_name="测试用例.md")


@bp.route("/api/groupbuild/groups/<name_en>/testcase", methods=["DELETE"])
def api_delete_testcase(name_en):
    """删除已生成的 测试用例.md（可随后重新生成）。"""
    if not _is_admin(_current_user()):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    path = APPS_DIR / name_en / "测试用例.md"
    if not path.is_file():
        return jsonify({"status": "error", "message": "测试用例不存在"}), 404
    try:
        path.unlink()
    except OSError as e:                     # Windows 下文件被占用（如编辑器打开）
        return jsonify({"status": "error",
                        "message": f"删除失败：文件可能被占用，请关闭占用程序后重试（{e}）"}), 500
    return jsonify({"status": "ok", "data": {"deleted": f"app/{name_en}/测试用例.md"}})


# ── 第 7 步：测试执行（脚本生成 + 真实树运行 + 修复回路，第⑤步）─

@bp.route("/api/groupbuild/groups/<name_en>/testexec", methods=["POST"])
def api_create_testexec(name_en):
    """建第⑤步任务：测试用例.md → verify_chain_<组>.py，真实树直跑（清表初始化：
    清空该组业务数据、保留库文件，平台开着也能跑），失败回喂 LLM 修脚本重跑（≤N 轮），
    产出脚本 + 测试报告.md（应用 bug 只记录不改码）。"""
    user = _current_user()
    if not _is_admin(user):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    if not (APPS_DIR / name_en / "测试用例.md").is_file():
        return jsonify({"status": "error",
                        "message": "缺少 测试用例.md，请先运行『生成测试用例』（第④步）"}), 400
    group_dir = APPS_DIR / name_en
    coded = ([d.name for d in group_dir.iterdir()
              if d.is_dir() and (d / f"{d.name}.py").is_file()] if group_dir.is_dir() else [])
    if not coded:
        return jsonify({"status": "error",
                        "message": "该组没有任何应用代码（<应用>/<应用>.py），请先运行『生成应用代码』（第③步）"}), 400
    tid = groupbuild_store.create_task(name_en, created_by=(user or {}).get("username"),
                                       kind="testexec")
    groupbuild_runner.enqueue(tid)
    return jsonify({"status": "ok", "id": tid, "count": len(coded)})


@bp.route("/api/groupbuild/groups/<name_en>/testexec", methods=["GET"])
def api_download_testexec(name_en):
    """下载测试脚本 verify_chain_<组>.py；?report=1 时下载 app/<组>/tests/测试报告_<组>.md；?zip=1 打包本组全部产物。"""
    if not _is_admin(_current_user()):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    tests_dir = APPS_DIR / name_en / "tests"
    if request.args.get("zip") == "1":
        files = ([tests_dir / f"verify_chain_{name_en}.py"]
                 + sorted(tests_dir.glob(f"verify_chain_{name_en}_part*.py"))
                 + [tests_dir / f"测试报告_{name_en}.md", tests_dir / f"BUGS_{name_en}.md",
                    tests_dir / f"修复提案_{name_en}.md"])
        files = [f for f in files if f.is_file()]
        if not files:
            return jsonify({"status": "error", "message": "测试产物尚未生成"}), 404
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in files:
                zf.write(f, arcname=f.name)
        buf.seek(0)
        return send_file(buf, as_attachment=True, download_name=f"test_{name_en}.zip",
                         mimetype="application/zip")
    if request.args.get("report") == "1":
        path = tests_dir / f"测试报告_{name_en}.md"
        dl = f"测试报告_{name_en}.md"
        miss = "测试报告尚未生成"
    else:
        path = tests_dir / f"verify_chain_{name_en}.py"
        dl = f"verify_chain_{name_en}.py"
        miss = "测试脚本尚未生成"
    if not path.is_file():
        return jsonify({"status": "error", "message": miss}), 404
    return send_file(str(path), as_attachment=True, download_name=dl)


@bp.route("/api/groupbuild/groups/<name_en>/testexec", methods=["DELETE"])
def api_delete_testexec(name_en):
    """删除自动生成的测试产物（app/<组>/tests/ 下本组脚本 + parts + 测试报告_<组>.md）；
    **不删** BUGS_<组>.md（台账）与 修复提案_<组>.md（提案留档）。"""
    if not _is_admin(_current_user()):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    tests_dir = APPS_DIR / name_en / "tests"
    targets = ([tests_dir / f"verify_chain_{name_en}.py", tests_dir / f"测试报告_{name_en}.md"]
               + list(tests_dir.glob(f"verify_chain_{name_en}_part*.py")))
    targets = [f for f in targets if f.is_file()]
    if not targets:
        return jsonify({"status": "error", "message": "测试执行产物不存在"}), 404
    try:
        for f in targets:
            f.unlink()
    except OSError as e:                     # Windows 下文件被占用（如编辑器打开）
        return jsonify({"status": "error",
                        "message": f"删除失败：文件可能被占用，请关闭占用程序后重试（{e}）"}), 500
    return jsonify({"status": "ok", "data": {"deleted": [f.name for f in targets]}})


# ── ⑧契约冻结：沙箱 dump _contracts.md（前端详设第⑥步的依赖屏障）────

@bp.route("/api/groupbuild/groups/<name_en>/contracts", methods=["POST"])
def api_create_contracts(name_en):
    """建⑧契约冻结任务：沙箱内跑 fde_platform.contract_dump.dump(seed=True)
    → app/<组>/_contracts.md（服务签名 + 造数级真实返回样例）。无 LLM、无修复回路。"""
    user = _current_user()
    if not _is_admin(user):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    group_dir = APPS_DIR / name_en
    coded = ([d.name for d in group_dir.iterdir()
              if d.is_dir() and (d / f"{d.name}.py").is_file()] if group_dir.is_dir() else [])
    if not coded:
        return jsonify({"status": "error",
                        "message": "该组没有任何应用代码（<应用>/<应用>.py），请先运行『生成应用代码』（第③步）"}), 400
    tid = groupbuild_store.create_task(name_en, created_by=(user or {}).get("username"),
                                       kind="contracts")
    groupbuild_runner.enqueue(tid)
    return jsonify({"status": "ok", "id": tid, "count": len(coded)})


@bp.route("/api/groupbuild/groups/<name_en>/contracts", methods=["GET"])
def api_download_contracts(name_en):
    """下载 app/<组>/_contracts.md（契约速查）。"""
    if not _is_admin(_current_user()):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    path = APPS_DIR / name_en / "_contracts.md"
    if not path.is_file():
        return jsonify({"status": "error",
                        "message": "尚未冻结契约（_contracts.md 不存在），请先运行『契约冻结』"}), 404
    return send_file(str(path), as_attachment=True, download_name="_contracts.md")


@bp.route("/api/groupbuild/groups/<name_en>/contracts", methods=["DELETE"])
def api_delete_contracts(name_en):
    """删除 app/<组>/_contracts.md（注意：前端详设第⑥步依赖此文件）。"""
    if not _is_admin(_current_user()):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    base = (APPS_DIR / name_en).resolve()
    path = (base / "_contracts.md").resolve()
    if not path.is_relative_to(base):
        return jsonify({"status": "error", "message": "非法路径"}), 400
    if not path.is_file():
        return jsonify({"status": "error", "message": "契约文件不存在"}), 404
    try:
        path.unlink()
    except OSError as e:                     # Windows 下文件被占用（如编辑器打开）
        return jsonify({"status": "error",
                        "message": f"删除失败：文件可能被占用，请关闭占用程序后重试（{e}）"}), 500
    return jsonify({"status": "ok", "data": {"deleted": f"app/{name_en}/_contracts.md"}})


# ── ⑨前端详设：逐应用 前端详设.md + 组级 前端详设/dashboard.md ────

def _fdesign_files(name_en: str) -> list:
    """列出 app/<组>/<应用>/前端详设.md（跳过组级 前端详设/ 目录 / brd / test / 隐藏目录）。"""
    base = APPS_DIR / name_en
    out = []
    if not base.is_dir():
        return out
    for d in sorted(p for p in base.iterdir()
                    if p.is_dir() and p.name not in ("brd", "test", "前端详设")
                    and not p.name.startswith(".")):
        f = d / "前端详设.md"
        if f.is_file():
            st = f.stat()
            out.append({"app": d.name, "size": st.st_size, "mtime": int(st.st_mtime)})
    return out


@bp.route("/api/groupbuild/groups/<name_en>/fdesign", methods=["POST"])
def api_create_fdesign(name_en):
    """建⑨前端详设任务：body {app_names?: []}（缺省=全部已详设应用）。
    硬预检：_contracts.md（⑧契约冻结屏障）+ 每个目标应用已有 应用详设.md（第②步）。"""
    user = _current_user()
    if not _is_admin(user):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    if not (APPS_DIR / name_en / "_contracts.md").is_file():
        return jsonify({"status": "error",
                        "message": f"缺少 app/{name_en}/_contracts.md，请先运行『契约冻结』（⑧，前端段依赖屏障）"}), 400
    d = request.get_json(silent=True) or {}
    app_names = d.get("app_names") or []
    group_dir = APPS_DIR / name_en
    all_apps = groupbuild_runner.arch_app_names(name_en)
    if not all_apps and group_dir.is_dir():        # 架构软依赖：无总表退路扫目录
        all_apps = sorted(p.name for p in group_dir.iterdir()
                          if p.is_dir() and (p / f"{p.name}.py").is_file()
                          and p.name not in ("brd", "test", "前端详设"))
    if not all_apps:
        return jsonify({"status": "error", "message": "该组没有任何应用（无架构总表且无应用目录）"}), 400
    if app_names:
        bad = [a for a in app_names if a not in all_apps]
        if bad:
            return jsonify({"status": "error", "message": f"应用不在组内：{', '.join(bad)}"}), 400
        target = [a for a in all_apps if a in app_names]   # 按总表序
    else:
        target = all_apps
    no_detail = [a for a in target
                 if not (group_dir / a / "应用详设.md").is_file()]
    if no_detail:
        return jsonify({"status": "error",
                        "message": "以下应用缺 应用详设.md，请先生成应用详设（第②步）："
                                   + ", ".join(no_detail)}), 400
    tid = groupbuild_store.create_task(name_en, created_by=(user or {}).get("username"),
                                       kind="fdesign", target_apps=",".join(target))
    groupbuild_runner.enqueue(tid)
    return jsonify({"status": "ok", "id": tid, "count": len(target)})


@bp.route("/api/groupbuild/groups/<name_en>/fdesign", methods=["GET"])
def api_list_fdesign(name_en):
    """列 前端详设 items；?zip=1 打包全部（逐应用 + 组级 dashboard.md，arcname 保结构）。"""
    if not _is_admin(_current_user()):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    base = APPS_DIR / name_en
    items = _fdesign_files(name_en)
    dashboard = base / "前端详设" / "dashboard.md"
    if request.args.get("zip") == "1":
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for it in items:
                zf.write(base / it["app"] / "前端详设.md",
                         arcname=f"{name_en}/{it['app']}/前端详设.md")
            if dashboard.is_file():
                zf.write(dashboard, arcname=f"{name_en}/前端详设/dashboard.md")
        buf.seek(0)
        return send_file(buf, as_attachment=True,
                         download_name=f"{name_en}_前端详设.zip",
                         mimetype="application/zip")
    return jsonify({"status": "ok", "data": {
        "items": items, "count": len(items),
        "aggregate_count": len(groupbuild_runner.arch_app_names(name_en)),
        "has_contracts": (base / "_contracts.md").is_file(),
        "has_dashboard": dashboard.is_file()}})


@bp.route("/api/groupbuild/groups/<name_en>/fdesign/<app>", methods=["GET"])
def api_download_fdesign(name_en, app):
    """下载单份前端详设；app=dashboard 时下载组级看板。"""
    if not _is_admin(_current_user()):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    base = (APPS_DIR / name_en).resolve()
    if app == "dashboard":
        path = (base / "前端详设" / "dashboard.md").resolve()
        dl = "dashboard.md"
    else:
        path = (base / app / "前端详设.md").resolve()
        dl = "前端详设.md"
    if not path.is_relative_to(base) or not path.is_file():
        return jsonify({"status": "error", "message": "前端详设不存在"}), 404
    return send_file(str(path), as_attachment=True, download_name=dl)


@bp.route("/api/groupbuild/groups/<name_en>/fdesign/<app>", methods=["DELETE"])
def api_delete_fdesign(name_en, app):
    """删除单份前端详设（app=dashboard 删组级看板；删后 前端详设/ 为空则连目录移除）。"""
    if not _is_admin(_current_user()):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    base = (APPS_DIR / name_en).resolve()
    if app == "dashboard":
        path = (base / "前端详设" / "dashboard.md").resolve()
    else:
        path = (base / app / "前端详设.md").resolve()
    if not path.is_relative_to(base):
        return jsonify({"status": "error", "message": "非法路径"}), 400
    if not path.is_file():
        return jsonify({"status": "error", "message": "前端详设不存在"}), 404
    try:
        path.unlink()
        if app == "dashboard":
            parent = path.parent
            if parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
    except OSError as e:
        return jsonify({"status": "error",
                        "message": f"删除失败：文件可能被占用，请关闭占用程序后重试（{e}）"}), 500
    return jsonify({"status": "ok", "data": {"deleted": str(path.relative_to(base))}})


# ── ⑩前端编码：逐应用 view.{js,html} + 组级 view/<组>/dashboard.{js,html} ────

def _fcode_files(name_en: str) -> list:
    """列出 app/<组>/<应用>/view.{js,html} 单元（跳过 brd / test / 前端详设 / 隐藏目录）。
    size = 两文件之和；mtime 取较新者。view.js / view.html 任一存在即计为一个单元。"""
    base = APPS_DIR / name_en
    out = []
    if not base.is_dir():
        return out
    for d in sorted(p for p in base.iterdir()
                    if p.is_dir() and p.name not in ("brd", "test", "前端详设")
                    and not p.name.startswith(".")):
        js, html = d / "view.js", d / "view.html"
        if js.is_file() or html.is_file():
            size = (js.stat().st_size if js.is_file() else 0) + \
                   (html.stat().st_size if html.is_file() else 0)
            mtime = max((int(f.stat().st_mtime) for f in (js, html) if f.is_file()), default=0)
            out.append({"app": d.name, "size": size, "mtime": mtime})
    return out


def _unit_view_files(app_base: Path) -> list:
    """单元内存在的 view.js / view.html 文件列表。"""
    return [f for f in (app_base / "view.js", app_base / "view.html") if f.is_file()]


@bp.route("/api/groupbuild/groups/<name_en>/fcode", methods=["POST"])
def api_create_fcode(name_en):
    """建⑩前端编码任务：body {app_names?: []}（缺省=全部已有前端详设的应用）。
    硬预检：_contracts.md（⑧契约冻结屏障）+ 每个目标应用已有 前端详设.md（⑨）。"""
    user = _current_user()
    if not _is_admin(user):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    if not (APPS_DIR / name_en / "_contracts.md").is_file():
        return jsonify({"status": "error",
                        "message": f"缺少 app/{name_en}/_contracts.md，请先运行『契约冻结』（⑧，前端段依赖屏障）"}), 400
    d = request.get_json(silent=True) or {}
    app_names = d.get("app_names") or []
    group_dir = APPS_DIR / name_en
    all_apps = [it["app"] for it in _fdesign_files(name_en)]   # 目标域 = 已有前端详设的应用
    if not all_apps:
        return jsonify({"status": "error",
                        "message": "该组没有任何含 前端详设.md 的应用，请先运行『前端详设』（⑨）"}), 400
    if app_names:
        bad = [a for a in app_names if a not in all_apps]
        if bad:
            return jsonify({"status": "error",
                            "message": f"以下应用缺 前端详设.md（或不在组内），请先生成前端详设（⑨）："
                                       + ", ".join(bad)}), 400
        target = [a for a in all_apps if a in app_names]
    else:
        target = all_apps
    tid = groupbuild_store.create_task(name_en, created_by=(user or {}).get("username"),
                                       kind="fcode", target_apps=",".join(target))
    groupbuild_runner.enqueue(tid)
    return jsonify({"status": "ok", "id": tid, "count": len(target)})


@bp.route("/api/groupbuild/groups/<name_en>/fcode", methods=["GET"])
def api_list_fcode(name_en):
    """列前端编码单元 items；?zip=1 打包全部（逐单元 view.{js,html} + 组级 dashboard.*，arcname 保结构）。"""
    if not _is_admin(_current_user()):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    base = APPS_DIR / name_en
    items = _fcode_files(name_en)
    vbase = VIEW_DIR / name_en
    dash_files = [f for f in (vbase / "dashboard.js", vbase / "dashboard.html") if f.is_file()]
    if request.args.get("zip") == "1":
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for it in items:
                for f in _unit_view_files(base / it["app"]):
                    zf.write(f, arcname=f"{name_en}/{it['app']}/{f.name}")
            for f in dash_files:
                zf.write(f, arcname=f"view/{name_en}/{f.name}")
        buf.seek(0)
        return send_file(buf, as_attachment=True,
                         download_name=f"{name_en}_前端编码.zip",
                         mimetype="application/zip")
    return jsonify({"status": "ok", "data": {
        "items": items, "count": len(items),
        "fdesign_count": len(_fdesign_files(name_en)),
        "has_contracts": (base / "_contracts.md").is_file(),
        "has_dashboard": bool(dash_files)}})


@bp.route("/api/groupbuild/groups/<name_en>/fcode/<app>", methods=["GET"])
def api_download_fcode(name_en, app):
    """下载单个单元（view.js + view.html 的 mini-zip）；app=dashboard 时下载组级看板单元。"""
    if not _is_admin(_current_user()):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    if app == "dashboard":
        base = (VIEW_DIR / name_en).resolve()
        files = [f for f in (base / "dashboard.js", base / "dashboard.html")
                 if f.is_relative_to(base) and f.is_file()]
    else:
        base = (APPS_DIR / name_en).resolve()
        unit = (base / app).resolve()
        if not unit.is_relative_to(base):
            return jsonify({"status": "error", "message": "非法路径"}), 400
        files = _unit_view_files(unit)
    if not files:
        return jsonify({"status": "error", "message": "前端编码产物不存在"}), 404
    if len(files) == 1:
        return send_file(str(files[0]), as_attachment=True, download_name=files[0].name)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, arcname=f"{app}/{f.name}")
    buf.seek(0)
    return send_file(buf, as_attachment=True,
                     download_name=f"{app}_view.zip", mimetype="application/zip")


@bp.route("/api/groupbuild/groups/<name_en>/fcode/<app>", methods=["DELETE"])
def api_delete_fcode(name_en, app):
    """删除单个单元（view.js + view.html）；app=dashboard 删组级看板（view/<组>/ 空则连目录移除）。"""
    if not _is_admin(_current_user()):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    if app == "dashboard":
        base = (VIEW_DIR / name_en).resolve()
        if not base.is_relative_to((VIEW_DIR).resolve()):
            return jsonify({"status": "error", "message": "非法路径"}), 400
        files = [f for f in (base / "dashboard.js", base / "dashboard.html") if f.is_file()]
    else:
        base = (APPS_DIR / name_en).resolve()
        unit = (base / app).resolve()
        if not unit.is_relative_to(base):
            return jsonify({"status": "error", "message": "非法路径"}), 400
        files = [f for f in (unit / "view.js", unit / "view.html") if f.is_file()]
    if not files:
        return jsonify({"status": "error", "message": "前端编码产物不存在"}), 404
    try:
        for f in files:
            f.unlink()
        if app == "dashboard" and base.is_dir() and not any(base.iterdir()):
            base.rmdir()
    except OSError as e:
        return jsonify({"status": "error",
                        "message": f"删除失败：文件可能被占用，请关闭占用程序后重试（{e}）"}), 500
    return jsonify({"status": "ok", "data": {"deleted": [f.name for f in files]}})


# ── ⑪前端测试用例：逐应用 前端测试用例.md + 组级补充 app/<组>/前端测试用例.md ────

def _ftest_files(name_en: str) -> list:
    """列出 app/<组>/<应用>/前端测试用例.md（跳过 brd / test / 前端详设 / 隐藏目录）。"""
    base = APPS_DIR / name_en
    out = []
    if not base.is_dir():
        return out
    for d in sorted(p for p in base.iterdir()
                    if p.is_dir() and p.name not in ("brd", "test", "前端详设")
                    and not p.name.startswith(".")):
        f = d / "前端测试用例.md"
        if f.is_file():
            st = f.stat()
            out.append({"app": d.name, "size": st.st_size, "mtime": int(st.st_mtime)})
    return out


@bp.route("/api/groupbuild/groups/<name_en>/ftest", methods=["POST"])
def api_create_ftest(name_en):
    """建⑪前端测试用例任务：body {app_names?: []}（缺省=全部已有前端详设的应用）。
    硬预检：_contracts.md（⑧契约冻结屏障）+ 逐目标应用 前端详设.md（⑨）。"""
    user = _current_user()
    if not _is_admin(user):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    group_dir = APPS_DIR / name_en
    if not (group_dir / "_contracts.md").is_file():
        return jsonify({"status": "error",
                        "message": f"缺少 app/{name_en}/_contracts.md，请先运行『契约冻结』（⑧，前端段依赖屏障）"}), 400
    if not (group_dir / "前端详设" / "dashboard.md").is_file():
        return jsonify({"status": "error",
                        "message": f"缺少 app/{name_en}/前端详设/dashboard.md，请先运行『前端详设』（⑨，组级补充用例依赖）"}), 400
    d = request.get_json(silent=True) or {}
    app_names = d.get("app_names") or []
    all_apps = [it["app"] for it in _fdesign_files(name_en)]   # 目标域 = 已有前端详设的应用
    if not all_apps:
        return jsonify({"status": "error",
                        "message": "该组没有任何含 前端详设.md 的应用，请先运行『前端详设』（⑨）"}), 400
    if app_names:
        bad = [a for a in app_names if a not in all_apps]
        if bad:
            return jsonify({"status": "error",
                            "message": "以下应用缺 前端详设.md（或不在组内），请先生成前端详设（⑨）："
                                       + ", ".join(bad)}), 400
        target = [a for a in all_apps if a in app_names]
    else:
        target = all_apps
    tid = groupbuild_store.create_task(name_en, created_by=(user or {}).get("username"),
                                       kind="ftest", target_apps=",".join(target))
    groupbuild_runner.enqueue(tid)
    return jsonify({"status": "ok", "id": tid, "count": len(target)})


@bp.route("/api/groupbuild/groups/<name_en>/ftest", methods=["GET"])
def api_list_ftest(name_en):
    """列前端测试用例 items；?zip=1 打包全部（逐应用 + 组级补充，arcname 保结构）。"""
    if not _is_admin(_current_user()):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    base = APPS_DIR / name_en
    items = _ftest_files(name_en)
    group_file = base / "前端测试用例.md"
    if request.args.get("zip") == "1":
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for it in items:
                zf.write(base / it["app"] / "前端测试用例.md",
                         arcname=f"{name_en}/{it['app']}/前端测试用例.md")
            if group_file.is_file():
                zf.write(group_file, arcname=f"{name_en}/前端测试用例.md")
        buf.seek(0)
        return send_file(buf, as_attachment=True,
                         download_name=f"{name_en}_前端测试用例.zip",
                         mimetype="application/zip")
    return jsonify({"status": "ok", "data": {
        "items": items, "count": len(items),
        "fdesign_count": len(_fdesign_files(name_en)),
        "has_contracts": (base / "_contracts.md").is_file(),
        "has_group": group_file.is_file()}})


@bp.route("/api/groupbuild/groups/<name_en>/ftest/<app>", methods=["GET"])
def api_download_ftest(name_en, app):
    """下载单份用例；app=_group 时下载组级补充文件。"""
    if not _is_admin(_current_user()):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    base = (APPS_DIR / name_en).resolve()
    if app == "_group":
        path = (base / "前端测试用例.md").resolve()
    else:
        path = (base / app / "前端测试用例.md").resolve()
    if not path.is_relative_to(base) or not path.is_file():
        return jsonify({"status": "error", "message": "前端测试用例不存在"}), 404
    return send_file(str(path), as_attachment=True, download_name="前端测试用例.md")


@bp.route("/api/groupbuild/groups/<name_en>/ftest/<app>", methods=["DELETE"])
def api_delete_ftest(name_en, app):
    """删除单份用例（app=_group 删组级补充）。"""
    if not _is_admin(_current_user()):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    base = (APPS_DIR / name_en).resolve()
    if app == "_group":
        path = (base / "前端测试用例.md").resolve()
    else:
        path = (base / app / "前端测试用例.md").resolve()
    if not path.is_relative_to(base):
        return jsonify({"status": "error", "message": "非法路径"}), 400
    if not path.is_file():
        return jsonify({"status": "error", "message": "前端测试用例不存在"}), 404
    try:
        path.unlink()
    except OSError as e:
        return jsonify({"status": "error",
                        "message": f"删除失败：文件可能被占用，请关闭占用程序后重试（{e}）"}), 500
    return jsonify({"status": "ok", "data": {"deleted": str(path.relative_to(base))}})


# ── ⑫前端测试执行：app/<组>/tests/verify_view_<组>_*.py 脚本 + app/<组>/tests/前端测试报告.md ────

def _fverify_files(name_en: str) -> list:
    """列 app/<组>/tests/verify_view_<组>_*.py 逐应用脚本（组级 verify_view_<组>.py 单列 has_group）。"""
    tests_dir = APPS_DIR / name_en / "tests"
    out = []
    if not tests_dir.is_dir():
        return out
    prefix = f"verify_view_{name_en}_"
    for f in sorted(tests_dir.glob(f"{prefix}*.py")):
        st = f.stat()
        out.append({"app": f.name[len(prefix):-3], "size": st.st_size, "mtime": int(st.st_mtime)})
    return out


@bp.route("/api/groupbuild/groups/<name_en>/fverify", methods=["POST"])
def api_create_fverify(name_en):
    """建⑫前端测试执行任务：body {app_names?: []}（缺省=全部已有前端测试用例的应用）。
    硬预检：逐目标应用 前端测试用例.md + 组级补充用例（⑪产出）。"""
    user = _current_user()
    if not _is_admin(user):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    group_dir = APPS_DIR / name_en
    if not (group_dir / "前端测试用例.md").is_file():
        return jsonify({"status": "error",
                        "message": f"缺少组级补充用例 app/{name_en}/前端测试用例.md，请先运行『前端测试』（⑪）"}), 400
    d = request.get_json(silent=True) or {}
    app_names = d.get("app_names") or []
    all_apps = [it["app"] for it in _ftest_files(name_en)]   # 目标域 = 已有前端测试用例的应用
    if not all_apps:
        return jsonify({"status": "error",
                        "message": "该组没有任何含 前端测试用例.md 的应用，请先运行『前端测试』（⑪）"}), 400
    if app_names:
        bad = [a for a in app_names if a not in all_apps]
        if bad:
            return jsonify({"status": "error",
                            "message": "以下应用缺 前端测试用例.md（或不在组内），请先生成前端测试用例（⑪）："
                                       + ", ".join(bad)}), 400
        target = [a for a in all_apps if a in app_names]
    else:
        target = all_apps
    tid = groupbuild_store.create_task(name_en, created_by=(user or {}).get("username"),
                                       kind="fverify", target_apps=",".join(target))
    groupbuild_runner.enqueue(tid)
    return jsonify({"status": "ok", "id": tid, "count": len(target)})


@bp.route("/api/groupbuild/groups/<name_en>/fverify", methods=["GET"])
def api_list_fverify(name_en):
    """列前端测试脚本 items；?report=1 下载报告；?zip=1 打包全部脚本。"""
    if not _is_admin(_current_user()):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    tests_dir = APPS_DIR / name_en / "tests"
    items = _fverify_files(name_en)
    group_script = tests_dir / f"verify_view_{name_en}.py"
    report = tests_dir / "前端测试报告.md"
    if request.args.get("report") == "1":
        if not report.is_file():
            return jsonify({"status": "error", "message": "前端测试报告不存在（尚未执行）"}), 404
        return send_file(str(report), as_attachment=True, download_name="前端测试报告.md")
    if request.args.get("zip") == "1":
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for it in items:
                zf.write(tests_dir / f"verify_view_{name_en}_{it['app']}.py",
                         arcname=f"verify_view_{name_en}_{it['app']}.py")
            if group_script.is_file():
                zf.write(group_script, arcname=f"verify_view_{name_en}.py")
        buf.seek(0)
        return send_file(buf, as_attachment=True,
                         download_name=f"verify_view_{name_en}.zip", mimetype="application/zip")
    return jsonify({"status": "ok", "data": {
        "items": items, "count": len(items),
        "ftest_count": len(_ftest_files(name_en)),
        "has_group": group_script.is_file(),
        "has_report": report.is_file()}})


@bp.route("/api/groupbuild/groups/<name_en>/fverify", methods=["DELETE"])
def api_delete_fverify(name_en):
    """删除该组全部前端测试脚本（app/<组>/tests/verify_view_<组>*.py）+ 前端测试报告.md。"""
    if not _is_admin(_current_user()):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    tests_dir = APPS_DIR / name_en / "tests"
    targets = list(tests_dir.glob(f"verify_view_{name_en}_*.py")) + [tests_dir / f"verify_view_{name_en}.py"]
    report = tests_dir / "前端测试报告.md"
    targets = [f for f in targets if f.is_file()] + ([report] if report.is_file() else [])
    if not targets:
        return jsonify({"status": "error", "message": "没有可删除的前端测试产物"}), 404
    try:
        for f in targets:
            f.unlink()
    except OSError as e:
        return jsonify({"status": "error",
                        "message": f"删除失败：文件可能被占用，请关闭占用程序后重试（{e}）"}), 500
    return jsonify({"status": "ok", "data": {"deleted": [f.name for f in targets]}})


# ── 第⑤步回路：BUG 修复（提案 → 批准 → 应用 → 重测）────

@bp.route("/api/groupbuild/groups/<name_en>/bugfix", methods=["POST"])
def api_create_bugfix(name_en):
    """建 BUG 修复提案任务：对测试报告中每个未通过用例逐条 triage 并提案（只提案不落码）。"""
    user = _current_user()
    if not _is_admin(user):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    report = APPS_DIR / name_en / "tests" / f"测试报告_{name_en}.md"
    if not report.is_file():
        return jsonify({"status": "error",
                        "message": "缺少 测试报告.md，请先运行『测试执行』（第⑤步）"}), 400
    failed = groupbuild_runner._report_failed_entries(report.read_text(encoding="utf-8"))
    if not failed:
        return jsonify({"status": "error", "message": "测试报告无未通过用例，无需修复提案"}), 400
    tid = groupbuild_store.create_task(name_en, created_by=(user or {}).get("username"),
                                       kind="bugfix")
    groupbuild_runner.enqueue(tid)
    return jsonify({"status": "ok", "id": tid, "count": len(failed)})


@bp.route("/api/groupbuild/groups/<name_en>/bugfix/doc", methods=["GET"])
def api_bugfix_doc(name_en):
    """下载 修复提案.md（提案任务产出）。"""
    if not _is_admin(_current_user()):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    path = APPS_DIR / name_en / "tests" / f"修复提案_{name_en}.md"
    if not path.is_file():
        return jsonify({"status": "error", "message": "修复提案文档尚未生成"}), 404
    return send_file(str(path), as_attachment=True, download_name="修复提案.md")


@bp.route("/api/groupbuild/groups/<name_en>/bugfix/proposals", methods=["GET"])
def api_list_proposals(name_en):
    """列该组修复提案（可按 ?status= 过滤）。"""
    if not _is_admin(_current_user()):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    status = request.args.get("status") or None
    return jsonify({"status": "ok",
                    "data": groupbuild_store.list_proposals(name_en, status)})


@bp.route("/api/groupbuild/proposals/<int:pid>/decision", methods=["POST"])
def api_proposal_decision(pid):
    """批准 / 驳回单条提案（仅 pending 可决）。"""
    if not _is_admin(_current_user()):
        return jsonify({"status": "error", "message": "无权限"}), 403
    d = request.get_json(silent=True) or {}
    action = (d.get("action") or "").strip()
    if action not in ("approve", "reject"):
        return jsonify({"status": "error", "message": "action 须为 approve / reject"}), 400
    p = groupbuild_store.get_proposal(pid)
    if not p:
        return jsonify({"status": "error", "message": "提案不存在"}), 404
    if p["status"] != "pending":
        return jsonify({"status": "error",
                        "message": f"提案已是 {p['status']} 状态，不可再决"}), 400
    if action == "reject":
        groupbuild_store.set_proposal_status(pid, "rejected")
        return jsonify({"status": "ok", "message": "已驳回"})
    if p["category"] == "design_issue":
        # 设计层问题无可应用代码：批准即转「待人工处理」，不进代码应用 / 重测流程
        groupbuild_store.set_proposal_status(pid, "manual")
        return jsonify({"status": "ok",
                        "message": "已确认为设计层问题（待人工修订详设；无可应用代码，不参与应用 / 重测）"})
    groupbuild_store.set_proposal_status(pid, "approved")
    return jsonify({"status": "ok", "message": "已批准"})


@bp.route("/api/groupbuild/groups/<name_en>/bugfix/apply", methods=["POST"])
def api_apply_bugfix(name_en):
    """应用已批准提案（白名单 + 备份 + 精确替换 + 语法门），并自动派生 testexec 重测。"""
    user = _current_user()
    if not _is_admin(user):
        return jsonify({"status": "error", "message": "无权限"}), 403
    if not _valid_name_en(name_en):
        return jsonify({"status": "error", "message": "非法应用组名"}), 400
    approved = groupbuild_store.list_proposals(name_en, status="approved")
    if not approved:
        return jsonify({"status": "error", "message": "没有已批准的提案"}), 400
    tid = groupbuild_store.create_task(name_en, created_by=(user or {}).get("username"),
                                       kind="bugfix-apply")
    groupbuild_runner.enqueue(tid)
    return jsonify({"status": "ok", "id": tid, "count": len(approved)})


# ── 任务查询 ────────────────────────────────────────────

@bp.route("/api/groupbuild/tasks/<int:task_id>/cancel", methods=["POST"])
def api_cancel_task(task_id):
    """请求终止任务（协作式）：置 cancel_requested 标志，runner 在节点入口 / LLM 调用 /
    修复与运行循环 / 沙箱子进程等检查点感知后落终态 cancelled（重启续跑不会再捞起）。"""
    if not _is_admin(_current_user()):
        return jsonify({"status": "error", "message": "无权限"}), 403
    t = groupbuild_store.get_task(task_id)
    if not t:
        return jsonify({"status": "error", "message": "任务不存在"}), 404
    if t["status"] not in ("queued", "running"):
        return jsonify({"status": "error",
                        "message": f"任务已结束（{t['status']}），无需终止"}), 400
    groupbuild_runner.request_cancel_task(task_id)
    if t["status"] == "queued":
        # 排队任务不必等出队：直接落终态（若已出队在跑，run_task 入口据标志同样落 cancelled）
        groupbuild_store.update_task(task_id, status="cancelled", current_step="已终止")
        return jsonify({"status": "ok", "message": "已终止（排队任务立即生效）"})
    return jsonify({"status": "ok",
                    "message": "已请求终止：运行中任务在最近的检查点生效（LLM 流式生成可秒级中断）"})


@bp.route("/api/groupbuild/tasks/<int:task_id>", methods=["GET"])
def api_task_detail(task_id):
    if not _is_admin(_current_user()):
        return jsonify({"status": "error", "message": "无权限"}), 403
    t = groupbuild_store.get_task(task_id)
    if not t:
        return jsonify({"status": "error", "message": "任务不存在"}), 404
    return jsonify({"status": "ok", "data": groupbuild_store.public_view(t)})


@bp.route("/api/groupbuild/tasks", methods=["GET"])
def api_list_tasks():
    if not _is_admin(_current_user()):
        return jsonify({"status": "error", "message": "无权限"}), 403
    group = (request.args.get("group") or "").strip()
    tasks = (groupbuild_store.list_tasks_by_group(group) if group
             else groupbuild_store.list_tasks())
    return jsonify({"status": "ok", "data": [groupbuild_store.public_view(t) for t in tasks]})


def register(app) -> None:
    groupbuild_store.init_schema()
    # 启动后台 worker（并续跑重启前未完成的任务）。FDE_NO_WORKER 时跳过：
    # 验收脚本自起的平台子进程同样注册本蓝图、共享任务库，若续跑「运行中」任务
    # 会与主进程 worker 并行执行同一任务（⑫前端测试执行引擎显式注入此环境变量）。
    if not os.environ.get("FDE_NO_WORKER"):
        groupbuild_runner.start_worker()
    app.register_blueprint(bp)
