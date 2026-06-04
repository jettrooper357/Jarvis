from __future__ import annotations

from datetime import datetime

from openjarvis.watchtower.dnd import DoNotDisturbPolicy
from openjarvis.watchtower.local_reasoner import is_local_provider
from openjarvis.watchtower.notifier import WatchtowerNotifier
from openjarvis.watchtower.rules import WatchtowerRules
from openjarvis.watchtower.speech import WatchtowerSpeech
from openjarvis.watchtower.store import WatchtowerStore
from openjarvis.watchtower.types import DndDecision, Priority, WatchtowerSettings


def test_local_provider_guard_rejects_cloud_providers() -> None:
    assert not is_local_provider({"engine": "openai", "api_key": "x"})
    assert not is_local_provider({"provider": "anthropic"})
    assert not is_local_provider({"base_url": "https://api.openai.com/v1"})
    assert is_local_provider({"engine": "ollama"})
    assert is_local_provider({"engine": "vllm", "base_url": "http://127.0.0.1:8000"})


def test_rules_detect_overdue_project_task() -> None:
    rules = WatchtowerRules()
    findings = rules.scan_project_bundle(
        {
            "projects": [{"id": "p1", "name": "AutoFax", "status": "Active"}],
            "tasks_by_project": {
                "p1": [
                    {
                        "id": "t1",
                        "project_id": "p1",
                        "title": "Schema change",
                        "status": "In Progress",
                        "due_date": "2026-01-01",
                    }
                ]
            },
        },
        now=datetime.fromisoformat("2026-01-02T12:00:00+00:00"),
    )

    assert findings[0]["finding_type"] == "overdue_task"
    assert findings[0]["priority"] == Priority.HIGH
    assert findings[0]["task_id"] == "t1"


def test_rules_detect_blocked_agent() -> None:
    findings = WatchtowerRules().scan_agents(
        [{"id": "a1", "name": "SQL Engineer", "status": "stalled"}],
        now_ts=1_000,
    )

    assert findings[0]["finding_type"] == "blocked_agent"
    assert findings[0]["priority"] == Priority.HIGH


def test_dnd_defers_normal_but_allows_internal_work_policy_separately() -> None:
    settings = WatchtowerSettings(
        dnd_enabled=True,
        quiet_hours_start="22:00",
        quiet_hours_end="07:00",
        defer_normal_priority=True,
    )
    policy = DoNotDisturbPolicy(settings)

    decision = policy.decide(
        Priority.NORMAL,
        now=datetime.fromisoformat("2026-06-03T23:30:00"),
    )

    assert decision == DndDecision.DEFER


def test_emergency_bypasses_dnd_when_enabled() -> None:
    policy = DoNotDisturbPolicy(WatchtowerSettings(allow_emergency_bypass=True))

    assert (
        policy.decide(
            Priority.EMERGENCY,
            now=datetime.fromisoformat("2026-06-03T23:30:00"),
        )
        == DndDecision.BYPASS
    )


def test_store_dedupes_same_active_finding(tmp_path) -> None:
    store = WatchtowerStore(tmp_path / "watchtower.db")
    first = store.upsert_finding(
        finding_type="overdue_task",
        entity_type="project_task",
        entity_id="t1",
        priority=Priority.HIGH,
        reason="late",
    )
    second = store.upsert_finding(
        finding_type="overdue_task",
        entity_type="project_task",
        entity_id="t1",
        priority=Priority.HIGH,
        reason="still late",
    )

    assert first.finding_id == second.finding_id
    assert len(store.list_findings()) == 1
    assert store.list_findings()[0].reason == "still late"
    store.close()


def test_telegram_route_respects_min_priority(tmp_path) -> None:
    store = WatchtowerStore(tmp_path / "watchtower.db")
    settings = WatchtowerSettings(
        telegram_enabled=True,
        telegram_min_priority=Priority.HIGH,
        in_app_enabled=False,
    )
    notifier = WatchtowerNotifier(store, settings)
    normal = store.upsert_finding(
        finding_type="due_soon_task",
        entity_type="project_task",
        entity_id="t1",
        priority=Priority.NORMAL,
        reason="soon",
    )
    high = store.upsert_finding(
        finding_type="overdue_task",
        entity_type="project_task",
        entity_id="t2",
        priority=Priority.HIGH,
        reason="late",
    )

    assert notifier.decide_route(normal).value == "none"
    assert notifier.decide_route(high).value == "telegram_user"
    store.close()


class _FakeTts:
    backend_id = "fake"

    def synthesize(self, text: str, **kwargs):
        self.last_text = text
        return object()


def test_speech_only_triggers_at_configured_priority(tmp_path) -> None:
    store = WatchtowerStore(tmp_path / "watchtower.db")
    speech = WatchtowerSpeech(
        store,
        WatchtowerSettings(
            speech_enabled=True,
            speech_min_priority=Priority.URGENT,
            # Isolate the priority threshold from DND quiet hours so this
            # test is deterministic regardless of wall-clock time of day.
            dnd_enabled=False,
        ),
        tts_backend=_FakeTts(),
    )
    normal = store.upsert_finding(
        finding_type="due_soon_task",
        entity_type="project_task",
        entity_id="t1",
        priority=Priority.NORMAL,
        reason="soon",
    )
    urgent = store.upsert_finding(
        finding_type="blocked_agent",
        entity_type="agent",
        entity_id="a1",
        priority=Priority.URGENT,
        reason="blocked",
    )

    assert speech.speak(normal)["success"] is False
    assert speech.speak(urgent)["success"] is True
    assert len(store.list_speech_events()) == 2
    store.close()
