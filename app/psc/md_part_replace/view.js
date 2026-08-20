/* app/psc/md_part_replace/view.js —— 替换关系（主数据页，与后端 md_part_replace.py 同文件夹）
   数据来源：独立创建（PLM 冗余同步 + 本地录入）；无 delete / import_batch，有效期经 disable 软失效。
   状态机：生效 → 失效（单向、幂等），无反向激活。 */
import { svc, hue, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

/* 页面自描述（平台扫描的唯一入口）：key = 应用文件夹名；order 升序 = 菜单顺序 */
export const PAGE_META = {
  key: "md_part_replace",
  name: "替换关系",
  ic: "🔁",
  title: "替换关系",
  crumb: "主数据 · 零件替换关系(原件→替换件)",
  order: 70,
  // 关系号(rel_no)为系统生成内部主键，业务价值低，默认隐藏（可经列设置开启）
  col_default_hidden: "关系号",
};

export default function pageMdPartReplace() {
  const self = Alpine.reactive({
    tpl: "",
    hue,                            // 展示工具（dash 为 window 全局，模板直接用；本页无金额/时间字段）

    /* ---- 列表 + 过滤（与 md_part_replace.list(old_material_no, new_material_no, status, page, size) 一一对应；
            契约无 keyword 参数 → 不设关键字搜索，禁止前端假过滤） ---- */
    list: null,
    fOld: "",                       // old_material_no（后端 LIKE 模糊）
    fNew: "",                       // new_material_no（后端 LIKE 模糊）
    fStatus: "",                    // 全部 / 生效 / 失效

    /* ---- 物料主数据（过滤条回显 + 表单 autocomplete 共用一份） ---- */
    materialOptions: [],            // [{material_no, material_name, ...}]
    materialMap: {},                // { material_no: material_name }

    /* ---- 详情模态 ---- */
    modalX: { open: false, loading: false, d: null },

    /* ---- 创建 / 编辑表单（复用；create 无 rel_no，edit 锁定 rel_no） ---- */
    form: { open: false, busy: false, more: false, mode: "create",
            rel_no: "", old_material_no: "", new_material_no: "", ecn_no: "" },

    /* ---- 物料 autocomplete 交互态（原/替换各自独立，共用 materialOptions） ---- */
    oldQuery: "", oldOpen: false,
    newQuery: "", newOpen: false,

    async init() {
      // list 实例须先于 tpl 赋值建好（items:[]）：tpl 一旦赋值 Alpine 即注入模板并求值 list.*，
      // 若此时 list 仍为 null 会喷「reading 'items' of null」（对标 task 范式）。
      self.list = pageable(async (q) => svc("md_part_replace", "list", {
        old_material_no: self.fOld || undefined,
        new_material_no: self.fNew || undefined,
        status: self.fStatus || undefined,
        ...q,                       // page / size（契约 string 型，照传）
      }));
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      await self.loadMaterials();   // 备齐物料名称映射，再拉列表数据
      await self.list.load();
    },

    /* 物料下拉数据源：quiet 探测，失败不喷 toast，零值兜底 */
    async loadMaterials() {
      try {
        const r = await svc("md_material", "list", { page: 1, size: 500 }, { quiet: true });
        const rows = Array.isArray(r) ? r : (r && r.items) || [];
        self.materialOptions = rows;
        const map = {};
        for (const m of rows) if (m && m.material_no) map[m.material_no] = m.material_name || "";
        self.materialMap = map;
      } catch { /* 失败兜底：autocomplete 仅「暂无可选物料」禁用项 */ }
    },

    materialName(no) { return (no && self.materialMap[no]) || ""; },

    /* ---- 物料 autocomplete：过滤同时匹配 material_no / material_name ---- */
    get oldFiltered() {
      const q = (self.oldQuery || "").toLowerCase();
      if (!q) return self.materialOptions;
      return self.materialOptions.filter((p) =>
        (p.material_no || "").toLowerCase().includes(q) ||
        (p.material_name || "").toLowerCase().includes(q));
    },
    get newFiltered() {
      const q = (self.newQuery || "").toLowerCase();
      if (!q) return self.materialOptions;
      return self.materialOptions.filter((p) =>
        (p.material_no || "").toLowerCase().includes(q) ||
        (p.material_name || "").toLowerCase().includes(q));
    },
    selectOld(p) { self.form.old_material_no = p.material_no; self.oldQuery = ""; self.oldOpen = false; },
    selectNew(p) { self.form.new_material_no = p.material_no; self.newQuery = ""; self.newOpen = false; },

    /* ---- 过滤 / 分页 ---- */
    search() { self.list.load(1); },
    resetFilters() {
      self.fOld = ""; self.fNew = ""; self.fStatus = "";
      self.list.load(1);
    },

    /* ---- 详情模态 ---- */
    async viewX(d) {
      self.modalX = { open: true, loading: true, d: null };
      try {
        self.modalX.d = await svc("md_part_replace", "get", { rel_no: d.rel_no });
      } catch { self.modalX.open = false; } finally { self.modalX.loading = false; }
    },
    closeX() { self.modalX.open = false; },

    /* ---- 创建 / 编辑表单 ---- */
    openCreate() {
      self.form = { open: true, busy: false, more: false, mode: "create",
                    rel_no: "", old_material_no: "", new_material_no: "", ecn_no: "" };
      self.oldQuery = ""; self.oldOpen = false; self.newQuery = ""; self.newOpen = false;
    },
    openEdit(d) {
      if (!d) return;
      self.form = { open: true, busy: false, more: false, mode: "edit",
                    rel_no: d.rel_no, old_material_no: d.old_material_no,
                    new_material_no: d.new_material_no, ecn_no: d.ecn_no || "" };
      self.oldQuery = ""; self.oldOpen = false; self.newQuery = ""; self.newOpen = false;
    },
    closeForm() { self.form.open = false; },

    async save() {
      const f = self.form;
      if (!f.old_material_no || !String(f.old_material_no).trim()) return toast("请选择原物料号", "warn");
      if (!f.new_material_no || !String(f.new_material_no).trim()) return toast("请选择替换物料号", "warn");
      if (String(f.old_material_no).trim() === String(f.new_material_no).trim())
        return toast("原物料号与替换物料号不能相同", "warn");
      f.busy = true;
      try {
        const base = {
          old_material_no: String(f.old_material_no).trim(),
          new_material_no: String(f.new_material_no).trim(),
          ecn_no: f.ecn_no && String(f.ecn_no).trim() ? String(f.ecn_no).trim() : undefined,
        };
        if (f.mode === "edit") {
          const r = await svc("md_part_replace", "update", { rel_no: f.rel_no, ...base });
          toast("已更新替换关系 · " + f.rel_no);
          if (self.modalX.open && self.modalX.d && self.modalX.d.rel_no === f.rel_no) self.modalX.d = r;
          await self.list.load(self.list.page);       // 编辑：刷新当前页
        } else {
          const r = await svc("md_part_replace", "create", base);
          toast("已创建替换关系 · " + ((r && r.rel_no) || ""));
          self.fOld = ""; self.fNew = ""; self.fStatus = "";   // 新关系恒「生效」，重置过滤确保可见
          await self.list.load(1);
        }
        self.form.open = false;
      } catch { /* 物料不存在 / 组合已存在 / 原=替换 / ECN 超长均由 api.js 统一 toast */ }
      finally { f.busy = false; }
    },

    /* ---- 设为失效（状态机动作：生效→失效；行内与模态页脚共用；后端幂等） ---- */
    async disable(d) {
      if (!confirm("确认将替换关系设为失效？失效后毛需求替换件合并中将排除此关系")) return;
      try {
        await svc("md_part_replace", "disable", { rel_no: d.rel_no });
        toast("替换关系已设为失效");
        if (self.modalX.open && self.modalX.d && self.modalX.d.rel_no === d.rel_no) {
          self.modalX.d = await svc("md_part_replace", "get", { rel_no: d.rel_no });  // 已开模态原地刷新
        }
        await self.list.load(self.list.page);
      } catch { /* 非法流转等由 api.js 统一 toast，页面不硬编状态机校验 */ }
    },
  });
  return self;
}
