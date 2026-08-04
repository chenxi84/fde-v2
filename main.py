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

# FDE 应用组构建（可插拔）：五步法（架构 / 详设 / 编码 / 用例 / 测试执行）+ BUG 修复回路 + 契约冻结
# + 前端段；独立 LangGraph 任务链，共用 llm.py 的 builder 模型配置
try:
    from fde_platform import groupbuild_admin

    groupbuild_admin.register(app)
    GROUPBUILD_ON = True
except ImportError:
    GROUPBUILD_ON = False


def main():
    names = platform.app_names()
    bar = "=" * 54
    print(f"\n{bar}")
    print(f"FDE 技术平台 {VERSION} 启动")
    print(bar)
    print(f"浏览器端 : http://{HOST}:{PORT}")
    print(f"鉴权     : {'开启（首次登录 admin/admin，请尽快改密）' if AUTH_ON else '关闭（无认证模式）'}")
    print(f"定时任务 : {'开启（/scheduler）' if SCHED_ON else '关闭'}")
    print(f"大模型配置: {'开启（/llm，两个 Agent 独立配模型）' if LLM_ADMIN_ON else '关闭'}")
    print(f"应用组构建: {'开启（/groupbuild，五步法：架构/详设/编码/用例/测试执行）' if GROUPBUILD_ON else '关闭'}")
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
