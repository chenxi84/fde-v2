/* app/psc/md_material/view.js（与后端 md_material.py 同文件夹）
   物料主数据：列表 / 详情 / 创建 / 编辑 / 批量导入。
   页面零鉴权：数据范围（主数据管理员增改导 / 计划员只读）由后端闸门执法。 */
import { svc, hue as baseHue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

/* 页面自描述（平台扫描的唯一入口）：key = 应用文件夹名（与后端应用名对齐）；
   order 升序 = 菜单顺序 */
export const PAGE_META = {
  key: "md_material", name: "物料主数据", ic: "⚙",
  title: "物料主数据", crumb: "主数据 · 物料属性/预测方法/库存参数",
  order: 520,
  // 列表默认只显示关键列；其余全字段列由列设置图标按需开启（CONVENTION：list 返回全字段）
  col_default_hidden: "单位货值,切线成本,生产时间,物流时间,满足率,组批窗口,基线参数,拟合版本,拟合生效",
};

/* 本应用私有状态色：公共 HUES 无「正常/EOP/停用/高/低」，此处局部补齐（不改公共层） */
const LOCAL_HUES = {
  "正常": "green", "EOP": "amber", "停用": "slate",
  "高": "red", "低": "teal",
};
const hue = (v) => LOCAL_HUES[v] || baseHue(v);

/* 各基线方法的合法参数模板（用于表单 base_params 的 placeholder 提示） */
const BASE_METHOD_PARAMS = {
  "移动平均": '{"window": 6}',
  "指数平滑": '{"alpha": 0.3, "trend": false}',
  "阶跃检测": '{"threshold": 0.3, "confirm_periods": 2, "lookback": 6}',
  "借用参考": '{"ref_material": "M12345", "scale": 1.0, "mode": "trend"}',
};

const IMPORT_HEADER =
  "material_no,material_name,status,unit_value,value_class,change_cost,prod_days,"
  + "logistics_days,change_risk,service_level,batch_window,base_method,base_params";

/* CSV 解析（支持双引号包裹含逗号字段，如 base_params JSON） */
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
    } else if (c === ",") {
      row.push(field); field = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(field); field = "";
      if (row.some((x) => x.trim() !== "")) rows.push(row);
      row = [];
    } else field += c;
  }
  row.push(field);
  if (row.some((x) => x.trim() !== "")) rows.push(row);
  return rows;
}

