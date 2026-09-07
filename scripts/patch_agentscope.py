#!/usr/bin/env python3
"""Docker 构建时在 agentscope 源码上打 FDE-PATCH。

背景：FDE 依赖两个打在 agentscope 源码上的补丁（本机开发时手动打的）。
Docker 构建 pip install 装的是干净 agentscope，补丁丢失会导致：
- agent 对话报 ``'list' object has no attribute 'name'``（extra_factory 元组被误当工具）
- 定时任务按 UTC 触发（偏差 8 小时）

requirements.txt 已固定 ``agentscope==2.0.6``，本脚本针对 2.0.6 源码结构。
若未来升级 agentscope，需同步核对补丁是否仍命中（脚本会打印 FAIL）。
"""
import sys
from pathlib import Path

import agentscope

BASE = Path(agentscope.__file__).resolve().parent

_FAILED = []  # 未命中/文件缺失的补丁名（脚本末尾据此决定退出码）


def apply(path: Path, old: str, new: str, name: str, marker: str = None) -> None:
    if not path.exists():
        print(f"[patch] FAIL  {name}: 文件不存在 {path}（agentscope 版本可能变化）")
        _FAILED.append(name)
        return
    src = path.read_text(encoding="utf-8")
    # 已打过补丁：new 精确命中，或单行 marker 命中（应对 CRLF/LF 换行导致 new 不完全匹配）
    if (new and new in src) or (marker and marker in src):
        print(f"[patch] SKIP  {name}: 已打过补丁")
        return
    if old not in src:
        print(f"[patch] FAIL  {name}: 未命中目标代码（agentscope 版本可能变化）")
        _FAILED.append(name)
        return
    path.write_text(src.replace(old, new, 1), encoding="utf-8")
    print(f"[patch] OK    {name}")


# ── 补丁 1：_toolkit.py get_toolkit 支持 extra_factory 返回 (tools, tool_groups) 元组 ──
apply(
    BASE / "app" / "_service" / "_toolkit.py",
    (
        "    if extra_factory is not None:\n"
        "        tools += await extra_factory(\n"
        "            user_id,\n"
        "            agent_record.id,\n"
        "            session_record.id,\n"
        "        )"
    ),
    (
        "    if extra_factory is not None:\n"
        "        extras = await extra_factory(\n"
        "            user_id,\n"
        "            agent_record.id,\n"
        "            session_record.id,\n"
        "        )\n"
        "        # [FDE-PATCH] extra_factory 可返回 (tools, tool_groups) 元组：工具分组懒加载\n"
        "        if isinstance(extras, tuple) and len(extras) == 2:\n"
        "            extra_tools, extra_groups = extras\n"
        "            tools += (extra_tools or [])\n"
        "            tool_groups += (extra_groups or [])\n"
        "        else:\n"
        "            tools += extras"
    ),
    "extra_factory 元组",
    marker="[FDE-PATCH] extra_factory",
)

# ── 补丁 2：_schedule_create.py 定时任务默认本地时区 ──
_sched = BASE / "app" / "_manager" / "_scheduler" / "_tools" / "_schedule_create.py"
apply(
    _sched,
    (
        "    timezone: str = Field(\n"
        "        default=\"UTC\",\n"
        "        description=\"IANA timezone name used to evaluate the cron expression, \"\n"
        "        \"e.g. 'America/New_York' or 'Asia/Shanghai'.\",\n"
        "    )\n"
    ),
    "",
    "删 timezone 字段",
    marker="timezone: str | None = None,",
)
apply(
    _sched,
    "        timezone: str = \"UTC\",",
    "        timezone: str | None = None,",
    "timezone 默认 None",
)
apply(
    _sched,
    (
        "        source_session_id = (\n"
        "            _agent_state.session_id if _agent_state is not None else \"\"\n"
        "        )\n"
        "\n"
        "        record = ScheduleRecord("
    ),
    (
        "        source_session_id = (\n"
        "            _agent_state.session_id if _agent_state is not None else \"\"\n"
        "        )\n"
        "\n"
        "        # [FDE-PATCH] timezone 默认本地时区（不传时用 tzlocal，而非 UTC）\n"
        "        if timezone is None:\n"
        "            try:\n"
        "                from tzlocal import get_localzone\n"
        "                timezone = str(get_localzone())\n"
        "            except Exception:\n"
        "                timezone = \"UTC\"\n"
        "\n"
        "        record = ScheduleRecord("
    ),
    "tzlocal 回落",
    marker="[FDE-PATCH] timezone",
)

# ── 末尾：任一补丁未命中/文件缺失 → 非零退出码，让 Docker 构建 / 启动明确失败 ──
if _FAILED:
    print(
        f"\n[patch] 失败 {len(_FAILED)} 个补丁：{', '.join(_FAILED)}。"
        "agentscope 版本可能已变化，请同步核对补丁。",
    )
    sys.exit(1)
print("\n[patch] 全部完成")
