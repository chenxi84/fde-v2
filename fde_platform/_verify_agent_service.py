"""agent_service 端到端验证/联调脚本。

走 HTTP API 验证「credential → agent → session → chat → SSE 流」全链路，含：
- 模型连通（单对话流式回复）
- team 建队（leader 调用 TeamCreate/AgentCreate 组建专家团队）

前置：先启动 `python -m fde_platform.agent_service`（:4100）。
"""
import asyncio
import sys

import httpx

sys.path.insert(0, ".")
from fde_platform import llm  # noqa: E402

BASE = "http://127.0.0.1:4100"
USER_ID = "admin"


async def main():
    # 1. 解密 FDE operator 的 deepseek key（复用 llm.db 现有配置）
    profile = llm.load_profile("operator")
    api_key = llm.decrypt_key(profile["api_key_enc"])
    model = profile["model"]
    base_url = profile["base_url"] or "https://api.deepseek.com/v1"
    print(f"[1] LLM: {model} @ {base_url} (key 已解密)")

    async with httpx.AsyncClient(timeout=120) as c:
        h = {"X-User-ID": USER_ID}

        # 2. 注册 credential
        r = await c.post(f"{BASE}/credential/", json={
            "data": {"type": "deepseek_credential", "api_key": api_key, "base_url": base_url},
        }, headers=h)
        r.raise_for_status()
        cred_id = r.json()["credential_id"]
        print(f"[2] credential_id = {cred_id}")

        # 3. 建 leader agent
        r = await c.post(f"{BASE}/agent/", json={
            "name": "leader",
            "system_prompt": (
                "你是产销协同的多智能体编排 leader。你持有团队工具（TeamCreate/AgentCreate/TeamSay），"
                "遇到需要多领域协作的任务时必须组建团队：先 TeamCreate 建团队，再用 AgentCreate "
                "按 subagent_type 创建成员（可选类型：sales/planning/inventory/delivery），"
                "用 TeamSay 给成员派活。"
            ),
        }, headers=h)
        r.raise_for_status()
        agent_id = r.json()["agent_id"]
        print(f"[3] agent_id = {agent_id}")

        # 4. 建 session（带 chat_model_config）
        r = await c.post(f"{BASE}/sessions/", json={
            "agent_id": agent_id,
            "chat_model_config": {
                "type": "deepseek_credential",
                "credential_id": cred_id,
                "model": model,
                "parameters": {},
            },
        }, headers=h)
        r.raise_for_status()
        session_id = r.json()["session_id"]
        print(f"[4] session_id = {session_id}")

        # 5. 触发建队任务
        msg = {"role": "user", "name": "user",
               "content": [{"type": "text", "text": (
                   "客户突然加单，请组建一个团队，分别由销售、计划、库存、交付四位专家"
                   "协同分析应对。先建团队，再按角色类型创建成员并派活。"
               )}]}
        r = await c.post(f"{BASE}/chat/", json={
            "agent_id": agent_id, "session_id": session_id, "input": msg,
        }, headers=h)
        r.raise_for_status()
        print(f"[5] chat 触发: {r.json()}")

        # 6. 读 SSE stream：打印工具调用事件（看 subagent_type 建对角色），
        #    文本增量只累积，最后打印完整回复。
        print("[6] 订阅 stream，观察建队 + 角色类型…")
        text_parts = []
        async with c.stream("GET", f"{BASE}/sessions/{session_id}/stream",
                            params={"agent_id": agent_id}, headers=h) as resp:
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                import json as _json
                evt = _json.loads(line[5:].strip())
                t = evt.get("type")
                if t == "TEXT_BLOCK_DELTA":
                    text_parts.append(evt.get("delta", "") or "")
                elif t == "TOOL_CALL_START":
                    name = evt.get("tool_call_name") or evt.get("name") or ""
                    inp = evt.get("input") or evt.get("tool_input") or evt.get("arguments") or ""
                    print(f"    [TOOL_CALL] {name} {str(inp)[:160]}")
                elif t in ("REPLY_END", "REPLY_START", "TOOL_CALL_END"):
                    print(f"    [{t}]")
                    if t == "REPLY_END":
                        break
        print("\n=== leader 最终回复 ===")
        print("".join(text_parts))


if __name__ == "__main__":
    asyncio.run(main())