export default function pageMdMaterial() {
  const self = Alpine.reactive({
    tpl: "",
    hue, fmt,
    list: null,                                        // pageable 实例
    material_no: "",                                   // 物料号过滤（后端 LIKE）
    material_name: "",                                 // 物料名称过滤（后端 LIKE）
    filter: "",                                        // 状态过滤：'' 全部 / 正常 / EOP / 停用
    modalX: { open: false, loading: false, d: null },  // 详情模态
    form: { open: false, busy: false, mode: "create",  // 创建/编辑表单（status 不进表单）
      material_no: "", material_name: "",
      unit_value: "", value_class: "", change_cost: "",
      prod_days: "", logistics_days: "", change_risk: "",
      service_level: "", batch_window: "", base_method: "", base_params: "" },
    imp: { open: false, busy: false, fileName: "", rows: [], summary: null },  // 批量导入模态

    /* 数字字段：空/非法 → 空串（create 视作 None、update 可清空），否则转 Number */
    num(v) {
      if (v === "" || v === null || v === undefined) return "";
      const n = Number(v);
      return Number.isNaN(n) ? "" : n;
    },
    bpPlaceholder() {
      return BASE_METHOD_PARAMS[self.form.base_method] || "留空 = 后端按该方法默认参数落库";
    },
    bwLabel(v) {
      if (v === null || v === undefined || v === "") return "—";
      const weeks = Math.round((Number(v) / 7) * 10) / 10;
      return `${v} 天（≈ ${weeks} 周）`;
    },

    async init() {
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      self.list = pageable(async (q) => svc("md_material", "list", {
        material_no: self.material_no || undefined,
        material_name: self.material_name || undefined,
        status: self.filter || undefined,
        ...q,
      }));                                             // 闭包引用 self（代理）
      await self.list.load();
    },

    search() { self.list.load(1); },

    /* 详情模态：点物料号 → get 全量字段 + 所属项目（跨应用 md_project_part/md_project） */
    async viewX(doc) {
      self.modalX = { open: true, loading: true, d: null, projects: [] };
      try {
        self.modalX.d = await svc("md_material", "get", { material_no: doc.material_no });
        self.modalX.projects = await self.loadProjectsFor(doc.material_no);
      } catch { self.modalX.open = false; } finally { self.modalX.loading = false; }
    },
    closeModal() { self.modalX.open = false; },

    /* 物料所属项目：md_project_part.list_by_material 取映射，md_project.list 补项目名（quiet 兜底） */
    async loadProjectsFor(material_no) {
      try {
        const rows = await svc("md_project_part", "list_by_material", { material_no }, { quiet: true }) || [];
        if (!rows.length) return [];
        let projMap = {};
        try {
          const pr = await svc("md_project", "list", {}, { quiet: true });
          const items = Array.isArray(pr) ? pr : (pr && pr.items) || [];
          for (const p of items) if (p && p.project_no) projMap[p.project_no] = p;
        } catch { /* 项目信息兜底为空 */ }
        // 车型/供应份额为项目级信息，从 md_project 关联取；映射只给单车用量
        return rows.map((r) => {
          const p = projMap[r.project_no] || {};
          return {
            project_no: r.project_no,
            project_name: p.project_name || "",
            veh_model: p.veh_model || "",
            usage: r.usage,
            share: (p.share === undefined ? null : p.share),
          };
        });
      } catch { return []; }
    },
    pct(v) { return (v === null || v === undefined || v === "") ? "—" : Math.round(Number(v) * 100) + "%"; },

    /* 创建表单 */
    openCreate() {
      self.form = { open: true, busy: false, mode: "create",
        material_no: "", material_name: "",
        unit_value: "", value_class: "", change_cost: "",
        prod_days: "", logistics_days: "", change_risk: "",
        service_level: "", batch_window: "", base_method: "", base_params: "" };
    },
    closeCreate() { self.form.open = false; },

    /* 编辑表单：始终取 get 全量回填（列表行仅 6 字段，防误清空数值） */
    async openEdit(doc) {
      try {
        const d = await svc("md_material", "get", { material_no: doc.material_no });
        self.form = { open: true, busy: false, mode: "edit",
          material_no: d.material_no, material_name: d.material_name || "",
          unit_value: d.unit_value ?? "", value_class: d.value_class || "",
          change_cost: d.change_cost ?? "", prod_days: d.prod_days ?? "",
          logistics_days: d.logistics_days ?? "", change_risk: d.change_risk || "",
          service_level: d.service_level ?? "", batch_window: d.batch_window ?? "",
          base_method: d.base_method || "", base_params: d.base_params || "" };
        self.modalX.open = false;
      } catch { /* api.js 已 toast */ }
    },

    async save() {
      const f = self.form;
      if (!f.material_no || !f.material_name) return toast("物料号与物料名称必填", "warn");
      f.busy = true;
      try {
        const payload = {
          material_no: f.material_no.trim(),
          material_name: f.material_name.trim(),
          unit_value: self.num(f.unit_value),
          value_class: f.value_class,
          change_cost: self.num(f.change_cost),
          prod_days: self.num(f.prod_days),
          logistics_days: self.num(f.logistics_days),
          change_risk: f.change_risk,
          service_level: self.num(f.service_level),
          batch_window: self.num(f.batch_window),
        };
        if (f.base_method) {
          payload.base_method = f.base_method;
          payload.base_params = f.base_params;
        }
        if (f.mode === "edit") {
          await svc("md_material", "update", payload);
          toast(`物料 ${f.material_no} 更新成功`);
          f.open = false;
          await self.list.load(self.list.page);
        } else {
          await svc("md_material", "create", payload);
          toast(`物料 ${f.material_no} 创建成功`);
          f.open = false;
          await self.list.load(1);
        }
      } catch { /* api.js 已 toast；模态保持打开便于修改后重试 */ } finally { f.busy = false; }
    },

    /* 批量导入 */
    openImport() {
      self.imp = { open: true, busy: false, fileName: "", rows: [], summary: null };
    },
    closeImport() { self.imp.open = false; },

    downloadTemplate() {
      const sample = 'M10001,示例螺栓,正常,12.5,高,300,10,5,低,0.95,28,移动平均,"{""window"": 6}"';
      const csv = "﻿" + IMPORT_HEADER + "\n" + sample + "\n";
      const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "md_material_template.csv";
      a.click();
      URL.revokeObjectURL(a.href);
    },

    async onImportFile(e) {
      const file = e.target.files && e.target.files[0];
      if (!file) return;
      const text = await file.text();
      const grid = parseCsv(text);
      if (grid.length < 2) { toast("文件无数据行", "warn"); return; }
      const header = grid[0].map((h) => h.trim());
      const rows = grid.slice(1)
        .filter((cells) => cells.some((c) => c.trim() !== ""))
        .map((cells) => {
          const row = {};
          header.forEach((h, i) => { if (h) row[h] = (cells[i] ?? "").trim(); });
          return row;
        });
      self.imp.fileName = file.name;
      self.imp.rows = rows;
      self.imp.summary = null;
      e.target.value = "";                              // 允许重复选择同一文件
    },

    async doImport() {
      if (!self.imp.rows.length) return toast("请先选择文件", "warn");
      self.imp.busy = true;
      try {
        const r = await svc("md_material", "import_batch", { rows: self.imp.rows });
        self.imp.summary = r;
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { self.imp.busy = false; }
    },
  });
  return self;
}
