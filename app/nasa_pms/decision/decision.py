from __future__ import annotations

import re

from fde import FdeError

# 评价方法字典（材料 §6.8.1.2.3 的典型方法 + §6.8.2 列出的工具 + §6.8.1.2.4 NOTE
# "Completing the decision matrix can be thought of as a default evaluation method" —— 故默认取加权决策矩阵）
EVAL_METHODS = ("weighted_matrix", "trade_study", "cost_benefit", "decision_tree",
                "influence_diagram", "ahp", "borda", "utility", "simulation",
                "testing", "review_meeting")
DEFAULT_METHOD = "weighted_matrix"
# 得分口径：0~100 的整数（材料 §6.8.1.2.4 的归一化 "low/medium/high"、"1-3-9" 或工具自动归一
# —— 本版取百分制做可比得分，属第②步就地细化，见详设 §6.3 与 新增术语.md）
SCORE_MAX = 100
# 硬终态：到达后一律拒（BR-06 后半）；已决策是「内容冻结」而非终态（BR-06 前半）
_TERMINAL = "implemented"
_FROZEN = ("decided",)
_STATUS_CN = {"proposed": "提出", "weighing": "权衡中",
              "decided": "已决策", "implemented": "已实施"}
_METHOD_CN = {"weighted_matrix": "加权决策矩阵", "trade_study": "权衡研究",
              "cost_benefit": "成本收益分析", "decision_tree": "决策树",
              "influence_diagram": "影响图", "ahp": "层次分析法",
              "borda": "波达计数", "utility": "效用分析", "simulation": "仿真",
              "testing": "测试验证", "review_meeting": "评审会商"}
# 主档字段清单 —— `get` 与 `list` **共用同一份**，杜绝两处口径漂移（CONVENTION §7）
_MAIN_COLS = ("dec_no, topic, issue, measure_no, eval_method, status,"
              " chosen_seq, chosen_name, rationale, risk_note, dissent,"
              " implement_note, owner, project_no")


