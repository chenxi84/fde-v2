"""FDE v2 平台 — 知识库管理页（可插拔 Blueprint）。

非结构化知识文件的入口：上传（增量索引）→ 删除（增量删索引）→ 查询。
底层复用 knowledge_graph 的 add_doc / remove_doc / build_index / query_sync。

仅 admin 可访问（无鉴权模式全通，与 llm_admin / scheduler 同口径）。
可插拔：删除本模块 + main.py 的 register 调用即无此页。
"""
import threading
from pathlib import Path

from flask import Blueprint, jsonify, redirect, render_template, request

from fde_platform import knowledge_graph, users

bp = Blueprint("rules_admin", __name__)

RULES_DIR = knowledge_graph.RULES_DIR

# 索引状态（异步全量索引的进度，供前端轮询）
_INDEX_STATE = {"running": False, "done": False, "docs": 0, "nodes": 0, "edges": 0, "error": ""}


def _is_admin(user) -> bool:
    return user is None or bool(user.get("is_admin"))


def _current_user():
    try:
        return users.session_user()
    except Exception:
        return None


def _guard():
    return redirect("/") if not _is_admin(_current_user()) else None


def _list_files() -> list:
    if not RULES_DIR.is_dir():
        return []
    out = []
    for p in sorted(RULES_DIR.iterdir()):
        if p.is_file() and p.suffix.lower() in (".md", ".txt"):
            st = p.stat()
            out.append({"name": p.name, "size": st.st_size, "mtime": int(st.st_mtime)})
    return out


def _doc_id(name: str) -> str:
    return f"rules/{name}"


def _index_status() -> dict:
    """索引状态：是否已建 + 图规模（节点/边），叠加异步索引进度。"""
    graphml = knowledge_graph.KG_DIR / "rules" / "graph_chunk_entity_relation.graphml"
    status = dict(_INDEX_STATE)
    status["built"] = graphml.is_file()
    status["nodes"] = 0
    status["edges"] = 0
    if graphml.is_file():
        try:
            import networkx as nx

            g = nx.read_graphml(str(graphml))
            status["nodes"] = g.number_of_nodes()
            status["edges"] = g.number_of_edges()
        except Exception:
            pass
    return status


@bp.route("/rules-admin")
def page():
    g = _guard()
    if g is not None:
        return g
    return render_template("rules_admin.html", files=_list_files(), status=_index_status())


@bp.route("/rules-admin/upload", methods=["POST"])
def upload():
    g = _guard()
    if g is not None:
        return g
    f = request.files.get("file")
    if not f or not f.filename:
        return redirect("/rules-admin")
    name = Path(f.filename).name
    if not name.lower().endswith((".md", ".txt")):
        return redirect("/rules-admin")
    RULES_DIR.mkdir(parents=True, exist_ok=True)
    f.save(RULES_DIR / name)
    # 增量索引放后台线程，避免阻塞上传响应（add_doc_sync 走持久 loop）
    content = (RULES_DIR / name).read_text(encoding="utf-8")
    threading.Thread(
        target=knowledge_graph.add_doc_sync, args=("rules", _doc_id(name), content), daemon=True
    ).start()
    return redirect("/rules-admin")


@bp.route("/rules-admin/delete", methods=["POST"])
def delete():
    g = _guard()
    if g is not None:
        return g
    name = (request.form.get("name") or "").strip()
    if not name or "/" in name or "\\" in name:
        return redirect("/rules-admin")
    p = RULES_DIR / name
    if p.is_file():
        p.unlink()
        threading.Thread(
            target=knowledge_graph.remove_doc_sync, args=("rules", _doc_id(name)), daemon=True
        ).start()
    return redirect("/rules-admin")


@bp.route("/rules-admin/index", methods=["POST"])
def index():
    g = _guard()
    if g is not None:
        return g
    _INDEX_STATE.update({"running": True, "done": False, "docs": 0, "nodes": 0, "edges": 0, "error": ""})

    def _run():
        try:
            r = knowledge_graph.build_index_sync("rules")
            _INDEX_STATE.update({"done": True, "docs": r.get("docs", 0)})
        except Exception as e:  # noqa: BLE001
            _INDEX_STATE.update({"error": f"{type(e).__name__}: {e}"})
        finally:
            _INDEX_STATE["running"] = False

    threading.Thread(target=_run, daemon=True).start()
    return redirect("/rules-admin")


@bp.route("/rules-admin/status")
def status():
    g = _guard()
    if g is not None:
        return jsonify({"status": "error", "message": "无权限"}), 403
    return jsonify({"status": "ok", "data": _index_status()})


@bp.route("/rules-admin/query", methods=["POST"])
def query():
    g = _guard()
    if g is not None:
        return jsonify({"status": "error", "message": "无权限"}), 403
    q = (request.form.get("q") or "").strip()
    if not q:
        return jsonify({"status": "error", "message": "问题不能为空"}), 400
    try:
        answer = knowledge_graph.query_sync("rules", q)
        return jsonify({"status": "ok", "answer": answer})
    except Exception as e:  # noqa: BLE001
        return jsonify({"status": "error", "message": f"{type(e).__name__}: {e}"}), 500


def register(app) -> None:
    app.register_blueprint(bp)
