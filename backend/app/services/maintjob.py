"""检修任务业务规则：状态流转、班组权限、改派/撤回记录与汇总台账联动。

口径约定：
- 状态序列固定为 待派发 → 已派发 → 检修中 → 已完成，不允许把已完成任务拉回。
- 变更类动作（派发、改派、撤回、开始检修、确认完成）只有当前接管班组与值班管理员
  能提交，其它班组只读；越权提交返回可读原因，不产生任何改动。
- 派发与撤回保留完整历史记录，改派只保留一条最新记录（重复改派覆盖旧记录）。
- 列表、详情、导出统一走 _present 投影，任务状态/作业班组/负责人只有一个数据源。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "maintjob"
LEDGER_MODULE = "maintledger"
REQUIRED_FIELDS = ["任务编号", "关联机组", "检修类型"]
OPTIONAL_FIELDS = ["计划开始日", "计划工时", "作业班组", "负责人"]
STATUS_ORDER = ["待派发", "已派发", "检修中", "已完成"]
DONE_STATUS = STATUS_ORDER[-1]
ACTION_RULES = {"派发任务": "已派发", "开始检修": "检修中", "确认完成": "已完成"}
ADMIN_ROLE = "值班管理员"
ADMIN_CREW = "值班管理组"
LEDGER_SOURCE_DISPATCH = "检修任务派发"
LEDGER_SOURCE_CONFIRM = "检修任务确认"
LEDGER_SOURCE_BACKFILL = "存量回填"
BACKFILL_REMARK = "存量回填：按改派治理前当时口径补录"
BACKFILL_TIME = "2026-09-01 08:00:00"
CONCLUSION_OK = "一次验收合格"
CONCLUSION_PENDING = "未检定（任务未完成）"


class Operator:
    """请求身份：姓名、所属班组与角色；角色缺省按值班管理员兜底。"""

    def __init__(self, name: str, crew: str, role: str) -> None:
        self.name = name.strip() or "未署名"
        self.crew = crew.strip()
        self.role = role.strip() or ADMIN_ROLE

    @property
    def is_admin(self) -> bool:
        return self.role == ADMIN_ROLE

    @property
    def crew_label(self) -> str:
        return ADMIN_CREW if self.is_admin else self.crew


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _text(values: dict[str, Any], key: str) -> str:
    return str(values.get(key) or "").strip()


class MaintjobService:
    _backfilled = False

    # ---------- 读取与统一投影 ----------

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("任务编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self._present(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return self._present(entry) if entry is not None else None

    def _present(self, entry: dict[str, Any]) -> dict[str, Any]:
        """统一出口：所有字段以同一份底层数据投影，保证列表/详情/刷新后口径一致。

        前端各入口读的是「任务状态」，这里统一由内部 status 派生，杜绝两处对不上。
        """
        data = dict(entry)
        data["任务状态"] = entry.get("status", STATUS_ORDER[0])
        return data

    # ---------- 登记 ----------

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str], str]:
        missing = [field for field in REQUIRED_FIELDS if not _text(values, field)]
        if missing:
            return None, missing, ""
        task_no = _text(values, "任务编号")
        if any(str(row.get("任务编号", "")) == task_no for row in store.rows(MODULE)):
            return None, [], f"任务编号 {task_no} 已存在，请勿重复登记"
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry["任务编号"] = task_no
        for field in REQUIRED_FIELDS[1:] + OPTIONAL_FIELDS:
            value = _text(values, field)
            if value:
                entry[field] = value
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["派发记录"] = []
        rows.append(entry)
        return self._present(entry), [], ""

    # ---------- 动作主入口 ----------

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any],
        operator: Operator,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"检修任务单 {entry_id} 不存在或已归档"
        if not action:
            return None, "未指定要执行的动作"
        if action == "改派":
            return self._reassign(entry, values, operator)
        if action == "撤回":
            return self._withdraw(entry, operator)
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于检修任务可执行范围"
        target = ACTION_RULES[action]

        denied = self._deny_change(entry, operator)
        if denied:
            return None, denied
        if action == "派发任务":
            return self._dispatch(entry, values, operator)
        if entry["status"] == DONE_STATUS:
            return None, "任务已确认完成，不允许再变更状态"
        if target == "检修中" and entry["status"] != "已派发":
            return None, "只有已派发的任务才能开始检修"
        if action == "确认完成":
            if entry["status"] not in ("已派发", "检修中"):
                return None, f"当前状态为「{entry['status']}」，只有在途任务能确认完成"
            return self._confirm(entry, values, operator)

        entry["status"] = target
        entry["pending"] = target != DONE_STATUS
        return self._present(entry), f"检修任务单已{action}"

    # ---------- 权限 ----------

    def _deny_change(self, entry: dict[str, Any], operator: Operator) -> str:
        """变更类动作的统一闸门：值班管理员或当前接管班组可操作，其它班组只读。"""
        if operator.is_admin:
            return ""
        current = str(entry.get("作业班组") or "").strip()
        if not current:
            return "任务尚未派发到班组，只有值班管理员能发起派发"
        if operator.crew != current:
            return (
                f"任务当前由「{current}」接管，{operator.crew or '该账号'}只能查看，"
                f"无权提交变更；如需处理请联系值班管理员改派"
            )
        return ""

    # ---------- 派发 ----------

    def _dispatch(
        self,
        entry: dict[str, Any],
        values: dict[str, Any],
        operator: Operator,
    ) -> tuple[dict[str, Any] | None, str]:
        if not operator.is_admin:
            return None, "只有值班管理员能派发任务"
        if entry["status"] != STATUS_ORDER[0]:
            return None, f"当前状态为「{entry['status']}」，只有待派发任务能执行派发"
        crew = _text(values, "作业班组")
        owner = _text(values, "负责人")
        if not crew or not owner:
            return None, "派发必须指定作业班组与负责人"
        entry["作业班组"] = crew
        entry["负责人"] = owner
        entry["status"] = "已派发"
        entry["pending"] = True
        # 派发与撤回保留完整历史（修复此前撤回后历史记录丢失的问题）
        self._append_record(entry, "派发任务", crew, owner, operator, _text(values, "remark"))
        self._sync_ledger(entry, LEDGER_SOURCE_DISPATCH)
        return self._present(entry), f"检修任务单已派发给 {crew}（负责人：{owner}）"

    # ---------- 改派 ----------

    def _reassign(
        self,
        entry: dict[str, Any],
        values: dict[str, Any],
        operator: Operator,
    ) -> tuple[dict[str, Any] | None, str]:
        if entry["status"] not in ("已派发", "检修中"):
            return None, f"当前状态为「{entry['status']}」，只有已派发/检修中的任务能改派"
        denied = self._deny_change(entry, operator)
        if denied:
            return None, denied
        new_crew = _text(values, "接管班组")
        new_owner = _text(values, "接管负责人")
        if not new_crew or not new_owner:
            return None, "改派必须指定接管班组与接管负责人"
        old_crew = str(entry.get("作业班组") or "")
        if new_crew == old_crew and not operator.is_admin:
            return None, f"任务已经在「{new_crew}」名下，无需改派回本班组"
        entry["作业班组"] = new_crew
        entry["负责人"] = new_owner
        self._append_record(
            entry, "改派", new_crew, new_owner, operator, _text(values, "remark"),
            replace_kind="改派",
        )
        self._sync_ledger(entry, LEDGER_SOURCE_DISPATCH)
        return self._present(entry), f"任务已改派给 {new_crew}（负责人：{new_owner}），原班组 {old_crew or '—'} 不再持有"

    # ---------- 撤回 ----------

    def _withdraw(
        self,
        entry: dict[str, Any],
        operator: Operator,
    ) -> tuple[dict[str, Any] | None, str]:
        if entry["status"] == DONE_STATUS:
            return None, "任务已确认完成，不能拉回待派发"
        if entry["status"] not in ("已派发", "检修中"):
            return None, f"当前状态为「{entry['status']}」，没有可撤回的派发"
        denied = self._deny_change(entry, operator)
        if denied:
            return None, denied
        old_crew = str(entry.get("作业班组") or "")
        old_owner = str(entry.get("负责人") or "")
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry.pop("作业班组", None)
        entry.pop("负责人", None)
        # 撤回记录同样追加保留，形成完整派发/改派/撤回历史
        self._append_record(entry, "撤回", old_crew, old_owner, operator, "")
        self._sync_ledger(entry, LEDGER_SOURCE_DISPATCH)
        return self._present(entry), f"任务已撤回至待派发，原接管班组「{old_crew}」不再持有，请重新派发"

    # ---------- 确认完成（检定结论落台账） ----------

    def _confirm(
        self,
        entry: dict[str, Any],
        values: dict[str, Any],
        operator: Operator,
    ) -> tuple[dict[str, Any] | None, str]:
        conclusion = _text(values, "检定结论")
        if not conclusion:
            return None, "确认完成必须填写检定结论，结论需落入汇总台账"
        entry["检定结论"] = conclusion
        entry["status"] = DONE_STATUS
        entry["pending"] = False
        self._sync_ledger(entry, LEDGER_SOURCE_CONFIRM)
        return self._present(entry), f"检修任务单已确认完成，检定结论「{conclusion}」已落入汇总台账"

    # ---------- 派发记录 ----------

    def _append_record(
        self,
        entry: dict[str, Any],
        kind: str,
        crew: str,
        owner: str,
        operator: Operator,
        remark: str,
        *,
        replace_kind: str | None = None,
    ) -> None:
        """写入派发/改派/撤回记录。

        - 派发、撤回：追加保留完整历史（修复此前历史派发记录丢失的问题）；
        - 改派（replace_kind）：只保留一条最新改派记录，重复改派覆盖旧记录。
        """
        records = entry.setdefault("派发记录", [])
        if replace_kind is not None:
            records = [r for r in records if r.get("类型") != replace_kind]
            entry["派发记录"] = records
        record = {
            "类型": kind,
            "作业班组": crew,
            "负责人": owner,
            "操作人": operator.name,
            "操作人班组": operator.crew_label,
            "时间": _now(),
        }
        if remark:
            record["备注"] = remark
        records.append(record)

    # ---------- 汇总台账 ----------

    def _sync_ledger(self, entry: dict[str, Any], source: str) -> None:
        """以任务编号为键 upsert 汇总台账；确认完成时同步检定结论。"""
        task_no = str(entry.get("任务编号") or "")
        if not task_no:
            return
        rows = store.rows(LEDGER_MODULE)
        ledger = next((row for row in rows if str(row.get("任务编号")) == task_no), None)
        if ledger is None:
            ledger = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
            rows.append(ledger)
        ledger["任务编号"] = task_no
        for field in ("关联机组", "检修类型", "计划开始日", "计划工时", "检定结论"):
            value = entry.get(field)
            if value:
                ledger[field] = value
        # 撤回会清掉作业班组/负责人，台账必须同步删除，不能残留旧班组
        for field in ("作业班组", "负责人"):
            value = entry.get(field)
            if value:
                ledger[field] = value
            else:
                ledger.pop(field, None)
        ledger["任务状态"] = entry["status"]
        ledger["pending"] = bool(entry.get("pending"))
        ledger["abnormal"] = bool(entry.get("abnormal"))
        ledger["台账来源"] = source
        ledger["更新时间"] = _now()

    # ---------- 存量回填 ----------

    def backfill_legacy(self) -> int:
        """存量数据按当时口径回填：派发记录与汇总台账缺失的任务补成记录。

        幂等：已回填过的任务不重复补；已完成任务结论补“一次验收合格”，
        未完成任务补“未检定（任务未完成）”。
        """
        if MaintjobService._backfilled:
            return 0
        MaintjobService._backfilled = True
        changed = 0
        for entry in store.rows(MODULE):
            touched = False
            records = entry.setdefault("派发记录", [])
            crew = str(entry.get("作业班组") or "").strip()
            owner = str(entry.get("负责人") or "").strip()
            if crew and not records:
                records.append({
                    "类型": "派发任务",
                    "作业班组": crew,
                    "负责人": owner,
                    "操作人": "系统",
                    "操作人班组": "存量回填",
                    "时间": BACKFILL_TIME,
                    "备注": BACKFILL_REMARK,
                })
                touched = True
            if "检定结论" not in entry and entry.get("status") == DONE_STATUS:
                entry["检定结论"] = CONCLUSION_OK
                touched = True
            task_no = str(entry.get("任务编号") or "")
            ledger_rows = store.rows(LEDGER_MODULE)
            exists = any(str(row.get("任务编号")) == task_no for row in ledger_rows)
            if task_no and not exists:
                ledger = {"id": max((int(row.get("id", 0)) for row in ledger_rows), default=0) + 1}
                ledger["任务编号"] = task_no
                for field in ("关联机组", "检修类型", "计划开始日", "计划工时", "作业班组", "负责人"):
                    value = entry.get(field)
                    if value:
                        ledger[field] = value
                ledger["任务状态"] = entry["status"]
                ledger["pending"] = bool(entry.get("pending"))
                ledger["abnormal"] = bool(entry.get("abnormal"))
                ledger["检定结论"] = str(
                    entry.get("检定结论")
                    or (CONCLUSION_OK if entry.get("status") == DONE_STATUS else CONCLUSION_PENDING)
                )
                ledger["台账来源"] = LEDGER_SOURCE_BACKFILL
                ledger["更新时间"] = BACKFILL_TIME
                ledger_rows.append(ledger)
                touched = True
            if touched:
                changed += 1
        return changed