class Decision:
    """决策聚合根。一次技术决策，含评价准则、备选方案与结论。数据来源类型：独立创建。

    一致性边界（见 `architecture.md` 聚合根卡 8）：
      · **备选方案是聚合内的内部实体**（卡片核心属性「备选方案」）—— 它没有独立标识
        （`(dec_no, seq)` 复合主键，seq 只在本次决策内唯一），由 `add_option` 登记、
        `score_option` 打分、`conclude` 指向其中之一，全程只在本决策的事务里被读写；
        「跨决策的方案汇总」不在本版服务面内（没有卡片「并入说明」那样的查询视图需求）——
        引用备选方案必须连它的决策一起读（`get` 一次带回 criteria + options）。
      · **评价准则**同属聚合内（`add_criterion`，材料 §6.8.1.2.1 把它列为第一步）：
        准则先定义、方案后评估（BR-01），准则清单是「权衡」这件事的前置。
      · **结论是快照**：`conclude` 之后主档内容、准则与方案一起冻结（BR-06），
        不能再补准则 / 补方案 / 改分 / 改议题。
      · 评价准则「可能取自技术度量」（卡片引用的聚合 `technical_measure`）——只落一个
        **弱引用文本** `measure_no`：本版不做跨应用校验（`technical_measure` 已建成，
        接线只是加一行 `self.fde.call("technical_measure", "get", ...)`，见详设 §6.3）。

    业务规则落点：BR-01 准则为空不得启动权衡 / BR-02 备选方案少于两个不得结论（I-2）/
                 BR-03 结论必须指向有评价得分的备选方案（I-1）/ BR-04 选非最高分方案须给依据 /
                 BR-05 编号唯一且不可变 / BR-06 已决策冻结·已实施终态 / BR-07 评价方法受字典约束 /
                 BR-08 准则权重与评价得分的取值口径。
    """

    # ── 服务（公共方法即服务） ──────────────────────────────

    def create(self, topic: str, eval_method: str = DEFAULT_METHOD, measure_no: str = None,
               issue: str = None, owner: str = None, project_no: str = None):
        """新建一个决策议题，落库为「提出」状态，编号自动生成（`DC-001` 起）。

        议题非空校验 + 评价方法过字典（BR-07）。`measure_no`（准则来源的技术度量）、
        `issue`（议题说明）、`owner`、`project_no` 都是选填文本 —— `measure_no` 是**弱引用**，
        该应用待建成，本版只存不校验（详设 §6.3）。
        """
        topic = self._clean(topic)
        if not topic:
            raise FdeError("决策议题不能为空")
        eval_method = self._check_method(eval_method)               # BR-07

        dec_no = self._next_no()
        self.db.execute(
            "INSERT INTO decision (dec_no, topic, issue, measure_no, eval_method,"
            " status, owner, project_no) VALUES (?, ?, ?, ?, ?, 'proposed', ?, ?)",
            (dec_no, topic, self._clean(issue), self._clean(measure_no), eval_method,
             self._clean(owner), self._clean(project_no)),
        )
        return self.get(dec_no)

    def add_criterion(self, dec_no: str, criterion: str, weight=1):
        """往评价准则清单里加一条准则（提出 / 权衡中都可加，已决策后冻结，BR-06）。

        材料 §6.8.1.2.1 把「定义评价准则」列为决策分析的第一步，并要求给出
        "the acceptable range and scale of the criteria" 与 "the rank of each criterion
        by its importance" —— 后者在本版落成 `weight`（正整数，BR-08）。
        """
        cur = self._need(dec_no)
        self._check_frozen(cur)                                     # BR-06
        criterion = self._clean(criterion)
        if not criterion:
            raise FdeError("评价准则不能为空")
        w = self._int(weight, "准则权重")                            # BR-08

        seq = self._next_seq("decision_criterion", dec_no)
        self.db.execute(
            "INSERT INTO decision_criterion (dec_no, seq, criterion, weight)"
            " VALUES (?, ?, ?, ?)", (dec_no, seq, criterion, w),
        )
        return self.get(dec_no)

    def add_option(self, dec_no: str, name: str, description: str = None):
        """往备选方案清单里加一个方案（提出 / 权衡中都可加，已决策后冻结，BR-06）。

        材料 §6.8.1.2.2 "Identify Alternative Solutions to Address Decision Issues"：
        "Almost every decision will have options to choose from" —— 方案在定义准则之后登记
        （准则先、方案后，见 `start` 的 BR-01），并可反复增补直到出结论。
        方案**没有单独的打分入口**：打分走 `score_option`（权衡中才允许）。
        """
        cur = self._need(dec_no)
        self._check_frozen(cur)                                     # BR-06
        name = self._clean(name)
        if not name:
            raise FdeError("备选方案名称不能为空")

        seq = self._next_seq("decision_option", dec_no)
        self.db.execute(
            "INSERT INTO decision_option (dec_no, seq, name, description)"
            " VALUES (?, ?, ?, ?)", (dec_no, seq, name, self._clean(description)),
        )
        return self.get(dec_no)

    def start(self, dec_no: str):
        """开始权衡：提出 → 权衡中（`proposed → weighing`）。

        「开始评估」的标志 —— 材料 §6.8.1.2.1 的顺序是**先定义准则、再定义备选方案供评估**
        （"With this defined, a set of alternative solutions can be defined for evaluation"），
        所以准则清单为空时不许进入权衡（BR-01），也就谈不上打分。
        """
        cur = self._need(dec_no)
        # 守卫顺序 = 安全边界：硬终态排最前（否则终态能被后续分支绕过）
        if cur["status"] == _TERMINAL:
            raise FdeError(f"决策 {dec_no} 已实施（终态），不能再启动权衡（BR-06）")
        if cur["status"] in _FROZEN:
            raise FdeError(
                f"决策 {dec_no} 已作出决策（结论是快照），不能回到权衡中（BR-06）")
        if cur["status"] == "weighing":
            raise FdeError(f"决策 {dec_no} 已经处于权衡中")
        if not cur["criteria"]:                                     # BR-01
            raise FdeError(
                f"决策 {dec_no} 还没有评价准则，不能开始权衡 —— 准则先于备选方案的评估（BR-01）")
        self.db.execute(
            "UPDATE decision SET status = 'weighing' WHERE dec_no = ?", (dec_no,))
        return self.get(dec_no)

    def score_option(self, dec_no: str, seq, score, note: str = None):
        """给一个备选方案打评价得分（仅「权衡中」；`score` 为 0~100 的整数，BR-08）。

        材料 §6.8.1.2.4 "Evaluate Alternative Solutions with the Established Criteria and
        Selected Methods" —— 得分是归一化后的可比结果（决策矩阵可按工具自动归一）。
        **打的是全矩阵的口径分**（准则 × 权重加权后的总分），逐格打分不在本版子表结构里（详设 §6.3）。
        打分是**迭代的**（§6.8.1.2.4 NOTE "Completing the decision matrix is iterative"），
        所以允许反复改分，直到 `conclude` 冻结。
        """
        cur = self._need(dec_no)
        if cur["status"] == _TERMINAL:
            raise FdeError(f"决策 {dec_no} 已实施（终态），不能再给它的备选方案打分（BR-06）")
        if cur["status"] in _FROZEN:
            raise FdeError(
                f"决策 {dec_no} 已作出决策（结论是快照），不能再改分（BR-06）")
        if cur["status"] != "weighing":
            raise FdeError(
                f"决策 {dec_no} 当前为「{self._status_cn(cur['status'])}」，须先启动权衡（start）再打分")
        s = self._int(seq, "备选方案序号")
        target = [o for o in cur["options"] if int(o["seq"]) == s]
        if not target:
            raise FdeError(f"决策 {dec_no} 没有序号为 {s} 的备选方案")
        sc = self._score(score)                                     # BR-08

        self.db.execute(
            "UPDATE decision_option SET score = ?, note = ? WHERE dec_no = ? AND seq = ?",
            (sc, self._clean(note), dec_no, s),
        )
        return self.get(dec_no)

    def conclude(self, dec_no: str, chosen_seq, rationale: str = None,
                 risk_note: str = None, dissent: str = None):
        """作决策：权衡中 → 已决策（`weighing → decided`）。

        这是本聚合**唯一**写结论的入口（BR-06），两条不变量同时落在这里：
          · **BR-02（卡片 I-2）备选方案少于两个不允许结论** —— 决策必须有权衡；
          · **BR-03（卡片 I-1）结论必须指向一个备选方案，且该方案须有评价得分**。

        另外两条来自材料的报告口径：
          · **BR-04** 选中的**不是最高分**方案时，**必须给出依据**（材料 §6.8.1.2.5：
            "The highest score ... is typically the option that is recommended to management.
            **If a different option is recommended, an explanation should be provided as to why
            the lower score is preferred**"）—— 选最高分时依据选填；
          · `risk_note` / `dissent` 对应决策报告的第 6 节（Risk/Benefits）与第 8 节（Dissent），
            皆选填（TABLE 6.8-1）。
        """
        cur = self._need(dec_no)
        if cur["status"] == _TERMINAL:
            raise FdeError(f"决策 {dec_no} 已实施（终态），不能再作决策（BR-06）")
        if cur["status"] in _FROZEN:
            raise FdeError(f"决策 {dec_no} 已经作出决策（结论是快照），不能重复决策（BR-06）")
        if cur["status"] != "weighing":
            raise FdeError(
                f"决策 {dec_no} 当前为「{self._status_cn(cur['status'])}」，须先启动权衡（start）再作决策")

        s = self._int(chosen_seq, "备选方案序号")
        target = [o for o in cur["options"] if int(o["seq"]) == s]
        if not target:                                              # BR-03（指向的方案要存在）
            raise FdeError(f"决策 {dec_no} 没有序号为 {s} 的备选方案，结论必须指向一个备选方案（BR-03）")
        if len(cur["options"]) < 2:                                 # BR-02（卡片 I-2）
            raise FdeError(
                f"决策 {dec_no} 只有 {len(cur['options'])} 个备选方案，"
                "少于两个不允许作结论 —— 决策必须有权衡（BR-02）")
        chosen = target[0]
        if chosen["score"] is None:                                 # BR-03（卡片 I-1）
            raise FdeError(
                f"决策 {dec_no} 的备选方案「{chosen['name']}」还没有评价得分，"
                "不能作为结论（BR-03）")

        rationale = self._clean(rationale)
        top = cur["top_score"]
        if top is not None and chosen["score"] < top and not rationale:   # BR-04
            top_row = [o for o in cur["options"] if int(o["seq"]) == int(cur["top_seq"])][0]
            raise FdeError(
                f"决策 {dec_no} 选中的「{chosen['name']}」（{chosen['score']} 分）不是得分最高的方案"
                f"（「{top_row['name']}」{top} 分），必须给出依据（BR-04）")

        self.db.execute(
            "UPDATE decision SET status = 'decided', chosen_seq = ?, chosen_name = ?,"
            " rationale = ?, risk_note = ?, dissent = ? WHERE dec_no = ?",
            (s, chosen["name"], rationale, self._clean(risk_note), self._clean(dissent), dec_no),
        )
        return self.get(dec_no)

    def implement(self, dec_no: str, note: str = None):
        """实施：已决策 → 已实施（`decided → implemented`，**硬终态**）。

        材料 §6.8.1.2.7 "Capture Work Products" 要求把"recommendations 与 corrective
        actions"一并留痕 —— 决策落地为行动才算走完（状态机的末位，无后继）。
        """
        cur = self._need(dec_no)
        if cur["status"] == _TERMINAL:
            raise FdeError(f"决策 {dec_no} 已经是实施状态")
        if cur["status"] not in _FROZEN:
            raise FdeError(
                f"决策 {dec_no} 当前为「{self._status_cn(cur['status'])}」，"
                "只有已决策的议题才能实施（须先作决策）")

        self.db.execute(
            "UPDATE decision SET status = 'implemented', implement_note = ? WHERE dec_no = ?",
            (self._clean(note), dec_no),
        )
        return self.get(dec_no)

    def update(self, dec_no: str, topic: str = None, eval_method: str = None,
               measure_no: str = None, issue: str = None, owner: str = None,
               project_no: str = None):
        """修改决策的议题性内容（议题 / 议题说明 / 评价方法 / 来源度量 / 责任人 / 所属项目）。

        **结论与选中方案不在字段白名单里**：结论只能经 `conclude` 写入（BR-06），
        编号落库不可变（BR-05）—— 没有参数可传，也就无从改起。
        已决策后内容冻结、已实施为终态，两者都拒绝（BR-06）。
        """
        cur = self._need(dec_no)
        self._check_frozen(cur)                                     # BR-06

        sets, args = [], []
        if topic is not None:
            topic = self._clean(topic)
            if not topic:
                raise FdeError("决策议题不能为空")
            sets.append("topic = ?")
            args.append(topic)
        if eval_method is not None:
            sets.append("eval_method = ?")
            args.append(self._check_method(eval_method))             # BR-07
        if measure_no is not None:
            sets.append("measure_no = ?")
            args.append(self._clean(measure_no))
        if issue is not None:
            sets.append("issue = ?")
            args.append(self._clean(issue))
        if owner is not None:
            sets.append("owner = ?")
            args.append(self._clean(owner))
        if project_no is not None:
            sets.append("project_no = ?")
            args.append(self._clean(project_no))
        if not sets:
            raise FdeError("没有要修改的内容")
        args.append(dec_no)
        self.db.execute("UPDATE decision SET " + ", ".join(sets) + " WHERE dec_no = ?",
                        tuple(args))
        return self.get(dec_no)

    def get(self, dec_no: str):
        """按决策编号查询（含评价准则 `criteria` 与备选方案 `options`）；未命中返回 None，不抛异常。

        方案 / 准则计数与 `top_seq` / `top_score`（最高分方案）与 `list` 同口径 ——
        前端"最高分是谁""选中的是不是最高分"都读它。
        """
        dec_no = self._clean(dec_no)
        if not dec_no:
            return None
        row = self.db.execute(
            "SELECT " + _MAIN_COLS + " FROM decision WHERE dec_no = ?", (dec_no,),
        ).fetchone()
        if not row:
            return None
        out = dict(row)
        out["criteria"] = [dict(r) for r in self.db.execute(
            "SELECT seq, criterion, weight FROM decision_criterion"
            " WHERE dec_no = ? ORDER BY seq", (dec_no,)).fetchall()]
        out["options"] = [dict(r) for r in self.db.execute(
            "SELECT seq, name, description, score, note FROM decision_option"
            " WHERE dec_no = ? ORDER BY seq", (dec_no,)).fetchall()]
        out.update(self._counts(len(out["criteria"]), out["options"]))
        return out

    def list(self, eval_method: str = None, status: str = None, owner: str = None,
             page: int = None, size: int = None):
        """按评价方法 / 状态 / 责任人筛选，**分页返回 `{items, total}`**，默认按编号升序。

        ⚠ `page`/`size` 与 `{items, total}` 是**前端 `pageable` 的契约**（见 VIEW_CONVENTION）——
        少了它们，前端拿到的 `items` 恒为空、页面静默显示空态而**不报错**（同组实测踩过）。
        返回项与 `get` 同字段口径（`_MAIN_COLS` 共用 + 同一份准则 / 方案计数）；
        准则与方案**明细只在 `get`**（列表不需要 N+1 取子表）。
        """
        where, args = [], []
        for col, val in (("eval_method", eval_method), ("status", status), ("owner", owner)):
            val = self._clean(val)
            if val:
                where.append(f"{col} = ?")
                args.append(val)
        sql = "SELECT " + _MAIN_COLS + " FROM decision"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY dec_no"
        rows = []
        for r in self.db.execute(sql, tuple(args)).fetchall():
            d = dict(r)
            d.update(self._counts_by_no(d["dec_no"]))
            rows.append(d)

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
    def _int(v, label: str) -> int:
        """把入参解析为正整数，非法即拒（None / 空串 / 小数 / 负数 / 非数字都拦下）。"""
        s = str(v).strip() if v is not None else ""
        if not re.match(r"^\d+$", s):
            raise FdeError(f"{label}必须是正整数")
        n = int(s)
        if n < 1:
            raise FdeError(f"{label}必须大于 0")
        return n

    @staticmethod
    def _score(v) -> int:
        """评价得分：0~100 的整数（BR-08）。`0` 是**有效的分**，与「未打分」不是一回事。"""
        s = str(v).strip() if v is not None else ""
        if not re.match(r"^\d+$", s) or int(s) > SCORE_MAX:
            raise FdeError(f"评价得分必须是 0~{SCORE_MAX} 的整数（BR-08）")
        return int(s)

    @staticmethod
    def _check_method(eval_method: str) -> str:
        """评价方法非空 + 过字典（BR-07）。返回清洗后的值，供写入。"""
        m = Decision._clean(eval_method)
        if not m:
            raise FdeError("评价方法不能为空")
        if m not in EVAL_METHODS:
            raise FdeError(f"评价方法只能是 {'/'.join(EVAL_METHODS)} 之一（BR-07）")
        return m

    @staticmethod
    def _status_cn(status: str) -> str:
        return _STATUS_CN.get(status, status or "—")

    @staticmethod
    def _check_frozen(cur: dict):
        """已实施为硬终态、已决策后内容冻结 —— 两者都不许再改主档、准则或方案（BR-06）。"""
        if cur["status"] == _TERMINAL:
            raise FdeError(f"决策 {cur['dec_no']} 已实施（终态），不能再修改（BR-06）")
        if cur["status"] in _FROZEN:
            raise FdeError(
                f"决策 {cur['dec_no']} 已作出决策（结论是快照），"
                "不能再修改内容或增删准则 / 备选方案（BR-06）")

    @staticmethod
    def _top(options: list):
        """最高分方案：得分高者优先，同分取**序号小**者（口径唯一，`get` 与 `list` 共用）。"""
        scored = [o for o in options if o["score"] is not None]
        if not scored:
            return None
        best = scored[0]
        for o in scored[1:]:
            if o["score"] > best["score"] or (o["score"] == best["score"]
                                              and int(o["seq"]) < int(best["seq"])):
                best = o
        return best

    def _counts(self, criterion_total: int, options: list):
        """由准则条数 / 方案清单推导 5 个派生字段 —— `get` 与 `list` 共用同一算法。"""
        top = self._top(options)
        return {"criterion_total": int(criterion_total),
                "option_total": len(options),
                "scored_total": sum(1 for o in options if o["score"] is not None),
                "top_seq": int(top["seq"]) if top else None,
                "top_score": int(top["score"]) if top else None}

    def _counts_by_no(self, dec_no: str):
        crit = self.db.execute(
            "SELECT COUNT(*) AS n FROM decision_criterion WHERE dec_no = ?", (dec_no,),
        ).fetchone()
        opts = [dict(r) for r in self.db.execute(
            "SELECT seq, score FROM decision_option WHERE dec_no = ?", (dec_no,)).fetchall()]
        return self._counts(int(crit["n"] or 0), opts)

    def _need(self, dec_no: str):
        dec_no = self._clean(dec_no)
        if not dec_no:
            raise FdeError("决策编号不能为空")
        cur = self.get(dec_no)
        if not cur:
            raise FdeError(f"决策 {dec_no} 不存在")
        return cur

    def _next_no(self) -> str:
        """生成下一个决策编号：DC-<三位序号>（BR-05：编号唯一且不可变）。"""
        rows = self.db.execute("SELECT dec_no FROM decision").fetchall()
        mx = 0
        for r in rows:
            m = re.match(r"^DC-(\d+)$", str(r["dec_no"]))
            if m:
                mx = max(mx, int(m.group(1)))
        return f"DC-{mx + 1:03d}"

    def _next_seq(self, table: str, dec_no: str) -> int:
        """聚合内子表的序号：本决策内递增（`(dec_no, seq)` 是复合主键，无全局标识）。"""
        rows = self.db.execute(
            f"SELECT seq FROM {table} WHERE dec_no = ?", (dec_no,)).fetchall()
        mx = 0
        for r in rows:
            mx = max(mx, int(r["seq"]))
        return mx + 1
