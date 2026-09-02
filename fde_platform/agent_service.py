"""AgentScope agent_service 入口（多智能体编排层，独立 FastAPI 进程）。

裸跑验证用：先不接 FDE 业务工具（extra_agent_tools=None），只验证
create_app + SQLite storage + InMemory bus + LocalWorkspace 能起、
team 端点可达。后续接入见 design-plus/ 多智能体方案。

启动：python -m fde_platform.agent_service  → http://127.0.0.1:4100
"""
import os
from pathlib import Path

from agentscope.app import create_app
from agentscope.app.message_bus import InMemoryMessageBus
from agentscope.app.storage import AsyncSQLAlchemyStorage
from agentscope.app.workspace_manager import LocalWorkspaceManager

# 数据落 config/（与 FDE 的 auth.db/skills.db 同级，零外部依赖）
_BASE = Path(__file__).resolve().parents[1] / "config"
_DB_URL = os.environ.get(
    "AGENT_SERVICE_DB",
    f"sqlite+aiosqlite:///{(_BASE / 'agent_service.db').as_posix()}",
)
_WORKDIR = str(_BASE / "agent_workspaces")

app = create_app(
    storage=AsyncSQLAlchemyStorage(_DB_URL, create_tables=True),
    message_bus=InMemoryMessageBus(),
    workspace_manager=LocalWorkspaceManager(basedir=_WORKDIR),
    title="FDE Agent Service",
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("fde_platform.agent_service:app", host="127.0.0.1", port=4100)
