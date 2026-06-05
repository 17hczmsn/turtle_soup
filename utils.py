"""海龟汤工具函数。"""

from __future__ import annotations

from typing import Any


def get_stream_key(chat_stream: Any) -> str:
    """从聊天流生成状态隔离键。"""

    platform = str(getattr(chat_stream, "platform", "unknown"))
    chat_type = str(getattr(chat_stream, "chat_type", "private"))
    stream_id = getattr(chat_stream, "stream_id", "")
    if stream_id:
        return f"{platform}:stream:{stream_id}"

    raw_id_getter = getattr(chat_stream, "get_raw_id", None)
    if callable(raw_id_getter):
        raw_id = raw_id_getter()
        if raw_id:
            return str(raw_id)

    context = getattr(chat_stream, "context", None)
    current_message = getattr(context, "current_message", None) if context else None
    triggering_user_id = getattr(context, "triggering_user_id", "") if context else ""

    if chat_type == "group":
        group_id = getattr(current_message, "group_id", "") if current_message else ""
        if not group_id and current_message:
            extra = getattr(current_message, "extra", {}) or {}
            group_id = str(extra.get("group_id") or "")
        if group_id:
            return f"{platform}:group:{group_id}"

    user_id = triggering_user_id or (getattr(current_message, "sender_id", "") if current_message else "")
    if user_id:
        return f"{platform}:user:{user_id}"

    return f"{platform}:unknown"
