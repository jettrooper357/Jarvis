# Jarvis Watchtower Proactive Assistant Plan

Status: planning artifact created before implementation, 2026-06-03.

This phase extends the existing additive Watchtower subsystem into a more
visible proactive assistant. It does not authorize breaking changes. If a step
requires changing an existing API shape, persistence meaning, scheduler
behavior, approval behavior, Telegram behavior, speech behavior, agent
workflow, or protected UI surface, create a Change Impact Notice and stop.

## Existing Surfaces Reused

- `src/openjarvis/watchtower/*`: existing findings, DND, local-only guard,
  notifications, routes, settings, and scan loop.
- `app.state.tts_backend`: existing text-to-speech backend for optional spoken
  alerts.
- `src/openjarvis/channels/telegram.py`: existing Telegram adapter.
- `src/openjarvis/agents/manager.py`: Chief Orchestrator routing and message
  ledger.
- `frontend/src/components/Watchtower/*`: existing Command Center panel,
  settings section, and login/focus notifier.
- `frontend/src/components/ui/sonner`: existing in-app toast surface.

## Additive Changes

1. Add `src/openjarvis/watchtower/speech.py`.
2. Add `watchtower_speech_events` table owned by Watchtower.
3. Add settings:
   - `speech_enabled`
   - `speech_min_priority`
   - `speak_normal_priority`
   - `speak_high_priority`
4. Extend `WatchtowerNotifier` to trigger speech after DND and priority checks.
5. Add API endpoints:
   - `POST /v1/watchtower/test-telegram`
   - `POST /v1/watchtower/test-speech`
   - `POST /v1/watchtower/speak-again`
6. Extend `/v1/watchtower/brief` and UI panel to include speech events.
7. Add Watchtower panel tabs:
   - Spoken Alerts
   - Telegram Alerts
8. Add quick actions:
   - Ask Chief
   - Speak Again
   - Telegram Test
9. Extend System > Watchtower settings with speech controls and priority
   thresholds.

## Rules

- Monitoring and classification remain local-AI-only with deterministic fallback.
- Speech never includes secrets and uses the same sanitizer as notifications.
- Speech is not used for info/low routine updates.
- DND can defer speech except urgent/emergency bypass behavior.
- Internal Chief routing continues during DND.
- Existing speech, Telegram, approvals, scheduler, project, task, and agent APIs
  are reused, not replaced.

## Tests

- Backend tests for speech threshold, speech audit logging, test-speech,
  speak-again, test-telegram, and brief speech payload.
- Frontend tests for Spoken Alerts tab, Telegram Alerts tab, Speak Again, Ask
  Chief, Telegram Test, and settings save behavior.
- Existing Watchtower, project, approval, and Telegram regression tests remain
  in place.
