"""检修任务接口：派发/改派/撤回/检修/完成，按当前登录账号班组做越权拦截。"""
from __future__ import annotations

from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Query, Request

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.maintjob import (
    ADMIN_ROLE,
    ActionDenied,
    ActionRejected,
    MaintjobService,
)

router = APIRouter(prefix="/api/maintjob", tags=["检修任务"])

service = MaintjobService()

LIST_FIELDS = ["任务编号", "关联机组", "检修类型", "计划开始日", "计划工时", "作业班组", "负责人", "任务状态"]
STATUSES = ["待派发", "已派发", "检修中", "已完成"]


def _actor(request: Request) -> dict[str, str]:
    """从请求头解析当前账号；身份信息由前端百分号编码，这里统一解码。"""
    def head(name: str) -> str:
        return unquote(request.headers.get(name, "").strip())

    return {
        "name": head("x-operator-name"),
        "team": head("x-operator-team"),
        "role": head("x-operator-role") or "班组人员",
    }


def _denied(exc: ActionDenied | ActionRejected) -> HTTPException:
    if isinstance(exc, ActionDenied):
        return HTTPException(status_code=403, detail=exc.message)
    return HTTPException(status_code=409, detail=exc.message)


# 注意：/export、/history、/ledger 都是静态路径，必须排在 /{entry_id} 之前，
# 否则 “export” 会被当成任务单 id 解析。
@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出检修任务清单：返回当前全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "maintjob", "total": total, "items": items}


@router.get("/history")
def list_history(
    entry_id: int | None = Query(default=None, description="按任务单 id 过滤派发记录"),
) -> dict[str, Any]:
    """派发/改派/撤回历史：同一任务重复改派只保留最新一条。"""
    return {"items": service.list_history(entry_id=entry_id)}


@router.get("/ledger")
def list_ledger(
    keyword: str | None = Query(default=None, description="按任务编号检索汇总台账"),
) -> dict[str, Any]:
    """汇总台账：任务编号与检定结论一一对应。"""
    return {"items": service.list_ledger(keyword=keyword)}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按任务编号检索"),
    status: str | None = Query(default=None, description="待派发、已派发、检修中、已完成"),
    team: str | None = Query(default=None, description="按当前接管班组过滤"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按任务编号、状态与接管班组过滤检修任务列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, team=team, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条检修任务单明细（含派发记录与台账）；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"检修任务单 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条检修任务单，缺字段或编号重复时说明原因而不是静默丢弃。"""
    try:
        entry, missing = service.create_entry(payload.values)
    except ActionRejected as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="检修任务单已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload, request: Request) -> ActionResult:
    """派发/改派/撤回/开始检修/确认完成；越权 403，状态不符 409，都带可读原因。"""
    action = str(payload.values.get("action") or "").strip()
    try:
        entry, message = service.run_action(entry_id, action, payload.values, _actor(request))
    except (ActionDenied, ActionRejected) as exc:
        raise _denied(exc) from exc
    return ActionResult(ok=True, message=message, entry=entry)
