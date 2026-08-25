"""FDE v2 平台 — LLM 模型配置基座（双 Agent 独立配模型）。

系统内两个**完全独立**的 Agent，各自从按角色(role)索引的模型配置中心取模型：
- ``operator``：操作助手（agent.py 的交互式服务调用 / 跨应用编排）
- ``builder`` ：构建器（「应用组构建」/groupbuild 各步生成任务的模型档案）

设计要点：
- 每个 role 一份配置（provider / base_url / model / 参数 / 密钥），存 ``config/llm.db``；
- **密钥加密落库**（Fernet；主密钥来自 env ``LLM_MASTER_KEY``，缺则自动生成并持久到
  ``config/llm_master.key``）。亦支持 ``env:<变量名>`` 形式直接引用环境变量里的密钥；
- provider 可插拔：``openai_compat``（DeepSeek/通义/智谱/OpenAI/任意 OpenAI 兼容网关）、
  ``anthropic``（Claude 原生）。openai/anthropic/cryptography 均**惰性导入**，缺失仅在用到时报清晰错误；
- **兼容现状**：某 role 未在库里配置（或被禁用）时，回退读环境变量 ``LLM_BASE_URL/LLM_API_KEY/LLM_MODEL``
  （即现有 operator 行为），老部署无感升级；
- 统一接口 ``provider.chat(messages, tools=None) -> {"content": str, "tool_calls": list|None}``，
  与 agent.py 既有 ``_call_llm`` 返回同构。

本模块为**核心基座**，仅依赖标准库（加密/厂商 SDK 惰性导入），故可被 agent.py 直接 import；
配置页与 API 在 ``llm_admin.py``（可插拔 Blueprint），由 main.py 注册。
"""
import json
import os
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "config" / "llm.db"
MASTER_KEY_PATH = PROJECT_ROOT / "config" / "llm_master.key"

# 系统内置的两个独立 Agent 角色
ROLES = ("operator", "vision")
ROLE_LABELS = {"operator": "Agent 对话模型", "vision": "多模态兜底模型"}
ROLE_DESC = {
    "operator": "交互式调用应用服务、跨应用编排",
    "vision": "遇到图片时临时调用的视觉模型（看图转文字），默认不参与主对话",
}

# 一键载入预设：各 role 的 DeepSeek 默认配置（前端「一键载入」按钮填入，用户只需填 key）
DEEPSEEK_PRESETS = {
    "operator": {
        "provider": "openai_compat",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-pro",
        "temperature": 0.1,
    },
    "vision": {
        "provider": "openai_compat",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash-vision-exp",
        "temperature": 0.1,
    },
}

PROVIDERS = ("openai_compat", "anthropic")


class LLMInterrupted(Exception):
    """生成被外部中断（如调用方请求终止任务）。由中断钩子触发、向上传播。"""


# 外部中断钩子：chat 生成期间周期性调用，返回真值即中止本次生成（抛 LLMInterrupted）。
# 由 groupbuild_runner 注入（按任务取消标志检查）；缺省 None = 永不中断。
_INTERRUPT_CHECK = None


def set_interrupt_check(fn) -> None:
    """安装中断检查钩子（fn: () -> bool）。传 None 卸载。"""
    global _INTERRUPT_CHECK
    _INTERRUPT_CHECK = fn
