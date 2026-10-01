"""检修任务改派权限/历史/台账场景测试（内存仓库，直接跑：python3 -m pytest 或 python3 文件）。"""
from __future__ import annotations

from app.services.accept import service as accept_service
from app.services.maintjob import ActionDenied, ActionRejected, service
from app.store import store

ADMIN = {"name": "赵值班", "team": "值班室", "role": "值班管理员"}
MECH = {"name": "张工", "team": "机械一班", "role": "班组人员"}
ELEC = {"name": "李工", "team": "电气二班", "role": "班组人员"}
NOBODY = {"name": "", "team": "", "role": "班组人员"}


def setup_function(_) -> None:
    # 重新装载内存数据，保证用例间互不干扰
    from app import seed
    for name in list(store._tables):
        if name.startswith("maintjob_"):
            store._tables[name] = []
    store._tables["maintjob"] = [dict(r) for r in seed.SEED_ROWS["maintjob"]]
    service._backfill_done = False
    service.ensure_backfill()


def test_backfill_and_consistency() -> None:
    rows, total = service.list_entries()
    assert total == 4
    by_id = {row["id"]: row for row in rows}
    # 待派发没有接管班组
    assert by_id[1]["作业班组"] == "" and by_id[1]["负责人"] == ""
    # 存量班组/负责人按当时口径回填
    assert (by_id[2]["作业班组"], by_id[2]["负责人"]) == ("机械一班", "张工")
    assert (by_id[3]["作业班组"], by_id[3]["负责人"]) == ("电气二班", "李工")
    # 列表与详情同一投影
    for row in rows:
        detail = service.get_entry(row["id"])
        assert (detail["作业班组"], detail["负责人"], detail["status"]) == (
            row["作业班组"], row["负责人"], row["status"],
        )
    # 已完成存量任务台账已回填
    ledger = {x["任务编号"]: x for x in service.list_ledger()}
    assert ledger["MAIN-0004"]["检定结论"] == "合格"
    # 存量历史按当时口径（时间倒序，同时间按 id 倒序）
    h4 = service.list_history(entry_id=4)
    assert [(x["动作"], x["作业班组"]) for x in h4] == [
        ("开始检修", "机械一班"), ("派发任务", "机械一班"),
    ]
    h2 = service.list_history(entry_id=2)
    assert [(x["动作"], x["作业班组"]) for x in h2] == [("派发任务", "机械一班")]


def test_cross_team_withdraw_blocked() -> None:
    # 电气二班不能撤回机械一班的任务
    try:
        service.run_action(2, "撤回任务", {}, ELEC)
        raise AssertionError("越权撤回未拦截")
    except ActionDenied as exc:
        assert "电气二班" in exc.message and "机械一班" in exc.message
        assert "仅可查看" in exc.message


def test_owner_withdraw_and_history_kept() -> None:
    entry, msg = service.run_action(2, "撤回任务", {}, MECH)
    assert entry["status"] == "待派发"
    assert entry["作业班组"] == "" and entry["负责人"] == ""
    assert "机械一班" in msg
    history = service.list_history(entry_id=2)
    assert [x["动作"] for x in history] == ["撤回任务", "派发任务"]
    # 撤回记录不挂撤回人班组，列表/详情不会显示成撤回人
    assert history[0]["作业班组"] == ""


def test_dispatch_requires_admin_when_pending() -> None:
    try:
        service.run_action(1, "派发任务", {"作业班组": "电气二班"}, ELEC)
        raise AssertionError("普通班组不应能派发待派发任务")
    except ActionDenied:
        pass
    entry, _ = service.run_action(
        1, "派发任务", {"作业班组": "电气二班", "负责人": "李工"}, ADMIN
    )
    assert (entry["作业班组"], entry["负责人"], entry["status"]) == (
        "电气二班", "李工", "已派发",
    )


def test_reassign_permission_follows_new_team() -> None:
    # 管理员改派给电气二班
    service.run_action(
        2, "改派任务", {"作业班组": "电气二班", "负责人": "李工"}, ADMIN
    )
    # 原班组机械一班立即失权
    try:
        service.run_action(2, "撤回任务", {}, MECH)
        raise AssertionError("改派后旧班组仍能操作")
    except ActionDenied:
        pass
    # 新接管班组可以操作
    entry, _ = service.run_action(2, "撤回任务", {}, ELEC)
    assert entry["status"] == "待派发"


