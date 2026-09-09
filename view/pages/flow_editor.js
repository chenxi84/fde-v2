/* 流程编排：可视化编辑工作流（flow）——节点 + 依赖 + 条件分支/循环，落盘 _flow_*.yaml。
   三个标签：画布（拖拽节点 + 连线）/ 表单 / YAML 源码。 */
import { get, post, del, toast } from "../lib/api.js";

const OPS = ["contains", "equals", "not_empty", "empty", "gt", "lt", "gte", "lte"];
const NODE_W = 200;   // 节点卡片宽（px）
const NODE_H = 60;    // 节点卡片高（px）

function _split(v) {
  if (Array.isArray(v)) return v;
  if (!v) return [];
  return String(v).split(/[,，\s]+/).filter(Boolean);
}

function _esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
}

/* call/skill 节点的 args 编辑为 JSON 文本，保存/导出时解析；非法/空 → {} */
function _parseArgs(text) {
  if (!text || !String(text).trim()) return {};
  try {
    const v = JSON.parse(text);
    return v && typeof v === "object" ? v : {};
  } catch {
    return {};
  }
}

/* 节点类型（call=直调服务 / skill=跑技能 / agent=智能体，缺省 agent） */
const NODE_TYPES = [
  { value: "agent", label: "智能体（自然语言）" },
  { value: "call", label: "调用服务（确定性）" },
  { value: "skill", label: "执行技能（确定性）" },
];

function _jsonText(obj) {
  if (!obj || typeof obj !== "object" || Object.keys(obj).length === 0) return "";
  return JSON.stringify(obj, null, 2);
}

/* raw 节点（后端/YAML）→ 编辑态（args 转 JSON 文本，input/depends_on 转逗号串） */
function _nodeToEditing(n) {
  return {
    id: n.id || "", role: n.role || "", task: n.task || "", output: n.output || "",
    input: (n.input || []).join(", "), depends_on: (n.depends_on || []).join(", "),
    type: n.type || "agent",
    call: { service: (n.call && n.call.service) || "", args: _jsonText(n.call && n.call.args) },
    skill: { name: (n.skill && n.skill.name) || "", args: _jsonText(n.skill && n.skill.args) },
    x: n.x ?? null, y: n.y ?? null,
    when: n.when || { key: "", op: "", value: "" },
    until: n.until || { key: "", op: "", value: "" },
    max_loop: n.max_loop || "",
  };
}

/* 新建节点的默认字段（type 缺省 agent） */
function _emptyNode(over = {}) {
  return {
    id: "", role: "", task: "", output: "", input: "", depends_on: "",
    type: "agent", call: { service: "", args: "" }, skill: { name: "", args: "" },
    x: null, y: null,
    when: { key: "", op: "", value: "" },
    until: { key: "", op: "", value: "" },
    max_loop: "",
    ...over,
  };
}

/* 编辑态 → raw 节点（args JSON 文本解析成对象；agent 省略 type 字段） */
function _nodeFromEditing(n) {
  const node = {
    id: n.id.trim(), role: n.role, task: n.task, output: n.output,
    input: _split(n.input), depends_on: _split(n.depends_on),
    x: n.x ?? undefined, y: n.y ?? undefined,
    when: n.when && n.when.key ? n.when : null,
    until: n.until && n.until.key ? n.until : null,
    max_loop: n.max_loop ? Number(n.max_loop) : undefined,
  };
  const type = n.type || "agent";
  if (type !== "agent") node.type = type;
  if (type === "call") node.call = { service: (n.call.service || "").trim(), args: _parseArgs(n.call.args) };
  if (type === "skill") node.skill = { name: (n.skill.name || "").trim(), args: _parseArgs(n.skill.args) };
  return node;
}

