"""检修任务接口：维护检修任务单，覆盖派发、改派、撤回、开始检修、确认完成等动作。

身份通过请求头带入：X-Operator（姓名）、X-Operator-Crew（所属班组）、
X-Operator-Role（值班管理员/班组账号）。变更类动作的班组权限在服务层兜底校验。
"""
from __future__ import annotations

from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, Header, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.maintjob import ADMIN_ROLE, STATUS_ORDER, MaintjobService, Operator
from app.services.maintledger import MaintledgerService

router = APIRouter(prefix="/api/maintjob", tags=["检修任务"])

service = MaintjobService()
ledger_service = MaintledgerService()

LIST_FIELDS = ["任务编号", "关联机组", "检修类型", "计划开始日", "计划工时", "作业班组", "负责人", "任务状态"]
STATUSES = STATUS_ORDER
LEDGER_SOURCES = ["检修任务派发", "检修任务确认", "存量回填"]


def _operator(
    x_operator: str | None,
    x_operator_crew: str | None,
    x_operator_role: str | None,
) -> Operator:
    # HTTP 头只允许 Latin-1，前端对中文身份字段做百分号编码传输，这里统一解码
    def decode(value: str | None) -> str:
        return unquote(value).strip() if value else ""

    return Operator(
        name=decode(x_operator),
        crew=decode(x_operator_crew),
        role=decode(x_operator_role) or ADMIN_ROLE,
    )


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按任务编号检索"),
    status: str | None = Query(default=None, description="待派发、已派发、检修中、已完成"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按任务编号与状态过滤检修任务列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    if status and status not in STATUSES:
        raise HTTPException(status_code=400, detail=f"任务状态「{status}」不合法，可选：{'、'.join(STATUSES)}")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出检修任务清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "maintjob", "total": total, "items": items}


@router.get("/ledger", response_model=PageResult[dict])
def list_ledger(
    keyword: str | None = Query(default=None, description="按任务编号检索"),
    crew: str | None = Query(default=None, description="按作业班组检索"),
    source: str | None = Query(default=None, description="台账来源：检修任务派发、检修任务确认、存量回填"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """读取检修汇总台账；检定结论在任务确认完成时落入。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    if source and source not in LEDGER_SOURCES:
        raise HTTPException(status_code=400, detail=f"台账来源「{source}」不合法")
    items, total = ledger_service.list_entries(keyword=keyword, crew=crew, source=source, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/ledger/export")
def export_ledger() -> dict[str, Any]:
    """导出检修汇总台账全量数据。"""
    items, total = ledger_service.list_entries(page=1, size=10000)
    return {"module": "maintledger", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条检修任务单明细（含派发记录）；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"检修任务单 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条检修任务单，缺字段时说明原因而不是静默丢弃。"""
    entry, missing, error = service.create_entry(payload.values)
    if error:
        return ActionResult(ok=False, message=error)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="检修任务单已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(
    entry_id: int,
    payload: EntryPayload,
    x_operator: str | None = Header(default=None),
    x_operator_crew: str | None = Header(default=None),
    x_operator_role: str | None = Header(default=None),
) -> ActionResult:
    """派发、改派、撤回、开始检修、确认完成；越权或非法流转会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    operator = _operator(x_operator, x_operator_crew, x_operator_role)
    entry, message = service.run_action(entry_id, action, payload.values, operator)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
