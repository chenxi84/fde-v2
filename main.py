"""FDE v2 平台启动入口。

用法：python main.py
启动后：
- 浏览器访问 http://127.0.0.1:4000  （应用清单 / 详情 / 手工调用 / Agent）
- MCP 服务另起：python -m fde_platform.mcp_server  （stdio）

Author: chenxi <tomcx@qq.com>
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# 加载配置（若存在 config/.env）；FDE_MOCK=1 时追加 config/mock.env
# （网关/主数据改走 mock-api 模拟器的 HTTP 地址，便于整体联调）
try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / "config" / ".env")
    if os.environ.get("FDE_MOCK", "").lower() in ("1", "true", "yes"):
        load_dotenv(ROOT / "config" / "mock.env")
except ImportError:
    pass

from fde_platform.web import HOST, PORT, VERSION, app, platform  # noqa: E402
from fde_platform import web as _web  # noqa: E402  # 暴露组件状态给首页监控区

# 启用鉴权（可插拔）：删除 fde_platform/auth.py 与 users.py 后此处 import 失败，
# 平台自动回落无认证模式，其余代码无需改动。
try:
    from fde_platform import auth

    auth.register(app)
    AUTH_ON = True
except ImportError:
    AUTH_ON = False

# 定时任务（可插拔）：删除 fde_platform/scheduler.py 后此处 import 失败即回落无定时任务
try:
    from fde_platform import scheduler

    scheduler.register(app, platform)
    SCHED_ON = True
except ImportError:
    SCHED_ON = False

# 大模型配置（可插拔）：删除 fde_platform/llm_admin.py 后此处 import 失败即回落无此页
try:
    from fde_platform import llm_admin

    llm_admin.register(app)
    LLM_ADMIN_ON = True
except ImportError:
    LLM_ADMIN_ON = False

# Agent 后端管理（可插拔）：删除 fde_platform/agent_admin.py 后此处 import 失败即回落无此页
try:
    from fde_platform import agent_admin

    agent_admin.register(app)
    AGENT_ADMIN_ON = True
except ImportError:
    AGENT_ADMIN_ON = False

# 制度库管理（可插拔）：删除 fde_platform/rules_admin.py 后此处 import 失败即回落无此页
try:
    from fde_platform import rules_admin

    rules_admin.register(app)
    RULES_ADMIN_ON = True
except ImportError:
    RULES_ADMIN_ON = False

# 组件状态收集（供首页「平台运行情况」监控区展示本次启动已加载的组件）
_web.COMPONENTS = [
    {"key": "auth", "name": "鉴权", "icon": "🔐", "loaded": AUTH_ON,
     "desc": "用户登录与会话、页面/服务级授权。可插拔：删除 auth.py / users.py 即回落无认证模式。"},
    {"key": "scheduler", "name": "定时任务", "icon": "🔌", "loaded": SCHED_ON,
     "desc": "按 cron 定时调用应用公共服务，成功/失败落库。可插拔：删除 scheduler.py 即回落无定时任务。"},
    {"key": "llm", "name": "大模型配置", "icon": "🧠", "loaded": LLM_ADMIN_ON,
     "desc": "配置 LLM 档案（operator 对话 / vision 视觉 / builder 构建）。未配置不影响应用清单/手工调用/MCP。"},
    {"key": "agent", "name": "Agent 后端", "icon": "🤖", "loaded": AGENT_ADMIN_ON,
     "desc": "AgentScope 多智能体编排（leader 建队派活），业务角色下沉到各组 _roles.py。"},
    {"key": "knowledge", "name": "知识库", "icon": "📚", "loaded": RULES_ADMIN_ON,
     "desc": "非结构化知识文件（制度/SOP/最佳实践），经 LightRAG 索引后语义检索。"},
    {"key": "db", "name": "数据库", "icon": "🗄️", "loaded": True,
     "desc": "SQLite（默认）或 PostgreSQL（设置 DATABASE_URL 即切换，建表/方言自动翻译）。"},
]

def main():
    names = platform.app_names()
    bar = "=" * 54
    print(f"\n{bar}")
    print(f"FDE 技术平台 {VERSION} 启动")
    print(bar)
    from fde_platform.db import db_mode
    print(f"浏览器端 : http://{HOST}:{PORT}")
    print(f"数据库   : {db_mode()}")
    print(f"鉴权     : {'开启（首次登录 admin/admin，请尽快改密）' if AUTH_ON else '关闭（无认证模式）'}")
    print(f"定时任务 : {'开启（/scheduler）' if SCHED_ON else '关闭'}")
    print(f"大模型配置: {'开启（/llm）' if LLM_ADMIN_ON else '关闭'}")
    print(f"Agent 后端: {os.environ.get('AGENT_BACKEND', 'agentscope')}（管理页 /agent-admin）")
    print(f"应用目录 : {platform.apps_dir}")
    print(f"发现应用 : {len(names)} 个")
    # 按应用组（app/ 一级目录）分组展示；未分组应用单列
    groups = platform.groups()
    for g in groups + ([None] if platform.apps_in_group(None) else []):
        members = platform.apps_in_group(g)
        if g is not None:
            print(f"  [组 {g}]（{len(members)} 个应用）")
        for name in members:
            n = len(platform.services(name))
            prefix = "    - " if g is not None else "  - "
            print(f"{prefix}{name}（{n} 个对外服务）")
    print("MCP 服务 : python -m fde_platform.mcp_server  (stdio)")
    print(f"{bar}\n")

    try:
        from waitress import serve
        print(f"使用 Waitress 启动（多线程生产模式）")
        serve(app, host=HOST, port=PORT, threads=4)
    except ImportError:
        print(f"Waitress 未安装，回退 Flask 内置服务器")
        app.run(host=HOST, port=PORT, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
