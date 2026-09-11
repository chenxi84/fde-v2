/* 知识库：非结构化知识文件（制度/SOP/最佳实践/FAQ）管理。平台级，语义检索。
   数据 /api/knowledge（概况）+ upload/delete/index/query。 */
import { get, post, del, toast } from "../lib/api.js";

export const PAGE_META = {
  key: "knowledge",
  name: "知识库",
  ic: "📚",
  title: "知识库",
  crumb: "非结构化知识 · 语义检索",
  order: 80,
};

export function pageKnowledge() {
  const self = Alpine.reactive({
    tpl: "",
    files: [],
    index: { running: false, done: false, docs: 0, nodes: 0, edges: 0, error: "" },
    q: "",
    answer: "",
    querying: false,

    async init() {
      self.tpl = await fetch(new URL("knowledge.html", import.meta.url)).then((r) => r.text());
      await self.load();
    },

    async load() {
      const d = await get("/api/knowledge", { quiet: true }).catch(() => ({ files: [], index: {} }));
      self.files = d.files || [];
      self.index = d.index || {};
    },

    async upload(ev) {
      const f = ev.target.files && ev.target.files[0];
      if (!f) return;
      const fd = new FormData();
      fd.append("file", f);
      try {
        const r = await fetch("/api/knowledge/upload", { method: "POST", body: fd, credentials: "same-origin" });
        const j = await r.json();
        if (j.status === "ok") { toast("已上传，增量索引中"); await self.load(); }
        else toast(j.message || "上传失败", "err");
      } catch { toast("上传失败", "err"); }
      ev.target.value = "";
    },

    async remove(name) {
      if (!confirm(`删除文件「${name}」并从知识图谱移除？`)) return;
      try {
        await del("/api/knowledge/" + encodeURIComponent(name));
        await self.load();
      } catch { /* api.js 统一 toast */ }
    },

    async rebuild() {
      if (!confirm("全量重建索引会重新抽取所有文件，耗时较长，确定？")) return;
      try {
        await post("/api/knowledge/index", {});
        toast("已开始重建索引");
        setTimeout(async () => { await self.load(); }, 3000);
      } catch { /* api.js 统一 toast */ }
    },

    async doQuery() {
      if (!self.q.trim()) return toast("请输入问题", "warn");
      self.querying = true;
      self.answer = "";
      try {
        const r = await post("/api/knowledge/query", { q: self.q.trim() });
        self.answer = r.answer || "（无答案）";
      } catch { /* api.js 统一 toast */ } finally { self.querying = false; }
    },

    fmtSize(n) { return (n / 1024).toFixed(1) + " KB"; },
  });
  return self;
}
