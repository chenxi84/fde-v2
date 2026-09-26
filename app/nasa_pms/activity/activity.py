from __future__ import annotations

import datetime as _dt

from fde import FdeError

# 活动类型（材料 §5.5.5：summary activity 与 discrete measurable activity 是两类写法）
KINDS = ("summary", "activity", "milestone")
KIND_CN = {"summary": "汇总", "activity": "活动", "milestone": "里程碑"}
# 边界里程碑：只有这两个允许"没有前置 / 没有后续"（§5.5.8 的 no open ends 的例外）
PHASES = ("start", "finish")
STATUS_CN = {"planned": "计划", "in_progress": "进行中", "completed": "已完成"}

# 四种逻辑关系模型（材料 §5.5.8.2「There are four relationship models for the activities」）
RELS = ("FS", "SS", "FF", "SF")
REL_CN = {"FS": "完成→开始", "SS": "开始→开始", "FF": "完成→完成", "SF": "开始→完成"}
# 工期口径（材料 §5.5.9.1：用 edays 还是 days 要「be consistent throughout the schedule」）
UNITS = ("days", "edays")
UNIT_CN = {"days": "工作日", "edays": "日历天（elapsed days）"}


class Activity:
    """进度活动聚合根。IMS 里的一个离散可度量工作单元（活动 / 里程碑）。

    一致性边界（见 `architecture.md` 聚合根卡 13）：
      · **日期不进表**：表里只有工期与逻辑链，计划日期由 `schedule_view()` **正推派生**
        —— 材料 §5.5.9.3 要的就是这个（"dates … determined by logic and durations rather than by
        wishful thinking or estimates constructed to meet a particular finish date"）；
      · **逻辑链是四值枚举 + 滞后 + 理由**（§5.5.8.2）：非 FS 关系必须写理由（材料要求把非标准
        依赖的缘由记进 BoE）；滞后可负（= lead，材料把 leads 与 lags 并列提到）；
      · **工期口径挂在日历上**（days 工作日 / edays 日历天）：材料要"全表一个口径"，所以它是
        项目级设置而不是逐条活动设；
      · **基线是正交维度**：`baseline_start` 非空即已基线，它不改 `status`；
      · **回填实绩不碰基线**：`record_progress` 的写集合里没有基线列（BR-08，§7.3 原话）。

    业务规则落点：BR-01 禁开口端 / BR-02 逻辑链（四类型 + 滞后 + 非 FS 给理由 + 禁冗余）/
                 BR-03 完整且无环 / BR-04 里程碑工期为 0 / BR-05 必须挂在 WBS 叶子 /
                 BR-06 名称唯一 / BR-07 基线后走变更 / BR-08 回填实绩不动基线。
    """

    # ── 服务（公共方法即服务） ──────────────────────────────

    def create(self, name: str, wbs_no: str, duration_days: int = 1,
               kind: str = "activity", predecessors: str = None, owner: str = None,
               phase: str = None, note: str = None):
        """建一个活动（或汇总活动）。编号系统生成；`wbs_no` 必须是 **WBS 的叶子元素**。

        `predecessors` 用结构化写法：`ACT-001`（完成→开始、无滞后）· `ACT-002:SS:2`（开始→开始、
        滞后 2 天）· `ACT-003:FF:0:与总装并行`（**非 FS 必须给理由**）。
        """
        name = self._clean(name)
        if not name:
            raise FdeError("活动名称不能为空（BR-06）")
        self._check_kind(kind)
        self._check_name_free(name)                                  # BR-06
        wbs_no = self._need_leaf(wbs_no)                             # BR-05（跨应用）
        phase = self._clean(phase)
        if phase and phase not in PHASES:
            raise FdeError(f"边界标记只能是 {'/'.join(PHASES)} 之一（BR-01）")
        dur = self._check_duration(kind, duration_days)              # BR-04
        rels = self._rels(predecessors, strict=True)                 # BR-02（类型/滞后/理由）
        self._assert_preds_exist(rels)                               # BR-03（存在性）
        self._assert_acyclic(None, rels)                             # BR-03（无环）
        self._assert_no_redundant(None, rels)                        # BR-02

        act_no = self._next_no()
        self.db.execute(
            "INSERT INTO activity (act_no, name, kind, phase, wbs_no, duration_days,"
            " predecessors, owner, status, percent_complete, note)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'planned', 0, ?)",
            (act_no, name, kind, phase or None, wbs_no, dur,
             self._fmt_rels(rels) or None, self._clean(owner), self._clean(note)),
        )
        return self.get(act_no)

    def add_milestone(self, name: str, wbs_no: str, predecessors: str = None,
                      owner: str = None, phase: str = None, note: str = None):
        """建里程碑（工期恒 0 的便捷入口 —— 里程碑是**事件**不是工作，§5.5.7.1）。"""
        return self.create(name=name, wbs_no=wbs_no, duration_days=0, kind="milestone",
                           predecessors=predecessors, owner=owner, phase=phase, note=note)

    def get(self, act_no: str):
        """按编号查活动（带回 `pred_list` 结构化逻辑链与当前日历口径）；未命中返回 None。"""
        act_no = self._clean(act_no)
        if not act_no:
            return None
        row = self.db.execute(
            "SELECT act_no, name, kind, phase, wbs_no, duration_days, predecessors, owner,"
            " status, percent_complete, actual_start, actual_finish, baseline_start,"
            " baseline_finish, change_no, note FROM activity WHERE act_no = ?", (act_no,),
        ).fetchone()
        if not row:
            return None
        out = dict(row)
        out["pred_list"] = self._rels(out["predecessors"])
        # ⚠ 不要在这里塞日历字段（口径/假日是**日历级**的，不是行级属性）——
        #   `get` 一旦比 `list` 多出字段，「列表项与 get 同口径」这条既有断言会当场失效（实测）。
        #   日历走 `list_calendars` / `schedule_view`。
        return out

    def list(self, status: str = None, kind: str = None, wbs_no: str = None,
             owner: str = None, baselined: str = None, keyword: str = None,
             page: int = None, size: int = None):
        """按状态 / 类型 / 挂靠元素 / 责任方 / 是否已基线 / 关键词筛选，**分页返回 `{items,total}`**。

        ⚠ `page`/`size` 与 `{items,total}` 是前端 `pageable` 的契约（VIEW_CONVENTION）——
        返回裸数组时页面显示空态而不报错（同组实测踩过）。
        """
        where, args = [], []
        for col, val in (("status", status), ("kind", kind), ("wbs_no", wbs_no), ("owner", owner)):
            val = self._clean(val)
            if val:
                where.append(f"{col} = ?")
                args.append(val)
        b = self._clean(baselined)
        if b in ("1", "true", "yes"):
            where.append("baseline_start IS NOT NULL")
        elif b in ("0", "false", "no"):
            where.append("baseline_start IS NULL")
        kw = self._clean(keyword)
        if kw:
            where.append("(act_no LIKE ? OR name LIKE ? OR wbs_no LIKE ?)")
            args += [f"%{kw}%"] * 3
        sql = ("SELECT act_no, name, kind, phase, wbs_no, duration_days, predecessors, owner,"
               " status, percent_complete, actual_start, actual_finish, baseline_start,"
               " baseline_finish, change_no, note FROM activity")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY act_no"
        rows = []
        for r in self.db.execute(sql, tuple(args)).fetchall():
            d = dict(r)
            d["pred_list"] = self._rels(d["predecessors"])
            rows.append(d)
        total = len(rows)
        if size:
            p = max(int(page or 1), 1)
            n = max(int(size), 1)
            rows = rows[(p - 1) * n: p * n]
        return {"items": rows, "total": total}

    def update(self, act_no: str, name: str = None, duration_days: int = None,
               predecessors: str = None, wbs_no: str = None, owner: str = None,
               note: str = None, change_no: str = None):
        """改**计划字段**（名称 / 工期 / 逻辑链 / 挂靠元素 / 责任方 / 备注）。

        BR-07：**已基线**的活动必须先 `change(act_no, change_no)` 挂上已批准的变更号才允许改
        —— 材料 §7.3：进度基线受项目的变更控制过程控制。**编号不可改**（不在可改字段里）。
        """
        cur = self._need(act_no)
        cn = self._clean(change_no)
        if cur["baseline_start"] and not cn:
            raise FdeError(
                f"活动 {act_no} 已基线（{cur['baseline_start']}），改动必须走变更流程："
                "先 change(act_no, change_no) 挂上已批准的变更号（BR-07）")
        sets, args = [], []
        nm = self._clean(name)
        if nm:
            self._check_name_free(nm, exclude=act_no)                # BR-06
            sets.append("name = ?")
            args.append(nm)
        if duration_days is not None:
            sets.append("duration_days = ?")
            args.append(self._check_duration(cur["kind"], duration_days))   # BR-04
        if predecessors is not None:
            rels = self._rels(predecessors, strict=True)             # BR-02
            self._assert_preds_exist(rels)                           # BR-03
            self._assert_acyclic(act_no, rels)                       # BR-03（改链也要查环）
            self._assert_no_redundant(act_no, rels)                  # BR-02
            sets.append("predecessors = ?")
            args.append(self._fmt_rels(rels) or None)
        wb = self._clean(wbs_no)
        if wb:
            sets.append("wbs_no = ?")
            args.append(self._need_leaf(wb))                         # BR-05
        ow = self._clean(owner)
        if ow:
            sets.append("owner = ?")
            args.append(ow)
        nt = self._clean(note)
        if nt:
            sets.append("note = ?")
            args.append(nt)
        if cn:
            sets.append("change_no = ?")
            args.append(cn)
        if not sets:
            raise FdeError("没有要修改的内容")
        args.append(act_no)
        self.db.execute("UPDATE activity SET " + ", ".join(sets) + " WHERE act_no = ?",
                        tuple(args))
        return self.get(act_no)

    def link(self, act_no: str, predecessor_no: str, rel_type: str = "FS",
             lag_days: int = 0, reason: str = None):
        """给活动加一条前置关系（默认 **完成→开始（FS）、无滞后**）。

        四种关系模型（§5.5.8.2）：`FS` 完成→开始 · `SS` 开始→开始 · `FF` 完成→完成 · `SF` 开始→完成。
        `lag_days` 是滞后（材料：「a finish-to-start relationship and a 5-day lag will result in the
        successor task's start being delayed until 5 days after the completion of the predecessor」）；
        可给负数（= 提前量 / lead）。

        ⚠ **非 FS 必须给 `reason`** —— 材料要求把非标准依赖的缘由记进 BoE：
        「document the rationale for non-standard dependencies between activities (e.g., relationships
        other than Finish-to-Start), as well as the use of leads, lags, or constraints」。

        其余闸门：前置必须存在（BR-03）· 不得成环（BR-03）· 不得冗余（BR-02）。
        """
        cur = self._need(act_no)
        pid = self._clean(predecessor_no)
        if not pid:
            raise FdeError("前置活动编号不能为空（BR-03）")
        if pid == act_no:
            raise FdeError("活动不能以自己为前置（BR-03）")
        self._assert_preds_exist([{"pred": pid}])
        old = self._rels(cur["predecessors"])
        if any(x["pred"] == pid for x in old):
            raise FdeError(f"{act_no} 已经有前置 {pid} 了")
        rel = self._check_rel({"pred": pid, "type": self._clean(rel_type).upper() or "FS",
                               "lag": lag_days, "reason": self._clean(reason)}, strict=True)
        self._assert_no_redundant(act_no, old + [rel])               # BR-02
        self._assert_acyclic(act_no, old + [rel])                    # BR-03
        if cur["baseline_start"]:
            # 连逻辑链同样改变时间相位 ⇒ 与改工期同款闸门（BR-07）
            raise FdeError(
                f"活动 {act_no} 已基线，改逻辑链必须先走变更流程（先 change 挂变更号，BR-07）")
        self.db.execute("UPDATE activity SET predecessors = ? WHERE act_no = ?",
                        (self._fmt_rels(old + [rel]), act_no))
        return self.get(act_no)

    def unlink(self, act_no: str, predecessor_no: str):
        """断掉一条前置。已基线的活动同样要走变更流程（BR-07）。"""
        cur = self._need(act_no)
        pid = self._clean(predecessor_no)
        rels = self._rels(cur["predecessors"])
        if not any(x["pred"] == pid for x in rels):
            raise FdeError(f"{act_no} 没有前置 {pid}")
        if cur["baseline_start"]:
            raise FdeError(f"活动 {act_no} 已基线，改逻辑链必须先走变更流程（BR-07）")
        left = [x for x in rels if x["pred"] != pid]
        self.db.execute("UPDATE activity SET predecessors = ? WHERE act_no = ?",
                        (self._fmt_rels(left) or None, act_no))
        return self.get(act_no)

    def check_network(self):
        """网络体检：返回**图论与格式可判**的问题 + 两类跨应用问题（挂靠非叶子 / 叶子无活动）。

        · `open_ends`     开口端（非边界活动入度或出度为 0）—— §5.5.8 的 no "open ends"
        · `redundant`     冗余链接（直接边被传递闭包覆盖）—— §5.5.8 原文的例子
        · `cycles`        环 —— 有环就没有可行执行序
        · `bad_duration`  工期异常（里程碑 ≠ 0 / 活动 ≤ 0）
        · `bad_rel`       关系不合法（类型不在四值里、或**非 FS 没写理由**）—— §5.5.8.2
        · `non_leaf`      挂靠的 WBS 元素**已不是叶子**（元素下面长了新子元素）—— 跨应用读 `wbs`
        · `no_activity`   **还没有任何活动的 WBS 叶子元素** —— 材料 WBS 手册 §4 原话：
          "The lowest level of each WBS element should have at least one task or activity"。
          这是**反方向**的判据（`non_leaf` 管"活动挂错了地方"，它管"地方还空着"）；
          只报**未收口**的元素（已关闭的不再要求补活动）。
        """
        rows = self.list()["items"]
        idx = {r["act_no"]: r for r in rows}
        edges = {r["act_no"]: [x["pred"] for x in r["pred_list"] if x["pred"] in idx] for r in rows}

        open_ends = []
        for no, r in idx.items():
            # ⚠ 边界里程碑的豁免是**单向**的：`start` 只免"缺前置"、`finish` 只免"缺后续"。
            if not edges[no] and r["phase"] != "start":
                open_ends.append({"act_no": no, "name": r["name"], "missing": "前置"})
            if not any(no in v for v in edges.values()) and r["phase"] != "finish":
                open_ends.append({"act_no": no, "name": r["name"], "missing": "后续"})

        redundant = []
        for no, preds in edges.items():
            for p in preds:
                # 判据：**去掉这条直连边之后**，p 是否仍是 no 的祖先（即还存在长度 ≥2 的路径）
                sub = dict(edges)
                sub[no] = [q for q in preds if q != p]
                if p in self._ancestors(no, sub):
                    redundant.append({"act_no": no, "predecessor": p})

        cycles = self._find_cycles(edges)

        bad_duration = [{"act_no": r["act_no"], "kind": r["kind"],
                         "duration_days": r["duration_days"]}
                        for r in rows
                        if (r["kind"] == "milestone" and r["duration_days"] != 0)
                        or (r["kind"] == "activity" and r["duration_days"] <= 0)]

        bad_rel = []
        for r in rows:
            for x in r["pred_list"]:
                if x["type"] not in RELS:
                    bad_rel.append({"act_no": r["act_no"], "predecessor": x["pred"],
                                    "why": f"关系类型 {x['type']} 不在 {'/'.join(RELS)} 里"})
                elif x["type"] != "FS" and not x.get("reason"):
                    bad_rel.append({"act_no": r["act_no"], "predecessor": x["pred"],
                                    "why": f"非 FS 关系（{x['type']}）必须写明理由（§5.5.8.2）"})

        non_leaf = []
        for no, r in idx.items():
            if self._wbs_children(r["wbs_no"]):
                non_leaf.append({"act_no": no, "wbs_no": r["wbs_no"]})

        # 反方向判据（跨应用读 `wbs`，一次取全表在内存里判叶子）：**还空着的最底层元素**。
        # ⚠ 跨应用读失败**不静默降级**（同 `_wbs_children`）：体检答不出就说答不出。
        try:
            els = (self.fde.call("wbs", "list", page=1, size=9999) or {}).get("items") or []
        except Exception as e:
            raise FdeError(f"体检失败：wbs 应用不可用（{str(e)[:60]}）")
        parents = {e["parent_no"] for e in els if e.get("parent_no")}
        covered = {r["wbs_no"] for r in rows}
        no_activity = [{"wbs_no": e["wbs_no"], "title": e["title"], "status": e["status"]}
                       for e in els
                       if e["wbs_no"] not in parents and e["wbs_no"] not in covered
                       and e["status"] != "closed"]

        problems = (len(open_ends) + len(redundant) + len(cycles) + len(bad_duration)
                    + len(bad_rel) + len(non_leaf) + len(no_activity))
        return {"total": problems, "activities": len(rows), "open_ends": open_ends,
                "redundant": redundant, "cycles": cycles, "bad_duration": bad_duration,
                "bad_rel": bad_rel, "non_leaf": non_leaf, "no_activity": no_activity}

    def schedule_view(self, project_start: str = None, calendar_no: str = None):
        """**派生排程**：按四种关系 + 滞后正推最早日期、逆推最晚日期、算浮时、标关键路径。

        材料 §5.5.9.3：日期由**逻辑与工期**决定，而不是为凑某个完成日填的 —— 所以日期不落库、
        在这里现算。工期口径与假日表取自**日历**（`unit` = days 工作日 / edays 日历天）。
        前置为空的活动（开口端）从 `project_start` 起算，`check_network` 会把它们报出来。
        """
        cal = self._cal(calendar_no)
        rows = self.list()["items"]
        idx = {r["act_no"]: r for r in rows}
        edges = {r["act_no"]: [x for x in r["pred_list"] if x["pred"] in idx] for r in rows}
        plain = {n: [x["pred"] for x in ps] for n, ps in edges.items()}
        order = self._topo(plain)
        start = self._parse_date(project_start) or _dt.date.today()
        span = {n: max(int(r["duration_days"]) - 1, 0) for n, r in idx.items()}

        es, ef = self._forward(order, edges, span)
        finish = max(ef.values(), default=0)
        ls, lf = self._backward(order, edges, span, finish)

        out = []
        for no in order:
            r = idx[no]
            total = ls[no] - es[no]
            out.append(dict(r, early_start=self._date_at(start, es[no], cal),
                            early_finish=self._date_at(start, ef[no], cal),
                            late_start=self._date_at(start, ls[no], cal),
                            late_finish=self._date_at(start, lf[no], cal),
                            float_days=total, critical=(total == 0),
                            offset_start=es[no], offset_finish=ef[no]))
        return {"project_start": start.isoformat(),
                "project_finish": self._date_at(start, finish, cal),
                "calendar_no": cal["cal_no"], "unit": cal["unit"],
                "unit_cn": UNIT_CN.get(cal["unit"], cal["unit"]),
                "holidays": self._holidays(cal), "items": out}

    def critical_path(self, project_start: str = None, calendar_no: str = None):
        """只取关键路径（浮时为 0 的活动，按最早开始排序）。"""
        view = self.schedule_view(project_start, calendar_no)
        crit = [x for x in view["items"] if x["critical"]]
        return {"project_start": view["project_start"], "project_finish": view["project_finish"],
                "calendar_no": view["calendar_no"], "items": crit, "total": len(crit)}

    def baseline(self, act_nos, project_start: str = None, calendar_no: str = None):
        """建立进度基线：把**派生日期**冻进 `baseline_start` / `baseline_finish`。

        材料 §7.3 允许两种粒度（整条 IMS / 只基线化关键里程碑子集）—— 这里传哪几个就基线哪几个。
        已基线的活动重跑会覆盖（= 变更落实后的重新冻基线）。
        """
        nos = self._as_list(act_nos)
        if not nos:
            raise FdeError("要基线哪些活动？请给出 act_no（材料允许只基线化关键里程碑子集，§7.3）")
        # ⚠ `project_start` 必须透传：不透传就按"今天"算，冻下来的基线与用户看到的排程不是同一个基准
        view = {x["act_no"]: x for x in self.schedule_view(project_start, calendar_no)["items"]}
        done = []
        for no in nos:
            cur = self._need(no)
            x = view.get(no)
            if not x:
                raise FdeError(f"活动 {no} 不在排程视图里（可能挂在环上）")
            self.db.execute(
                "UPDATE activity SET baseline_start = ?, baseline_finish = ? WHERE act_no = ?",
                (x["early_start"], x["early_finish"], no))
            done.append(self.get(cur["act_no"]))
        return {"baselined": len(done), "items": done}

    def change(self, act_no: str, change_no: str, note: str = None):
        """对已基线的活动发起修订：挂上**已批准**的变更号（跨应用只读校验 `change_request.get`）。

        材料 §7.3：进度基线的维护受项目的变更控制过程控制。挂上变更号之后才允许 `update`
        （BR-07）；**实绩照旧可以随时回填**（那不动基线，§7.3 末句）。
        """
        cur = self._need(act_no)
        cn = self._clean(change_no)
        if not cn:
            raise FdeError("发起修订必须给出已批准的变更请求号（BR-07，材料 §7.3）")
        if not cur["baseline_start"]:
            raise FdeError(f"活动 {act_no} 还没基线，直接改即可（不需要变更流程，BR-07）")
        cr = self.fde.call("change_request", "get", cr_no=cn)
        if not cr:
            raise FdeError(f"变更请求 {cn} 不存在（BR-07）")
        if cr.get("status") != "approved":
            raise FdeError(f"变更请求 {cn} 当前为「{cr.get('status')}」，尚未批准 —— "
                           "已基线的活动只能按已批准的变更修订（BR-07）")
        sets, args = ["change_no = ?"], [cn]
        nt = self._clean(note)
        if nt:
            sets.append("note = ?")
            args.append(nt)
        args.append(act_no)
        self.db.execute("UPDATE activity SET " + ", ".join(sets) + " WHERE act_no = ?",
                        tuple(args))
        return self.get(act_no)

    def record_progress(self, act_no: str, percent_complete: int = None,
                        actual_start: str = None, actual_finish: str = None, note: str = None):
        """回填实绩：实际开始 / 完成 / 完成百分比。

        ⚠ **写集合里没有基线列**（BR-08）—— 材料 §7.3 原话：「This procedure does not change any
        baseline data … but reports actuals and current performance **against** that baseline」。
        状态由百分比派生：0 且无实际开始 → `planned`；100 且有实际完成 → `completed`；其余 `in_progress`。
        """
        cur = self._need(act_no)
        sets, args = [], []
        pct = cur["percent_complete"]
        if percent_complete is not None:
            pct = max(0, min(100, int(percent_complete)))
            sets.append("percent_complete = ?")
            args.append(pct)
        a_s = self._clean(actual_start)
        a_f = self._clean(actual_finish)
        if a_s:
            self._parse_date(a_s) or self._bad_date("actual_start", a_s)
            sets.append("actual_start = ?")
            args.append(a_s)
        if a_f:
            self._parse_date(a_f) or self._bad_date("actual_finish", a_f)
            sets.append("actual_finish = ?")
            args.append(a_f)
        st = "completed" if (pct >= 100 and (a_f or cur["actual_finish"])) else (
            "in_progress" if (pct > 0 or a_s or cur["actual_start"]) else "planned")
        sets.append("status = ?")
        args.append(st)
        nt = self._clean(note)
        if nt:
            sets.append("note = ?")
            args.append(nt)
        args.append(act_no)
        self.db.execute("UPDATE activity SET " + ", ".join(sets) + " WHERE act_no = ?",
                        tuple(args))
        return self.get(act_no)

    # ── 日历（§5.5.9.2：P/p 通常有一个默认日历定义工作日与非工作日）──────

    def create_calendar(self, name: str, unit: str = "days", holidays: str = None,
                        is_default: bool = False):
        """建一个工作日历。`unit` 是**项目级口径**：`days`（工作日，跳过周末与假日）/ `edays`（日历天）。

        ⚠ 材料 §5.5.9.1 要求「be consistent throughout the schedule」—— 所以口径挂在日历上、
        全表共用，不逐条活动设。
        """
        name = self._clean(name)
        if not name:
            raise FdeError("日历名称不能为空")
        unit = self._clean(unit).lower() or "days"
        if unit not in UNITS:
            raise FdeError(f"工期口径只能是 {'/'.join(UNITS)} 之一（"
                           f"{'/'.join(UNIT_CN[u] for u in UNITS)}；材料 §5.5.9.1）")
        cal_no = self._next_cal_no()
        if is_default or not self._cal_rows():
            self.db.execute("UPDATE work_calendar SET is_default = 0")
            is_default = True
        self.db.execute(
            "INSERT INTO work_calendar (cal_no, name, unit, holidays, is_default)"
            " VALUES (?, ?, ?, ?, ?)",
            (cal_no, name, unit, self._norm_holidays(holidays), 1 if is_default else 0))
        return self.get_calendar(cal_no)

    def get_calendar(self, cal_no: str):
        """按编号取日历；未命中返回 None。"""
        cal_no = self._clean(cal_no)
        if not cal_no:
            return None
        row = self.db.execute(
            "SELECT cal_no, name, unit, holidays, is_default FROM work_calendar WHERE cal_no = ?",
            (cal_no,)).fetchone()
        return dict(row) if row else None

    def list_calendars(self):
        """全部日历（默认的排前面）。

        ⚠ 空库上要先**确保默认日历存在**：`schedule_view` 用不到它时才自动建，而前端一进来就调本服务
        （选择器要是空的，用户连口径都看不到）。实测：e2e 在干净影子库上跑，选择器为空。
        """
        self._cal(None)
        rows = [dict(r) for r in self.db.execute(
            "SELECT cal_no, name, unit, holidays, is_default FROM work_calendar"
            " ORDER BY is_default DESC, cal_no")]
        return {"items": rows, "total": len(rows)}

    def update_calendar(self, cal_no: str, name: str = None, unit: str = None,
                        holidays: str = None, add_holiday: str = None,
                        remove_holiday: str = None, is_default: bool = None):
        """改日历（名称 / 工期口径 / 假日表）。`add_holiday` / `remove_holiday` 是单条增删的便捷入口。"""
        cur = self.get_calendar(cal_no)
        if not cur:
            raise FdeError(f"日历 {self._clean(cal_no) or '（空）'} 不存在")
        sets, args = [], []
        nm = self._clean(name)
        if nm:
            sets.append("name = ?")
            args.append(nm)
        u = self._clean(unit).lower()
        if u:
            if u not in UNITS:
                raise FdeError(f"工期口径只能是 {'/'.join(UNITS)} 之一")
            sets.append("unit = ?")
            args.append(u)
        hol = self._holidays(cur)
        touched = False
        if holidays is not None:
            hol = [h for h in (self._norm_holidays(holidays) or "").split(",") if h]
            touched = True
        add = self._clean(add_holiday)
        if add:
            self._parse_date(add) or self._bad_date("add_holiday", add)
            hol = sorted(set(hol) | {add})
            touched = True
        rm = self._clean(remove_holiday)
        if rm:
            hol = [h for h in hol if h != rm]
            touched = True
        if touched:
            sets.append("holidays = ?")
            args.append(",".join(hol) or None)
        if is_default is not None:
            if is_default:
                self.db.execute("UPDATE work_calendar SET is_default = 0")
            sets.append("is_default = ?")
            args.append(1 if is_default else 0)
        if not sets:
            raise FdeError("没有要修改的内容")
        args.append(cur["cal_no"])
        self.db.execute("UPDATE work_calendar SET " + ", ".join(sets) + " WHERE cal_no = ?",
                        tuple(args))
        return self.get_calendar(cur["cal_no"])

    # ── 私有（非服务） ────────────────────────────────────

    @staticmethod
    def _clean(v):
        return str(v).strip() if v is not None else ""

    # —— 逻辑链的解析与格式化（结构化字符串 `PRED[:类型[:滞后[:理由]]]`）——

    def _rels(self, v, strict: bool = False):
        """把前置字段解析成 `[{pred, type, lag, reason}]`。裸编号按 **FS + 0 滞后**展开（向后兼容）。"""
        if v is None:
            return []
        parts = v if isinstance(v, (list, tuple)) else str(v).split(",")
        out = []
        for raw in parts:
            if isinstance(raw, dict):
                out.append(self._check_rel(raw, strict))
                continue
            s = str(raw).strip()
            if not s:
                continue
            bits = s.split(":")
            # ⚠ 多出第四段 ⇒ 理由里写了冒号：**不报错就会被静默截断**（只剩冒号前那半句）
            if len(bits) > 4:
                raise FdeError(
                    f"逻辑链写法最多四段（编号:类型:滞后:理由），收到 {len(bits)} 段 —— "
                    f"多出来的那段说明理由里出现了冒号：{s}")
            out.append(self._check_rel(
                {"pred": bits[0].strip(),
                 "type": (bits[1].strip().upper() if len(bits) > 1 else "FS"),
                 "lag": (bits[2].strip() if len(bits) > 2 else 0),
                 "reason": (bits[3].strip() if len(bits) > 3 else "")}, strict))
        seen, uniq = set(), []
        for x in out:
            if x["pred"] in seen:
                continue
            seen.add(x["pred"])
            uniq.append(x)
        return uniq

    def _check_rel(self, item, strict: bool):
        """校验一条关系：类型四值枚举、滞后为整数、**非 FS 必须给理由**（§5.5.8.2）。"""
        t = self._clean(item.get("type")).upper() or "FS"
        if t not in RELS:
            raise FdeError(f"逻辑关系只能是 {'/'.join(RELS)} 之一（"
                           f"{'/'.join(REL_CN[r] for r in RELS)}）；材料 §5.5.8.2 的四种关系模型")
        try:
            lag = int(item.get("lag") or 0)
        except (TypeError, ValueError):
            raise FdeError(f"滞后必须是整数天（可负 = 提前量/lead）；收到 {item.get('lag')!r}")
        reason = self._clean(item.get("reason"))
        if t != "FS" and not reason:
            raise FdeError(
                f"非标准关系（{t} {REL_CN[t]}）必须写明理由 —— 材料 §5.5.8.2 要求把非标准依赖的"
                "缘由记进 BoE（『document the rationale for non-standard dependencies … relationships "
                "other than Finish-to-Start, as well as the use of leads, lags, or constraints』）")
        if reason and ("," in reason or ":" in reason):
            raise FdeError("关系理由里不能出现逗号或冒号（它们是本字段的分隔符）")
        return {"pred": self._clean(item.get("pred")), "type": t, "lag": lag, "reason": reason}

    @staticmethod
    def _fmt_rels(rels):
        out = []
        for x in rels:
            if x["type"] == "FS" and not x["lag"] and not x["reason"]:
                out.append(x["pred"])                       # 最常见的一种写成裸编号，读起来干净
            elif x["reason"]:
                out.append(f"{x['pred']}:{x['type']}:{x['lag']}:{x['reason']}")
            elif x["lag"]:
                out.append(f"{x['pred']}:{x['type']}:{x['lag']}")
            else:
                out.append(f"{x['pred']}:{x['type']}")
        return ",".join(out)

    # —— 排程内核（四种关系 + 滞后，迭代松弛到收敛）——

    @staticmethod
    def _forward(order, edges, span):
        """正推 ES/EF（偏移域）。四种关系：
        FS: ES ≥ EF(p)+1+lag · SS: ES ≥ ES(p)+lag · FF: EF ≥ EF(p)+lag · SF: EF ≥ ES(p)+lag
        """
        ES = {n: 0 for n in order}
        EF = {n: 0 for n in order}
        for _ in range(len(order) * 3 + 3):
            changed = False
            for n in order:
                es = ES[n]
                for x in edges[n]:
                    p, T, lag = x["pred"], x["type"], x["lag"]
                    if T == "FS":
                        es = max(es, EF[p] + 1 + lag)
                    elif T == "SS":
                        es = max(es, ES[p] + lag)
                    elif T == "FF":
                        es = max(es, EF[p] + lag - span[n])
                    elif T == "SF":
                        es = max(es, ES[p] + lag - span[n])
                ef = es + span[n]
                if es != ES[n] or ef != EF[n]:
                    ES[n], EF[n], changed = es, ef, True
            if not changed:
                break
        return ES, EF

    @staticmethod
    def _backward(order, edges, span, finish):
        """逆推 LS/LF（偏移域）。反向约束：
        FS: LF(p) ≤ LS(n)-1-lag · FF: LF(p) ≤ LF(n)-lag · SS: LS(p) ≤ LS(n)-lag · SF: LS(p) ≤ LF(n)-lag
        """
        succ = {n: [] for n in order}
        for n in order:
            for x in edges[n]:
                succ[x["pred"]].append((n, x))
        LF = {n: finish for n in order}
        LS = {n: finish - span[n] for n in order}
        for _ in range(len(order) * 3 + 3):
            changed = False
            for n in reversed(order):
                lf = LF[n]
                for (m, x) in succ[n]:
                    T, lag = x["type"], x["lag"]
                    if T == "FS":
                        lf = min(lf, LS[m] - 1 - lag)
                    elif T == "FF":
                        lf = min(lf, LF[m] - lag)
                    elif T == "SS":
                        lf = min(lf, LS[m] - lag + span[n])
                    elif T == "SF":
                        lf = min(lf, LF[m] - lag + span[n])
                ls = lf - span[n]
                if lf != LF[n] or ls != LS[n]:
                    LF[n], LS[n], changed = lf, ls, True
            if not changed:
                break
        return LS, LF

    # —— 日历 ——

    def _cal_rows(self):
        return [dict(r) for r in self.db.execute(
            "SELECT cal_no, name, unit, holidays, is_default FROM work_calendar")]

    def _cal(self, cal_no=None):
        """取日历；没给编号就用默认日历；一张都没有就**自动建一张默认日历**（周一~周五、days）。"""
        want = self._clean(cal_no)
        if want:
            c = self.get_calendar(want)
            if not c:
                raise FdeError(f"日历 {want} 不存在")
            return c
        rows = self._cal_rows()
        if not rows:
            return self.create_calendar("项目默认日历", unit="days", is_default=True)
        for c in rows:
            if c["is_default"]:
                return c
        return rows[0]

    def _default_cal(self):
        return self._cal(None)

    @staticmethod
    def _holidays(cal):
        return [h for h in str(cal.get("holidays") or "").split(",") if h]

    def _norm_holidays(self, holidays):
        if holidays is None:
            return None
        got = []
        for h in str(holidays).split(","):
            h = h.strip()
            if not h:
                continue
            self._parse_date(h) or self._bad_date("holiday", h)
            if h not in got:
                got.append(h)
        return ",".join(got) or None

    def _next_cal_no(self):
        n = 1
        for r in self.db.execute("SELECT cal_no FROM work_calendar"):
            s = str(r["cal_no"])
            if s.startswith("CAL-") and s[4:].isdigit():
                n = max(n, int(s[4:]) + 1)
        return f"CAL-{n:03d}"

    def _workday(self, d: _dt.date, cal) -> bool:
        """这一天是不是工作日：非周末、且不在假日表里（`edays` 口径下忽略非工作时段）。"""
        if cal["unit"] == "edays":
            return True
        return d.weekday() < 5 and d.isoformat() not in self._holidays(cal)

    def _date_at(self, start: _dt.date, offset: int, cal):
        """把**偏移**换算成日期。`days` → 第 offset 个工作日（跳过周末与假日）；
        `edays` → 直接加 offset 个日历天（材料 §5.5.9.1：elapsed duration 忽略非工作时段）。"""
        if cal["unit"] == "edays":
            return (start + _dt.timedelta(days=max(offset, 0))).isoformat()
        d, n = start, max(offset, 0)
        while not self._workday(d, cal):
            d += _dt.timedelta(days=1)
        while n > 0:
            d += _dt.timedelta(days=1)
            if self._workday(d, cal):
                n -= 1
        return d.isoformat()

    # —— 其余私有 ——

    @staticmethod
    def _as_list(v):
        return [x.strip() for x in (v if isinstance(v, (list, tuple)) else str(v or "").split(","))
                if x.strip()]

    def _next_no(self):
        n = 1
        for r in self.db.execute("SELECT act_no FROM activity"):
            s = str(r["act_no"])
            if s.startswith("ACT-") and s[4:].isdigit():
                n = max(n, int(s[4:]) + 1)
        return f"ACT-{n:03d}"

    def _rows(self):
        return self.list()["items"]

    def _check_kind(self, kind: str):
        if kind not in KINDS:
            raise FdeError(f"类型只能是 {'/'.join(KINDS)} 之一"
                           f"（{'/'.join(KIND_CN[k] for k in KINDS)}）")

    def _check_duration(self, kind: str, d):
        """BR-04：里程碑工期恒 0；活动工期必须 > 0。"""
        try:
            d = int(d)
        except (TypeError, ValueError):
            raise FdeError("工期必须是整数（口径由日历决定：工作日 / 日历天，§5.5.9）")
        if kind == "milestone" and d != 0:
            raise FdeError(f"里程碑的工期必须为 0（它是**事件**不是工作，§5.5.7.1）；收到 {d}")
        if kind == "activity" and d <= 0:
            raise FdeError(f"活动的工期必须大于 0（收到 {d}）")
        if d < 0:
            raise FdeError("工期不能为负")
        return d

    def _check_name_free(self, name: str, exclude: str = None):
        for r in self.db.execute("SELECT act_no, name FROM activity WHERE name = ?", (name,)):
            if exclude and r["act_no"] == exclude:
                continue
            raise FdeError(f"已存在同名活动「{name}」（{r['act_no']}）—— "
                           "活动与里程碑的描述必须唯一可区分（BR-06，§5.5.5）")

    def _need(self, act_no: str):
        cur = self.get(act_no)
        if not cur:
            raise FdeError(f"活动编号 {self._clean(act_no) or '（空）'} 不存在")
        return cur

    def _assert_preds_exist(self, rels):
        for x in rels:
            if not self.get(x["pred"]):
                raise FdeError(f"前置活动 {x['pred']} 不存在（BR-03：逻辑链必须完整）")

    def _wbs_children(self, wbs_no):
        try:
            r = self.fde.call("wbs", "list", parent_no=wbs_no, page=1, size=1)
        except Exception as e:
            raise FdeError(f"挂靠校验失败：wbs 应用不可用（{str(e)[:60]}）")
        return (r or {}).get("items") or []

    def _need_leaf(self, wbs_no: str):
        """BR-05：挂靠的 WBS 元素必须存在**且是叶子**（跨应用只读）。"""
        wbs_no = self._clean(wbs_no)
        if not wbs_no:
            raise FdeError("必须挂在某个 WBS 元素上（BR-05）")
        try:
            el = self.fde.call("wbs", "get", wbs_no=wbs_no)
        except Exception as e:
            raise FdeError(f"挂靠校验失败：wbs 应用不可用（{str(e)[:60]}）")
        if not el:
            raise FdeError(f"WBS 元素 {wbs_no} 不存在，请先在 WBS 台账里登记（BR-05）")
        kids = self._wbs_children(wbs_no)
        if kids:
            raise FdeError(
                f"WBS 元素 {wbs_no} 下面还有 {len(kids)} 个子元素 —— 活动只能挂在**最底层元素**上"
                f"（BR-05，材料 §4.3）；请挂到它的子元素上")
        return wbs_no

    @staticmethod
    def _ancestors(act_no, edges):
        """`act_no` 的全部祖先（前置的传递闭包）。

        ⚠ 别加"跳过某个节点"的参数：冗余判据恰恰要靠**那个节点出现在祖先集里**才算成立。
        """
        seen, stack = set(), list(edges.get(act_no, []))
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            stack.extend(edges.get(x, []))
        return seen

    def _assert_no_redundant(self, act_no, rels):
        """BR-02：**前置集合里若有一条已被别的路径蕴含**，就是冗余链接。

        判据（一条式子覆盖两种入口）：p 冗余 ⟺ 集合里存在另一个 q，使得 **p 是 q 的祖先**。
        · 连边：A→B、B→C 之后连 A→C —— 集合是 [B, A]，A 是 B 的祖先 ⇒ 冗余（§5.5.8 的例子）
        · 建活动：一次性塞 [A, B] 而 A→B 已存在 ⇒ 冗余
        """
        edges = {r["act_no"]: [x["pred"] for x in r["pred_list"]] for r in self._rows()}
        preds = [x["pred"] if isinstance(x, dict) else x for x in rels]
        for p in preds:
            for q in preds:
                if q == p:
                    continue
                if p in self._ancestors(q, edges):
                    raise FdeError(
                        f"{p} → {self._clean(act_no) or '（新活动）'} 是**冗余链接**："
                        f"{p} 已经通过 {q} 间接前置了它（BR-02，材料 §5.5.8 的例子："
                        "A→B、B→C 时 A→C 冗余）")

    def _assert_acyclic(self, act_no, rels):
        """BR-03：把 `act_no` 的前置设为 `rels` 后，网络不得成环。"""
        edges = {r["act_no"]: [x["pred"] for x in r["pred_list"]] for r in self._rows()}
        edges[self._clean(act_no) or "\x00new"] = [x["pred"] for x in rels]
        cyc = self._find_cycles(edges)
        if cyc:
            raise FdeError(f"这条前置关系会让逻辑链成环（BR-03）：{cyc[:1]}")

    @staticmethod
    def _find_cycles(edges):
        WHITE, GREY, BLACK = 0, 1, 2
        color = dict.fromkeys(edges, WHITE)
        cycles = []

        def dfs(u, path):
            color[u] = GREY
            for v in edges.get(u, []):
                if v not in color:
                    continue
                if color[v] == GREY:
                    cycles.append(path + [u, v])
                elif color[v] == WHITE:
                    dfs(v, path + [u])
            color[u] = BLACK

        for n in list(edges):
            if color[n] == WHITE:
                dfs(n, [])
        return cycles

    @staticmethod
    def _topo(edges):
        """拓扑排序（Kahn）。有环时把剩下的按编号兜底拼上（体检会报环）。"""
        indeg = {n: 0 for n in edges}
        for n, ps in edges.items():
            for p in ps:
                if p in indeg:
                    indeg[n] += 1
        q = sorted([n for n, d in indeg.items() if d == 0])
        out = []
        while q:
            u = q.pop(0)
            out.append(u)
            for v, ps in edges.items():
                if u in ps:
                    indeg[v] -= 1
                    if indeg[v] == 0:
                        q.append(v)
                        q.sort()
        rest = [n for n in sorted(edges) if n not in out]
        return out + rest

    @staticmethod
    def _parse_date(s):
        s = (s or "").strip()
        if not s:
            return None
        for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
            try:
                return _dt.datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def _bad_date(field, val):
        raise FdeError(f"{field} 不是合法日期（用 YYYY-MM-DD）：{val}")
