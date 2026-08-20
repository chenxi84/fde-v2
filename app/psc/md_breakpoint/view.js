/* app/psc/md_breakpoint/view.js —— 断点基础数据页面工厂（与后端 md_breakpoint.py 同文件夹）
   主数据页：新旧件断点切换关系（客户 × 原物料号 × 新物料号 × 切换时间）。
   服务：create / get / list / update / disable；无状态机（disabled 为软失效布尔标记）。
   trace 为跨应用服务（供 sales_forecast.calc_baseline 断点追溯），前端不主动调用。 */
import { svc, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

/* 页面自描述（平台扫描的唯一入口）：key = 应用文件夹名；order 升序 = 菜单顺序 */
export const PAGE_META = {
  key: "md_breakpoint",
  name: "断点基础数据",
  ic: "⏱",
  title: "断点基础数据",
  crumb: "主数据 · 新旧件断点切换关系",
  order: 60,
  // 断点标识(bp_id)为内部自增主键，业务价值低，默认隐藏（可经列设置图标开启）
  col_default_hidden: "断点标识",
};

export default function pageMdBreakpoint() {
  const self = Alpine.reactive({
    tpl: "",

    /* ---- 列表 + 过滤（与 md_breakpoint.list(customer_no, old_material_no, new_material_no, page, size)
            一一对应；契约无 keyword / status 参数 → 不设关键字框 / 状态 chips，禁止前端假过滤） ---- */
    list: null,
    fC: { no: "", q: "", open: false },   // 客户 autocomplete（选中即精确匹配）
    fO: { no: "", q: "", open: false },   // 原物料号 autocomplete
    fN: { no: "", q: "", open: false },   // 新物料号 autocomplete

    /* ---- 主数据（客户 + 物料；过滤条与创建/编辑表单共用同一份 options/map） ---- */
    customerOptions: [],   // [{ customer_no, customer_name }] 扁平数组
    customerMap: {},       // { customer_no: customer_name }
    materialOptions: [],   // [{ material_no, material_name }] 扁平数组
    materialMap: {},       // { material_no: material_name }

    /* ---- 详情模态 ---- */
    modalX: { open: false, loading: false, d: null },

    /* ---- 创建 / 编辑表单（create 5 参数；update 加 bp_id 只读定位键） ---- */
    form: { open: false, mode: "create", busy: false, more: false,
            bp_id: null, customer_no: "", old_material_no: "", new_material_no: "",
            switch_time: "", ecn_no: "" },
    acC: { q: "", open: false },   // 表单客户 autocomplete
    acO: { q: "", open: false },   // 表单原物料 autocomplete
    acN: { q: "", open: false },   // 表单新物料 autocomplete

    async init() {
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      // list 实例须在任何后续 await 之前同步建好（items:[]）：tpl 一旦赋值 Alpine 即注入
      // 模板并求值 list.*，若此时 list 仍为 null 会喷「reading 'items' of null」。
      self.list = pageable(async (q) => svc("md_breakpoint", "list", {
        customer_no: self.fC.no || undefined,
        old_material_no: self.fO.no || undefined,
        new_material_no: self.fN.no || undefined,
        ...q,                        // page / size
      }));
      await self.loadMaster();
      await self.list.load();
    },

    /* 主数据下拉：quiet 探测，失败不喷 toast，零值兜底 */
    async loadMaster() {
      try {
        const r = await svc("md_customer", "list", { page: 1, size: 200 }, { quiet: true });
        const rows = Array.isArray(r) ? r : (r && r.items) || [];
        self.customerOptions = rows
          .filter((c) => c && c.customer_no)
          .map((c) => ({ customer_no: c.customer_no, customer_name: c.customer_name || "" }));
        const cmap = {};
        for (const c of self.customerOptions) cmap[c.customer_no] = c.customer_name;
        self.customerMap = cmap;
      } catch { self.customerOptions = []; }
      try {
        const r = await svc("md_material", "list", { page: 1, size: 500 }, { quiet: true });
        const rows = Array.isArray(r) ? r : (r && r.items) || [];
        self.materialOptions = rows
          .filter((m) => m && m.material_no)
          .map((m) => ({ material_no: m.material_no, material_name: m.material_name || "" }));
        const mmap = {};
        for (const m of self.materialOptions) mmap[m.material_no] = m.material_name;
        self.materialMap = mmap;
      } catch { self.materialOptions = []; }
    },

    /* autocomplete 实时过滤：同时匹配代号与名称 */
    filterCustomers(q) {
      const s = (q || "").trim().toLowerCase();
      if (!s) return self.customerOptions;
      return self.customerOptions.filter((c) =>
        (c.customer_no || "").toLowerCase().includes(s) ||
        (c.customer_name || "").toLowerCase().includes(s));
    },
    filterMaterials(q) {
      const s = (q || "").trim().toLowerCase();
      if (!s) return self.materialOptions;
      return self.materialOptions.filter((m) =>
        (m.material_no || "").toLowerCase().includes(s) ||
        (m.material_name || "").toLowerCase().includes(s));
    },

    /* 名称回显（列表列 / 详情模态），未命中原样展示编号 */
    customerName(no) { return (no && self.customerMap[no]) || ""; },
    materialName(no) { return (no && self.materialMap[no]) || ""; },

    /* 过滤条选中（精确匹配 → 回第 1 页） */
    pickFCustomer(c) { self.fC.no = c.customer_no; self.fC.q = c.customer_no; self.fC.open = false; self.list.load(1); },
    pickFOld(m) { self.fO.no = m.material_no; self.fO.q = m.material_no; self.fO.open = false; self.list.load(1); },
    pickFNew(m) { self.fN.no = m.material_no; self.fN.q = m.material_no; self.fN.open = false; self.list.load(1); },

    search() { self.list.load(1); },
    resetFilters() {
      self.fC = { no: "", q: "", open: false };
      self.fO = { no: "", q: "", open: false };
      self.fN = { no: "", q: "", open: false };
      self.list.load(1);
    },

    /* ---- 详情模态（get 全字段，含已停用） ---- */
    async viewX(d) {
      self.modalX = { open: true, loading: true, d: null };
      try {
        self.modalX.d = await svc("md_breakpoint", "get", { bp_id: d.bp_id });
      } catch { self.modalX.open = false; } finally { self.modalX.loading = false; }
    },
    closeX() { self.modalX.open = false; },

    /* disabled 布尔标记 → 徽章（正常=绿 / 已停用=灰） */
    bpBadge(d) { return (d && d.disabled) ? { txt: "已停用", hue: "slate" } : { txt: "正常", hue: "green" }; },

    /* ---- 创建 / 编辑表单 ---- */
    openCreate() {
      self.form = { open: true, mode: "create", busy: false, more: false,
                    bp_id: null, customer_no: "", old_material_no: "", new_material_no: "",
                    switch_time: "", ecn_no: "" };
      self.acC = { q: "", open: false };
      self.acO = { q: "", open: false };
      self.acN = { q: "", open: false };
    },
    openEdit(d) {
      if (!d) return;
      self.form = { open: true, mode: "edit", busy: false, more: false,
                    bp_id: d.bp_id, customer_no: d.customer_no || "", old_material_no: d.old_material_no || "",
                    new_material_no: d.new_material_no || "", switch_time: d.switch_time || "",
                    ecn_no: d.ecn_no || "" };
      self.acC = { q: d.customer_no || "", open: false };
      self.acO = { q: d.old_material_no || "", open: false };
      self.acN = { q: d.new_material_no || "", open: false };
    },
    closeForm() { self.form.open = false; },

    pickFC(c) { self.form.customer_no = c.customer_no; self.acC.q = c.customer_no; self.acC.open = false; },
    pickFO(m) { self.form.old_material_no = m.material_no; self.acO.q = m.material_no; self.acO.open = false; },
    pickFN(m) { self.form.new_material_no = m.material_no; self.acN.q = m.material_no; self.acN.open = false; },

    async save() {
      const f = self.form;
      if (!f.customer_no) return toast("请选择客户", "warn");
      if (!f.old_material_no) return toast("请选择原物料号", "warn");
      if (!f.new_material_no) return toast("请选择新物料号", "warn");
      if (!f.switch_time) return toast("请选择切换时间", "warn");
      if (f.old_material_no === f.new_material_no) return toast("原物料号与新物料号不能相同", "warn");
      f.busy = true;
      try {
        if (f.mode === "edit") {
          await svc("md_breakpoint", "update", {
            bp_id: f.bp_id,
            customer_no: f.customer_no,
            old_material_no: f.old_material_no,
            new_material_no: f.new_material_no,
            switch_time: f.switch_time,
            ecn_no: f.ecn_no || undefined,
          });
          toast("断点更新成功");
          self.closeForm();
          self.closeX();
          await self.list.load(self.list.page);
        } else {
          await svc("md_breakpoint", "create", {
            customer_no: f.customer_no,
            old_material_no: f.old_material_no,
            new_material_no: f.new_material_no,
            switch_time: f.switch_time,
            ecn_no: f.ecn_no || undefined,
          });
          toast("断点创建成功");
          self.closeForm();
          self.fC = { no: "", q: "", open: false };
          self.fO = { no: "", q: "", open: false };
          self.fN = { no: "", q: "", open: false };
          await self.list.load(1);
        }
      } catch { /* 重复组合 / old=new / 物料不存在 / 组合唯一等由 api.js 统一 toast */ } finally { f.busy = false; }
    },

    /* ---- 停用（软失效，事实记录不可物理删除） ---- */
    async disable(d) {
      if (!confirm("确认停用该断点？停用后不再参与断点追溯（trace）与列表默认展示")) return;
      try {
        await svc("md_breakpoint", "disable", { bp_id: d.bp_id });
        toast(`断点已停用 · BP#${d.bp_id}`);
        if (self.modalX.open && self.modalX.d && self.modalX.d.bp_id === d.bp_id) self.modalX.open = false;
        await self.list.load(self.list.page);   // 该行因 disabled=1 从列表消失
      } catch { /* 幂等拦截「该断点已停用」等由 api.js 统一 toast */ }
    },
  });
  return self;
}