def test_duplicate_reassign_merges_latest() -> None:
    service.run_action(2, "撤回任务", {}, MECH)
    service.run_action(2, "派发任务", {"作业班组": "电气二班", "负责人": "李工"}, ADMIN)
    # 完全相同的改派直接拦下
    try:
        service.run_action(2, "改派任务", {"作业班组": "电气二班", "负责人": "李工"}, ELEC)
        raise AssertionError("完全相同改派未拦截")
    except ActionRejected:
        pass
    # 改派机械一班：新增一条
    service.run_action(2, "改派任务", {"作业班组": "机械一班", "负责人": "张工"}, ADMIN)
    n_before = len(service.list_history(entry_id=2))
    # 紧接着又改派机械一班换负责人：并入最新一条，不新增
    _, msg = service.run_action(
        2, "改派任务", {"作业班组": "机械一班", "负责人": "王工"}, ADMIN
    )
    assert "并入最新" in msg
    history = service.list_history(entry_id=2)
    assert len(history) == n_before
    latest = history[0]
    assert latest["动作"] == "改派任务" and latest["负责人"] == "王工"
    # 归属表同步更新，列表/详情一致
    assert service.get_entry(2)["负责人"] == "王工"


def test_reassign_after_progress_keeps_separate_record() -> None:
    service.run_action(2, "撤回任务", {}, MECH)
    service.run_action(2, "派发任务", {"作业班组": "电气二班", "负责人": "李工"}, ADMIN)
    service.run_action(2, "改派任务", {"作业班组": "机械一班", "负责人": "张工"}, ADMIN)
    service.run_action(2, "开始检修", {}, MECH)
    n_before = len(service.list_history(entry_id=2))
    # 检修中改派回电气二班：属于新一轮改派，应独立留痕
    service.run_action(2, "改派任务", {"作业班组": "电气二班", "负责人": "李工"}, ADMIN)
    assert len(service.list_history(entry_id=2)) == n_before + 1


def test_finished_task_cannot_be_pulled_back() -> None:
    for action, values in [
        ("撤回任务", {}),
        ("改派任务", {"作业班组": "电气二班"}),
        ("确认完成", {"检定结论": "x"}),
    ]:
        try:
            service.run_action(4, action, values, ADMIN)
            raise AssertionError(f"已完成任务可执行 {action}")
        except ActionRejected:
            pass
    assert service.get_entry(4)["status"] == "已完成"


def test_full_flow_writes_ledger_conclusion() -> None:
    service.run_action(1, "派发任务", {"作业班组": "电气二班", "负责人": "李工"}, ADMIN)
    try:
        service.run_action(1, "开始检修", {}, MECH)
        raise AssertionError("非接管班组能开始检修")
    except ActionDenied:
        pass
    service.run_action(1, "开始检修", {}, ELEC)
    try:
        service.run_action(1, "确认完成", {"检定结论": "整改后合格"}, NOBODY)
        raise AssertionError("无身份账号能完成任务")
    except ActionDenied:
        pass
    _, msg = service.run_action(1, "确认完成", {"检定结论": "整改后合格"}, ELEC)
    assert "汇总台账" in msg
    ledger = service.ledger_of("MAIN-0001")
    assert ledger["检定结论"] == "整改后合格"
    # 再次 upsert 不产生重复行
    ledger_rows = [x for x in service.list_ledger() if x["任务编号"] == "MAIN-0001"]
    assert len(ledger_rows) == 1


def test_accept_conclusion_syncs_to_ledger() -> None:
    store.rows("accept").append({
        "id": 99, "status": "验收中", "pending": True, "abnormal": False,
        "验收单号": "ACCE-0099", "关联任务": "MAIN-0003",
        "验收项目": "变桨消缺验收", "验收结论": "验收合格，准予投运",
    })
    accept_service.run_action(99, "确认通过")
    assert service.ledger_of("MAIN-0003")["检定结论"] == "验收合格，准予投运"
