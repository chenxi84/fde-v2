"""agent_service 反代端到端验证（临时）：经 FDE /api/agent2/ 走完整链路。

验证：FDE 登录态 → X-User-ID 桥接 + SSE 流式转发。
前置：FDE 主进程（:4000）+ agent_service（:4100）都已在跑。
"""
import sys

import httpx

sys.path.insert(0, ".")
from fde_platform import llm  # noqa: E402

FDE = "http://127.0.0.1:4000"
PROXY = "http://127.0.0.1:4000/api/agent2"


def main():
    # 1. 登录 FDE（cookie 自动保存到 client）
    client = httpx.Client(timeout=120)
    r = client.post(f"{FDE}/login", data={"username": "admin", "password": "123456"},
                    follow_redirects=False)
    print(f"[1] 登录 FDE: {r.status_code}")

    # 2. 解密 key + 经反代建 credential
    p = llm.load_profile("operator")
    api_key = llm.decrypt_key(p["api_key_enc"])
    r = client.post(f"{PROXY}/credential/", json={"data": {
        "type": "deepseek_credential", "api_key": api_key, "base_url": p["base_url"],
    }})
    cred_id = r.json()["credential_id"]
    print(f"[2] credential: {cred_id[:8]}…")

    # 3. 经反代建 agent + session
    r = client.post(f"{PROXY}/agent/", json={"name": "leader",
                                             "system_prompt": "你是 FDE 助手，能调业务服务工具"})
    agent_id = r.json()["agent_id"]
    r = client.post(f"{PROXY}/sessions/", json={"agent_id": agent_id, "chat_model_config": {
        "type": "deepseek_credential", "credential_id": cred_id,
        "model": p["model"], "parameters": {},
    }})
    session_id = r.json()["session_id"]
    print(f"[3] agent={agent_id[:8]}… session={session_id[:8]}…")

    # 4. 经反代触发 chat
    msg = {"role": "user", "name": "user",
           "content": [{"type": "text", "text": "查一下客户主数据列表，一共有多少客户？"}]}
    r = client.post(f"{PROXY}/chat/", json={"agent_id": agent_id, "session_id": session_id, "input": msg})
    print(f"[4] chat 触发: {r.json()}")

    # 5. 经反代读 SSE stream（验证流式转发）
    print("[5] 经反代订阅 SSE stream…")
    text = []
    with client.stream("GET", f"{PROXY}/sessions/{session_id}/stream",
                       params={"agent_id": agent_id}) as resp:
        for line in resp.iter_lines():
            if not line.startswith("data:"):
                continue
            import json as _j
            evt = _j.loads(line[5:].strip())
            t = evt.get("type")
            if t == "TEXT_BLOCK_DELTA":
                text.append(evt.get("delta", "") or "")
            elif t in ("TOOL_CALL_START", "REPLY_END"):
                print(f"    [{t}]", evt.get("tool_call_name") or "")
                if t == "REPLY_END":
                    break
    print("\n=== leader 回复 ===")
    print("".join(text)[:400])


if __name__ == "__main__":
    main()
