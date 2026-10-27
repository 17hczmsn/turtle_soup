"""主持人 reminder 注入/移除测试。"""

from __future__ import annotations

import pytest

import plugins.turtle_soup.reminder as reminder_module
from ..reminder import build_host_reminder, inject_host_reminder, remove_host_reminder


@pytest.fixture()
def reminder_calls(monkeypatch):
    """记录对 prompt_api 的调用。"""

    calls: dict[str, list] = {"add": [], "delete": []}

    def fake_add(stream_id, bucket, name, content, *args, **kwargs):
        calls["add"].append((stream_id, bucket, name, content))

    def fake_delete(stream_id, bucket, name):
        calls["delete"].append((stream_id, bucket, name))
        return True

    monkeypatch.setattr(reminder_module.prompt_api, "add_stream_reminder", fake_add)
    monkeypatch.setattr(reminder_module.prompt_api, "delete_stream_reminder", fake_delete)
    return calls


class TestInjectHostReminder:
    def test_injects_to_actor_bucket(self, reminder_calls) -> None:
        inject_host_reminder("s1", "题名", "汤面", "汤底")

        assert len(reminder_calls["add"]) == 1
        stream_id, bucket, name, content = reminder_calls["add"][0]
        assert stream_id == "s1"
        assert bucket == "actor"
        assert name == "turtle_soup_host"
        assert "汤面：汤面" in content
        assert "汤底：汤底" in content
        assert "ask_turtle_soup_question" in content

    def test_empty_stream_id_noop(self, reminder_calls) -> None:
        inject_host_reminder("", "题名", "汤面", "汤底")
        assert reminder_calls["add"] == []

    def test_prompt_api_failure_does_not_raise(self, monkeypatch) -> None:
        def boom(*args, **kwargs):
            raise RuntimeError("store 不可用")

        monkeypatch.setattr(reminder_module.prompt_api, "add_stream_reminder", boom)
        inject_host_reminder("s1", "题名", "汤面", "汤底")  # 不应抛出


class TestRemoveHostReminder:
    def test_removes_from_actor_bucket(self, reminder_calls) -> None:
        remove_host_reminder("s1")
        assert reminder_calls["delete"] == [("s1", "actor", "turtle_soup_host")]

    def test_missing_reminder_is_silent(self, reminder_calls, monkeypatch) -> None:
        monkeypatch.setattr(
            reminder_module.prompt_api, "delete_stream_reminder", lambda *a: False
        )
        remove_host_reminder("s1")  # 不应抛出


class TestBuildHostReminder:
    def test_content_covers_rules_and_secret(self) -> None:
        content = build_host_reminder("题名", "汤面内容", "汤底内容")
        assert "汤面：汤面内容" in content
        assert "汤底：汤底内容" in content
        assert "禁止以任何形式向玩家透露" in content
        assert "判定从严" in content
        assert "answers 一一对应" in content
