/* Agent 右栏（平台级跨应用，复用 /api/agent2/* 端点）。
   服务级授权由后端 AgentSession 保证：工具清单 = 当前用户被授权的服务，
   执行时 fail-closed；本组件只是换个窄栏入口，不新增任何授权逻辑。 */
import { get, post, del, toast } from "../lib/api.js";

/* 工具名提取：兼容 live 扁平 {tool} 与存储历史 OpenAI 形 {function:{name}} */
function toolNameOf(t) {
  if (!t) return "";
  if (typeof t === "string") return t;
  return t.tool || (t.function && t.function.name) || t.name || "";
}
/* qualname 美化：demo__sales_order__create → sales_order.create（同后端 _tool_disp 口径） */
function toolDisp(name) {
  const parts = String(name).split("__");
  return parts.length >= 3 ? parts.slice(-2).join(".") : name;
}

export function agentRail() {
  const self = Alpine.reactive({
    tpl: "",
    sessions: [],
    sid: "",          // 空 = 未选会话（发送时自动创建）
    msgs: [],
    input: "",
    sending: false,
    progress: "",     // 「执行中」阶段文案
    live: null,       // 流式回复气泡 {content, tool_calls}
    confirm: null,    // 待人工确认的危险操作 [{id,name,input}]
    uploading: false, // 附件上传中

    /* ---- 文件面板 ---- */
    filesOpen: true,        // 面板默认自动展开
    importFiles: [],        // import-file 目录文件列表
    exportFiles: [],        // export-file 目录文件列表
    filesLoading: false,

    /* ---- 多智能体团队可见（方案 3 第一步：成员 + 最近工具，不展示结论文本）---- */
    team: null,             // { members: [{name, tools: []}] }

    async init() {
      self.tpl = await fetch(new URL("agent_rail.html", import.meta.url)).then((r) => r.text());
      await self.loadSessions();
      // 默认选中最近一次历史会话（sessions 按 updated_at 降序，[0] 即最新）；无历史则保持新对话
      if (!self.sid && self.sessions.length) self.sid = self.sessions[0].session_id;
      await self.loadMsgs();
      /* 其他页面（如流程总览）注入 prompt 并触发分析 */
      window.addEventListener("fde:agent-prompt", (e) => {
        const msg = e.detail && e.detail.message;
        if (msg) { self.input = msg; self.send(); }
      });
      /* 页面切换时刷新文件列表（shell.js 路由变化后触发） */
      window.addEventListener("fde:route-changed", () => { if (self.filesOpen) self.loadFiles(); });
      // 初始加载延迟到 window.__fdePage 稳定：shell 的 syncRoute 要等 /api/my_pages
      // 异步返回后才把 __fdePage 从初始 dashboard 更新为实际页，过早读会导致 resolveUploadApp 返回 null
      setTimeout(() => self.loadFiles(), 600);
    },

    async loadSessions() {
      self.sessions = (await get("/api/agent2/sessions").catch(() => [])) || [];
    },

    async loadMsgs() {
      if (self.sending) return;   // 发送中不覆盖，避免首次对话「select 触发 change→loadMsgs」竞态清空消息区
      if (!self.sid) { self.msgs = []; return; }
      const r = await get(`/api/agent2/sessions/${encodeURIComponent(self.sid)}/messages`,
        { quiet: true }).catch(() => []);
      self.msgs = self.toDisplayMsgs(r || []);
      self.scrollEnd();
    },

    /* 存储历史（OpenAI 对话格式）→ 展示消息：过滤 system/tool；tool_calls 规整为服务名；
       无正文的工具调用轮并入最近 reply 气泡（与整页 Agent 同形）。 */
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
        const el = document.querySelector(".agent-rail .chatbox");
        if (el) el.scrollTop = el.scrollHeight;
      }, 30);
    },

    visible(m) { return m.role === "user" || m.role === "assistant"; },

    async send() {
      const m = self.input.trim();
      if (!m || self.sending) return;
      self.input = "";
      self.sending = true;
      self.progress = "思考中…";
      self.live = { content: "", tool_calls: [] };
      self.confirm = null;
      const tools = [];
      try {
        if (!self.sid) {
          const s = await post("/api/agent2/sessions", {});
          self.sid = s.session_id;
          await self.loadSessions();
        }
        self.msgs.push({ role: "user", content: m });
        self.scrollEnd();
        const sid = self.sid;
        const onEvent = (evt) => {
          if (evt.event === "delta") { self.live.content += evt.data; }
          else if (evt.event === "tool") {
            tools.push(toolDisp(evt.data));
            self.live.tool_calls = [...tools];
            self.progress = `正在调用 ${toolDisp(evt.data)}`;
          }
          else if (evt.event === "done") {
            self.live.content = evt.data || self.live.content;
            self.live.tool_calls = tools;
          }
          else if (evt.event === "error" && !self.live.content) {
            self.live.content = "⚠ " + evt.data;
          }
          else if (evt.event === "confirm_required") {
            self.confirm = evt.data;  // 停车，等人工确认
          }
          self.scrollEnd();
        };
        await this.streamRequest("/api/agent2/chat/stream", { message: m, session_id: sid }, onEvent);
        // HITL：危险操作需人工确认，确认/拒绝后继续（可多轮）
        while (self.confirm) {
          const names = self.confirm.map(c => c.name).join("\n");
          const ok = window.confirm("⚠ Agent 请求执行以下操作（需人工确认）：\n" + names +
            "\n\n「确定」= 确认执行；「取消」= 拒绝。");
          const decisions = self.confirm.map(c => ({ id: c.id, confirmed: ok }));
          self.confirm = null;
          await this.streamRequest("/api/agent2/confirm", { session_id: sid, decisions }, onEvent);
        }
        self.progress = "";
        this.commitLive();
        await self.loadSessions();
        // 多智能体：leader 收敛后，加载 team 成员 + 各 worker 最近工具（状态可见）
        if (sid) this.loadTeam(sid);
      } catch (e) {
        self.progress = "";
        if (self.live && !self.live.content) self.live.content = "⚠ 请求失败，请重试";
        this.commitLive();
      } finally {
        self.sending = false;
        self.scrollEnd();
      }
    },

    /* POST SSE 流式读取：逐帧解析 data: {...} 并回调。 */
    async streamRequest(url, payload, onEvent) {
      const resp = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!resp.ok || !resp.body) throw new Error("HTTP " + resp.status);
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf("\n\n")) >= 0) {
          const frame = buf.slice(0, idx).trim();
          buf = buf.slice(idx + 2);
          if (!frame.startsWith("data:")) continue;
          let evt;
          try { evt = JSON.parse(frame.slice(5).trim()); } catch { continue; }
          onEvent(evt);
        }
      }
    },

    /* 把流式 live 气泡落为一条历史消息（快照，避免引用 live 反应式对象导致渲染丢失） */
    commitLive() {
      if (!self.live) return;
      const content = self.live.content || "";
      const tools = (self.live.tool_calls || []).filter(Boolean);
      self.msgs.push({
        role: "assistant",
        content,
        tool_calls: tools.length ? [...tools] : undefined,
      });
      self.live = null;
    },

    async newSession() {
      const r = await post("/api/agent2/sessions", {});
      self.sid = r.session_id;
      self.msgs = [];
      self.progress = "";
      await self.loadSessions();
    },

    async onSessionChange() { await self.loadMsgs(); },

    async delSession() {
      if (!self.sid) return;
      if (!confirm("删除当前会话及其全部历史？")) return;
      await del(`/api/agent2/sessions/${encodeURIComponent(self.sid)}`).catch(() => {});
      self.sid = "";
      self.msgs = [];
      self.progress = "";
      await self.loadSessions();
    },

    /* ---- 附件上传（跟随当前页应用 → resource/import-file/） ---- */

    /* 从 window.__fdePage 解析目标应用 qualname（如 psc:md_customer → psc/md_customer）。
       仅「有后端应用」的页面可上传（bootShell 标记的 __fdeAppPages）；组级聚合页（如流程总览
       process）/ 平台页 / 首页均无对应应用，返回 null。 */
    resolveUploadApp() {
      const page = window.__fdePage || "";
      const apps = window.__fdeAppPages;
      if (!apps || !apps.has(page)) return null;
      const idx = page.indexOf(":");
      if (idx < 0) return null;
      const grp = page.slice(0, idx);
      const key = page.slice(idx + 1);
      if (!grp || !key) return null;
      return `${grp}/${key}`;
    },

    /* 触发隐藏 file input */
    attachFile() {
      const el = document.getElementById("agent-rail-file");
      if (el) el.click();
    },

    /* 文件选择 → 逐个上传到目标应用 resource/import-file/；成功后注入消息 + 预填解析导入提示 */
    async onAttachChange(evt) {
      const files = evt.target && evt.target.files;
      if (!files || !files.length) return;
      const target = self.resolveUploadApp();
      if (!target) {
        toast("当前页面没有对应的数据应用（附件只能上传到具体应用）。请先进入某个应用页，如「客户主数据」「销售预测」，再上传附件。", "warn");
        evt.target.value = "";
        return;
      }
      self.uploading = true;
      const uploaded = [];
      try {
        for (const f of files) {
          const fd = new FormData();
          fd.append("files", f);
          const r = await fetch(`/api/apps/${target}/files`, { method: "POST", body: fd });
          const j = await r.json().catch(() => ({}));
          if (!r.ok || j.status === "error") {
            throw new Error(j.message || `上传失败（HTTP ${r.status}）`);
          }
          uploaded.push(f.name);
        }
        const names = uploaded.join("、");
        self.msgs.push({ role: "assistant", content: `📎 已上传附件：${names} → ${target}/resource/import-file/` });
        self.input = `请读取 ${names}（${target}/resource/import-file/）解析内容，并按该应用的导入服务导入数据`;
        self.scrollEnd();
        if (self.filesOpen) self.loadFiles();  // 文件面板展开时同步刷新
      } catch (e) {
        toast((e && e.message) || "上传失败", "err");
      } finally {
        self.uploading = false;
        evt.target.value = "";
      }
    },

    /* ---- 文件面板 ---- */

    toggleFiles() {
      self.filesOpen = !self.filesOpen;
      if (self.filesOpen) self.loadFiles();
    },

    /* 同时加载 import-file / export-file 两个目录 */
    async loadFiles() {
      const app = self.resolveUploadApp();
      if (!app) { self.importFiles = []; self.exportFiles = []; return; }
      self.filesLoading = true;
      try {
        const [imp, exp] = await Promise.all([
          get(`/api/apps/${app}/files?directory=import-file`, { quiet: true }).catch(() => null),
          get(`/api/apps/${app}/files?directory=export-file`, { quiet: true }).catch(() => null),
        ]);
        // get() 已解包 .data：返回即 {directory, count, files}
        self.importFiles = (imp && imp.files) || [];
        self.exportFiles = (exp && exp.files) || [];
      } catch {
        self.importFiles = []; self.exportFiles = [];
      } finally {
        self.filesLoading = false;
      }
    },

    async deleteFile(dir, name) {
      const app = self.resolveUploadApp();
      if (!app) return;
      if (!confirm(`删除 ${dir}/${name}？`)) return;
      try {
        await del(`/api/apps/${app}/files/${dir}/${encodeURIComponent(name)}`);
        await self.loadFiles();
      } catch { /* api.js 统一 toast */ }
    },

    /* 文件面板内的上传（复用 onAttachChange 逻辑，上传后刷新列表） */
    async onFileUpload(evt) {
      const files = evt.target && evt.target.files;
      if (!files || !files.length) return;
      const target = self.resolveUploadApp();
      if (!target) { toast("当前页面没有对应的数据应用", "warn"); evt.target.value = ""; return; }
      self.uploading = true;
      try {
        const fd = new FormData();
        for (const f of files) fd.append("files", f);
        const r = await fetch(`/api/apps/${target}/files`, { method: "POST", body: fd });
        const j = await r.json().catch(() => ({}));
        if (!r.ok || j.status === "error") throw new Error(j.message || `上传失败（HTTP ${r.status}）`);
        toast(`已上传 ${((j.data || []).length || files.length)} 个文件`);
        await self.loadFiles();
      } catch (e) {
        toast((e && e.message) || "上传失败", "err");
      } finally {
        self.uploading = false;
        evt.target.value = "";
      }
    },

    /* ---- 多智能体团队可见（方案 3 第一步）---- */

    /* 加载当前会话的 team 成员 + 各 worker 最近工具调用。
       只展示「谁 + 调了什么工具」，不展示结论文本（避免与 leader 收敛报告重复）。 */
    async loadTeam(sid) {
      if (!sid) { self.team = null; return; }
      const sessions = await get("/api/agent2/sessions", { quiet: true }).catch(() => []);
      const cur = (sessions || []).find((s) => s.session_id === sid);
      if (!cur || !cur.team || !cur.team.members || !cur.team.members.length) {
        self.team = null;
        return;
      }
      const members = [];
      for (const m of cur.team.members) {
        const tools = await this.collectWorkerTools(m);
        members.push({ name: m.name, tools });
      }
      self.team = { members };
    },

    /* 读单个 worker 的历史，提取其调用过的工具名 */
    async collectWorkerTools(member) {
      const msgs = await get(
        `/api/agent2/sessions/${encodeURIComponent(member.session_id)}/messages?agent_id=${encodeURIComponent(member.agent_id)}`,
        { quiet: true }).catch(() => null);
      const tools = [];
      for (const m of (msgs || [])) {
        if (m && m.role === "assistant") {
          for (const tc of (m.tool_calls || [])) {
            const name = (tc && tc.function && tc.function.name) || (tc && tc.name) || "";
            if (name) tools.push(toolDisp(name));
          }
        }
      }
      return tools;
    },

    /* 文件大小人可读格式 */
    fmtSize(b) {
      if (b == null) return "";
      if (b < 1024) return b + " B";
      if (b < 1024 * 1024) return (b / 1024).toFixed(1) + " KB";
      return (b / (1024 * 1024)).toFixed(1) + " MB";
    },

    /* mtime（秒级 unix timestamp）→ YYYY-MM-DD HH:mm */
    fmtTime(t) {
      if (!t) return "";
      const d = new Date(t * 1000);
      const p = (n) => String(n).padStart(2, "0");
      return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
    },

    /* 当前页是否有关联应用（控制文件面板可用性） */
    get hasApp() { return !!self.resolveUploadApp(); },
  });
  return self;
}
