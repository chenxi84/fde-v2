from __future__ import annotations

from fde import FdeError
from typing import Optional
import uuid
from datetime import datetime, timezone


class Task:
    """任务聚合根，管理任务创建、查询与状态流转。"""

    VALID_PRIORITIES = ("low", "high")
    VALID_STATUSES = ("待办", "进行中", "已完成")

    def create(
        self,
        title: str,
        description: Optional[str] = None,
        assignee_member_no: Optional[str] = None,
        priority: Optional[str] = None,
    ):
        clean_title = "" if title is None else str(title).strip()
        if not clean_title:
            raise FdeError("任务标题不能为空")
        if len(clean_title) > 200:
            raise FdeError("任务标题长度不能超过200")

        clean_description = None if description is None else str(description)
        if clean_description is not None and len(clean_description) > 2000:
            raise FdeError("任务描述长度不能超过2000")

        clean_assignee_member_no = "" if assignee_member_no is None else str(assignee_member_no).strip()
        if not clean_assignee_member_no:
            raise FdeError("指派成员编号不能为空")

        clean_priority = "" if priority is None else str(priority).strip()
        if clean_priority not in self.VALID_PRIORITIES:
            raise FdeError("优先级只能为 low 或 high")

        try:
            member = self.fde.call("member", "get", member_no=clean_assignee_member_no)
        except FdeError:
            raise FdeError(f"指派成员 {clean_assignee_member_no} 不存在") from None
        except Exception:
            raise FdeError(f"校验指派成员 {clean_assignee_member_no} 失败") from None

        if not member:
            raise FdeError(f"指派成员 {clean_assignee_member_no} 不存在")

        task_no = self._generate_task_no()
        now = self._now()
        self.db.execute(
            """
                INSERT INTO task (
                    task_no,
                    title,
                    description,
                    assignee_member_no,
                    priority,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_no,
                clean_title,
                clean_description,
                clean_assignee_member_no,
                clean_priority,
                "待办",
                now,
                now,
            ),
        )
        return self._get_task(task_no)

    def get(self, task_no: str):
        return self._get_task(task_no)

    def list(
        self,
        status: Optional[str] = None,
        assignee_member_no: Optional[str] = None,
        priority: Optional[str] = None,
        page: Optional[int] = None,
        page_size: Optional[int] = None,
    ):
        if status is not None:
            status = str(status).strip()
            if status == "":
                status = None
        if assignee_member_no is not None:
            assignee_member_no = str(assignee_member_no).strip()
            if assignee_member_no == "":
                assignee_member_no = None
        if priority is not None:
            priority = str(priority).strip()
            if priority == "":
                priority = None
        if page is not None and str(page).strip() == "":
            page = None
        if page_size is not None and str(page_size).strip() == "":
            page_size = None

        if status is not None and status not in self.VALID_STATUSES:
            raise FdeError("状态筛选不合法")
        if priority is not None and priority not in self.VALID_PRIORITIES:
            raise FdeError("优先级筛选不合法")

        clauses = []
        params = []

        if status is not None:
            clauses.append("status = ?")
            params.append(status)

        if assignee_member_no is not None:
            clauses.append("assignee_member_no = ?")
            params.append(assignee_member_no)

        if priority is not None:
            clauses.append("priority = ?")
            params.append(priority)

        where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        select_sql = """
            SELECT task_no, title, description, assignee_member_no, priority, status, created_at, updated_at
            FROM task
        """ + where_sql + " ORDER BY created_at DESC, task_no DESC"

        if page is None and page_size is None:
            rows = self.db.execute(select_sql, tuple(params)).fetchall()
            return [dict(row) for row in rows]

        try:
            page_int = int(page) if page is not None else 1
            page_size_int = int(page_size) if page_size is not None else 100
        except (TypeError, ValueError):
            raise FdeError("分页参数不合法") from None

        if page_int < 1:
            raise FdeError("页码必须大于等于1")
        if page_size_int < 1:
            raise FdeError("每页条数必须大于等于1")

        total_row = self.db.execute("SELECT COUNT(*) FROM task" + where_sql, tuple(params)).fetchone()
        total = total_row[0] if total_row is not None else 0

        offset_int = (page_int - 1) * page_size_int
        rows = self.db.execute(
            select_sql + " LIMIT ? OFFSET ?",
            tuple(params + [page_size_int, offset_int]),
        ).fetchall()
        items = [dict(row) for row in rows]

        return {
            "total": total,
            "page": page_int,
            "page_size": page_size_int,
            "items": items,
            "data": items,
            "rows": items,
            "list": items,
            "records": items,
        }

    def start(self, task_no: str):
        task = self._get_task(task_no)
        task_no = task["task_no"]

        if task["status"] == "进行中":
            raise FdeError("进行中任务不能再次启动")
        if task["status"] == "已完成":
            raise FdeError("已完成任务不能启动")
        if task["status"] != "待办":
            raise FdeError("仅待办任务可以启动")

        self._change_status(task_no, "进行中")
        return self._get_task(task_no)

    def complete(self, task_no: str):
        task = self._get_task(task_no)
        task_no = task["task_no"]

        if task["status"] == "待办":
            raise FdeError("待办任务不能直接完成")
        if task["status"] == "已完成":
            raise FdeError("已完成任务不能重复完成")
        if task["status"] != "进行中":
            raise FdeError("仅进行中任务可以完成")

        self._change_status(task_no, "已完成")
        return self._get_task(task_no)

    def reopen(self, task_no: str):
        task = self._get_task(task_no)
        task_no = task["task_no"]

        if task["status"] == "待办":
            raise FdeError("待办任务不能退回")
        if task["status"] == "已完成":
            raise FdeError("已完成任务不能退回")
        if task["status"] != "进行中":
            raise FdeError("仅进行中任务可以退回")

        self._change_status(task_no, "待办")
        return self._get_task(task_no)

    def _now(self):
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")

    def _clean_task_no(self, task_no):
        clean_task_no = "" if task_no is None else str(task_no).strip()
        if not clean_task_no:
            raise FdeError("任务编号不能为空")
        return clean_task_no

    def _get_task(self, task_no):
        clean_task_no = self._clean_task_no(task_no)

        row = self.db.execute(
            """
                SELECT task_no, title, description, assignee_member_no, priority, status, created_at, updated_at
                FROM task
                WHERE task_no = ?
            """,
            (clean_task_no,),
        ).fetchone()

        if row is None:
            raise FdeError("任务不存在")
        return dict(row)

    def _change_status(self, task_no, new_status):
        clean_task_no = self._clean_task_no(task_no)

        if new_status not in self.VALID_STATUSES:
            raise FdeError("任务状态不合法")

        cursor = self.db.execute(
            """
                UPDATE task
                SET status = ?, updated_at = ?
                WHERE task_no = ?
            """,
            (new_status, self._now(), clean_task_no),
        )
        if cursor.rowcount == 0:
            raise FdeError("任务不存在")

    def _generate_task_no(self):
        for _ in range(5):
            task_no = "T" + uuid.uuid4().hex.upper()
            row = self.db.execute(
                "SELECT 1 FROM task WHERE task_no = ?",
                (task_no,),
            ).fetchone()
            if row is None:
                return task_no

        raise FdeError("任务编号生成失败，请重试")