from __future__ import annotations

from fde import FdeError
from typing import Optional
import uuid


class MdPartReplace:
    """替换关系聚合根，管理零件间替换关系（原物料→替换物料）的创建、查询、更新与失效。"""

    VALID_STATUSES = ("生效", "失效")

    def create(self, old_material_no: str, new_material_no: str, ecn_no: Optional[str] = None):
        """新建替换关系：校验原/替换物料存在、原≠替换、组合唯一后入库，status 默认「生效」。"""
        clean_old = self._clean_material_no(old_material_no, "原物料号")
        clean_new = self._clean_material_no(new_material_no, "替换物料号")
        clean_ecn = self._clean_ecn_no(ecn_no)

        self._validate_pair(clean_old, clean_new)

        # 原+替换组合唯一性（BR-01）
        self._assert_combo_available(clean_old, clean_new)

        rel_no = self._generate_rel_no()
        self.db.execute(
            """
                INSERT INTO md_part_replace (rel_no, old_material_no, new_material_no, ecn_no, status)
                VALUES (?, ?, ?, ?, ?)
            """,
            (rel_no, clean_old, clean_new, clean_ecn, "生效"),
        )
        return self.get(rel_no)

    def get(self, rel_no: str):
        """查看单条替换关系详情。"""
        clean_rel_no = self._clean_rel_no(rel_no)
        row = self.db.execute(
            """
                SELECT rel_no, old_material_no, new_material_no, ecn_no, status
                FROM md_part_replace
                WHERE rel_no = ?
            """,
            (clean_rel_no,),
        ).fetchone()
        if row is None:
            raise FdeError("替换关系不存在")
        return dict(row)

    def list(
        self,
        old_material_no: Optional[str] = None,
        new_material_no: Optional[str] = None,
        status: Optional[str] = None,
        page: Optional[int] = None,
        size: Optional[int] = None,
    ):
        """按原物料号/替换物料号（模糊）、状态（精确）筛选分页列表。"""
        if old_material_no is not None:
            old_material_no = str(old_material_no).strip()
            if old_material_no == "":
                old_material_no = None
        if new_material_no is not None:
            new_material_no = str(new_material_no).strip()
            if new_material_no == "":
                new_material_no = None
        if status is not None:
            status = str(status).strip()
            if status == "":
                status = None

        if status is not None and status not in self.VALID_STATUSES:
            raise FdeError("状态仅支持生效/失效")

        clauses = []
        params = []

        if old_material_no is not None:
            clauses.append("old_material_no LIKE ?")
            params.append("%" + old_material_no + "%")
        if new_material_no is not None:
            clauses.append("new_material_no LIKE ?")
            params.append("%" + new_material_no + "%")
        if status is not None:
            clauses.append("status = ?")
            params.append(status)

        where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        select_sql = """
            SELECT rel_no, old_material_no, new_material_no, ecn_no, status
            FROM md_part_replace
        """ + where_sql + " ORDER BY rel_no ASC"

        rows = self.db.execute(select_sql, tuple(params)).fetchall()
        total = len(rows)

        if page is None and size is None:
            return {"items": [dict(r) for r in rows], "total": total}

        try:
            page_int = int(page) if page is not None else 1
            size_int = int(size) if size is not None else 100
        except (TypeError, ValueError):
            raise FdeError("分页参数不合法") from None

        if page_int < 1:
            raise FdeError("页码必须大于等于1")
        if size_int < 1:
            raise FdeError("每页条数必须大于等于1")

        start = (page_int - 1) * size_int
        items = [dict(r) for r in rows[start:start + size_int]]
        return {"items": items, "total": total}

    def update(self, rel_no: str, old_material_no: str, new_material_no: str, ecn_no: Optional[str] = None):
        """更新替换关系的原/替换物料号与 ECN 依据，重新校验物料引用、原≠替换与组合唯一。"""
        clean_rel_no = self._clean_rel_no(rel_no)
        existing = self.db.execute(
            "SELECT 1 FROM md_part_replace WHERE rel_no = ?",
            (clean_rel_no,),
        ).fetchone()
        if existing is None:
            raise FdeError("替换关系不存在")

        clean_old = self._clean_material_no(old_material_no, "原物料号")
        clean_new = self._clean_material_no(new_material_no, "替换物料号")
        clean_ecn = self._clean_ecn_no(ecn_no)

        self._validate_pair(clean_old, clean_new)
        self._assert_combo_available(clean_old, clean_new, exclude_rel_no=clean_rel_no)

        self.db.execute(
            """
                UPDATE md_part_replace
                SET old_material_no = ?, new_material_no = ?, ecn_no = ?
                WHERE rel_no = ?
            """,
            (clean_old, clean_new, clean_ecn, clean_rel_no),
        )
        return self.get(clean_rel_no)

    def disable(self, rel_no: str):
        """将替换关系设为「失效」（幂等：已失效直接返回）。"""
        clean_rel_no = self._clean_rel_no(rel_no)
        row = self.db.execute(
            "SELECT status FROM md_part_replace WHERE rel_no = ?",
            (clean_rel_no,),
        ).fetchone()
        if row is None:
            raise FdeError("替换关系不存在")

        if row["status"] == "失效":
            return self.get(clean_rel_no)

        self.db.execute(
            "UPDATE md_part_replace SET status = '失效' WHERE rel_no = ?",
            (clean_rel_no,),
        )
        return self.get(clean_rel_no)

    # ---- 内部辅助（_ 前缀，不对外暴露）----

    def _clean_rel_no(self, rel_no):
        clean = "" if rel_no is None else str(rel_no).strip()
        if not clean:
            raise FdeError("关系号不能为空")
        return clean

    def _clean_material_no(self, material_no, label):
        clean = "" if material_no is None else str(material_no).strip()
        if not clean:
            raise FdeError(label + "不能为空")
        return clean

    def _clean_ecn_no(self, ecn_no):
        clean = None if ecn_no is None else str(ecn_no).strip()
        if clean == "":
            clean = None
        if clean is not None and len(clean) > 50:
            raise FdeError("ECN依据长度不能超过50")
        return clean

    def _validate_pair(self, old_material_no, new_material_no):
        if old_material_no == new_material_no:
            raise FdeError("原物料号与替换物料号不能相同")
        self._assert_material_exists(old_material_no, "原物料号")
        self._assert_material_exists(new_material_no, "替换物料号")

    def _assert_material_exists(self, material_no, label):
        try:
            result = self.fde.call("md_material", "get", material_no=material_no)
        except FdeError:
            raise FdeError(label + "不存在") from None
        except Exception:
            raise FdeError(label + "校验失败") from None
        if not result:
            raise FdeError(label + "不存在")

    def _assert_combo_available(self, old_material_no, new_material_no, exclude_rel_no=None):
        if exclude_rel_no is None:
            row = self.db.execute(
                "SELECT 1 FROM md_part_replace WHERE old_material_no = ? AND new_material_no = ?",
                (old_material_no, new_material_no),
            ).fetchone()
        else:
            row = self.db.execute(
                "SELECT 1 FROM md_part_replace WHERE old_material_no = ? AND new_material_no = ? AND rel_no != ?",
                (old_material_no, new_material_no, exclude_rel_no),
            ).fetchone()
        if row is not None:
            raise FdeError("该原物料+替换物料组合已存在")

    def _generate_rel_no(self):
        for _ in range(5):
            rel_no = "R" + uuid.uuid4().hex.upper()
            row = self.db.execute(
                "SELECT 1 FROM md_part_replace WHERE rel_no = ?",
                (rel_no,),
            ).fetchone()
            if row is None:
                return rel_no
        raise FdeError("关系号生成失败，请重试")
