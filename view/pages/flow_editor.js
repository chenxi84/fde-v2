/* 流程编排：可视化编辑工作流（flow）——节点 + 依赖 + 条件分支/循环，落盘 _flow_*.yaml。 */
import { get, post, del, toast } from "../lib/api.js";

const OPS = ["contains", "equals", "not_empty", "empty", "gt", "lt", "gte", "lte"];

function _split(v) {
  if (Array.isArray(v)) return v;
  if (!v) return [];
  return String(v).split(/[,，\s]+/).filter(Boolean);
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
    tab: "form",      // form = 表单编辑；yaml = YAML 源码
    yamlText: "",

    async init() {
      self.tpl = await fetch(new URL("flow_editor.html", import.meta.url)).then((r) => r.text());
      await Promise.all([self.load(), self.loadRoles()]);
    },

    async load() {
      self.flows = (await get("/api/flows", { quiet: true }).catch(() => [])) || [];
    },

    async loadRoles() {
      const d = await get("/api/agent-overview", { quiet: true }).catch(() => null);
      self.roles = (d && d.roles) ? d.roles.map((r) => ({ type: r.type, label: r.label })) : [];
    },

    edit(f) {
      // 深拷贝 + input/depends_on 数组转逗号串（便于编辑）
      self.editing = {
        group: f.group, key: f.key, name: f.name, description: f.description,
        nodes: (f.nodes || []).map((n) => ({
          id: n.id || "", role: n.role || "", task: n.task || "", output: n.output || "",
          input: (n.input || []).join(", "), depends_on: (n.depends_on || []).join(", "),
          when: n.when || { key: "", op: "", value: "" },
          until: n.until || { key: "", op: "", value: "" },
          max_loop: n.max_loop || "",
        })),
      };
      self.showNew = false;
    },

    newFlow() {
      self.editing = null;
      self.showNew = true;
      self.form = { group: window.__fdeModule || "psc", key: "", name: "", description: "" };
    },

    cancelEdit() { self.editing = null; self.showNew = false; },

    addNode() {
      self.editing.nodes.push({
        id: "", role: "", task: "", output: "", input: "", depends_on: "",
        when: { key: "", op: "", value: "" },
        until: { key: "", op: "", value: "" },
        max_loop: "",
      });
    },
    removeNode(i) { self.editing.nodes.splice(i, 1); },

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
        .map((n) => ({
          id: n.id.trim(), role: n.role, task: n.task, output: n.output,
          input: _split(n.input), depends_on: _split(n.depends_on),
          when: n.when && n.when.key ? n.when : null,
          until: n.until && n.until.key ? n.until : null,
          max_loop: n.max_loop ? Number(n.max_loop) : undefined,
        }));
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
    showYaml() { self.yamlText = self.toYaml(self.editing); self.tab = "yaml"; },
    showForm() { self.tab = "form"; },

    toYaml(e) {
      const L = [];
      L.push(`name: ${e.name}`);
      L.push(`key: ${e.key}`);
      L.push(`description: ${e.description || ""}`);
      L.push("nodes:");
      for (const n of e.nodes) {
        L.push(`  - id: ${n.id}`);
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
      self.tab = "form";
      await self.load();
    },
  });
  return self;
}
