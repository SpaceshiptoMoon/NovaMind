"""孤儿附件清理任务单测（引用集合收集逻辑 + 常量口径）。"""
import pytest
from novamind.features.qa.tasks.attachment_cleanup import (
    ORPHAN_CUTOFF_DAYS,
    _collect_referenced_ids,
)

pytestmark = pytest.mark.unit


def test_collect_referenced_ids_merges_agent_and_qa_shapes():
    """agent_messages.extra 与 question_answer.extra 的引用形态一致：extra.attachments[].id"""
    rows = [
        ({"attachments": [{"id": 1, "filename": "a.pdf"}, {"id": 2, "filename": "b.pdf"}]},),
        ({"attachments": [{"id": 3}]},),
        ({"attachments": []},),
        ({"other": 1},),
        (None,),
        ("not-a-dict",),
        # 非 dict 的 extra（脏数据）防御性跳过，不收集也不抛错
        ([{"id": 4}],),
    ]
    ids = _collect_referenced_ids(rows)
    assert ids == {1, 2, 3}


def test_collect_referenced_ids_empty():
    assert _collect_referenced_ids([]) == set()


def test_orphan_cutoff_days_sane():
    """误删兜底：至少 7 天，避免用户上传未发送即被清"""
    assert ORPHAN_CUTOFF_DAYS >= 7