from __future__ import annotations

from fde import FdeError
from typing import Optional


class MdBreakpoint:
    """断点基础数据聚合根，管理「客户 × 原/新物料号 × 切换时间」的新旧件断点关系。"""

    def create(self, customer_no: str, old_material_no: str, new_material_no: str, switch_time: str, ecn_no: Optional[str] = None):
        """新建断点：校验物料存在、原≠新、切换时间非空、组合唯一后入库。"""
        clean_customer = self._clean_required(customer_no, "客户")
        clean_old = self._clean_required(old_material_no, "原物料号")
        clean_new = self._clean_required(new_material_no, "新物料号")
        clean_switch_time = self._clean_required(switch_time, "切换时间")
        clean_ecn = self._clean_ecn_no(ecn_no)

        self._validate_pair(clean_old, clean_new)
        self._assert_combo_available(clean_customer, clean_old, clean_new, clean_switch_time)

        cur = self.db.execute(
            """
                INSERT INTO md_breakpoint
                    (customer_no, old_material_no, new_material_no, switch_time, ecn_no, disabled)
                VALUES (?, ?, ?, ?, ?, 0)
            """,
            (clean_customer, clean_old, clean_new, clean_switch_time, clean_ecn),
        )
        return self.get(cur.lastrowid)

    def get(self, bp_id: int):
        """按断点标识查询单条断点记录（含已停用记录）。"""
        clean_bp_id = self._clean_bp_id(bp_id)
        row = self._row(clean_bp_id)
        if row is None:
            raise FdeError("断点记录不存在")
        return dict(row)

    def list(
        self,
        customer_no: Optional[str] = None,
        old_material_no: Optional[str] = None,
        new_material_no: Optional[str] = None,
        page: Optional[int] = None,
        size: Optional[int] = None,
    ):
        """按客户/原物料号/新物料号（精确）筛选分页列表，默认不含已停用记录，按切换时间降序。"""
        customer_no = self._optional(customer_no)
        old_material_no = self._optional(old_material_no)
        new_material_no = self._optional(new_material_no)

        clauses = ["disabled = 0"]
        params = []

        if customer_no is not None:
            clauses.append("customer_no = ?")
            params.append(customer_no)
        if old_material_no is not None:
            clauses.append("old_material_no = ?")
            params.append(old_material_no)
        if new_material_no is not None:
            clauses.append("new_material_no = ?")
            params.append(new_material_no)

        select_sql = """
            SELECT bp_id, customer_no, old_material_no, new_material_no, switch_time, ecn_no, disabled
            FROM md_breakpoint
        """ + (" WHERE " + " AND ".join(clauses)) + " ORDER BY switch_time DESC, bp_id DESC"

        rows = self.db.execute(select_sql, tuple(params)).fetchall()
        total = len(rows)

        if page is None and size is None:
            return {"items": [dict(r) for r in rows], "total": total}

        try:
            page_int = int(page) if page is not None else 1
            size_int = int(size) if size is not None else 20
        except (TypeError, ValueError):
            raise FdeError("分页参数不合法") from None

        if page_int < 1:
            raise FdeError("页码必须大于等于1")
        if size_int < 1:
            raise FdeError("每页条数必须大于等于1")

        start = (page_int - 1) * size_int
        return {"items": [dict(r) for r in rows[start:start + size_int]], "total": total}

    def upcoming(self, days: int = 60):
        """即将切换的断点关系：switch_time 在 [今天, 今天+days] 且未停用。
        供销售预测 / 库存策略 / 流程总览做「即将切换」预警（旧件待替换 / 新件待上线）。"""
        try:
            days_int = int(days) if days is not None else 60
        except (TypeError, ValueError):
            raise FdeError("天数参数不合法") from None
        if days_int < 1:
            raise FdeError("天数必须大于等于1")

        from datetime import datetime, timedelta
        today = datetime.now().strftime("%Y-%m-%d")
        end = (datetime.now() + timedelta(days=days_int)).strftime("%Y-%m-%d")

        rows = self.db.execute(
            """
                SELECT bp_id, customer_no, old_material_no, new_material_no, switch_time, ecn_no, disabled
                FROM md_breakpoint
                WHERE disabled = 0 AND switch_time >= ? AND switch_time <= ?
                ORDER BY switch_time ASC, bp_id ASC
            """,
            (today, end),
        ).fetchall()
        return [dict(r) for r in rows]

    def update(
        self,
        bp_id: int,
        customer_no: Optional[str] = None,
        old_material_no: Optional[str] = None,
        new_material_no: Optional[str] = None,
        switch_time: Optional[str] = None,
        ecn_no: Optional[str] = None,
    ):
        """更新断点的切换时间/变更单号等字段，重新校验物料引用、原≠新、组合唯一。"""
        clean_bp_id = self._clean_bp_id(bp_id)
        existing = self._row(clean_bp_id)
        if existing is None:
            raise FdeError("断点记录不存在")

        clean_customer = (
            self._clean_required(customer_no, "客户") if customer_no is not None else existing["customer_no"]
        )
        clean_old = (
            self._clean_required(old_material_no, "原物料号") if old_material_no is not None else existing["old_material_no"]
        )
        clean_new = (
            self._clean_required(new_material_no, "新物料号") if new_material_no is not None else existing["new_material_no"]
        )
        clean_switch_time = (
            self._clean_required(switch_time, "切换时间") if switch_time is not None else existing["switch_time"]
        )
        clean_ecn = self._clean_ecn_no(ecn_no) if ecn_no is not None else existing["ecn_no"]

        self._validate_pair(clean_old, clean_new)
        self._assert_combo_available(
            clean_customer, clean_old, clean_new, clean_switch_time, exclude_bp_id=clean_bp_id
        )

        self.db.execute(
            """
                UPDATE md_breakpoint
                SET customer_no = ?, old_material_no = ?, new_material_no = ?,
                    switch_time = ?, ecn_no = ?
                WHERE bp_id = ?
            """,
            (clean_customer, clean_old, clean_new, clean_switch_time, clean_ecn, clean_bp_id),
        )
        return self.get(clean_bp_id)

    def disable(self, bp_id: int):
        """停用断点记录（软失效，不参与 trace 追溯与列表默认展示）。"""
        clean_bp_id = self._clean_bp_id(bp_id)
        row = self._row(clean_bp_id)
        if row is None:
            raise FdeError("断点记录不存在")
        if row["disabled"]:
            raise FdeError("该断点已停用")

        self.db.execute(
            "UPDATE md_breakpoint SET disabled = 1 WHERE bp_id = ?",
            (clean_bp_id,),
        )
        return self.get(clean_bp_id)

    def trace(self, new_material_no: str):
        """沿断点向上追溯原物料号链，返回从最上游原物料号到给定新物料号的序列（无断点返回自身）。"""
        clean_new = self._clean_required(new_material_no, "物料号")

        chain = [clean_new]
        current = clean_new
        visited = {clean_new}
        while True:
            row = self.db.execute(
                """
                    SELECT old_material_no
                    FROM md_breakpoint
                    WHERE new_material_no = ? AND disabled = 0
                    ORDER BY switch_time ASC, bp_id ASC
                    LIMIT 1
                """,
                (current,),
            ).fetchone()
            if row is None:
                break
            old = row["old_material_no"]
            if old in visited:
                break
            visited.add(old)
            chain.insert(0, old)
            current = old
        return chain

    def get_switch_time(self, new_material_no: str, customer_no: Optional[str] = None):
        """取某新物料的断点切换时间（可按客户收窄）；无断点返回 None。
        供销售预测 calc_baseline 回填处理表行的 switch_time（断点切换时间）。"""
        clean_new = self._clean_required(new_material_no, "物料号")
        customer = self._optional(customer_no)
        if customer:
            row = self.db.execute(
                """
                    SELECT switch_time FROM md_breakpoint
                    WHERE new_material_no = ? AND customer_no = ? AND disabled = 0
                    ORDER BY switch_time ASC, bp_id ASC LIMIT 1
                """,
                (clean_new, customer),
            ).fetchone()
        else:
            row = self.db.execute(
                """
                    SELECT switch_time FROM md_breakpoint
                    WHERE new_material_no = ? AND disabled = 0
                    ORDER BY switch_time ASC, bp_id ASC LIMIT 1
                """,
                (clean_new,),
            ).fetchone()
        return row["switch_time"] if row else None

    # ---- 内部辅助（_ 前缀，不对外暴露）----

    def _clean_required(self, value, label):
        clean = "" if value is None else str(value).strip()
        if not clean:
            raise FdeError(label + "不能为空")
        return clean

    def _optional(self, value):
        if value is None:
            return None
        clean = str(value).strip()
        if clean == "":
            return None
        return clean

    def _clean_ecn_no(self, ecn_no):
        clean = None if ecn_no is None else str(ecn_no).strip()
        if clean == "":
            clean = None
        if clean is not None and len(clean) > 50:
            raise FdeError("变更单号长度不能超过50")
        return clean

    def _clean_bp_id(self, bp_id):
        if bp_id is None:
            raise FdeError("断点标识不能为空")
        clean = str(bp_id).strip()
        if not clean:
            raise FdeError("断点标识不能为空")
        return clean

    def _validate_pair(self, old_material_no, new_material_no):
        if old_material_no == new_material_no:
            raise FdeError("原物料号与新物料号不能相同")
        self._assert_material_exists(old_material_no)
        self._assert_material_exists(new_material_no)

    def _assert_material_exists(self, material_no):
        try:
            result = self.fde.call("md_material", "get", material_no=material_no)
        except FdeError:
            raise FdeError("物料不存在") from None
        except Exception:
            raise FdeError("物料校验失败") from None
        if not result:
            raise FdeError("物料不存在")

    def _assert_combo_available(self, customer_no, old_material_no, new_material_no, switch_time, exclude_bp_id=None):
        if exclude_bp_id is None:
            row = self.db.execute(
                """
                    SELECT 1 FROM md_breakpoint
                    WHERE customer_no = ? AND old_material_no = ?
                      AND new_material_no = ? AND switch_time = ?
                """,
                (customer_no, old_material_no, new_material_no, switch_time),
            ).fetchone()
        else:
            row = self.db.execute(
                """
                    SELECT 1 FROM md_breakpoint
                    WHERE customer_no = ? AND old_material_no = ?
                      AND new_material_no = ? AND switch_time = ? AND bp_id != ?
                """,
                (customer_no, old_material_no, new_material_no, switch_time, exclude_bp_id),
            ).fetchone()
        if row is not None:
            raise FdeError("该断点组合已存在")

    def _row(self, bp_id):
        return self.db.execute(
            """
                SELECT bp_id, customer_no, old_material_no, new_material_no, switch_time, ecn_no, disabled
                FROM md_breakpoint
                WHERE bp_id = ?
            """,
            (bp_id,),
        ).fetchone()
