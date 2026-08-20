/* app/parts-fc/demand_release/view.js —— 毛需求发布单，加工链终点 */
import { svc, hue, fmt, dash, fmtTime, tryParse, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "demand_release",
  name: "毛需求发布",
  ic: "🚀",
  title: "毛需求发布",
  crumb: "加工链终点 · 消耗量+事件=发布量 · R版冻结·唯一出口",
  order: 110,
};

export default function pageDemandRelease() {
  const self = Alpine.reactive({
    tpl: "",
    hue, fmt,

    /* ---- 主数据 autocomplete ---- */
    partOptions: [], vehOptions: [], custOptions: [], userOptions: [], autoFiltered: [], autoShow: "", autoDisplay: {},

    async loadAutoOptions(source, field, nameField) {
      try {
        const r = await svc(source, "list", {page_size: 9999}, {quiet:true});
        const items = r.items || [];
        self.autoOptions = items;
        items.forEach(item => {
          self.autoDisplay[item[field]] = item[nameField] || item[field];
        });
      } catch { self.autoOptions = []; }
    },

    filterAuto(field, query) {
      const q = (query || "").toLowerCase();
      const src = field === "part_no" ? self.partOptions : field === "vehicle_code" ? self.vehOptions : field === "customer_code" ? self.custOptions : field === "user_code" ? self.userOptions : [];
      self.autoFiltered = src.filter(item => {
        const code = (item[field] || "").toLowerCase();
        const name = (self.autoDisplay[item[field]] || "").toLowerCase();
        return code.includes(q) || name.includes(q);
      }).slice(0, 50);
    },


    toggleAuto(showKey, dataField) {
      if (self.autoShow === showKey) { self.autoShow = ""; return; }
      self.autoShow = showKey;
      self.filterAuto(dataField || showKey, "");
    },

    selectAuto(item, formObj, field, dataField) {
      formObj[field] = item[dataField || field];
      self.autoShow = "";
    },

    openAuto(showKey, dataField) {
      self.autoShow = showKey;
      self.filterAuto(dataField || showKey, "");
    },

    /* ---- 列表 + 过滤 ---- */
    list: null,
    fStatus: "", fRelVersion: "",

    /* ---- 新建草稿 ---- */
    draftForm: { show: false, busy: false, base_period: "" },

    /* ---- 添加明细 ---- */
    lineForm: { show: false, busy: false, more: false,
      part_no: "", veh_model: "", period: "", cons_qty: "",
      event_items: "", basis: "", lineage: "", split_qty: "" },

    /* ---- 修订 ---- */
    reviseForm: { show: false, busy: false, reason: "" },

    /* ---- 详情模态 ---- */
    modalX: { open: false, loading: false, d: null },

    async init() {
      self.list = pageable(async (q) => svc("demand_release", "list", {
        rel_version: self.fRelVersion || undefined,
        status: self.fStatus || undefined,
        ...q,
      }));
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      await self.list.load();
      try { const r = await svc("md_part","list",{page_size:9999},{quiet:true}); self.partOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.part_no]=i.part_name||i.part_no}); } catch {}
      try { const r = await svc("md_vehicle","list",{page_size:9999},{quiet:true}); self.vehOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.vehicle_code]=i.vehicle_name||i.vehicle_code}); } catch {}
      try { const r = await svc("md_customer","list",{page_size:9999},{quiet:true}); self.custOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.customer_code]=i.customer_name||i.customer_code}); } catch {}
      try { const r = await svc("md_user","list",{page_size:9999},{quiet:true}); self.userOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.user_code]=i.user_name||i.user_code}); } catch {}
    },

    search() { self.list.load(1); },

    /* ---- 详情模态 ---- */
    async viewX(d) {
      self.modalX = { open: true, loading: true, d: null };
      self.lineForm.show = false;
      self.reviseForm.show = false;
      try {
        self.modalX.d = await svc("demand_release", "get", { rel_no: d.rel_no });
      } catch { self.modalX.open = false; } finally { self.modalX.loading = false; }
    },
    closeX() { self.modalX.open = false; self.lineForm.show = false; self.reviseForm.show = false; },

    /* ---- 创建草稿 ---- */
    openDraft() {
      self.draftForm = { show: true, busy: false, base_period: "" };
    },
    async submitDraft() {
      if (!self.draftForm.base_period) return toast("基准期间必填", "warn");
      self.draftForm.busy = true;
      try {
        const r = await svc("demand_release", "create_draft", { base_period: self.draftForm.base_period });
        toast(`已创建发布草稿 ${r.rel_no}`);
        self.draftForm.show = false;
        await self.list.load(1);
      } catch { /* api.js 已 toast */ } finally { self.draftForm.busy = false; }
    },

    /* ---- 添加明细 ---- */
    openLineForm() {
      self.lineForm = { show: true, busy: false, more: false,
        part_no: "", veh_model: "", period: "", cons_qty: "",
        event_items: "", basis: "", lineage: "", split_qty: "" };
    },
    async submitLine() {
      const f = self.lineForm;
      if (!f.part_no) return toast("零件号必填", "warn");
      if (!f.veh_model) return toast("车型必填", "warn");
      if (!f.period) return toast("期间必填", "warn");
      if (!f.cons_qty && f.cons_qty !== 0) return toast("消耗量必填", "warn");
      if (!f.event_items) return toast("事件项必填", "warn");
      if (!f.basis) return toast("依据必填", "warn");
      if (!f.lineage) return toast("链路线索必填", "warn");
      let eventParsed, lineageParsed, splitParsed;
      try { eventParsed = JSON.parse(f.event_items); } catch { return toast("事件项须为合法JSON", "warn"); }
      try { lineageParsed = JSON.parse(f.lineage); } catch { return toast("链路线索须为合法JSON", "warn"); }
      if (f.split_qty) { try { splitParsed = JSON.parse(f.split_qty); } catch { return toast("拆回量须为合法JSON", "warn"); } }
      f.busy = true;
      try {
        const payload = {
          rel_no: self.modalX.d.header.rel_no,
          part_no: f.part_no, veh_model: f.veh_model, period: f.period,
          cons_qty: Number(f.cons_qty),
          event_items: eventParsed, basis: f.basis, lineage: lineageParsed,
        };
        if (splitParsed) payload.split_qty = splitParsed;
        await svc("demand_release", "add_line", payload);
        toast("明细已添加");
        f.show = false;
        self.modalX.d = await svc("demand_release", "get", { rel_no: self.modalX.d.header.rel_no }).catch(() => self.modalX.d);
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { f.busy = false; }
    },

    /* ---- Checklist 校验 ---- */
    async checklistVerify(d) {
      const no = d.rel_no || (d.header && d.header.rel_no);
      try {
        const r = await svc("demand_release", "checklist_verify", { rel_no: no });
        toast(r.all_pass ? "Checklist 全部通过，状态已切换至「待发布」" : "Checklist 存在不通过项，请检查");
        if (self.modalX.open && self.modalX.d) {
          self.modalX.d = await svc("demand_release", "get", { rel_no: no });
        }
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ }
    },

    /* ---- 发布 ---- */
    async publish(d) {
      const no = d.rel_no || (d.header && d.header.rel_no);
      if (!confirm("发布后将联动锁定 D04 批次与 D03 版本，确定发布？")) return;
      try {
        await svc("demand_release", "publish", { rel_no: no });
        toast("已发布 · " + no);
        if (self.modalX.open && self.modalX.d) {
          self.modalX.d = await svc("demand_release", "get", { rel_no: no });
        }
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ }
    },

    /* ---- 修订 ---- */
    openRevise() {
      self.reviseForm = { show: true, busy: false, reason: "" };
    },
    async submitRevise() {
      if (!self.reviseForm.reason) return toast("修订原因必填", "warn");
      self.reviseForm.busy = true;
      try {
        const r = await svc("demand_release", "revise", {
          rel_no: self.modalX.d.header.rel_no,
          reason: self.reviseForm.reason,
        });
        toast(`已生成新版本 ${r.rel_no}`);
        self.reviseForm.show = false;
        self.modalX.d = await svc("demand_release", "get", { rel_no: r.rel_no || self.modalX.d.header.rel_no }).catch(() => self.modalX.d);
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { self.reviseForm.busy = false; }
    },

    /* ---- 版本比对 ---- */
    async versionDiff(d) {
      const no = d.rel_no || (d.header && d.header.rel_no);
      try {
        const diff = await svc("demand_release", "version_diff", { rel_no: no });
        toast(`版本比对完成：${diff.changes || 0} 处差异`);
      } catch { /* api.js 已 toast */ }
    },

    statusLabel(s) {
      return { "草稿": "草稿", "待发布": "待发布", "已发布": "已发布", "已替代": "已替代" }[s] || s || "—";
    },
  });
  return self;
}