PROVIDER_LABELS = {
    "openai_compat": "OpenAI 兼容（DeepSeek / 通义 / 智谱 / OpenAI / 兼容网关）",
    "anthropic": "Anthropic 协议（Claude 原生 / Anthropic 协议网关，如阿里云通义 MaaS）",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_profiles (
    role         TEXT PRIMARY KEY,
    enabled      INTEGER NOT NULL DEFAULT 1,
    provider     TEXT NOT NULL DEFAULT 'openai_compat',
    base_url     TEXT,
    model        TEXT,
    api_key_enc  TEXT,
    temperature  REAL,
    max_tokens   INTEGER,
    timeout_s    INTEGER,
    extra_json   TEXT,
    updated_by   TEXT,
    updated_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
"""


# ── DB 层 ───────────────────────────────────────────────

def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    fresh = not DB_PATH.exists() or DB_PATH.stat().st_size == 0
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    if fresh:
        conn.executescript(_SCHEMA)
        conn.commit()
    return conn


def init_schema() -> None:
    conn = get_conn()
    conn.executescript(_SCHEMA)
    conn.commit()
    conn.close()


def load_profile(role: str) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM llm_profiles WHERE role=?", (role,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def save_profile(role: str, *, provider: str, base_url: str, model: str,
                 api_key: str | None, temperature, max_tokens, timeout_s,
                 enabled: bool, extra: dict | None = None, updated_by: str | None = None) -> None:
    """写入某 role 配置。api_key：非空=加密更新；""=保持原密钥不变；None=清空密钥。"""
    if role not in ROLES:
        raise ValueError(f"未知 role：{role}")
    if provider not in PROVIDERS:
        raise ValueError(f"未知 provider：{provider}")
    conn = get_conn()
    try:
        if api_key is None:
            enc = ""
        elif api_key == "":
            row = conn.execute("SELECT api_key_enc FROM llm_profiles WHERE role=?", (role,)).fetchone()
            enc = row["api_key_enc"] if row else ""
        else:
            enc = encrypt_key(api_key)
        conn.execute(
            """INSERT INTO llm_profiles(role, enabled, provider, base_url, model, api_key_enc,
                   temperature, max_tokens, timeout_s, extra_json, updated_by, updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?, datetime('now','localtime'))
               ON CONFLICT(role) DO UPDATE SET
                   enabled=excluded.enabled, provider=excluded.provider, base_url=excluded.base_url,
                   model=excluded.model, api_key_enc=excluded.api_key_enc, temperature=excluded.temperature,
                   max_tokens=excluded.max_tokens, timeout_s=excluded.timeout_s,
                   extra_json=excluded.extra_json, updated_by=excluded.updated_by,
                   updated_at=datetime('now','localtime')""",
            (role, int(bool(enabled)), provider, (base_url or "").strip(), (model or "").strip(),
             enc, temperature, max_tokens, timeout_s, json.dumps(extra or {}, ensure_ascii=False), updated_by),
        )
        conn.commit()
    finally:
        conn.close()


# ── 密钥加密（Fernet）──────────────────────────────────

def _master_key() -> bytes:
    """主密钥：优先 env LLM_MASTER_KEY；否则自动生成并持久化到 config/llm_master.key。"""
    env = os.environ.get("LLM_MASTER_KEY", "").strip()
    if env:
        return env.encode()
    if MASTER_KEY_PATH.exists():
        return MASTER_KEY_PATH.read_bytes().strip()
    from cryptography.fernet import Fernet

    key = Fernet.generate_key()
    MASTER_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    MASTER_KEY_PATH.write_bytes(key)
    try:
        os.chmod(MASTER_KEY_PATH, 0o600)
    except OSError:  # Windows 无 POSIX 权限位
        pass
    return key


def encrypt_key(plain: str) -> str:
    """加密密钥；``env:<变量名>`` 原样保存（运行时从环境变量取，秘密不进库）。"""
    if not plain:
        return ""
    if plain.startswith("env:"):
        return plain
    from cryptography.fernet import Fernet

    return Fernet(_master_key()).encrypt(plain.encode()).decode()


def decrypt_key(stored: str) -> str:
    if not stored:
        return ""
    if stored.startswith("env:"):
        return os.environ.get(stored[4:], "").strip()
    from cryptography.fernet import Fernet

    return Fernet(_master_key()).decrypt(stored.encode()).decode()


# ── Provider ────────────────────────────────────────────

class LLMProvider:
    """统一接口：chat(messages, tools=None) -> {"content": str, "tool_calls": list|None}。"""

    def chat(self, messages: list, tools: list | None = None) -> dict:
        raise NotImplementedError


class NotConfiguredProvider(LLMProvider):
    """该 role 既无库内配置、也无环境变量回退时的优雅降级（不报错、不阻断）。"""

    def __init__(self, role: str):
        self.role = role

    def chat(self, messages: list, tools: list | None = None) -> dict:
        label = ROLE_LABELS.get(self.role, self.role)
        return {
            "content": (f"Agent「{label}」未配置 LLM。请在「大模型配置」页（/llm）为其设置模型，"
                        f"或在 config/.env 配置 LLM_BASE_URL 与 LLM_API_KEY 后重启平台。"),
            "tool_calls": None,
        }


# LLM 调用重试（网关瞬时错误/限流时退避重试，提升长时生成的健壮性）
# 可经 env 覆盖（FDE_LLM_RETRIES / FDE_LLM_BACKOFF）：测试据此把重试调成 1、退避调成 0，
# 使"不可达网关→快速降级"确定且秒回，不必等满默认退避。
_LLM_RETRIES = int(os.environ.get("FDE_LLM_RETRIES", "3"))
_LLM_BACKOFF = int(os.environ.get("FDE_LLM_BACKOFF", "8"))  # 秒，退避基数（第 n 次失败后睡 _LLM_BACKOFF*n 秒）


class OpenAICompatProvider(LLMProvider):
    """OpenAI 兼容接口（DeepSeek/通义/智谱/OpenAI/任意兼容网关）。"""

    def __init__(self, base_url: str, api_key: str, model: str,
                 temperature: float = 0.1, max_tokens: int | None = None, timeout_s: int | None = None):
        self.base_url = base_url or None
        self.api_key = api_key
        self.model = model
        self.temperature = 0.1 if temperature is None else temperature
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s

    def chat(self, messages: list, tools: list | None = None) -> dict:
        try:
            from openai import OpenAI
        except ImportError:
            return {"content": "openai 库未安装：pip install openai", "tool_calls": None}
        import time as _time
        client = OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=self.timeout_s)
        kwargs = {"model": self.model, "messages": messages, "temperature": self.temperature}
        if self.max_tokens:
            kwargs["max_tokens"] = self.max_tokens
        if tools:
            kwargs["tools"] = tools
        last_err = None
        for attempt in range(_LLM_RETRIES):
            try:
                if _INTERRUPT_CHECK and _INTERRUPT_CHECK():
                    raise LLMInterrupted("生成被外部中断")
                resp = client.chat.completions.create(**kwargs)
                choice = resp.choices[0]
                result = {"content": choice.message.content or ""}
                if choice.message.tool_calls:
                    result["tool_calls"] = [
                        {"id": tc.id, "type": "function",
                         "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                        for tc in choice.message.tool_calls
                    ]
                else:
                    result["tool_calls"] = None
                return result
            except Exception as e:
                last_err = e
                if attempt < _LLM_RETRIES - 1:
                    _time.sleep(_LLM_BACKOFF * (attempt + 1))  # 退避重试（网关瞬时错误/限流）
        return {"content": f"LLM 调用失败（重试{_LLM_RETRIES}次）：{last_err}", "tool_calls": None}


class AnthropicProvider(LLMProvider):
    """Anthropic Messages API（Claude 原生 / Anthropic 协议网关，如阿里云通义 MaaS token-plan）。

    用标准库 urllib 直连（**无需安装 anthropic SDK**）；支持自定义 base_url 以接入网关。
    OpenAI 风格 messages/tools ↔ Anthropic 格式互转见 _to_anthropic；适配「system+user→生成」
    与工具调用（tool_use/tool_result）常见路径，复杂多轮工具历史建议用 openai_compat。
    """

    DEFAULT_BASE_URL = "https://api.anthropic.com"
    ANTHROPIC_VERSION = "2023-06-01"

    def __init__(self, api_key: str, model: str, base_url: str | None = None,
                 temperature: float = 0.1, max_tokens: int | None = None, timeout_s: int | None = None):
        self.api_key = api_key
        self.model = model
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self.temperature = 0.1 if temperature is None else min(max(temperature, 0.0), 1.0)
        self.max_tokens = max_tokens or 4096  # Anthropic 必填
        self.timeout_s = timeout_s or 120

    @staticmethod
    def _convert_user_content(content):
        """OpenAI 风格 user content → Anthropic content（多模态 image_url → image block）。

        content 为 str 时原样返回；为 list（OpenAI 多模态 content parts）时逐项转换：
        text 保留、image_url 的 data URL 拆成 base64 image block。
        """
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return content
        out = []
        for part in content:
            if not isinstance(part, dict):
                continue
            ptype = part.get("type")
            if ptype == "text":
                out.append({"type": "text", "text": part.get("text", "")})
            elif ptype == "image_url":
                url = (part.get("image_url") or {}).get("url", "")
                if url.startswith("data:"):
                    meta, _, data = url.partition(",")
                    media_type = meta[len("data:"):].split(";")[0]
                    out.append({"type": "image", "source": {
                        "type": "base64", "media_type": media_type, "data": data}})
                elif url:
                    out.append({"type": "image", "source": {"type": "url", "url": url}})
        return out

    def _to_anthropic(self, messages, tools):
        system_parts, msgs = [], []
        for m in messages:
            role = m.get("role")
            if role == "system":
                system_parts.append(m.get("content", ""))
            elif role == "user":
                msgs.append({"role": "user", "content": self._convert_user_content(m.get("content", ""))})
            elif role == "assistant":
                content = []
                if m.get("content"):
                    content.append({"type": "text", "text": m["content"]})
                for tc in (m.get("tool_calls") or []):
                    fn = tc.get("function", {})
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    content.append({"type": "tool_use", "id": tc.get("id"),
                                    "name": fn.get("name"), "input": args})
                msgs.append({"role": "assistant",
                             "content": content or [{"type": "text", "text": ""}]})
            elif role == "tool":
                block = {"type": "tool_result", "tool_use_id": m.get("tool_call_id"),
                         "content": m.get("content", "")}
                if msgs and msgs[-1]["role"] == "user" and isinstance(msgs[-1]["content"], list):
                    msgs[-1]["content"].append(block)
                else:
                    msgs.append({"role": "user", "content": [block]})
        ant_tools = None
        if tools:
            ant_tools = [
                {"name": t["function"]["name"],
                 "description": t["function"].get("description", ""),
                 "input_schema": t["function"].get("parameters") or {"type": "object", "properties": {}}}
                for t in tools
            ]
        return "\n\n".join(p for p in system_parts if p), msgs, ant_tools

    def chat(self, messages: list, tools: list | None = None) -> dict:
        """Messages API 生成，**SSE 流式**读取。

        非流式下长输出（数千上万 token）的整段推理期间 HTTP 连接长时间无数据，
        中间代理 / 网关 LB 常以 504 掐断空闲连接（本功能第③/⑤步大段代码生成的主要失败源）。
        流式下分块持续到达、连接保活；timeout 作用于每次读取 → 真挂起快速失败并退避重试。
        兼容网关忽略 stream 而回整段 JSON 的情形（缓冲非 data 行回退解析）。
        返回与旧版一致：{"content": str, "tool_calls": list|None}；失败仍回
        {"content": "LLM 调用失败…"}（调用方按前缀判错）。
        """
        import time as _time
        import urllib.error
        import urllib.request

        system, msgs, ant_tools = self._to_anthropic(messages, tools)
        payload = {"model": self.model, "messages": msgs,
                   "max_tokens": self.max_tokens, "temperature": self.temperature,
                   "stream": True}
        if system:
            payload["system"] = system
        if ant_tools:
            payload["tools"] = ant_tools
        last_err = None
        for attempt in range(_LLM_RETRIES):
            req = urllib.request.Request(
                self.base_url + "/v1/messages", data=json.dumps(payload).encode(),
                headers={"x-api-key": self.api_key, "anthropic-version": self.ANTHROPIC_VERSION,
                         "content-type": "application/json", "accept": "text/event-stream"})
            text_parts, tool_calls, non_data = [], [], []
            cur_tool, cur_args = None, []     # 正在累积的 tool_use 块与其 input_json 碎片
            saw_event = False
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                    for raw in resp:          # 按行迭代；timeout 作用于每次读取
                        if _INTERRUPT_CHECK and _INTERRUPT_CHECK():
                            raise LLMInterrupted("生成被外部中断")
                        line = raw.decode("utf-8", "replace").strip()
                        if not line.startswith("data:"):
                            if line:
                                non_data.append(line)
                            continue
                        body = line[5:].strip()
                        if not body or body == "[DONE]":
                            continue
                        try:
                            ev = json.loads(body)
                        except json.JSONDecodeError:
                            continue
                        saw_event = True
                        etype = ev.get("type")
                        if etype == "content_block_start":
                            blk = ev.get("content_block") or {}
                            if blk.get("type") == "tool_use":
                                cur_tool = {"id": blk.get("id"), "name": blk.get("name")}
                                cur_args = []
                        elif etype == "content_block_delta":
                            d = ev.get("delta") or {}
                            if d.get("type") == "text_delta":
                                text_parts.append(d.get("text", ""))
                            elif d.get("type") == "input_json_delta" and cur_tool is not None:
                                cur_args.append(d.get("partial_json", ""))
                        elif etype == "content_block_stop":
                            if cur_tool is not None:
                                try:
                                    args = json.loads("".join(cur_args) or "{}")
                                except json.JSONDecodeError:
                                    args = {}
                                tool_calls.append(
                                    {"id": cur_tool.get("id"), "type": "function",
                                     "function": {"name": cur_tool.get("name"),
                                                  "arguments": json.dumps(args, ensure_ascii=False)}})
                                cur_tool, cur_args = None, []
                        elif etype == "error":
                            raise RuntimeError(str(ev.get("error") or ev)[:300])
                        # message_start / message_delta(stop_reason) / message_stop 无需处理
                if not saw_event and non_data:   # 网关忽略 stream → 整段 JSON 回退解析
                    data = json.loads("\n".join(non_data))
                    for block in data.get("content", []):
                        btype = block.get("type")
                        if btype == "text":
                            text_parts.append(block.get("text", ""))
                        elif btype == "tool_use":
                            tool_calls.append(
                                {"id": block.get("id"), "type": "function",
                                 "function": {"name": block.get("name"),
                                              "arguments": json.dumps(block.get("input", {}),
                                                                      ensure_ascii=False)}})
                if not text_parts and not tool_calls:
                    raise RuntimeError("流式响应为空（无内容块）")
                return {"content": "".join(text_parts), "tool_calls": tool_calls or None}
            except urllib.error.HTTPError as e:
                last_err = f"HTTP {e.code} {e.read().decode()[:300]}"
            except Exception as e:
                last_err = str(e)
            if attempt < _LLM_RETRIES - 1:
                _time.sleep(_LLM_BACKOFF * (attempt + 1))  # 退避重试（网关瞬时错误/限流）
        return {"content": f"LLM 调用失败（重试{_LLM_RETRIES}次）：{last_err}", "tool_calls": None}


# ── 解析 ────────────────────────────────────────────────

def _env_fallback() -> dict | None:
    """兼容现状：读全局 LLM_*（operator 历史行为）。base_url/key 缺一即视为未配置。"""
    base_url = os.environ.get("LLM_BASE_URL", "").strip()
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    model = os.environ.get("LLM_MODEL", "").strip() or "deepseek-chat"
    if not base_url or not api_key:
        return None
    return {"provider": "openai_compat", "base_url": base_url, "model": model,
            "api_key": api_key, "temperature": 0.1, "max_tokens": None, "timeout_s": None}


def get_provider(role: str) -> LLMProvider:
    """取某 role 的可用 provider：库内已启用配置 > 环境变量回退 > 未配置降级。"""
    p = load_profile(role)
    if p and p.get("enabled") and (p.get("model") or "").strip():
        api_key = decrypt_key(p.get("api_key_enc") or "")
        common = dict(api_key=api_key, model=p["model"].strip(),
                      temperature=p["temperature"] if p["temperature"] is not None else 0.1,
                      max_tokens=p["max_tokens"], timeout_s=p["timeout_s"])
        if p["provider"] == "anthropic":
            return AnthropicProvider(base_url=p.get("base_url") or "", **common)
        return OpenAICompatProvider(base_url=p.get("base_url") or "", **common)
    ep = _env_fallback()
    if ep:
        return OpenAICompatProvider(base_url=ep["base_url"], api_key=ep["api_key"], model=ep["model"],
                                    temperature=ep["temperature"], max_tokens=ep["max_tokens"],
                                    timeout_s=ep["timeout_s"])
    return NotConfiguredProvider(role)


def effective_source(role: str) -> str:
    """该 role 当前生效的模型来源（供 UI 提示）：'db' / 'env' / 'none'。"""
    p = load_profile(role)
    if p and p.get("enabled") and (p.get("model") or "").strip():
        return "db"
    if _env_fallback():
        return "env"
    return "none"


# ── 对外只读视图（绝不含密钥）──────────────────────────

def public_view(role: str) -> dict:
    p = load_profile(role)
    src = effective_source(role)
    if p:
        return {
            "role": role, "label": ROLE_LABELS.get(role, role), "desc": ROLE_DESC.get(role, ""),
            "configured": True, "enabled": bool(p["enabled"]), "provider": p["provider"],
            "base_url": p["base_url"] or "", "model": p["model"] or "",
            "temperature": p["temperature"], "max_tokens": p["max_tokens"], "timeout_s": p["timeout_s"],
            "has_key": bool(p["api_key_enc"]), "source": src, "updated_at": p["updated_at"],
        }
    return {
        "role": role, "label": ROLE_LABELS.get(role, role), "desc": ROLE_DESC.get(role, ""),
        "configured": False, "enabled": False, "provider": "openai_compat",
        "base_url": "", "model": "", "temperature": None, "max_tokens": None, "timeout_s": None,
        "has_key": False, "source": src, "updated_at": None,
    }


def list_profiles() -> list:
    return [public_view(r) for r in ROLES]


# ── 连接测试（不落库）──────────────────────────────────

def test_connection(provider: str, base_url: str, model: str, api_key: str,
                    temperature: float = 0.1, max_tokens: int | None = None,
                    timeout_s: int | None = 20, role: str | None = None) -> dict:
    """发一条 ping，返回 {ok, latency_ms, error, reply}。api_key 为空时用该 role 已存密钥。"""
    import time

    if not (api_key or "").strip() and role:
        p = load_profile(role)
        if p:
            api_key = decrypt_key(p.get("api_key_enc") or "")
    if provider == "anthropic":
        prov = AnthropicProvider(api_key=api_key, model=model, base_url=base_url,
                                 temperature=temperature, max_tokens=max_tokens or 64, timeout_s=timeout_s)
    else:
        prov = OpenAICompatProvider(base_url=base_url, api_key=api_key, model=model,
                                    temperature=temperature, max_tokens=max_tokens or 64, timeout_s=timeout_s)
    t0 = time.time()
    r = prov.chat([{"role": "user", "content": "ping"}])
    ms = int((time.time() - t0) * 1000)
    content = r.get("content") or ""
    is_err = content.startswith("LLM 调用失败") or "未安装" in content
    return {"ok": not is_err, "latency_ms": ms,
            "error": content if is_err else "", "reply": content[:120]}
