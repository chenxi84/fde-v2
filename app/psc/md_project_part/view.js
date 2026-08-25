/* app/psc/md_project_part/view.js —— 项目零件映射（主数据映射页，与后端 md_project_part.py 同文件夹）
   复合主键 project_no + material_no；量纲（veh_model / usage / share）随项目阶段隐式演进。
   契约：create / get / list / update / import_batch（无 delete / set_*，无状态机，无审计字段）。 */
import { svc, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

/* 页面自描述（平台扫描的唯一入口）：key = 应用文件夹名；order 升序 = 菜单顺序 */
export const PAGE_META = {
  key: "md_project_part",
  name: "项目零件映射",
  ic: "🔗",
  title: "项目零件映射",
  crumb: "主数据 · 项目×零件量纲(单车用量/份额)",
  order: 540,
};

/* 供应份额百分比格式化：0.8 → 80% */
function pct(v) {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  if (Number.isNaN(n)) return "—";
  return (n * 100).toLocaleString("zh-CN", { maximumFractionDigits: 2 }) + "%";
}

export default function pageMdProjectPart() {
  const self = Alpine.reactive({
    tpl: "",
    fmt, pct,                        // 展示工具（dash / fmtTime / tryParse 为 window 全局，模板直接用）

    /* ---- 列表 + 过滤（md_project_part.list(project_no, material_no, page, size) 一一对应；
            无 keyword 参数 → 不设关键字搜索，禁止前端假过滤） ---- */
    list: null,
    fProject: "", fMaterial: "",

    /* ---- 主数据（autocomplete 选项 + 编码→名称映射，各用独立扁平数组，勿嵌套） ---- */
    projectOptions: [], projectMap: {},
    materialOptions: [], materialMap: {},

    /* ---- autocomplete 展开 / 查询态 ---- */
    projOpen: false, projQuery: "",
    matOpen: false, matQuery: "",

    /* ---- 详情模态 ---- */
    modalX: { open: false, loading: false, d: null },

    /* ---- 创建 / 编辑表单（复用；edit 态复合主键锁定） ---- */
    form: { open: false, mode: "create", busy: false,
            project_no: "", material_no: "", usage: "" },

    /* ---- 批量导入模态 ---- */
    imp: { open: false, busy: false, text: "", result: null },

    async init() {
      /* list 实例须在首个 await 之前同步建好（items:[]），否则 tpl 注入后求值 list.* 报 null */
      self.list = pageable(async (q) => svc("md_project_part", "list", {
        project_no: self.fProject || undefined,
        material_no: self.fMaterial || undefined,
        ...q,                        // page / size
      }));
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      self.loadProjects();           // quiet 探测，失败零值兜底（跨应用派生边：md_project.list）
      self.loadMaterials();          // 同上（md_material.list）
      await self.list.load();
    },

    /* 项目主数据：quiet 探测、加载全量（不截断，供前端搜索覆盖几百+），构建 projectOptions + projectMap */
    async loadProjects() {
      try {
        const r = await svc("md_project", "list", {}, { quiet: true });
        const rows = Array.isArray(r) ? r : (r && r.items) || [];
        self.projectOptions = rows;
        const map = {};
        for (const p of rows) if (p && p.project_no) map[p.project_no] = p.project_name || "";
        self.projectMap = map;
      } catch { /* 兜底：下拉显示「暂无可选项目」 */ }
    },

    /* 车型/供应份额不存映射表，按 project_no 关联项目主数据取（项目级信息单一来源） */
    proj(no) { return (self.projectOptions || []).find((p) => p && p.project_no === no) || null; },
    projVeh(no) { const p = self.proj(no); return p ? p.veh_model : ""; },
    projShare(no) { const p = self.proj(no); return p ? p.share : null; },

    /* 物料主数据：quiet 探测、加载全量，构建 materialOptions + materialMap */
    async loadMaterials() {
      try {
        const r = await svc("md_material", "list", {}, { quiet: true });
        const rows = Array.isArray(r) ? r : (r && r.items) || [];
        self.materialOptions = rows;
        const map = {};
        for (const m of rows) if (m && m.material_no) map[m.material_no] = m.material_name || "";
        self.materialMap = map;
      } catch { /* 兜底：下拉显示「暂无可选物料」 */ }
    },

    /* autocomplete 过滤（同时匹配编码与名称） */
    get filteredProjects() {
      const q = (self.projQuery || "").toLowerCase();
      if (!q) return self.projectOptions;
      return self.projectOptions.filter((p) =>
        (p.project_no || "").toLowerCase().includes(q) ||
        (p.project_name || "").toLowerCase().includes(q));
    },
    get filteredMaterials() {
      const q = (self.matQuery || "").toLowerCase();
      if (!q) return self.materialOptions;
      return self.materialOptions.filter((m) =>
        (m.material_no || "").toLowerCase().includes(q) ||
        (m.material_name || "").toLowerCase().includes(q));
    },

    selectProject(p) {
      self.form.project_no = p.project_no;
      self.projQuery = p.project_no;
      self.projOpen = false;
    },
    selectMaterial(m) {
      self.form.material_no = m.material_no;
      self.matQuery = m.material_no;
      self.matOpen = false;
    },
    /* 手动输入即视为重选：清空已选，杜绝「输入了却没选中」的陈旧残留 */
    onProjInput() { self.projOpen = true; self.form.project_no = ""; },
    onMatInput() { self.matOpen = true; self.form.material_no = ""; },

    /* ---- 过滤 / 分页 ---- */
    search() { self.list.load(1); },
    resetFilters() {
      self.fProject = ""; self.fMaterial = ""; self.fVeh = "";
      self.list.load(1);
    },

    /* ---- 详情模态 ---- */
    async viewX(d) {
      self.modalX = { open: true, loading: true, d: null };
      try {
        self.modalX.d = await svc("md_project_part", "get", {
          project_no: d.project_no, material_no: d.material_no,
        });
      } catch { self.modalX.open = false; } finally { self.modalX.loading = false; }
    },
    closeX() { self.modalX.open = false; },

    /* ---- 创建 / 编辑表单 ---- */
    openCreate() {
      self.form = { open: true, mode: "create", busy: false,
                    project_no: "", material_no: "", usage: "" };
      self.projOpen = false; self.projQuery = "";
      self.matOpen = false; self.matQuery = "";
    },
    openEdit(d) {
      if (!d) return;
      self.form = { open: true, mode: "edit", busy: false,
                    project_no: d.project_no, material_no: d.material_no,
                    usage: d.usage != null ? String(d.usage) : "" };
      self.projOpen = false; self.projQuery = d.project_no;
      self.matOpen = false; self.matQuery = d.material_no;
      self.modalX.open = false;      // 从详情发起编辑时收起详情
    },
    closeForm() { self.form.open = false; },

    async save() {
      const f = self.form;
      if (!f.project_no) return toast("请选择项目", "warn");
      if (!f.material_no) return toast("请选择物料", "warn");
      if (f.usage === "" || f.usage == null) return toast("请填写单车用量", "warn");
      if (!Number.isInteger(Number(f.usage))) return toast("单车用量须为整数", "warn");
      if (Number(f.usage) <= 0) return toast("单车用量须大于0", "warn");
      f.busy = true;
      try {
        const payload = {
          project_no: f.project_no,
          material_no: f.material_no,
          usage: parseFloat(f.usage),
        };
        if (f.mode === "edit") {
          await svc("md_project_part", "update", payload);
          toast("映射更新成功");
          self.form.open = false;
          await self.list.load(self.list.page);
        } else {
          await svc("md_project_part", "create", payload);
          toast("项目零件映射创建成功");
          self.form.open = false;
          self.resetFilters();
        }
      } catch { /* FdeError（重复/引用不存在/范围非法）由 api.js 统一 toast，模态保持打开 */ }
      finally { f.busy = false; }
    },

    /* ---- 批量导入（upsert：逐行校验，失败行返回错误明细） ---- */
    openImport() {
      self.imp = { open: true, busy: false, text: "", result: null };
    },
    closeImport() {
      const imported = !!self.imp.result;
      self.imp.open = false;
      self.imp.result = null;
      if (imported) self.list.load(self.list.page);
    },
    downloadTemplate() {
      const csv = "project_no,material_no,usage\nPRJ-1,M1,1\n";
      const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "项目零件映射导入模板.csv";
      a.click();
      URL.revokeObjectURL(a.href);
    },
    onImportFile(ev) {
      const file = ev.target.files && ev.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => { self.imp.text = String(reader.result || ""); };
      reader.readAsText(file, "utf-8");
    },
    parseImportRows() {
      const text = (self.imp.text || "").replace(/^﻿/, "");
      const rows = [];
      for (const line of text.split(/\r?\n/)) {
        const s = line.trim();
        if (!s) continue;
        if (/^project_no\s*[,，\t]/.test(s)) continue;   // 跳过表头
        const parts = s.split(/[,，\t]/).map((x) => x.trim());
        if (parts.length < 3) continue;
        const [project_no, material_no, u] = parts;
        const un = parseFloat(u);
        rows.push({
          project_no, material_no,
          usage: Number.isNaN(un) ? undefined : un,
        });
      }
      return rows;
    },
    async runImport() {
      const rows = self.parseImportRows();
      if (!rows.length) return toast("请粘贴或上传至少一行数据", "warn");
      self.imp.busy = true;
      try {
        self.imp.result = await svc("md_project_part", "import_batch", { rows });
      } catch { /* api.js 统一 toast */ } finally { self.imp.busy = false; }
    },
  });
  return self;
}
