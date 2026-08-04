/* 平台 Agent：跨应用对话式编排（含会话历史） */
import { get, post, del } from "../lib/api.js";

/* 工具名提取：兼容两种形态——
   live 返回的扁平 tool_log 项 {tool, args, result} 与
   存储历史的 OpenAI 形态 {id, function:{name, arguments}} */
function toolNameOf(t) {
  if (!t) return "";
  if (typeof t === "string") return t;
  return t.tool || (t.function && t.function.name) || t.name || "";
}

/* qualname 美化：demo03__sales_order__create → sales_order.create（同后端 _tool_disp 口径） */
function toolDisp(name) {
  const parts = String(name).split("__");
  return parts.length >= 3 ? parts.slice(-2).join(".") : name;
}

export function pageAgent() {
  const self = Alpine.reactive({
    tpl: "",
    sessions: [],
    sid: "",          // 空 = 未选择会话（此时发送会自动创建新会话）
    msgs: [],
    input: "",
    sending: false,

    async init() {
      self.tpl = await fetch(new URL("agent.html", import.meta.url)).then((r) => r.text());
      await self.loadSessions();
      await self.loadMsgs();
    },

    async loadSessions() {
      self.sessions = (await get("/api/agent/sessions").catch(() => [])) || [];
    },

    async loadMsgs() {
      // 未选会话 → 空对话区（首条消息发送时自动创建新会话并建档）
      if (!self.sid) { self.msgs = []; return; }
      const r = await get(`/api/agent/sessions/${encodeURIComponent(self.sid)}/messages`,
        { quiet: true }).catch(() => []);
      self.msgs = self.toDisplayMsgs(r || []);
      self.scrollEnd();
    },

    /* 存储历史（OpenAI 对话格式，含 role=tool 应答）→ 展示消息：
       ① 过滤 system / tool（工具应答原文不入气泡）；
       ② tool_calls 规整为服务名字符串（兼容两种形态，防 [object Object]）；
       ③ 无正文的工具调用轮并入最近的 reply 气泡（与 live 路径同形：一个回复气泡带全部工具 chips）。 */
    toDisplayMsgs(raw) {
      const out = [];
      let pending = [];
      const flushPending = () => {
        if (pending.length) {
          out.push({ role: "assistant", content: "", tool_calls: pending });
          pending = [];
        }
      };
      for (const m of raw || []) {
        if (!m || m.role === "system" || m.role === "tool") continue;
        if (m.role === "user") {
          flushPending();
          out.push({ role: "user", content: m.content || "" });
          continue;
        }
        pending.push(...(m.tool_calls || []).map(toolNameOf).filter(Boolean).map(toolDisp));
        if ((m.content || "").trim()) {
          out.push({ role: "assistant", content: m.content, tool_calls: pending });
          pending = [];
        }
      }
      flushPending();
      return out;
    },

    scrollEnd() {
      setTimeout(() => {
        const el = document.querySelector(".chatbox");
        if (el) el.scrollTop = el.scrollHeight;
      }, 30);
    },

    visible(m) { return m.role === "user" || m.role === "assistant"; },

    async send() {
      const m = self.input.trim();
      if (!m || self.sending) return;
      self.input = "";
      self.sending = true;
      try {
        if (!self.sid) {                    // 未选会话：发送即开启新会话
          const s = await post("/api/agent/sessions", {});
          self.sid = s.session_id;
          await self.loadSessions();
        }
        self.msgs.push({ role: "user", content: m });
        self.scrollEnd();
        const r = await post("/api/agent/chat", { message: m, session_id: self.sid });
        const names = (r.tool_calls || []).map(toolNameOf).filter(Boolean).map(toolDisp);
        self.msgs.push({
          role: "assistant",
          content: r.reply || "",
          tool_calls: names.length ? names : undefined,
        });
        await self.loadSessions();
      } catch { /* toast 已提示 */ } finally {
        self.sending = false;
        self.scrollEnd();
      }
    },

    async newSession() {
      const r = await post("/api/agent/sessions", {});
      self.sid = r.session_id;
      self.msgs = [];
      await self.loadSessions();
    },

    async pickSession(s) {
      self.sid = s.session_id;
      await self.loadMsgs();
    },

    async delSession(s, $event) {
      $event.stopPropagation();
      if (!confirm(`删除会话「${s.title || "新对话"}」？`)) return;
      await del(`/api/agent/sessions/${encodeURIComponent(s.session_id)}`).catch(() => {});
      if (self.sid === s.session_id) { self.sid = ""; self.msgs = []; await self.loadMsgs(); }
      await self.loadSessions();
    },
  });
  return self;
}
