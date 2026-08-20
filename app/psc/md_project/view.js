/* app/psc/md_project/view.js（与后端 md_project.py 同文件夹） */
import { svc, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

/* 页面自描述（平台扫描的唯一入口）：key = 应用文件夹名（与后端应用名对齐）；
   order 升序 = 菜单顺序 */
export const PAGE_META = {
  key: "md_project", name: "项目台账", ic: "📁",
  title: "项目台账", crumb: "主数据 · 项目生命周期(阶段/SOP/EOP)",
  order: 40,
};

const STAGES = ["进行中", "SOP", "EOP"];
const NEXT_STAGE = { "进行中": "SOP", "SOP": "EOP", "EOP": null };

/* 简单 CSV 解析（支持引号包裹与转义），返回二维数组 */
function parseCsv(text) {
  const rows = [];
  let row = [], field = "", inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') { field += '"'; i++; }
        else inQuotes = false;
      } else field += c;
    } else if (c === '"') {
      inQuotes = true;
    } else if (c === ',') {
      row.push(field); field = "";
    } else if (c === '\n') {
      row.push(field); rows.push(row); row = []; field = "";
    } else if (c !== '\r') {
      field += c;
    }
  }
  if (field !== "" || row.length) { row.push(field); rows.push(row); }
  return rows;
}

/* CSV 文本 → import_batch 的 rows 数组（按首行表头映射到业务字段） */
function csvToRows(text) {
  const FIELDS = ["project_no", "project_name", "stage", "sop_date", "eop_date", "owner", "veh_model", "share"];
  const grid = parseCsv(text || "");
  if (!grid.length) return [];
  const headers = grid[0].map((h) => h.replace(/^﻿/, "").trim());
  return grid.slice(1)
    .filter((r) => r.some((c) => String(c).trim() !== ""))
    .map((r) => {
      const o = {};
      headers.forEach((h, i) => { if (FIELDS.includes(h)) o[h] = String(r[i] ?? "").trim(); });
      return o;
    });
}

