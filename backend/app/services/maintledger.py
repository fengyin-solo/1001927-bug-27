"""检修汇总台账：以任务编号为键汇总派发、改派与检定结论。

台账行由 MaintjobService 在动作流转时 upsert，本服务只负责读取、筛选与导出。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "maintledger"


class MaintledgerService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        crew: str | None = None,
        source: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("任务编号", ""))]
        if crew:
            rows = [row for row in rows if crew in str(row.get("作业班组", ""))]
        if source:
            rows = [row for row in rows if row.get("台账来源") == source]
        rows = sorted(rows, key=lambda row: str(row.get("更新时间", "")), reverse=True)
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total
