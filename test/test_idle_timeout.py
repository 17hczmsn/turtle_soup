"""闲置超时机制测试：状态时间戳、惰性过期与事件处理器。"""

from __future__ import annotations

from time import monotonic
from types import SimpleNamespace

import pytest

from .. import events as events_module
from .. import service as service_module
from ..config import TurtleSoupConfig
from ..events import TurtleSoupIdleTimeoutHandler
from ..models import TurtleSoupState
from ..service import TurtleSoupService
from ..state import state_store
from src.kernel.event import EventDecision


_SERVICE_SIGNATURE = "turtle_soup:service:turtle_soup"

_STREAM_KEY = "test"


def _make_service(config: TurtleSoupConfig | None = None) -> TurtleSoupService:
    service = TurtleSoupService(SimpleNamespace(config=config or TurtleSoupConfig()))
    return service


def _seed_state(last_activity_offset_seconds: float | None = None) -> TurtleSoupState:
    state = TurtleSoupState(
        stream_key=_STREAM_KEY,
        current_question="汤面",
        current_answer="汤底",
        game_active=True,
    )
    if last_activity_offset_seconds is not None:
        state.last_activity = monotonic() - last_activity_offset_seconds
    state_store.set(state)
    return state


@pytest.fixture(autouse=True)
def _clean():
    yield
    state_store.clear(_STREAM_KEY)
    try:
        from src.app.plugin_system.api import prompt_api

        prompt_api.clear_stream_reminders(_STREAM_KEY)
    except Exception:
        pass


class TestIdleExpiry:
    def test_is_idle_expired(self) -> None:
        state = TurtleSoupState(stream_key="s", game_active=True)
        assert state.is_idle_expired(30) is False  # 刚创建
        state.last_activity = monotonic() - 31 * 60
        assert state.is_idle_expired(30) is True

    def test_zero_disables_timeout(self) -> None:
        state = TurtleSoupState(stream_key="s", game_active=True)
        state.last_activity = monotonic() - 1000 * 60
        assert state.is_idle_expired(0) is False
        assert state.is_idle_expired(-1) is False

    def test_touch_refreshes(self) -> None:
        state = TurtleSoupState(stream_key="s", game_active=True)
        state.last_activity = monotonic() - 100 * 60
        state.touch()
        assert state.is_idle_expired(30) is False

    async def test_expire_if_idle_ends_game_and_removes_reminder(self, monkeypatch) -> None:
        removed: list[str] = []
        monkeypatch.setattr(service_module, "remove_host_reminder", lambda k: removed.append(k))
        service = _make_service()
        _seed_state(last_activity_offset_seconds=31 * 60)

        assert service.expire_if_idle(_STREAM_KEY) is True
        assert state_store.get(_STREAM_KEY).game_active is False
        assert removed == [_STREAM_KEY]
        # 已过期后再查不会再触发
        assert service.expire_if_idle(_STREAM_KEY) is False

    async def test_not_idle_keeps_game(self, monkeypatch) -> None:
        removed: list[str] = []
        monkeypatch.setattr(service_module, "remove_host_reminder", lambda k: removed.append(k))
        service = _make_service()
        _seed_state(last_activity_offset_seconds=60)

        assert service.expire_if_idle(_STREAM_KEY) is False
        assert state_store.get(_STREAM_KEY).game_active is True
        assert removed == []

    async def test_disabled_timeout_never_expires(self, monkeypatch) -> None:
        config = TurtleSoupConfig()
        config.game.idle_timeout_minutes = 0
        service = _make_service(config)
        _seed_state(last_activity_offset_seconds=1000 * 60)

        assert service.expire_if_idle(_STREAM_KEY) is False

    async def test_stale_reminder_self_heals_when_no_state(self, monkeypatch) -> None:
        """无游戏状态却残留 reminder（如插件热重载）时自动清理。"""

        removed: list[str] = []
        monkeypatch.setattr(service_module, "remove_host_reminder", lambda k: removed.append(k))
        service = _make_service()
        # 不 seed 任何状态

        assert service.expire_if_idle(_STREAM_KEY) is False
        assert removed == [_STREAM_KEY]

    async def test_require_active_state_expires_and_raises(self, monkeypatch) -> None:
        monkeypatch.setattr(service_module, "remove_host_reminder", lambda k: None)
        service = _make_service()
        _seed_state(last_activity_offset_seconds=31 * 60)

        with pytest.raises(RuntimeError, match="没有正在进行的海龟汤"):
            service._require_active_state(_STREAM_KEY)
        assert state_store.get(_STREAM_KEY).game_active is False

    async def test_require_active_state_touches(self, monkeypatch) -> None:
        monkeypatch.setattr(service_module, "remove_host_reminder", lambda k: None)
        service = _make_service()
        state = _seed_state(last_activity_offset_seconds=20 * 60)

        service._require_active_state(_STREAM_KEY)

        assert state.is_idle_expired(30) is False  # 交互后重新计时


class TestIdleTimeoutHandler:
    def _handler_with_service(self, monkeypatch, service: TurtleSoupService) -> TurtleSoupIdleTimeoutHandler:
        monkeypatch.setattr(events_module, "get_service", lambda signature: service if signature == _SERVICE_SIGNATURE else None)
        return TurtleSoupIdleTimeoutHandler(plugin=service.plugin)

    async def test_expires_idle_game_via_event(self, monkeypatch) -> None:
        removed: list[str] = []
        monkeypatch.setattr(service_module, "remove_host_reminder", lambda k: removed.append(k))
        service = _make_service()
        _seed_state(last_activity_offset_seconds=31 * 60)
        handler = self._handler_with_service(monkeypatch, service)

        decision, params = await handler.execute(
            "before_llm_request",
            {"meta_data": {"stream_id": _STREAM_KEY}},
        )

        assert decision == EventDecision.SUCCESS
        assert state_store.get(_STREAM_KEY).game_active is False
        assert removed == [_STREAM_KEY]

    async def test_active_game_untouched(self, monkeypatch) -> None:
        removed: list[str] = []
        monkeypatch.setattr(service_module, "remove_host_reminder", lambda k: removed.append(k))
        service = _make_service()
        _seed_state(last_activity_offset_seconds=60)
        handler = self._handler_with_service(monkeypatch, service)

        await handler.execute("before_llm_request", {"meta_data": {"stream_id": _STREAM_KEY}})

        assert state_store.get(_STREAM_KEY).game_active is True
        assert removed == []

    async def test_no_state_is_noop(self, monkeypatch) -> None:
        service = _make_service()
        handler = self._handler_with_service(monkeypatch, service)
        decision, params = await handler.execute(
            "before_llm_request", {"meta_data": {"stream_id": "no-such-stream"}}
        )
        assert decision == EventDecision.SUCCESS

    async def test_missing_meta_data_is_noop(self, monkeypatch) -> None:
        service = _make_service()
        handler = self._handler_with_service(monkeypatch, service)
        decision, params = await handler.execute("before_llm_request", {})
        assert decision == EventDecision.SUCCESS

    async def test_never_raises_on_internal_error(self, monkeypatch) -> None:
        service = _make_service()

        def boom(key):
            raise RuntimeError("store 坏了")

        monkeypatch.setattr(service_module.state_store, "get", boom)
        handler = self._handler_with_service(monkeypatch, service)
        decision, _ = await handler.execute(
            "before_llm_request", {"meta_data": {"stream_id": _STREAM_KEY}}
        )
        assert decision == EventDecision.SUCCESS
