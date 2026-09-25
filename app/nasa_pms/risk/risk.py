from __future__ import annotations

import re

from fde import FdeError

CATEGORIES = ("technical", "cost", "schedule", "programmatic", "safety")
DIMENSIONS = (1, 2, 3, 4, 5)
DISPOSITIONS = ("mitigated", "transferred", "accepted")
# 终态：到达后不得再改（BR-06）
_TERMINAL = ("closed", "accepted")
# 风险等级分档：风险值 = 可能性 × 后果 ∈ 1..25 → 四档（BR-01，NASA 5×5 风险矩阵）
_BANDS = ((4, "low"), (9, "medium"), (15, "high"), (25, "critical"))
_STATUS_CN = {"identified": "识别", "analyzing": "分析中", "mitigating": "缓解中",
              "closed": "已关闭", "accepted": "已接受"}


class Risk:
    """风险聚合根。一条技术风险，含风险情景、可能性/后果、缓解措施与处置结论。

    一致性边界（见 `architecture.md` 聚合根卡 2）：
      · 「风险等级」**不是录入字段** —— 恒由 `可能性 × 后果` 推导（BR-01），
        `create` / `update` 都没有写等级的入口，只有 `assess` 能改那对取值；
      · 「关闭」是终态动作：处置结论与状态**同事务**落库（BR-02），
        等级为高/严重的不得以「接受」收尾（BR-03）；
      · 受影响需求是**弱引用**（可留空、可悬空）——本聚合不复制需求内容，
        写入时经 `requirement.get` 校验一次存在性（BR-07，跨应用，非同一事务）。

    业务规则落点：BR-01 等级推导 / BR-02 关闭须有处置结论 / BR-03 高等级不得接受 /
                 BR-04 编号不可变 / BR-05 字典约束 / BR-06 终态不可改 / BR-07 受影响需求须存在。
    """

    # ── 服务（公共方法即服务） ──────────────────────────────

    def create(self, title: str, statement: str, category: str,
               likelihood: int = None, consequence: int = None,
               req_no: str = None, owner: str = None, project_no: str = None):
        """识别一条风险，落库为「识别」状态。

        `likelihood` / `consequence` 可暂缺（= 尚未评估）；一旦给出，**必须成对**，
        等级当即由二者推导（BR-01）—— 等级永远不是入参。
        """
        title = self._clean(title)
        statement = self._clean(statement)
        category = self._clean(category)
        if not title:
            raise FdeError("风险标题不能为空")
        if not statement:
            # 风险情景是风险的实质（材料 §6.4 的风险三元组：情景 → 可能性 → 后果）
            raise FdeError("风险情景不能为空")
        self._check_category(category)                            # BR-05
        req_no = self._clean(req_no)
        if req_no:
            self._assert_requirement_exists(req_no)               # BR-07（跨应用）
        dims = self._derive(likelihood, consequence)              # BR-01

        risk_no = self._next_no()
        self.db.execute(
            "INSERT INTO risk (risk_no, title, statement, category, likelihood, consequence,"
            " risk_score, risk_level, req_no, owner, status, project_no)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'identified', ?)",
            (risk_no, title, statement, category, dims[0], dims[1], dims[2], dims[3],
             req_no, self._clean(owner), self._clean(project_no)),
        )
        return self.get(risk_no)

    def assess(self, risk_no: str, likelihood: int, consequence: int):
        """重评风险等级：写入可能性 / 后果，等级**由二者推导**，状态推进到「分析中」。

        这是**唯一**能改动风险等级的入口（BR-01）——`create` / `update` 都不接受等级。
        """
        cur = self.get(risk_no)
        if not cur:
            raise FdeError(f"风险 {risk_no} 不存在")
        self._check_mutable(cur)                                  # BR-06
        lk, cq, score, level = self._derive(likelihood, consequence)   # BR-01 / BR-05
        self.db.execute(
            "UPDATE risk SET likelihood = ?, consequence = ?, risk_score = ?, risk_level = ?,"
            " status = 'analyzing' WHERE risk_no = ?",
            (lk, cq, score, level, risk_no),
        )
        return self.get(risk_no)

    def mitigate(self, risk_no: str, mitigation: str):
        """登记缓解措施，状态推进到「缓解中」。

        要求等级**已评估**（材料 §6.4.1.2.4：缓解动作由风险等级/阈值触发）——
        故状态机的顺序是 `识别的 → 评估过（可能性/后果齐备）→ 缓解中`。
        """
        cur = self.get(risk_no)
        if not cur:
            raise FdeError(f"风险 {risk_no} 不存在")
        self._check_mutable(cur)                                  # BR-06
        if not cur["risk_level"]:
            raise FdeError(f"风险 {risk_no} 尚未评估等级，请先评估（可能性 × 后果）再登记缓解措施")
        mitigation = self._clean(mitigation)
        if not mitigation:
            raise FdeError("缓解措施不能为空")
        self.db.execute(
            "UPDATE risk SET mitigation = ?, status = 'mitigating' WHERE risk_no = ?",
            (mitigation, risk_no),
        )
        return self.get(risk_no)

    def close(self, risk_no: str, disposition: str, note: str = None):
        """关闭风险：必须给出**处置结论**（缓解完成 / 转移 / 接受），结论与终态同事务落库。

        · `accepted` → 终态「已接受」；其余两种 → 终态「已关闭」（BR-02）；
        · **只有「缓解中」的风险可以关闭**（§3.4 状态机：`mitigating → close`）——
          它顺带守住了 BR-03 的适用前提：等级要经 `assess` 才有，
          否则一条**从未评估**的风险（`risk_level` 为空）可以径直以「接受」收尾；
        · 结论为「缓解完成」时**必须已登记缓解措施**（BR-02）；
        · 等级为「高」/「严重」时**不允许**以「接受」收尾（BR-03，须缓解或转移）。

        ⚠ **守卫顺序**（负例的期望信息 = 状态 × 顺序的交叉点，改顺序要同步改用例）：
        存在性 → 终态(BR-06) → **状态闸（须缓解中）** → 处置结论非空 → 字典 → BR-02 → BR-03。
        """
        cur = self.get(risk_no)
        if not cur:
            raise FdeError(f"风险 {risk_no} 不存在")
        self._check_mutable(cur)                                  # BR-06
        # ⚠ 2026-09-25 补：这一闸此前**缺失**（实现与 §3.4 状态机不一致）——
        # 实测后果：`identified` 且未评估的风险给个「转移」就能直接关闭；而 BR-03 因为
        # `risk_level` 为空**完全拦不住**「高风险直接接受」（子代理写 HOWTOUSE 时对账发现）。
        if cur["status"] != "mitigating":
            raise FdeError(
                f"风险 {risk_no} 当前为「{_STATUS_CN.get(cur['status'], cur['status'])}」，"
                "只有「缓解中」的风险可以关闭 —— 先 assess 评估等级、再 mitigate 登记缓解措施"
            )
        disposition = self._clean(disposition)
        if not disposition:
            raise FdeError("关闭风险必须给出处置结论：缓解完成 / 转移 / 接受（BR-02）")
        if disposition not in DISPOSITIONS:
            raise FdeError(f"处置结论只能是 {'/'.join(DISPOSITIONS)} 之一")
        if disposition == "mitigated" and not cur["mitigation"]:
            raise FdeError(f"风险 {risk_no} 未登记缓解措施，不能以「缓解完成」关闭（BR-02）")
        if disposition == "accepted" and cur["risk_level"] in ("high", "critical"):
            raise FdeError(
                f"风险 {risk_no} 等级为「{self._level_cn(cur['risk_level'])}」，"
                "不得以「接受」关闭，须缓解或转移（BR-03）"
            )
        status = "accepted" if disposition == "accepted" else "closed"
        self.db.execute(
            "UPDATE risk SET status = ?, disposition = ?, close_note = ? WHERE risk_no = ?",
            (status, disposition, self._clean(note), risk_no),
        )
        return self.get(risk_no)

    def update(self, risk_no: str, title: str = None, statement: str = None,
               category: str = None, req_no: str = None, owner: str = None):
        """修改风险描述性内容。

        ⚠ **改不了等级**：等级与风险值只能经 `assess` 由 可能性 × 后果 推导（BR-01）；
        终态（已关闭 / 已接受）的风险一律不得修改（BR-06）。
        """
        cur = self.get(risk_no)
        if not cur:
            raise FdeError(f"风险 {risk_no} 不存在")
        self._check_mutable(cur)                                  # BR-06

        sets, args = [], []
        if title is not None:
            title = self._clean(title)
            if not title:
                raise FdeError("风险标题不能为空")
            sets.append("title = ?")
            args.append(title)
        if statement is not None:
            statement = self._clean(statement)
            if not statement:
                raise FdeError("风险情景不能为空")
            sets.append("statement = ?")
            args.append(statement)
        if category is not None:
            category = self._clean(category)
            self._check_category(category)                        # BR-05
            sets.append("category = ?")
            args.append(category)
        if req_no is not None:
            req_no = self._clean(req_no)
            if req_no:
                self._assert_requirement_exists(req_no)           # BR-07（跨应用）
            sets.append("req_no = ?")
            args.append(req_no)
        if owner is not None:
            sets.append("owner = ?")
            args.append(self._clean(owner))
        if not sets:
            raise FdeError("没有要修改的内容")
        args.append(risk_no)
        self.db.execute("UPDATE risk SET " + ", ".join(sets) + " WHERE risk_no = ?", tuple(args))
        return self.get(risk_no)

    def get(self, risk_no: str):
        """按风险编号查询；未命中返回 None，不抛异常。"""
        risk_no = self._clean(risk_no)
        if not risk_no:
            return None
        row = self.db.execute(
            "SELECT risk_no, title, statement, category, likelihood, consequence, risk_score,"
            " risk_level, mitigation, req_no, owner, status, disposition, close_note, project_no"
            " FROM risk WHERE risk_no = ?", (risk_no,),
        ).fetchone()
        return dict(row) if row else None

    def list(self, category: str = None, status: str = None, risk_level: str = None,
             req_no: str = None, page: int = None, size: int = None):
        """按类别 / 状态 / 等级 / 受影响需求筛选，**分页返回 `{items, total}`**，默认按编号升序。

        ⚠ `page`/`size` 与 `{items, total}` 是**前端 `pageable` 的契约**（见 VIEW_CONVENTION）——
        少了它们，前端拿到的 `items` 恒为空、页面显示空态而**不报错**（实测踩过：
        后端返回裸数组时，页面静默显示「暂无数据」）。
        返回项与 `get` 同口径（全字段），列表只显示关键列是**视图层**的事。
        """
        where, args = [], []
        for col, val in (("category", category), ("status", status),
                         ("risk_level", risk_level), ("req_no", req_no)):
            val = self._clean(val)
            if val:
                where.append(f"{col} = ?")
                args.append(val)
        sql = ("SELECT risk_no, title, statement, category, likelihood, consequence, risk_score,"
               " risk_level, mitigation, req_no, owner, status, disposition, close_note, project_no"
               " FROM risk")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY risk_no"
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
    def _check_category(category: str):
        if category not in CATEGORIES:
            raise FdeError(f"风险类别只能是 {'/'.join(CATEGORIES)} 之一（BR-05）")

    @staticmethod
    def _check_mutable(cur: dict):
        if cur["status"] in _TERMINAL:
            raise FdeError(
                f"风险 {cur['risk_no']} 已处于终态「{_STATUS_CN.get(cur['status'], cur['status'])}」，"
                "不能再修改（BR-06）"
            )

    @staticmethod
    def _check_dim(value, label: str):
        try:
            n = int(value)
        except (TypeError, ValueError):
            raise FdeError(f"{label}必须是 1..5 的整数（BR-05）") from None
        if n not in DIMENSIONS:
            raise FdeError(f"{label}只能是 1..5（BR-05）")
        return n

    def _derive(self, likelihood, consequence):
        """由 可能性 × 后果 推导 (可能性, 后果, 风险值, 风险等级) —— 等级的唯一来源（BR-01）。"""
        if likelihood is None and consequence is None:
            return None, None, None, None
        lk = self._check_dim(likelihood, "可能性")
        cq = self._check_dim(consequence, "后果")
        score = lk * cq
        return lk, cq, score, self._band(score)

    @staticmethod
    def _band(score: int) -> str:
        for top, name in _BANDS:
            if score <= top:
                return name
        return "critical"

    @staticmethod
    def _level_cn(level: str) -> str:
        return {"low": "低", "medium": "中", "high": "高", "critical": "严重"}.get(level, level or "—")

    def _assert_requirement_exists(self, req_no: str):
        """跨应用校验弱引用：受影响需求必须真实存在（BR-07，只读调用，非同一事务）。"""
        try:
            found = self.fde.call("requirement", "get", req_no=req_no)
        except FdeError:
            raise FdeError(f"受影响需求 {req_no} 不存在") from None
        except Exception:
            raise FdeError(f"受影响需求 {req_no} 校验失败（requirement 应用不可用）") from None
        if not found:
            raise FdeError(f"受影响需求 {req_no} 不存在，请先在需求台账中录入（BR-07）")

    def _next_no(self) -> str:
        """生成下一个风险编号：RSK-<三位序号>（唯一且不可变，BR-04）。"""
        rows = self.db.execute("SELECT risk_no FROM risk").fetchall()
        mx = 0
        for r in rows:
            m = re.match(r"^RSK-(\d+)$", str(r["risk_no"]))
            if m:
                mx = max(mx, int(m.group(1)))
        return f"RSK-{mx + 1:03d}"
