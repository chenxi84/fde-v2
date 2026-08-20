/* FDE 视图 · 公共 API 层（所有模块共享，业务模块不修改）
   约定：同源调用（平台 Flask 托管 view/ 目录，无 CORS 问题）；会话 Cookie 默认携带。
   响应契约 {status:"ok",data} / {status:"error",kind,message}；401 → 回登录页。 */

export function toast(message, kind = "ok") {
  window.dispatchEvent(new CustomEvent("fde:toast", { detail: { message, kind } }));
}

async function request(path, options = {}) {
  const quiet = options.quiet;   // quiet：静默模式，不弹 toast（调用方自行处理错误）
  let resp;
  try {
    resp = await fetch(path, { credentials: "same-origin", ...options });
  } catch (e) {
    if (!quiet) toast("网络不可达：平台服务未启动？", "err");
    throw e;
  }
  if (resp.status === 401) {
    location.href = "/login?next=" + encodeURIComponent(location.pathname);
    throw new Error("未登录");
  }
  if (resp.status === 403) {
    const body = await resp.json().catch(() => ({}));
    if (!quiet) toast(body.message || "无权执行该操作", "err");
    throw new Error(body.message || "403");
  }
  if (resp.status === 404) {
    if (!quiet) toast("目标不存在（应用/服务/页面）", "err");
    throw new Error("404");
  }
  const json = await resp.json().catch(() => null);
  if (!json) { if (!quiet) toast("响应解析失败", "err"); throw new Error("bad response"); }
  if (json.status === "error") {
    if (!quiet) toast(json.message || "操作失败", "err");
    throw new Error(json.message);
  }
  return json.data !== undefined ? json.data : json;
}

export const get = (path, opts = {}) => request(path, opts);

export const del = (path) => request(path, { method: "DELETE" });

export const post = (path, body, opts = {}) => {
  const { headers, ...rest } = opts;
  return request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(headers || {}) },
    body: JSON.stringify(body || {}),
    ...rest,
  });
};

/** 调用应用服务：svc("sales_order", "create", {...})；opts 可传 {quiet:true} 静默。
    自动注入 X-Fde-Page（shell 在路由切换时写入 window.__fdePage）——后端闸门据此
    做页面授权隐式放行：角色获授该页，则页面源码派生出的服务调用一并放行。 */
export const svc = (app, service, params = {}, opts = {}) => {
  const headers = { ...(opts.headers || {}) };
  if (window.__fdePage) headers["X-Fde-Page"] = window.__fdePage;
  // 组内解析（与后端 CONVENTION §5 组内优先一致）：页面所属组 + 短名 → 组限定路径 '组/名'。
  // 平台页（_platform）或 app 本身已是 '组/名' 时保持原样（跨组重名的短名需调用方自行带组）。
  const grp = (window.__fdePage || "").split(":")[0];
  const appPath = (grp && grp !== "_platform" && !app.includes("/")) ? `${grp}/${app}` : app;
  return post(`/api/apps/${appPath}/call/${service}`, params, { ...opts, headers });
};

/* ── 状态色映射（未知状态回落 slate）──────────────────── */
const HUES = {
  草稿: "slate", 已驳回: "red", 审批中: "amber", 审批完成: "blue",
  已提交: "blue", 已排产: "blue", 计划接收: "blue", 已排产待转单: "blue",
  已部分转单: "blue", 已全部转单完成: "green", 已变更: "green", 已生效: "green",
  已释放: "slate", 取消: "slate",
  全部入库: "teal", 已入库: "teal", 部分入库: "blue", 待发运: "blue",
  已发运: "green", 部分发运: "blue", 全部发运: "green", 待生产: "amber",
  完成: "green", 已完成: "green", 已同步: "green", 已结案: "green",
  已撤回: "red", 申请中: "amber", 待重试: "red", 失败: "red",
  SAP退回: "red", SAP失败: "red", SAP处理中: "amber",
  调用失败: "red", 重试耗尽: "red", 执行中: "amber",
  待回调: "amber", 回调完成: "green",
  待审批: "amber", 已通过: "green", 已审批: "green", 处理中: "amber",
  已冻结: "red", 已核注: "teal",
  冻结: "red", "发布（锁定）": "blue",
  有效: "green", 已过期: "red", 已核销: "teal", 已注销: "slate",
  待发: "amber", 成功: "green",
  // ── demo 组业务态（公共层演进 · 2026-08-02 第⑦步收尾补录）──
  内销: "teal", 外销: "blue", 内贸: "teal", 外贸: "blue",
  标品: "teal", 非标: "amber",
  一级: "blue", 二级: "teal", 启用: "green", 已停用: "red",
  撤回待审: "amber", 撤回申请中: "amber", 未结算: "amber", 已结算: "green",
  计划审批: "amber", 已作废: "red", 生产变更: "amber", 一般变更: "blue",
  已完工: "green", 已取消: "slate", 待入库: "amber",
  预测转单: "blue", SO直接下单: "teal",
  审批驳回: "red", 部分交货: "blue",
  // ── psc 组业务态（2026-08-14 第⑦步 md_part_replace 补录）──
  生效: "green", 失效: "slate",
  // ── psc 组业务态（库存策略品种分层 · 第⑦步补录）──
  库存: "teal", 速度: "blue",
  // ── psc 组业务态（需求池补库单 · 第⑦步补录）──
  缺货补库: "red", 最低库存补库: "amber", 安全库存补库: "blue",
  待下达: "slate", 已下达: "teal", 生产中: "amber",
  // 英文状态码（return_order 状态机按英文码原样展示；settlement_result 双值）
  draft: "slate", submitted: "blue", approved: "green",
  sap_processing: "amber", completed: "green", sap_failed: "red",
  rejected: "red", withdrawn: "red",
  COMPLETED: "green", SAP_REJECTED: "red",
  // ── psc 组策略拟合业务态（第⑦步补录：三态状态机 + 预测方法四类）──
  待复核: "amber", 已否决: "slate",
  移动平均: "blue", 指数平滑: "teal", 阶跃检测: "amber", 借用参考: "slate",
};
export const hue = (status) => HUES[status] || "slate";
export const liveStatus = new Set(["审批中", "执行中", "待重试", "申请中", "待回调"]);

/* 数字千分位 */
export const fmt = (n) =>
  n === null || n === undefined || n === "" ? "—"
    : Number(n).toLocaleString("zh-CN", { maximumFractionDigits: 2 });

/* 空值兜底为「—」 */
export const dash = (v) => (v === null || v === undefined || v === "" ? "—" : v);

/* 时间截断到秒 */
export const fmtTime = (v) => (v ? String(v).slice(0, 19) : "—");

/* 解析 *_json 快照字段（对象原样返回；解析失败返回 null） */
export const tryParse = (v) => {
  if (v === null || v === undefined || v === "") return null;
  if (typeof v === "object") return v;
  try { return JSON.parse(v); } catch { return null; }
};

/* 今天 +N 天（ISO），供表单默认交货期 */
export function plusDays(n) {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}
