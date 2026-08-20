/* app/psc/demand_pool/view.js —— 需求池（补库单）页面工厂（与后端 demand_pool.py 同文件夹）
   自动参考创建：无创建表单，create 由库存推移表击穿水位线跨应用触发（非手工新建）；
   状态机单向下发 + ERP 回传闭环：release（待下达→已下达）/ cancel（待下达·已下达→已取消）用户触发，
   on_workorder_started / on_inbound 为 ERP 回传，前端仅展示不主动调用；
   契约无 update / set_* / import_batch / delete → 无编辑 / 删除 / 批量导入入口。 */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

/* 页面自描述（平台扫描的唯一入口）：key = 应用文件夹名；order 升序 = 菜单顺序 */
export const PAGE_META = {
  key: "demand_pool",
  name: "需求池",
  ic: "🛠",
  title: "需求池",
  crumb: "三类补库单 · 待下达→已下达→生产中→已完成/已取消",
  order: 150,
};

export default function pageDemandPool() {
  const self = Alpine.reactive({
    tpl: "",
    hue, fmt,                        // 展示工具（dash / fmtTime / tryParse 为 window 全局，模板直接用）

    /* ---- 列表 + 过滤（与 demand_pool.list(material_no, replenish_type, status, page, size) 一一对应；
            契约无 keyword → 不设关键字搜索框，禁止前端假过滤） ---- */
    list: null,
    fMaterial: "",                   // material_no（来自 md_material.list autocomplete，精确匹配）
    fType: "",                       // 全部 / 缺货补库 / 最低库存补库 / 安全库存补库
    fStatus: "",                     // 全部 / 待下达 / 已下达 / 生产中 / 已完成 / 已取消

    /* ---- 物料主数据 autocomplete（过滤条内联下拉，主数据引用铁律 BR-08） ---- */
    materialOptions: [],             // 扁平数组 [{material_no, material_name, ...}]，禁止嵌套对象
    materialMap: {},                 // { material_no: material_name }，供列表列与详情物料名回显
    materialQuery: "",               // 下拉输入过滤关键词（匹配 material_no 与 material_name）
    materialOpen: false,             // 下拉展开态

    /* ---- 详情模态 ---- */
    modalX: { open: false, loading: false, d: null },

    /* ---- 下达确认对话框（release 可选回填 promised_inbound） ---- */
    releaseForm: { open: false, busy: false, replenish_no: "", promised_inbound: "" },
    /* ---- 取消确认对话框 ---- */
    cancelForm: { open: false, busy: false, replenish_no: "" },

    async init() {
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      // list 实例须在任何后续 await 之前同步建好（items:[]）：tpl 一旦赋值 Alpine 即注入
      // 模板并求值 list.*，若此时 list 仍为 null 会喷「reading 'items' of null」。
      self.list = pageable(async (q) => svc("demand_pool", "list", {
        material_no: self.fMaterial || undefined,
        replenish_type: self.fType || undefined,
        status: self.fStatus || undefined,
        ...q,                        // page / size（契约 string 型，照传）
      }));
      await self.loadMaterials();    // 备齐物料名映射，再拉列表数据
      await self.list.load();
    },

    /* 物料下拉数据源：quiet 探测，失败不喷 toast，零值兜底（过滤下拉仅「全部」） */
    async loadMaterials() {
      try {
        const r = await svc("md_material", "list", { page: 1, size: 200 }, { quiet: true });
        const rows = Array.isArray(r) ? r : (r && r.items) || [];
        self.materialOptions = rows;
        const map = {};
        for (const m of rows) if (m && m.material_no) map[m.material_no] = m.material_name || m.material_no;
        self.materialMap = map;
      } catch { /* 失败兜底：列表物料名不显示、下拉为空 */ }
    },

    /* 过滤物料号与物料名（实时过滤） */
    get filteredMaterials() {
      const q = (self.materialQuery || "").toLowerCase();
      if (!q) return self.materialOptions;
      return self.materialOptions.filter((m) =>
        (m.material_no || "").toLowerCase().includes(q) ||
        (m.material_name || "").toLowerCase().includes(q)
      );
    },
    materialName(no) { return (no && self.materialMap[no]) || ""; },
    selectMaterial(m) {
      self.fMaterial = m.material_no;
      self.materialQuery = "";
      self.materialOpen = false;
      self.search();
    },
    clearMaterial() {
      self.fMaterial = "";
      self.materialQuery = "";
      self.materialOpen = false;
      self.search();
    },

    /* ---- 过滤 / 分页 ---- */
    search() { self.list.load(1); },

    /* ---- 详情模态 ---- */
    async viewX(d) {
      self.modalX = { open: true, loading: true, d: null };
      try {
        self.modalX.d = await svc("demand_pool", "get", { replenish_no: d.replenish_no });
      } catch { self.modalX.open = false; } finally { self.modalX.loading = false; }
    },
    closeX() { self.modalX.open = false; },

    /* ---- 状态机动作：行内操作列与模态页脚共用（待下达→下达/取消；已下达→取消；
            生产中/已完成/已取消为回传/终态无按钮）。
            字面量逐项书写，勿变量拼名；ERP 回传（on_workorder_started/on_inbound）前端不主动调。 ---- */
    openRelease(d) {
      self.releaseForm = { open: true, busy: false, replenish_no: d.replenish_no, promised_inbound: "" };
    },
    closeRelease() { self.releaseForm.open = false; },
    async confirmRelease() {
      const f = self.releaseForm;
      f.busy = true;
      try {
        const r = await svc("demand_pool", "release", {
          replenish_no: f.replenish_no,
          promised_inbound: (f.promised_inbound && String(f.promised_inbound).trim()) || undefined,
        });
        toast(`已下达 · ${f.replenish_no}`);
        self.releaseForm.open = false;
        if (self.modalX.open && r) self.modalX.d = r;   // 已开模态原地刷新
        await self.list.load(self.list.page);           // 列表刷新当前页
      } catch { /* 非法流转等由 api.js 统一 toast */ } finally { f.busy = false; }
    },

    openCancel(d) {
      self.cancelForm = { open: true, busy: false, replenish_no: d.replenish_no };
    },
    closeCancel() { self.cancelForm.open = false; },
    async confirmCancel() {
      const f = self.cancelForm;
      f.busy = true;
      try {
        const r = await svc("demand_pool", "cancel", { replenish_no: f.replenish_no });
        toast(`已取消 · ${f.replenish_no}`);
        self.cancelForm.open = false;
        if (self.modalX.open && r) self.modalX.d = r;
        await self.list.load(self.list.page);
      } catch { /* 非法流转等由 api.js 统一 toast */ } finally { f.busy = false; }
    },
  });
  return self;
}
