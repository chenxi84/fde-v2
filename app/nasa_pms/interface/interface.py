from __future__ import annotations

import re

from fde import FdeError

# 接口类型字典 —— 材料 §6.3.1.3「Outputs」原文给出四类接口文档：
# "Types of interface documentation include the Interface Requirements Document (IRD),
#  Interface Control Document/Drawing (ICD), Interface Definition Document (IDD),
#  and Interface Control Plan (ICP)."
# 术语表已收「接口控制文档（ICD）」；其余三个第②步就地取名并回填（见 新增术语.md）。
IF_TYPES = ("icd", "ird", "idd", "icp")
IF_TYPE_CN = {"icd": "接口控制文档（ICD）", "ird": "接口需求文档（IRD）",
              "idd": "接口定义文档（IDD）", "icp": "接口控制计划（ICP）"}
# 接口的两端 —— 卡片 I-1「提供方与使用方都不能为空」；两行通知记录就是按它逐端写出的
PARTIES = ("provider", "consumer")
# 版本：字母修订版（A 起）。首次发布定版为 A（BR-03），此后只能递增。
FIRST_VERSION = "A"
# 状态机（卡片 9）：定义中 → 已发布 → 变更中 → 已冻结
_STATUS_CN = {"defined": "定义中", "released": "已发布",
              "changing": "变更中", "frozen": "已冻结"}
# 硬终态（卡片状态机末位，无后继）
_TERMINAL = "frozen"
# 主档字段清单 —— `get` 与 `list` **共用同一份**，杜绝两处口径漂移（CONVENTION §7）
_MAIN_COLS = ("if_no, if_name, if_type, provider, consumer, icd_content, version,"
              " status, ci_no, freeze_note, owner, project_no")