export default function pageMdProject() {
  const self = Alpine.reactive({
    tpl: "",

    list: null,                                       // pageable 实例
    fNo: "", fName: "", fStage: "",                   // 过滤：项目号/项目名称（模糊）+ 阶段（精确）

    modalX: { open: false, loading: false, d: null }, // 详情模态

    /* 创建 / 编辑 / 阶段推进 共用表单（mode: create | edit | advance） */
    form: {
      open: false, busy: false, more: false, mode: "create",
      advanceTo: "",
      project_no: "", project_name: "", owner: "", stage: "进行中",
      sop_date: "", eop_date: "", veh_model: "", share: "",
    },

    /* 批量导入（CSV 文件或粘贴文本 → rows） */
    importForm: { open: false, busy: false, text: "", fileName: "", result: null },

    /* stage 徽章色：进行中=绿 / SOP=黄 / EOP=红（api.js HUES 未收录该枚举，本地映射） */
    stageHue(s) { return { "进行中": "green", "SOP": "amber", "EOP": "red" }[s] || "slate"; },
    nextStage(s) { return NEXT_STAGE[s] || null; },
    /* 份额 0~1 → 百分比展示（空 → —） */
    sharePct(v) { return (v === null || v === undefined || v === "") ? "—" : Math.round(Number(v) * 100) + "%"; },

    /* 编辑态 stage select 选项 = 当前阶段 + 下一阶段（无回退 / 无跳级） */
    editStageOptions() {
      const cur = self.form.stage;
      const nxt = NEXT_STAGE[cur];
      return nxt ? [cur, nxt] : [cur];
    },

    formTitle() {
      const f = self.form;
      if (f.mode === "create") return "新建项目";
      if (f.mode === "advance") return `阶段推进 · ${f.project_no} → ${f.advanceTo}`;
      return `编辑 · ${f.project_no}`;
    },

    async init() {
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      self.list = pageable(async (q) => svc("md_project", "list", {
        project_no: self.fNo || undefined,
        project_name: self.fName || undefined,
        stage: self.fStage || undefined,
        ...q,
      }));
      await self.list.load();
    },

    search() { self.list.load(1); },

    /* 详情模态：点项目号 → get 全量 6 字段 */
    async viewProject(doc) {
      self.modalX = { open: true, loading: true, d: null };
      try {
        self.modalX.d = await svc("md_project", "get", { project_no: doc.project_no });
      } catch { self.modalX.open = false; } finally { self.modalX.loading = false; }
    },
    closeModal() { self.modalX.open = false; },

    /* 详情页脚 → 表单（先关详情再开表单，避免双模态叠层） */
    editFromDetail() {
      const d = self.modalX.d;
      self.modalX.open = false;
      self.openEdit(d);
    },
    advanceFromDetail(target) {
      const d = self.modalX.d;
      self.modalX.open = false;
      self.openAdvance(d, target);
    },

    openCreate() {
      self.form = {
        open: true, busy: false, more: false, mode: "create", advanceTo: "",
        project_no: "", project_name: "", owner: "", stage: "进行中",
        sop_date: "", eop_date: "", veh_model: "", share: "",
      };
    },
    openEdit(d) {
      self.form = {
        open: true, busy: false, more: true, mode: "edit", advanceTo: "",
        project_no: d.project_no, project_name: d.project_name || "", owner: d.owner || "",
        stage: d.stage || "进行中", sop_date: d.sop_date || "", eop_date: d.eop_date || "",
        veh_model: d.veh_model || "", share: (d.share === null || d.share === undefined) ? "" : String(d.share),
      };
    },
    openAdvance(d, target) {
      self.form = {
        open: true, busy: false, more: true, mode: "advance", advanceTo: target,
        project_no: d.project_no, project_name: d.project_name || "", owner: d.owner || "",
        stage: target, sop_date: d.sop_date || "", eop_date: d.eop_date || "",
        veh_model: d.veh_model || "", share: (d.share === null || d.share === undefined) ? "" : String(d.share),
      };
    },
    closeForm() { self.form.open = false; },

    async save() {
      const f = self.form;
      if (!f.project_name || !f.owner) return toast("项目名称 / 责任销售为必填", "warn");
      if (f.mode === "create" && !f.project_no) return toast("项目号必填", "warn");
      if (f.mode === "advance" && f.advanceTo === "SOP" && !f.sop_date)
        return toast("推进到 SOP 阶段须填写 SOP 时间", "warn");
      if (f.mode === "advance" && f.advanceTo === "EOP" && !f.eop_date)
        return toast("推进到 EOP 阶段须填写 EOP 时间", "warn");
      f.busy = true;
      try {
        if (f.mode === "create") {
          await svc("md_project", "create", {
            project_no: f.project_no, project_name: f.project_name, owner: f.owner,
            stage: "进行中", sop_date: f.sop_date || undefined, eop_date: f.eop_date || undefined,
            veh_model: f.veh_model || undefined, share: f.share === "" ? undefined : f.share,
          });
          toast("项目台账创建成功");
          f.open = false;
          await self.list.load(1);
        } else {
          await svc("md_project", "update", {
            project_no: f.project_no, project_name: f.project_name, owner: f.owner,
            stage: f.stage, sop_date: f.sop_date || undefined, eop_date: f.eop_date || undefined,
            veh_model: f.veh_model || undefined, share: f.share === "" ? undefined : f.share,
          });
          toast(f.mode === "advance"
            ? `已推进至 ${f.advanceTo} · ${f.project_no}` : "项目台账更新成功");
          f.open = false;
          await self.list.load(self.list.page);
        }
      } catch { /* api.js 已 toast；表单保持打开便于修改后重试 */ } finally { f.busy = false; }
    },

    /* ---- 批量导入 ---- */
    openImport() { self.importForm = { open: true, busy: false, text: "", fileName: "", result: null }; },
    closeImport() { self.importForm.open = false; },

    onImportFile(evt) {
      const file = evt.target.files && evt.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => {
        self.importForm.text = String(reader.result || "");
        self.importForm.fileName = file.name;
      };
      reader.readAsText(file, "utf-8");
    },

    importTemplateHref() {
      const csv = "﻿project_no,project_name,stage,sop_date,eop_date,owner,veh_model,share\n"
        + "PRJ-1,项目1,进行中,,,S001,车型A,0.3\n";
      return "data:text/csv;charset=utf-8," + encodeURIComponent(csv);
    },

    async submitImport() {
      const txt = self.importForm.text.trim();
      if (!txt) return toast("请选择文件或粘贴 CSV 数据", "warn");
      const rows = csvToRows(txt);
      if (!rows.length) return toast("未解析到有效数据行", "warn");
      self.importForm.busy = true; self.importForm.result = null;
      try {
        const r = await svc("md_project", "import_batch", { rows });
        self.importForm.result = r;
        toast(`导入完成 · 成功 ${r.success} 条 / 失败 ${r.fail} 条`);
        await self.list.load(1);
      } catch { /* api.js 已 toast */ } finally { self.importForm.busy = false; }
    },
  });
  return self;
}
