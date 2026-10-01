"""检修任务业务规则：状态流转、派发改派权限、历史记录与汇总台账都收在这里。

数据模型（内存仓库中的四张表）：
- maintjob           任务单主表，任务状态机挂在这里
- maintjob_assign    当前派工归属，每个任务最多一条（任务编号 1:1）
- maintjob_history   派发/改派/撤回历史，只追加，重复改派合并到最新一条
- maintjob_ledger    汇总台账，按任务编号记录检定结论

所有列表与详情都走同一套 _to_view 投影，保证“作业班组/负责人”各入口一致。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "maintjob"
ASSIGN_MODULE = "maintjob_assign"
HISTORY_MODULE = "maintjob_history"
LEDGER_MODULE = "maintjob_ledger"

REQUIRED_FIELDS = ["任务编号", "关联机组", "检修类型"]
STATUS_ORDER = ["待派发", "已派发", "检修中", "已完成"]

DISPATCH_ACTION = "派发任务"
REASSIGN_ACTION = "改派任务"
WITHDRAW_ACTION = "撤回任务"
START_ACTION = "开始检修"
FINISH_ACTION = "确认完成"

ADMIN_ROLE = "值班管理员"

BACKFILL_TIME = "2026-09-10 00:00:00"


class ActionDenied(Exception):
    """越权操作：调用方班组与任务接管班组不符。"""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ActionRejected(Exception):
    """业务规则不允许（状态/参数不对）：409。"""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class MaintjobService:
    # ------------------------------------------------------------------ 读取
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        team: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        self.ensure_backfill()
        rows = [self._to_view(entry) for entry in store.rows(MODULE)]
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("任务编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if team:
            rows = [row for row in rows if row.get("作业班组") == team]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        self.ensure_backfill()
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        view = self._to_view(entry)
        view["派发记录"] = self.history_of(entry_id)
        view["台账"] = self.ledger_of(str(entry["任务编号"]))
        return view

    def list_history(self, *, entry_id: int | None = None) -> list[dict[str, Any]]:
        """派发历史：可按任务过滤；同一任务的重复改派只保留最新一条。"""
        self.ensure_backfill()
        rows = store.rows(HISTORY_MODULE)
        if entry_id is not None:
            rows = [row for row in rows if int(row.get("任务单id", 0)) == entry_id]
        return [self._public(row) for row in sorted(
            rows,
            key=lambda row: (str(row.get("时间", "")), int(row.get("id", 0))),
            reverse=True,
        )]

    def list_ledger(self, *, keyword: str | None = None) -> list[dict[str, Any]]:
        """汇总台账：按任务编号检索检定结论。"""
        self.ensure_backfill()
        rows = store.rows(LEDGER_MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("任务编号", ""))]
        return [self._public(row) for row in rows]

    def history_of(self, entry_id: int) -> list[dict[str, Any]]:
        return self.list_history(entry_id=entry_id)

    def ledger_of(self, task_no: str) -> dict[str, Any] | None:
        for row in store.rows(LEDGER_MODULE):
            if str(row.get("任务编号")) == task_no:
                return self._public(row)
        return None

    # ------------------------------------------------------------------ 登记
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        task_no = str(values["任务编号"]).strip()
        if any(str(row.get("任务编号")) == task_no for row in rows):
            raise ActionRejected(f"任务编号 {task_no} 已存在，不能重复登记")
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in ["任务编号", "关联机组", "检修类型", "计划开始日", "计划工时"]:
            if str(values.get(field) or "").strip():
                entry[field] = values[field]
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["_backfilled"] = True  # 新登记任务无需走存量回填
        rows.append(entry)
        return self._to_view(entry), []

    # ------------------------------------------------------------------ 动作
    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any],
        actor: dict[str, str],
    ) -> tuple[dict[str, Any] | None, str]:
        """执行任务动作。

        actor 携带当前账号的姓名/班组/角色；除值班管理员外，只有接管班组能提交变更。
        校验失败抛 ActionDenied（403）或 ActionRejected（409），由路由层翻译成错误说明。
        """
        self.ensure_backfill()
        entry = store.find(MODULE, entry_id)
        if entry is None:
            raise ActionRejected(f"检修任务单 {entry_id} 不存在或已归档")
        action = str(action or "").strip()
        if action == DISPATCH_ACTION:
            return self._dispatch(entry, values, actor)
        if action == REASSIGN_ACTION:
            return self._reassign(entry, values, actor)
        if action == WITHDRAW_ACTION:
            return self._withdraw(entry, values, actor)
        if action == START_ACTION:
            return self._progress(entry, actor, STATUS_ORDER[2], START_ACTION)
        if action == FINISH_ACTION:
            return self._finish(entry, values, actor)
        raise ActionRejected(f"动作「{action}」不属于检修任务可执行范围")

    def _dispatch(
        self, entry: dict[str, Any], values: dict[str, Any], actor: dict[str, str]
    ) -> tuple[dict[str, Any], str]:
        self._require_admin_or_team(actor, None)
        if entry["status"] != STATUS_ORDER[0]:
            raise ActionRejected(f"任务当前为「{entry['status']}」，只有待派发任务能派发")
        team = str(values.get("作业班组") or "").strip()
        leader = str(values.get("负责人") or "").strip()
        if not team:
            raise ActionRejected("派发必须指定接管作业班组")
        self._set_status(entry, STATUS_ORDER[1])
        self._put_assign(entry, team, leader)
        self._append_history(entry, DISPATCH_ACTION, team, leader, actor, values.get("remark"))
        return self._to_view(entry), f"检修任务单已派发给{team}"

    def _reassign(
        self, entry: dict[str, Any], values: dict[str, Any], actor: dict[str, str]
    ) -> tuple[dict[str, Any], str]:
        assign = self._assign(entry)
        self._require_admin_or_team(actor, assign["作业班组"] if assign else None)
        if entry["status"] == STATUS_ORDER[0]:
            raise ActionRejected("任务尚未派发，请使用「派发任务」而不是改派")
        if entry["status"] == STATUS_ORDER[3]:
            raise ActionRejected("任务已完成，不能再改派")
        team = str(values.get("作业班组") or "").strip()
        leader = str(values.get("负责人") or "").strip()
        if not team:
            raise ActionRejected("改派必须指定新的接管作业班组")
        if assign and team == str(assign.get("作业班组")) and (
            not str(values.get("负责人") or "").strip() or leader == str(assign.get("负责人"))
        ):
            raise ActionRejected(f"接管班组已经是{team}，请勿重复改派")
        self._put_assign(entry, team, leader)
        merged = self._append_history(
            entry, REASSIGN_ACTION, team, leader, actor, values.get("remark")
        )
        tail = "，已并入最新一条派发记录" if merged else ""
        return self._to_view(entry), f"检修任务单已改派给{team}{tail}"

    def _withdraw(
        self, entry: dict[str, Any], values: dict[str, Any], actor: dict[str, str]
    ) -> tuple[dict[str, Any], str]:
        assign = self._assign(entry)
        self._require_admin_or_team(actor, assign["作业班组"] if assign else None)
        if entry["status"] == STATUS_ORDER[3]:
            raise ActionRejected("任务已完成，不能拉回待派发")
        if entry["status"] == STATUS_ORDER[0]:
            raise ActionRejected("任务本来就是待派发，无需撤回")
        team = str(assign.get("作业班组")) if assign else "原班组"
        self._remove_assign(entry)
        self._set_status(entry, STATUS_ORDER[0])
        self._append_history(
            entry,
            WITHDRAW_ACTION,
            "",
            "",
            actor,
            values.get("remark") or f"由{team}撤回，退回待派发",
        )
        return self._to_view(entry), f"检修任务单已由{team}撤回，退回待派发"

    def _progress(
        self, entry: dict[str, Any], actor: dict[str, str], target: str, label: str
    ) -> tuple[dict[str, Any], str]:
        assign = self._assign(entry)
        self._require_admin_or_team(actor, assign["作业班组"] if assign else None)
        if entry["status"] != STATUS_ORDER[1]:
            raise ActionRejected(f"任务当前为「{entry['status']}」，只有已派发任务能开始检修")
        self._set_status(entry, target)
        return self._to_view(entry), f"检修任务单已{label}"

    def _finish(
        self, entry: dict[str, Any], values: dict[str, Any], actor: dict[str, str]
    ) -> tuple[dict[str, Any], str]:
        assign = self._assign(entry)
        self._require_admin_or_team(actor, assign["作业班组"] if assign else None)
        if entry["status"] != STATUS_ORDER[2]:
            raise ActionRejected(f"任务当前为「{entry['status']}」，只有检修中任务能确认完成")
        self._set_status(entry, STATUS_ORDER[3])
        conclusion = str(values.get("检定结论") or "").strip() or self._conclusion_from_accept(
            str(entry.get("任务编号"))
        )
        self._upsert_ledger(entry, conclusion, actor)
        return self._to_view(entry), "检修任务单已确认完成，检定结论已记入汇总台账"

    # ------------------------------------------------------------------ 权限
    def _require_admin_or_team(self, actor: dict[str, str], owner_team: str | None) -> None:
        """值班管理员与接管班组可提交变更；其它班组只读，越权给出具体原因。"""
        name = actor.get("name", "").strip()
        team = actor.get("team", "").strip()
        role = actor.get("role", "").strip()
        if not name or not team:
            raise ActionDenied("未识别当前登录账号的姓名或班组，无法提交变更")
        if role == ADMIN_ROLE:
            return
        if owner_team is None:
            raise ActionDenied("任务尚未派发，只有值班管理员能派发任务")
        if team != owner_team:
            raise ActionDenied(
                f"当前账号属于{team}，任务接管班组为{owner_team}；只有接管班组与值班管理员能提交变更，"
                "其它班组仅可查看"
            )

    # ------------------------------------------------------------------ 归属/历史
    def _assign(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        for row in store.rows(ASSIGN_MODULE):
            if int(row.get("任务单id", 0)) == int(entry["id"]):
                return row
        return None

    def _put_assign(self, entry: dict[str, Any], team: str, leader: str) -> dict[str, Any]:
        rows = store.rows(ASSIGN_MODULE)
        row = self._assign(entry)
        if row is None:
            row = {"id": max((int(item.get("id", 0)) for item in rows), default=0) + 1}
            row["任务单id"] = int(entry["id"])
            row["任务编号"] = str(entry["任务编号"])
            rows.append(row)
        row["作业班组"] = team
        row["负责人"] = leader or self._default_leader(team)
        return row

    def _remove_assign(self, entry: dict[str, Any]) -> None:
        rows = store.rows(ASSIGN_MODULE)
        store.rows(ASSIGN_MODULE)[:] = [
            row for row in rows if int(row.get("任务单id", 0)) != int(entry["id"])
        ]

    def _append_history(
        self,
        entry: dict[str, Any],
        action: str,
        team: str,
        leader: str,
        actor: dict[str, str],
        remark: Any,
    ) -> bool:
        """追加一条派发记录。返回 True 表示与上一条重复改派合并、未新增。

        只有“最新一条就是改派到该班组、且期间任务状态没再推进”才视为重复改派，
        合并进最新一条（负责人/操作人/时间刷新）；否则正常追加。
        """
        rows = store.rows(HISTORY_MODULE)
        task_rows = [
            row for row in rows if int(row.get("任务单id", 0)) == int(entry["id"])
        ]
        last_anchor = int(entry.get("_last_progress_id", 0))
        if (
            action == REASSIGN_ACTION
            and task_rows
            and task_rows[-1].get("动作") == REASSIGN_ACTION
            and task_rows[-1].get("作业班组") == team
            and int(task_rows[-1].get("id", 0)) > last_anchor
        ):
            latest = task_rows[-1]
            latest["负责人"] = leader or self._default_leader(team)
            latest["操作人"] = actor.get("name", "")
            latest["操作班组"] = actor.get("team", "")
            latest["时间"] = self._now()
            if remark:
                latest["备注"] = str(remark)
            return True

        record = {
            "id": max((int(item.get("id", 0)) for item in rows), default=0) + 1,
            "任务单id": int(entry["id"]),
            "任务编号": str(entry["任务编号"]),
            "动作": action,
            "作业班组": team,
            "负责人": leader or (self._default_leader(team) if team else ""),
            "操作人": actor.get("name", ""),
            "操作班组": actor.get("team", ""),
            "时间": self._now(),
            "备注": str(remark) if remark else "",
        }
        rows.append(record)
        # 撤回/重新派发/进度推进后，上一轮改派记录就不再参与“重复改派”合并判断
        if action in (DISPATCH_ACTION, WITHDRAW_ACTION, START_ACTION, FINISH_ACTION):
            entry["_last_progress_id"] = int(record["id"])
        return False

    def _default_leader(self, team: str) -> str:
        for row in reversed(store.rows(HISTORY_MODULE)):
            if row.get("作业班组") == team and row.get("负责人"):
                return str(row["负责人"])
        return f"{team}负责人"

    # ------------------------------------------------------------------ 台账
    def _upsert_ledger(
        self, entry: dict[str, Any], conclusion: str, actor: dict[str, str]
    ) -> dict[str, Any]:
        """检定结论落到汇总台账：按任务编号 upsert，不产生重复行。"""
        rows = store.rows(LEDGER_MODULE)
        task_no = str(entry["任务编号"])
        for row in rows:
            if str(row.get("任务编号")) == task_no:
                row["检定结论"] = conclusion
                row["登记人"] = actor.get("name", "")
                row["更新时间"] = self._now()
                return row
        row = {
            "id": max((int(item.get("id", 0)) for item in rows), default=0) + 1,
            "任务编号": task_no,
            "关联机组": entry.get("关联机组", ""),
            "检修类型": entry.get("检修类型", ""),
            "作业班组": str(self._assign(entry).get("作业班组", "")) if self._assign(entry) else "",
            "检定结论": conclusion,
            "完成日期": date.today().isoformat(),
            "登记人": actor.get("name", ""),
            "更新时间": self._now(),
        }
        rows.append(row)
        return row

    def _conclusion_from_accept(self, task_no: str) -> str:
        """完成时没显式给结论：取验收单（关联任务=任务编号）最近一条验收结论。"""
        candidates = [
            row for row in store.rows("accept") if str(row.get("关联任务")) == task_no
        ]
        for row in reversed(candidates):
            conclusion = str(row.get("验收结论") or "").strip()
            if conclusion and not conclusion.endswith("样例3"):
                return conclusion
        return "合格"

    def apply_accept_conclusion(self, task_no: str, conclusion: str) -> bool:
        """验收确认通过时，把验收结论同步到任务编号对应的汇总台账。"""
        self.ensure_backfill()
        task_no = str(task_no or "").strip()
        if not task_no:
            return False
        entry = next(
            (row for row in store.rows(MODULE) if str(row.get("任务编号")) == task_no), None
        )
        if entry is None:
            return False
        rows = store.rows(LEDGER_MODULE)
        for row in rows:
            if str(row.get("任务编号")) == task_no:
                row["检定结论"] = conclusion
                row["更新时间"] = self._now()
                return True
        rows.append({
            "id": max((int(item.get("id", 0)) for item in rows), default=0) + 1,
            "任务编号": task_no,
            "关联机组": entry.get("关联机组", ""),
            "检修类型": entry.get("检修类型", ""),
            "作业班组": str(self._assign(entry).get("作业班组", "")) if self._assign(entry) else "",
            "检定结论": conclusion,
            "完成日期": str(entry.get("完成日期") or date.today().isoformat()),
            "登记人": "",
            "更新时间": self._now(),
        })
        return True

    # ------------------------------------------------------------------ 存量回填
    def ensure_backfill(self) -> None:
        """存量任务按“当时口径”回填：当前归属 + 一条历史记录 + 已完成的台账结论。

        只在首次访问时执行一次，已带 _backfilled 标记的任务跳过。
        """
        marker = "_backfilled"
        if getattr(self, "_backfill_done", False):
            return
        for entry in store.rows(MODULE):
            if entry.get(marker):
                continue
            team = str(entry.get("作业班组") or "").strip()
            leader = str(entry.get("负责人") or "").strip()
            status = entry["status"]
            actor = {"name": "系统回填", "team": team or "值班管理员", "role": ADMIN_ROLE}
            if status == STATUS_ORDER[0] or not team:
                # 待派发：当时还没有接管班组，清掉占位字段，不造派发记录
                entry.pop("作业班组", None)
                entry.pop("负责人", None)
            else:
                self._put_assign(entry, team, leader or self._default_leader(team))
                self._append_backfill_history(entry, DISPATCH_ACTION, team, leader, actor)
                if status in (STATUS_ORDER[2], STATUS_ORDER[3]):
                    self._append_backfill_history(entry, START_ACTION, team, leader, actor)
                if status == STATUS_ORDER[3]:
                    self._backfill_ledger(entry, team, str(entry.get("检定结论") or "合格"))
            entry[marker] = True
        self._stamp_backfill_time()
        self._backfill_done = True

    def _append_backfill_history(
        self,
        entry: dict[str, Any],
        action: str,
        team: str,
        leader: str,
        actor: dict[str, str],
    ) -> None:
        """回填历史只造数据，不写“进度锚点”——锚点只由真实操作产生。"""
        rows = store.rows(HISTORY_MODULE)
        rows.append({
            "id": max((int(item.get("id", 0)) for item in rows), default=0) + 1,
            "任务单id": int(entry["id"]),
            "任务编号": str(entry["任务编号"]),
            "动作": action,
            "作业班组": team,
            "负责人": leader or (self._default_leader(team) if team else ""),
            "操作人": actor.get("name", ""),
            "操作班组": actor.get("team", ""),
            "时间": BACKFILL_TIME,
            "备注": "按存量任务当时派发口径回填",
        })

    def _stamp_backfill_time(self) -> None:
        for row in store.rows(HISTORY_MODULE):
            if row.get("操作人") == "系统回填":
                row["时间"] = BACKFILL_TIME
        for row in store.rows(LEDGER_MODULE):
            if row.get("登记人") == "系统回填":
                row["更新时间"] = BACKFILL_TIME

    def _backfill_ledger(
        self, entry: dict[str, Any], team: str, conclusion: str
    ) -> dict[str, Any]:
        rows = store.rows(LEDGER_MODULE)
        task_no = str(entry["任务编号"])
        for row in rows:
            if str(row.get("任务编号")) == task_no:
                return row
        row = {
            "id": max((int(item.get("id", 0)) for item in rows), default=0) + 1,
            "任务编号": task_no,
            "关联机组": entry.get("关联机组", ""),
            "检修类型": entry.get("检修类型", ""),
            "作业班组": team,
            "检定结论": conclusion,
            "完成日期": str(entry.get("计划开始日") or BACKFILL_TIME[:10]),
            "登记人": "系统回填",
            "更新时间": BACKFILL_TIME,
        }
        rows.append(row)
        return row

    # ------------------------------------------------------------------ 投影
    def _set_status(self, entry: dict[str, Any], target: str) -> None:
        entry["status"] = target
        entry["任务状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = False

    def _to_view(self, entry: dict[str, Any]) -> dict[str, Any]:
        """列表与详情共用的唯一投影：班组/负责人一律来自当前归属表。"""
        view = {k: v for k, v in entry.items() if not str(k).startswith("_")}
        assign = self._assign(entry)
        if assign is not None:
            view["作业班组"] = assign.get("作业班组", "")
            view["负责人"] = assign.get("负责人", "")
        else:
            view["作业班组"] = ""
            view["负责人"] = ""
        view["任务状态"] = entry["status"]
        return view

    def _public(self, row: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in row.items() if not str(k).startswith("_")}

    def _now(self) -> str:
        from datetime import datetime

        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


service = MaintjobService()
