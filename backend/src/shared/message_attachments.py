"""qa 与 agent 消息附件 extra JSON 的键名契约常量（附件清理解析两方 extra 的唯一契约源）。"""
from __future__ import annotations

ATTACHMENT_EXTRA_KEY = "attachments"


def read_attachment_ids(extra: dict | None) -> list[int]:
    """从消息 extra 读附件 ID 列表（缺键/形态异常返回空表，不抛）。

    Args:
        extra: 消息 extra dict（含 attachments 键）；None 视为无附件。

    Returns:
        附件 ID（int）列表，仅收集 id 为整数的附件项。
    """
    if not extra:
        return []
    items = extra.get(ATTACHMENT_EXTRA_KEY) or []
    ids: list[int] = []
    for it in items:
        if isinstance(it, dict) and isinstance(it.get("id"), int):
            ids.append(it["id"])
    return ids


def write_attachment_ids(extra: dict | None, items: list[dict]) -> dict:
    """把附件信息列表写入消息 extra（返回新 dict，不改原对象）。

    Args:
        extra: 原消息 extra dict；None 视为空 dict。
        items: 附件信息 dict 列表（每项含 id 等字段）。

    Returns:
        带 attachments 键的新 extra dict。
    """
    out = dict(extra or {})
    out[ATTACHMENT_EXTRA_KEY] = items
    return out


__all__ = ["ATTACHMENT_EXTRA_KEY", "read_attachment_ids", "write_attachment_ids"]
