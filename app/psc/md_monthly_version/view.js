/* app/psc/md_monthly_version/view.js —— 月度版本主数据页工厂（与 md_monthly_version.py 同文件夹）
   主数据：独立创建（版本号 YYYYMM）；状态机 草稿 --publish--> 发布（锁定） --freeze--> 冻结 --unfreeze--> 草稿（可回退）。
   契约无 update / delete / import_batch → 无编辑入口、无删除；单据变更仅经 publish / freeze / unfreeze。 */
import { svc, hue, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

/* 页面自描述（平台扫描的唯一入口）：key = 应用文件夹名；order 升序 = 菜单顺序 */
export const PAGE_META = {
  key: "md_monthly_version",
  name: "月度版本",
  ic: "📅",
  title: "月度版本",
  crumb: "主数据 · 计划周期版本(草稿→发布→冻结)",
  order: 570,
};

export default function pageMdMonthlyVersion() {
  const self = Alpine.reactive({
    tpl: "",
    hue,                          // 展示工具（dash / fmtTime / tryParse 为 window 全局，模板直接用）

    /* ---- 列表 + 过滤（与 md_monthly_version.list(version_no, lock_status, page, size) 一一对应；
            version_no 精确匹配；契约无 keyword 参数 → 不设关键字搜索，禁止前端假过滤） ---- */
    list: null,
    fVersion: "",                 // 版本号（精确匹配，空值不传）
    fStatus: "",                  // 全部 / 草稿 / 发布（锁定） / 冻结

    /* ---- 详情模态 ---- */
    modalX: { open: false, loading: false, d: null },

    /* ---- 创建表单（create 全参数：version_no / anchor_period / opening_date；lock_status 由后端默认「草稿」） ---- */
    form: { open: false, busy: false, version_no: "", anchor_period: "", opening_date: "" },

    async init() {
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      // list 实例须在 tpl 赋值前同步建好（items:[]）：tpl 一旦赋值 Alpine 即注入模板并求值 list.*
      self.list = pageable(async (q) => svc("md_monthly_version", "list", {
        version_no: self.fVersion || undefined,
        lock_status: self.fStatus || undefined,
        ...q,                      // page / size（契约 integer 型，照传）
      }));
      await self.list.load();
    },

    /* ---- 过滤 / 分页 ---- */
    search() { self.list.load(1); },
    resetFilters() { self.fVersion = ""; self.fStatus = ""; self.list.load(1); },

    /* ---- 详情模态 ---- */
    async viewX(d) {
      self.modalX = { open: true, loading: true, d: null };
      try {
        self.modalX.d = await svc("md_monthly_version", "get", { version_no: d.version_no });
      } catch { self.modalX.open = false; } finally { self.modalX.loading = false; }
    },
    closeX() { self.modalX.open = false; },

    /* ---- 状态机动作：行内操作列与模态页脚共用（草稿→发布；发布（锁定）→冻结；冻结→草稿回退）
           字面量逐项书写，勿变量拼名 ---- */
    async act(d, kind) {
      const no = d.version_no;
      try {
        let r = null;
        if (kind === "publish") r = await svc("md_monthly_version", "publish", { version_no: no });
        else if (kind === "freeze") r = await svc("md_monthly_version", "freeze", { version_no: no });
        else if (kind === "unfreeze") r = await svc("md_monthly_version", "unfreeze", { version_no: no });
        else return;
        const msg = { publish: "版本发布成功，预测已锁定", freeze: "版本冻结成功", unfreeze: "版本已回退到草稿" }[kind];
        toast(`${msg} · ${no}`);
        if (self.modalX.open && r) self.modalX.d = r;   // 已开模态原地刷新
        await self.list.load(self.list.page);           // 列表刷新当前页
      } catch { /* 非法流转（仅草稿可发布/仅发布（锁定）可冻结/仅冻结可回退）等由 api.js 统一 toast */ }
    },

    /* ---- 创建表单 ---- */
    openCreate() {
      self.form = { open: true, busy: false, version_no: "", anchor_period: "", opening_date: "" };
    },
    closeCreate() { self.form.open = false; },

    async save() {
      const f = self.form;
      if (!f.version_no || !f.version_no.trim()) return toast("请填写版本号", "warn");
      if (!f.anchor_period || !f.anchor_period.trim()) return toast("请填写锚定期间", "warn");
      if (!f.opening_date) return toast("请选择 opening 日", "warn");
      f.busy = true;
      try {
        await svc("md_monthly_version", "create", {
          version_no: f.version_no.trim(),
          anchor_period: f.anchor_period.trim(),
          opening_date: f.opening_date,
        });
        toast("月度版本创建成功");
        self.closeCreate();
        self.fVersion = ""; self.fStatus = "";   // 新版本恒「草稿」，重置过滤确保可见
        await self.list.load(1);
      } catch { /* 版本号已存在/格式非法/已存在活跃版本（BR-06）等由 api.js 统一 toast */ } finally { f.busy = false; }
    },
  });
  return self;
}