class Interface:
    """接口聚合根。两个系统/分系统之间的接口约定（ICD），含两端、约定内容与版本。
    数据来源类型：独立创建（接口由项目内人员在系统设计活动中识别并约定）。

    ⚠ 这里的「接口」是**系统/分系统之间的接口约定（ICD）**，不是代码里的 API 接口 ——
      材料 §6.3 Interface Management 的产物：§6.3.1.1 Inputs 的 Interface Requirements、
      §6.3.1.2.2 "establish the origin, destination, stimuli, and special characteristics of
      the interfaces"、§6.3.1.3 Outputs 的 IRD / ICD / IDD / ICP 四类接口文档。

    一致性边界（见 `architecture.md` 聚合根卡 9）：
      · **两端（提供方 / 使用方）是接口的身份**（材料 §6.3.1.2.2 的 origin / destination）——
        卡片 I-1 要求两端都不能为空；发布之后两端**不可直接改**（改端等于换一条接口，BR-05）；
      · **版本变更通知记录并入本聚合**（`interface_change` 子表，`(if_no, seq)` 复合主键）——
        卡片 I-2「版本变更必须通知两端（变更记录同事务）」：每次版本变更由 `_notify`
        **一次写两条**（提供方一条、使用方一条），没有"只通知一端"的入口；
        跨接口的「变更通知台账」由 `list_changes` 这个**查询视图**提供，不是独立聚合；
      · **接口文档本身是配置项** —— `ci_no` 是**弱引用**（可留空、可悬空），
        本应用只做存在性 + 未归档校验（跨应用 `configuration_item.list`，非同一事务，§8）。

    业务规则落点：BR-01 两端必填且相异（I-1）/ BR-02 类型受字典约束 /
                 BR-03 版本只能递增（首次发布定 A）/ BR-04 版本变更必须通知两端（I-2）/
                 BR-05 已发布后两端与 ICD 内容不可直接改（须走 revise）/
                 BR-06 编号唯一且不可变 / BR-07 已冻结为硬终态 /
                 BR-08 关联配置项必须存在且未归档 / BR-09 未定版的接口不能冻结。
    """

    # ── 服务（公共方法即服务） ──────────────────────────────

    def create(self, if_name: str, if_type: str, provider: str, consumer: str,
               icd_content: str = None, ci_no: str = None, owner: str = None,
               project_no: str = None):
        """定义一条接口，落库为「定义中」状态，编号自动生成（`IF-001` 起）；**此时尚无版本**。

        四项逐个校验非空：接口名称 / 接口类型 / 提供方 / 使用方（卡片 I-1 的 I-1 落在这里）；
        类型还要过字典（BR-02）；**两端不能是同一个系统**（一条接口的两端必须是两个东西，
        否则它不构成接口）。`ci_no`（关联配置项）为弱引用，选填；填了就必须真实存在且未归档（BR-08）。
        """
        if_name = self._clean(if_name)
        if not if_name:
            raise FdeError("接口名称不能为空")
        self._check_type(if_type)                                  # BR-02
        provider = self._clean(provider)
        consumer = self._clean(consumer)
        self._check_ends(provider, consumer)                       # BR-01（卡片 I-1）
        ci_no = self._clean(ci_no)
        if ci_no:
            self._check_ci(ci_no)                                  # BR-08（跨应用）

        if_no = self._next_no()
        self.db.execute(
            "INSERT INTO interface (if_no, if_name, if_type, provider, consumer,"
            " icd_content, status, ci_no, owner, project_no)"
            " VALUES (?, ?, ?, ?, ?, ?, 'defined', ?, ?, ?)",
            (if_no, if_name, self._clean(if_type), provider, consumer,
             self._clean(icd_content) or None, ci_no or None,
             self._clean(owner), self._clean(project_no)),
        )
        return self.get(if_no)

    def update(self, if_no: str, if_name: str = None, if_type: str = None,
               provider: str = None, consumer: str = None, icd_content: str = None,
               ci_no: str = None, owner: str = None, project_no: str = None):
        """修改接口的描述性内容（名称 / 类型 / 责任人 / 所属项目 / 关联配置项…）。

        **编号与版本都不在字段白名单里**：编号落库不可变（BR-06）；版本只能经
        `release`（首次定版）与 `revise`（版本变更）两步走（BR-03）—— 没有参数可传，也就无从改起。
        **结论性的两项按状态锁**（BR-05，逐条重判、不照抄别的页的解锁条件）：
          · **两端**（提供方 / 使用方）只在「定义中」可改 —— 一旦发布，两端就是被通知的对象，
            改端等于换一条接口（材料 §6.3.1.2.2 的 origin / destination 是接口的身份）；
          · **约定内容（ICD）** 也只在「定义中」可改 —— 已发布接口要改约定内容属于**接口变更**，
            必须走 `revise`（带新版本号与变更原因，并通知两端），这正是 BR-04 的入口；
          · 其余描述性字段（名称 / 类型 / 责任人 / 项目 / 关联配置项）非终态可改。
        已冻结（`frozen`）是硬终态，任何修改都拒绝（BR-07）。
        """
        cur = self._need(if_no)
        if cur["status"] == _TERMINAL:                             # BR-07（硬终态排最前）
            raise FdeError(f"接口 {if_no} 已冻结（终态），不能再修改")
        if provider is not None or consumer is not None:
            if cur["status"] != "defined":                         # BR-05 前半
                raise FdeError(
                    f"接口 {if_no} 已定版（{self._status_cn(cur['status'])}），"
                    "两端不能再改（改端等于换一条接口，BR-05）")
        if icd_content is not None and cur["status"] != "defined":  # BR-05 后半
            raise FdeError(
                f"接口 {if_no} 已定版（{self._status_cn(cur['status'])}），"
                "约定内容（ICD）不能直接改，请走版本变更（revise，BR-05）")

        sets, args = [], []
        if if_name is not None:
            if_name = self._clean(if_name)
            if not if_name:
                raise FdeError("接口名称不能为空")
            sets.append("if_name = ?")
            args.append(if_name)
        if if_type is not None:
            self._check_type(if_type)                              # BR-02
            sets.append("if_type = ?")
            args.append(self._clean(if_type))
        if provider is not None or consumer is not None:
            # ⚠ 校验的是**改完之后的两端**，不是本次传入的那一个：只改一端也可能把两端改成同一个
            p = self._clean(provider) if provider is not None else cur["provider"]
            c = self._clean(consumer) if consumer is not None else cur["consumer"]
            self._check_ends(p, c)                                 # BR-01（改后整体校验）
            if provider is not None:
                sets.append("provider = ?")
                args.append(p)
            if consumer is not None:
                sets.append("consumer = ?")
                args.append(c)
        if icd_content is not None:
            sets.append("icd_content = ?")
            args.append(self._clean(icd_content) or None)
        if ci_no is not None:
            ci = self._clean(ci_no)
            if ci:
                self._check_ci(ci)                                 # BR-08（跨应用）
            sets.append("ci_no = ?")
            args.append(ci or None)
        if owner is not None:
            sets.append("owner = ?")
            args.append(self._clean(owner))
        if project_no is not None:
            sets.append("project_no = ?")
            args.append(self._clean(project_no))
        if not sets:
            raise FdeError("没有要修改的内容")
        args.append(if_no)
        self.db.execute("UPDATE interface SET " + ", ".join(sets) + " WHERE if_no = ?",
                        tuple(args))
        return self.get(if_no)

    def release(self, if_no: str):
        """发布接口 —— **首次发布**：定义中 → 已发布（`defined → released`），定版为 `A`；
        **变更落实**：变更中 → 已发布（`changing → released`）。

        两种起因的状态迁移不同，故守卫顺序也分两段：
          · 从「定义中」进来：**定版**（版本从"未定版"变为 `A`）并按 BR-04 **通知两端** ——
            对两端而言这同样是一次版本变化（材料 §6.3.1.3：接口文档随配置管理过程获批并成为
            受控文档，两端必须知悉自己签的是哪一版）；
          · 从「变更中」进来：版本号**已在 `revise` 时改定并通知过**（那是"版本发生变化的那一刻"），
            这里只是把变更收口回已发布，**不再重复通知**（否则同一次变更会在台账里出现两轮）。
        """
        cur = self._need(if_no)
        if cur["status"] == _TERMINAL:                             # BR-07（硬终态排最前）
            raise FdeError(f"接口 {if_no} 已冻结（终态），不能再发布")
        if cur["status"] == "released":
            raise FdeError(f"接口 {if_no} 已经是已发布状态")
        if cur["status"] == "defined":
            self._notify(cur, "release", "", FIRST_VERSION, None)  # BR-04（卡片 I-2）
            self.db.execute(
                "UPDATE interface SET version = ?, status = 'released' WHERE if_no = ?",
                (FIRST_VERSION, if_no))
            return self.get(if_no)
        if cur["status"] == "changing":
            self.db.execute("UPDATE interface SET status = 'released' WHERE if_no = ?", (if_no,))
            return self.get(if_no)
        raise FdeError(
            f"接口 {if_no} 当前为「{self._status_cn(cur['status'])}」，不能发布")

    def revise(self, if_no: str, new_version: str, reason: str, icd_content: str = None):
        """发起版本变更：已发布 → 变更中（`released → changing`），改版本号并**通知两端**。

        这是本聚合**唯一**改版本的入口（BR-03），也是**通知记录的唯一的版本变更产生点**
        （BR-04，卡片 I-2）—— 通知与版本号**同事务**落库：要么版本变了且两端都被通知，
        要么版本没变（不存在"版本已改、有一端不知情"的中间态）。

        四步校验：状态守卫（终态 → 变更中 → 定义中）→ 新版本号是单个大写字母 →
        **严格大于当前版本**（材料 §6.3.1.3：接口需求一经基线，变更须走需求管理过程评估影响，
        接口版本不能回退）→ 变更原因非空（§6.3.1.3 要求留 "the rationale for interface decisions"）。
        `icd_content` 选填：它是接口变更的**实质内容**（改了什么约定），随版本一起落库。
        """
        cur = self._need(if_no)
        if cur["status"] == _TERMINAL:                             # BR-07（硬终态排最前）
            raise FdeError(f"接口 {if_no} 已冻结（终态），不能再变更版本")
        if cur["status"] == "changing":
            raise FdeError(
                f"接口 {if_no} 已经在变更中，请先完成本次变更（release）再发起下一次（BR-03）")
        if cur["status"] == "defined":
            raise FdeError(
                f"接口 {if_no} 尚未定版（定义中），请先发布（release）再变更版本（BR-03）")

        nv = self._clean(new_version)
        if not nv:
            raise FdeError("新版本号不能为空")
        if not re.match(r"^[A-Z]$", nv):
            raise FdeError("新版本号必须是单个大写字母（如 B / C，BR-03）")
        old = self._clean(cur["version"])
        if nv <= old:
            raise FdeError(
                f"接口版本只能递增：新版本 {nv} 不大于当前版本 {old or '未定版'}（BR-03）")
        reason = self._clean(reason)
        if not reason:
            raise FdeError("版本变更必须说明变更原因（BR-04）")

        self._notify(cur, "revise", old, nv, reason)               # BR-04（卡片 I-2）
        sets, args = ["version = ?", "status = 'changing'"], [nv]
        if icd_content is not None:
            sets.append("icd_content = ?")
            args.append(self._clean(icd_content) or None)
        args.append(if_no)
        self.db.execute("UPDATE interface SET " + ", ".join(sets) + " WHERE if_no = ?",
                        tuple(args))
        return self.get(if_no)

    def freeze(self, if_no: str, note: str = None):
        """冻结接口：已发布 → 已冻结（`released → frozen`，硬终态）。

        冻结是接口约定的收尾（对已定版接口的定稿）—— 材料 §6.3.1.3 的接口文档最终
        "will then be maintained and approved using the Configuration Management Process"，
        进入配置管理后本应用不再改它。**只有已发布的接口才能冻结**（BR-09）：
        定义中的接口还没有版本可冻，变更中的接口应先 `release` 完成变更再冻结 ——
        否则会出现"版本刚改、变更未落实就已冻结"的空洞。
        冻结后**不删除**：材料要求接口变更留痕（§6.3.1.2.5 Capture Work Products），
        记录必须留存且不可再改（BR-07）。
        """
        cur = self._need(if_no)
        if cur["status"] == _TERMINAL:                             # BR-07（硬终态排最前）
            raise FdeError(f"接口 {if_no} 已经是冻结状态")
        if cur["status"] != "released":                            # BR-09
            raise FdeError(
                f"接口 {if_no} 当前为「{self._status_cn(cur['status'])}」，"
                "只有已发布的接口才能冻结（BR-09）")
        self.db.execute("UPDATE interface SET status = 'frozen', freeze_note = ? WHERE if_no = ?",
                        (self._clean(note) or None, if_no))
        return self.get(if_no)

    def get(self, if_no: str):
        """按接口编号查询（含版本变更通知记录 `changes`）；未命中返回 None，不抛异常。

        通知记录条数 `change_total` 与 `list` 同口径（前端"变更通知 N 条"读它）。
        """
        if_no = self._clean(if_no)
        if not if_no:
            return None
        row = self.db.execute(
            "SELECT " + _MAIN_COLS + " FROM interface WHERE if_no = ?", (if_no,),
        ).fetchone()
        if not row:
            return None
        out = dict(row)
        out["changes"] = [dict(r) for r in self.db.execute(
            "SELECT seq, action, old_version, new_version, party, party_name, reason, created_at"
            " FROM interface_change WHERE if_no = ? ORDER BY seq", (if_no,)).fetchall()]
        out.update(self._counts(out["changes"]))
        return out

    def list(self, if_type: str = None, status: str = None, provider: str = None,
             consumer: str = None, ci_no: str = None, page: int = None, size: int = None):
        """按类型 / 状态 / 提供方 / 使用方 / 关联配置项筛选，**分页返回 `{items, total}`**，
        默认按编号升序。

        ⚠ `page`/`size` 与 `{items, total}` 是**前端 `pageable` 的契约**（见 VIEW_CONVENTION）——
        少了它们，前端拿到的 `items` 恒为空、页面静默显示空态而**不报错**（同组实测踩过）。
        返回项与 `get` 同字段口径（`_MAIN_COLS` 共用 + 同一份通知计数）；
        通知记录**明细只在 `get`**（列表不需要 N+1 取子表）。
        """
        where, args = [], []
        for col, val in (("if_type", if_type), ("status", status), ("provider", provider),
                         ("consumer", consumer), ("ci_no", ci_no)):
            val = self._clean(val)
            if val:
                where.append(f"{col} = ?")
                args.append(val)
        sql = "SELECT " + _MAIN_COLS + " FROM interface"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY if_no"
        rows = []
        for r in self.db.execute(sql, tuple(args)).fetchall():
            d = dict(r)
            d.update(self._counts_by_no(d["if_no"]))
            rows.append(d)

        total = len(rows)
        if size:
            p = max(int(page or 1), 1)
            n = max(int(size), 1)
            rows = rows[(p - 1) * n: p * n]
        return {"items": rows, "total": total}

    def list_changes(self, if_no: str = None, party: str = None, action: str = None,
                     page: int = None, size: int = None):
        """**跨接口的版本变更通知台账**（查询视图 —— 卡片 9 只有「通知记录并入本聚合」，
        跨接口的汇总没有独立生命周期，故不成聚合）。

        汇总行把所属接口的名称 / 类型 / 当前状态一并带出（前端"通知台账"一屏看全），
        并按 `{items, total}` 分页 —— 与 `list` 同一契约口径。
        可筛「端」是这张表的主要用途：一眼看到**每次变更的两端各收到了一条**（I-2 的视图面）。
        """
        where, args = [], []
        for col, val in (("c.if_no", if_no), ("c.party", party), ("c.action", action)):
            val = self._clean(val)
            if val:
                where.append(f"{col} = ?")
                args.append(val)
        sql = ("SELECT c.if_no, c.seq, c.action, c.old_version, c.new_version, c.party,"
               " c.party_name, c.reason, c.created_at, i.if_name, i.if_type, i.status AS if_status"
               " FROM interface_change c JOIN interface i ON i.if_no = c.if_no")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY c.if_no, c.seq"
        rows = [dict(r) for r in self.db.execute(sql, tuple(args)).fetchall()]

        total = len(rows)
        if size:
            p = max(int(page or 1), 1)
            n = max(int(size), 1)
            rows = rows[(p - 1) * n: p * n]
        return {"items": rows, "total": total}

    # ── 私有（非服务） ────────────────────────────────────

    @staticmethod
    def _clean(v):
        return str(v).strip() if v is not None else ""

    @staticmethod
    def _check_type(if_type: str):
        if_type = Interface._clean(if_type)
        if not if_type:
            raise FdeError("接口类型不能为空")
        if if_type not in IF_TYPES:
            raise FdeError(f"接口类型只能是 {'/'.join(IF_TYPES)} 之一（BR-02）")

    @staticmethod
    def _check_ends(provider: str, consumer: str):
        """卡片 I-1：接口必须明确两端 —— 提供方与使用方都不能为空、且**不能是同一个系统**。"""
        if not provider:
            raise FdeError("接口的提供方不能为空（接口必须明确两端，BR-01）")
        if not consumer:
            raise FdeError("接口的使用方不能为空（接口必须明确两端，BR-01）")
        if provider == consumer:
            raise FdeError(f"接口的两端不能是同一个系统（提供方与使用方都是「{provider}」，BR-01）")

    @staticmethod
    def _status_cn(status: str) -> str:
        return _STATUS_CN.get(status, status or "—")

    def _check_ci(self, ci_no: str):
        """弱引用校验：跨应用读一次 `configuration_item.list`，确认配置项**存在且未归档**（BR-08）。

        ⚠ **目标应用名必须是字面量**（`self.fde.call("configuration_item", "list")`）——
        静态扫描器据此校验跨应用契约（CONVENTION §10.8）；写成变量会退化成
        "动态目标，需人工确认"的告警，把契约校验让位给运行期。
        跨应用调用**只读、非同一事务**（§8）：接口文档本身是配置项，这里只挡住明显不成立的关联。
        """
        try:
            res = self.fde.call("configuration_item", "list")
        except FdeError as e:
            raise FdeError(f"关联配置项校验失败：配置项台账不可用（{e}）") from None
        except Exception:
            raise FdeError("关联配置项校验失败：配置项台账不可用") from None
        items = (res or {}).get("items") or []
        hit = [r for r in items if r.get("ci_no") == ci_no]
        if not hit:
            raise FdeError(
                f"关联的配置项 {ci_no} 不存在（接口文档本身是配置项，只能关联已有配置项，BR-08）")
        if hit[0].get("status") == "archived":
            raise FdeError(f"关联的配置项 {ci_no} 已归档（终态），不能作为新的关联（BR-08）")

    def _need(self, if_no: str):
        if_no = self._clean(if_no)
        if not if_no:
            raise FdeError("接口编号不能为空")
        cur = self.get(if_no)
        if not cur:
            raise FdeError(f"接口 {if_no} 不存在")
        return cur

    def _next_no(self) -> str:
        """生成下一个接口编号：IF-<三位序号>（BR-06：编号唯一且不可变）。"""
        rows = self.db.execute("SELECT if_no FROM interface").fetchall()
        mx = 0
        for r in rows:
            m = re.match(r"^IF-(\d+)$", str(r["if_no"]))
            if m:
                mx = max(mx, int(m.group(1)))
        return f"IF-{mx + 1:03d}"

    def _next_seq(self, if_no: str) -> int:
        """聚合内子表的序号：本接口内递增（`(if_no, seq)` 是复合主键，无全局标识）。"""
        rows = self.db.execute(
            "SELECT seq FROM interface_change WHERE if_no = ?", (if_no,)).fetchall()
        mx = 0
        for r in rows:
            mx = max(mx, int(r["seq"]))
        return mx + 1

    def _notify(self, cur: dict, action: str, old_version: str, new_version: str,
                reason: str = None):
        """把一次版本变更**通知到两端**：提供方一条、使用方一条，与版本变更**同事务**落库。

        这是卡片 I-2 的落法 —— 不变量不靠调用方自觉，而靠**没有"只写一条"的路径**：
        两条记录由本方法一次写完，`release` / `revise` 都只能经它产出通知。
        行里的 `party_name` 是**端名快照**：接口两端日后不可改（BR-05），快照保证台账
        永远能回答"当时通知的是谁"（材料 §6.3.1.2.5 的 "actions taken to correct
        identified interface anomalies" 需要可追溯）。
        """
        for party in PARTIES:
            seq = self._next_seq(cur["if_no"])
            self.db.execute(
                "INSERT INTO interface_change (if_no, seq, action, old_version, new_version,"
                " party, party_name, reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (cur["if_no"], seq, action, old_version or None, new_version, party,
                 cur[party], reason or None),
            )

    def _counts(self, changes: list):
        """由通知记录清单推导 `{change_total}` —— `get` 与 `list` 共用同一算法。"""
        return {"change_total": len(changes)}

    def _counts_by_no(self, if_no: str):
        row = self.db.execute(
            "SELECT COUNT(*) AS total FROM interface_change WHERE if_no = ?", (if_no,),
        ).fetchone()
        return {"change_total": int(row["total"] or 0)}