export function pageFlowEditor() {
  const self = Alpine.reactive({
    tpl: "",
    flows: [],
    roles: [],        // 角色下拉 {type, label}
    editing: null,    // 当前编辑的 flow {group, key, name, description, nodes}
    showNew: false,
    form: { group: "", key: "", name: "", description: "" },
    ops: OPS,
    nodeTypes: NODE_TYPES,   // 节点类型下拉（agent/call/skill）
    tab: "canvas",    // canvas = 画布；form = 表单；yaml = YAML 源码
    yamlText: "",

    // 画布交互状态
    sel: null,        // 当前选中节点 index（null = 无）
    selEdge: null,    // 当前选中边 {from, to}（null = 无）
    drag: null,       // 节点拖拽 {index, dx, dy}
    pendingEdge: null,// 连线中 {from, x, y}（画布坐标）

    async init() {
      // 全局监听同步注册（先于 await，避免与 destroy 竞态后仍挂上监听）
      window.addEventListener("pointermove", self._onMove);
      window.addEventListener("pointerup", self._onUp);
      self.tpl = await fetch(new URL("flow_editor.html", import.meta.url)).then((r) => r.text());
      await Promise.all([self.load(), self.loadRoles()]);
    },

    destroy() {
      // 路由切换会销毁旧实例重建新实例：移除全局监听，避免跨实例重复触发/泄漏。
      window.removeEventListener("pointermove", self._onMove);
      window.removeEventListener("pointerup", self._onUp);
    },

    async load() {
      self.flows = (await get("/api/flows", { quiet: true }).catch(() => [])) || [];
    },

    async loadRoles() {
      const d = await get("/api/agent-overview", { quiet: true }).catch(() => null);
      self.roles = (d && d.roles) ? d.roles.map((r) => ({ type: r.type, label: r.label })) : [];
    },

    edit(f) {
      // 深拷贝 + input/depends_on 数组转逗号串（便于编辑），保留画布坐标 x/y 与节点 type。
      self.editing = {
        group: f.group, key: f.key, name: f.name, description: f.description,
        nodes: (f.nodes || []).map(_nodeToEditing),
      };
      self.showNew = false;
      self.sel = null;
      self.selEdge = null;
      self.tab = "canvas";
      self.ensureLayout();
    },

    newFlow() {
      self.editing = null;
      self.showNew = true;
      self.form = { group: window.__fdeModule || "psc", key: "", name: "", description: "" };
    },

    cancelEdit() { self.editing = null; self.showNew = false; },

    showCanvas() { self.tab = "canvas"; self.ensureLayout(); },
    showForm() { self.tab = "form"; },
    showYaml() { self.yamlText = self.toYaml(self.editing); self.tab = "yaml"; },

    addNode() {
      self.editing.nodes.push(_emptyNode());
      self.sel = self.editing.nodes.length - 1;
    },

    /* 画布：按角色 palette 加节点（自动生成唯一 id，置于现有节点下方） */
    addNodeAt(role) {
      const nodes = self.editing.nodes;
      let maxY = 40;
      nodes.forEach((n) => { if ((n.y ?? 0) > maxY) maxY = n.y; });
      let id = "node" + (nodes.length + 1), k = 2;
      while (nodes.some((m) => m.id === id)) id = "node" + (nodes.length + 1) + "_" + k++;
      nodes.push(_emptyNode({ id, role: role || "", x: 40, y: maxY + NODE_H + 24 }));
      self.sel = nodes.length - 1;
    },

    removeNode(i) {
      const n = self.editing.nodes[i];
      const id = n && n.id;
      const out = n && n.output;
      // 先关侧栏/选中态，再删数组：否则 splice 触发的中间态 render 会读到 editing.nodes[sel]=undefined
      if (self.sel === i) self.sel = null;
      else if (self.sel > i) self.sel -= 1;
      self.selEdge = null;
      self.editing.nodes.splice(i, 1);
      if (id || out) {
        self.editing.nodes.forEach((m) => {
          if (id) m.depends_on = _split(m.depends_on).filter((d) => d !== id).join(", ");
          if (out) m.input = _split(m.input).filter((k) => k !== out).join(", ");
        });
      }
    },

    roleLabel(t) { const r = self.roles.find((x) => x.type === t); return r ? r.label : t; },

    async saveNew() {
      if (!self.form.key.trim() || !self.form.name.trim()) { toast("请填 key 和 name", "warn"); return; }
      await post("/api/flows", {
        group: self.form.group.trim(), key: self.form.key.trim(),
        name: self.form.name.trim(), description: self.form.description.trim(), nodes: [],
      });
      self.showNew = false;
      await self.load();
    },

    async saveEdit() {
      const nodes = self.editing.nodes
        .filter((n) => n.id && n.id.trim())
        .map(_nodeFromEditing);
      await post("/api/flows", {
        group: self.editing.group, key: self.editing.key,
        name: self.editing.name, description: self.editing.description, nodes,
      });
      self.editing = null;
      await self.load();
    },

    async remove(f) {
      if (!confirm(`删除流程「${f.name}」？`)) return;
      await del(`/api/flows/${encodeURIComponent(f.group)}/${encodeURIComponent(f.key)}`);
      await self.load();
    },

    /* ---- YAML 源码视图 ---- */
    toYaml(e) {
      const L = [];
      L.push(`name: ${e.name}`);
      L.push(`key: ${e.key}`);
      L.push(`description: ${e.description || ""}`);
      L.push("nodes:");
      for (const n of e.nodes) {
        L.push(`  - id: ${n.id}`);
        const type = n.type || "agent";
        if (type !== "agent") L.push(`    type: ${type}`);
        if (type === "call") {
          L.push(`    call:`);
          L.push(`      service: ${n.call.service}`);
          L.push(`      args: ${JSON.stringify(_parseArgs(n.call.args))}`);
        } else if (type === "skill") {
          L.push(`    skill:`);
          L.push(`      name: ${n.skill.name}`);
          L.push(`      args: ${JSON.stringify(_parseArgs(n.skill.args))}`);
        }
        if (n.role) L.push(`    role: ${n.role}`);
        if (n.task) L.push(`    task: ${n.task}`);
        if (n.output) L.push(`    output: ${n.output}`);
        const input = _split(n.input);
        if (input.length) { L.push("    input:"); input.forEach((k) => L.push(`      - ${k}`)); }
        const deps = _split(n.depends_on);
        if (deps.length) { L.push("    depends_on:"); deps.forEach((d) => L.push(`      - ${d}`)); }
        if (n.when && n.when.key) L.push(`    when: {key: ${n.when.key}, op: ${n.when.op || "not_empty"}, value: ${n.when.value || ""}}`);
        if (n.until && n.until.key) L.push(`    until: {key: ${n.until.key}, op: ${n.until.op || "not_empty"}, value: ${n.until.value || ""}}`);
        if (n.max_loop) L.push(`    max_loop: ${n.max_loop}`);
      }
      return L.join("\n");
    },

    async saveYaml() {
      if (!self.editing) return;
      await post("/api/flows", { group: self.editing.group, yaml_text: self.yamlText });
      self.editing = null;
      self.tab = "canvas";
      await self.load();
    },

    /* ---- 画布：坐标换算 ---- */
    _canvasXY(e) {
      const el = document.querySelector(".fc-content");  // 单实例，直接查 DOM，避免 DOM 元素进 reactive
      if (!el) return { x: e.clientX, y: e.clientY };
      const r = el.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    },

    /* ---- 画布：自动布局（拓扑分层，最长路径法） ---- */
    autoLayout() {
      const nodes = self.editing.nodes;
      if (!nodes.length) return;
      const byId = {};
      nodes.forEach((n) => { if (n.id) byId[n.id] = n; });
      const deps = {};
      nodes.forEach((n) => { deps[n.id] = _split(n.depends_on).filter((d) => byId[d]); });
      const layer = {};
      let changed = true;
      while (changed) {
        changed = false;
        nodes.forEach((n) => {
          let l = 0;
          for (const d of deps[n.id]) l = Math.max(l, (layer[d] ?? 0) + 1);
          if (l !== (layer[n.id] ?? 0)) { layer[n.id] = l; changed = true; }
        });
      }
      const byLayer = {};
      nodes.forEach((n) => { (byLayer[layer[n.id] ?? 0] ||= []).push(n); });
      Object.keys(byLayer).sort((a, b) => Number(a) - Number(b)).forEach((l) => {
        byLayer[l].forEach((n, idx) => {
          n.x = 40 + Number(l) * 260;
          n.y = 40 + idx * 140;
        });
      });
    },

    ensureLayout() {
      const nodes = self.editing && self.editing.nodes;
      if (!nodes || !nodes.length) return;
      if (nodes.some((n) => n.x == null || n.y == null)) self.autoLayout();
    },

    /* ---- 画布：节点拖拽 ---- */
    dragStart(e, i) {
      const { x, y } = self._canvasXY(e);
      const n = self.editing.nodes[i];
      if (n.x == null || n.y == null) { n.x = x; n.y = y; }
      self.drag = { index: i, dx: x - n.x, dy: y - n.y };
      self.sel = i;
    },

    _onMove(e) {
      if (self.drag) {
        const d = self.drag;
        const n = self.editing.nodes[d.index];
        const { x, y } = self._canvasXY(e);
        n.x = x - d.dx;
        n.y = y - d.dy;
      }
      if (self.pendingEdge) {
        const p = self._canvasXY(e);
        self.pendingEdge.x = p.x;
        self.pendingEdge.y = p.y;
      }
    },

    _onUp(e) {
      if (self.drag) self.drag = null;
      if (self.pendingEdge) self._finishEdge(e);
    },

    /* ---- 画布：连线 ---- */
    edgeStart(e, i) {
      const p = self._canvasXY(e);
      self.pendingEdge = { from: i, x: p.x, y: p.y };
      self.sel = i;
    },

    _finishEdge(e) {
      const from = self.pendingEdge.from;
      self.pendingEdge = null;
      const { x, y } = self._canvasXY(e);
      const nodes = self.editing.nodes;
      for (let i = 0; i < nodes.length; i++) {
        if (i === from) continue;
        const n = nodes[i];
        if (x >= n.x && x <= n.x + NODE_W && y >= n.y && y <= n.y + NODE_H) {
          self.addEdge(from, i);
          return;
        }
      }
    },

    addEdge(fromIdx, toIdx) {
      const src = self.editing.nodes[fromIdx];
      const dst = self.editing.nodes[toIdx];
      if (!src || !dst || !src.id || !dst.id || src.id === dst.id) return;
      const deps = _split(dst.depends_on);
      if (!deps.includes(src.id)) deps.push(src.id);
      dst.depends_on = deps.join(", ");
      if (src.output) {  // 自动同步输入键（用户确认）
        const ins = _split(dst.input);
        if (!ins.includes(src.output)) ins.push(src.output);
        dst.input = ins.join(", ");
      }
    },

    removeEdge(fromId, toId) {
      const nodes = self.editing.nodes;
      const dst = nodes.find((m) => m.id === toId);
      const src = nodes.find((m) => m.id === fromId);
      if (dst) dst.depends_on = _split(dst.depends_on).filter((d) => d !== fromId).join(", ");
      if (dst && src && src.output) {
        dst.input = _split(dst.input).filter((k) => k !== src.output).join(", ");
      }
    },

    selectEdge(from, to) { self.selEdge = { from, to }; },
    isEdgeSel(from, to) { return self.selEdge && self.selEdge.from === from && self.selEdge.to === to; },
    removeSelEdge() {
      if (!self.selEdge) return;
      self.removeEdge(self.selEdge.from, self.selEdge.to);
      self.selEdge = null;
    },

    edgePathXY(x1, y1, x2, y2) {
      const dx = Math.max(40, Math.abs(x2 - x1) / 2);
      return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
    },

    /* 生成整段 SVG 连线标记（含 defs + 边 + 临时连线），经 x-html 注入。
       避免在 <svg> 里用 <template x-for>（Alpine 3.14 在 SVG 内克隆模板会
       触发 importNode / 循环变量 e 作用域失效的 bug）。 */
    svgEdges() {
      const nodes = (self.editing && self.editing.nodes) || [];
      const byId = {};
      nodes.forEach((n) => { if (n.id) byId[n.id] = n; });
      let out = '<defs><marker id="fc-arrow" viewBox="0 0 10 10" refX="9" refY="5"'
        + ' markerWidth="7" markerHeight="7" orient="auto">'
        + '<path d="M 0 0 L 10 5 L 0 10 z" fill="#8a94a6"></path></marker></defs>';
      nodes.forEach((n) => {
        _split(n.depends_on).forEach((dep) => {
          const src = byId[dep];
          if (!src) return;
          const d = self.edgePathXY(src.x + NODE_W, src.y + NODE_H / 2, n.x, n.y + NODE_H / 2);
          const cls = self.isEdgeSel(dep, n.id) ? "fc-edge on" : "fc-edge";
          out += `<path d="${d}" class="${cls}" data-from="${_esc(dep)}" data-to="${_esc(n.id)}" marker-end="url(#fc-arrow)"></path>`;
        });
      });
      if (self.pendingEdge) {
        const src = nodes[self.pendingEdge.from];
        if (src) {
          const d = self.edgePathXY(src.x + NODE_W, src.y + NODE_H / 2, self.pendingEdge.x, self.pendingEdge.y);
          out += `<path d="${d}" class="fc-pending"></path>`;
        }
      }
      return out;
    },

    onEdgeClick(e) {
      const p = e.target && e.target.closest ? e.target.closest("path[data-from]") : null;
      if (!p) return;
      self.selectEdge(p.getAttribute("data-from"), p.getAttribute("data-to"));
    },
  });
  return self;
}
