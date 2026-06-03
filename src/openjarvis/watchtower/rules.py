"""Deterministic Watchtower finding rules."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List

from openjarvis.watchtower.priority import PriorityEngine
from openjarvis.watchtower.types import WatchtowerSettings

_DONE_TASK_STATUSES = {"done", "completed", "cancelled", "canceled"}
_BLOCKED_TASK_STATUSES = {"blocked", "stalled", "waiting", "waiting_on_user"}


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def _task_open(task: Dict[str, Any]) -> bool:
    return str(task.get("status") or "").strip().casefold() not in _DONE_TASK_STATUSES


class WatchtowerRules:
    def __init__(
        self,
        settings: WatchtowerSettings | None = None,
        priority_engine: PriorityEngine | None = None,
    ) -> None:
        self.settings = settings or WatchtowerSettings()
        self.priority_engine = priority_engine or PriorityEngine()

    def scan_project_bundle(
        self, bundle: Dict[str, Any], *, now: datetime | None = None
    ) -> List[Dict[str, Any]]:
        current = now or datetime.now(timezone.utc)
        today = current.date()
        due_soon_days = max(1, round(self.settings.due_soon_hours / 24))
        findings: list[dict[str, Any]] = []
        projects = bundle.get("projects") or []
        tasks_by_project = bundle.get("tasks_by_project") or {}
        by_project = {str(project.get("id")): project for project in projects}
        for project_id, tasks in tasks_by_project.items():
            project = by_project.get(str(project_id), {})
            for task in tasks or []:
                if not _task_open(task):
                    continue
                status = str(task.get("status") or "").strip().casefold()
                due_date = _parse_date(task.get("due_date"))
                if status in _BLOCKED_TASK_STATUSES:
                    findings.append(
                        self._project_task_finding(
                            "blocked_task",
                            project,
                            task,
                            "Project task is blocked.",
                            "Ask the Chief to check the blocker and route the work.",
                        )
                    )
                if due_date and due_date < today:
                    findings.append(
                        self._project_task_finding(
                            "overdue_task",
                            project,
                            task,
                            f"Project task was due on {due_date.isoformat()}.",
                            "Route to Chief for status check and recovery plan.",
                        )
                    )
                elif due_date and (due_date - today).days <= due_soon_days:
                    findings.append(
                        self._project_task_finding(
                            "due_soon_task",
                            project,
                            task,
                            f"Project task is due on {due_date.isoformat()}.",
                            "Route to Chief to confirm owner and next action.",
                        )
                    )
        for project in projects:
            if str(project.get("status") or "").strip().casefold() in {
                "at risk",
                "blocked",
            }:
                project_name = project.get("name") or project.get("id")
                status = project.get("status")
                findings.append(
                    {
                        "finding_type": "project_at_risk",
                        "entity_type": "project",
                        "entity_id": str(project.get("id")),
                        "project_id": str(project.get("id")),
                        "reason": f"Project {project_name} is marked {status}.",
                        "recommended_action": "Route to Chief for project risk review.",
                        "metadata": {
                            "project_name": project.get("name"),
                            "status": project.get("status"),
                        },
                    }
                )
        return [self._with_priority(f) for f in findings]

    def scan_agents(
        self, agents: Iterable[Dict[str, Any]], *, now_ts: float
    ) -> List[Dict[str, Any]]:
        stale_after = self.settings.stale_agent_minutes * 60
        findings: list[dict[str, Any]] = []
        for agent in agents:
            status = str(agent.get("status") or "").strip().casefold()
            agent_id = str(agent.get("id") or "")
            if not agent_id or status == "archived":
                continue
            if status in {"stalled", "error", "needs_attention", "input_required"}:
                agent_name = agent.get("name") or agent_id
                findings.append(
                    self._with_priority(
                        {
                            "finding_type": "blocked_agent",
                            "entity_type": "agent",
                            "entity_id": agent_id,
                            "agent_id": agent_id,
                            "reason": f"Agent {agent_name} is {status}.",
                            "recommended_action": (
                                "Route to Chief to request status and "
                                "unblock the chain."
                            ),
                            "metadata": {
                                "agent_name": agent.get("name"),
                                "status": status,
                            },
                        }
                    )
                )
            last_activity = float(agent.get("last_activity_at") or 0)
            if status == "running" and (
                not last_activity or now_ts - last_activity > stale_after
            ):
                agent_name = agent.get("name") or agent_id
                findings.append(
                    self._with_priority(
                        {
                            "finding_type": "blocked_agent",
                            "entity_type": "agent",
                            "entity_id": agent_id,
                            "agent_id": agent_id,
                            "reason": (
                                f"Agent {agent_name} appears stale while running."
                            ),
                            "recommended_action": (
                                "Route to Chief to verify whether the agent "
                                "is still working."
                            ),
                            "metadata": {
                                "agent_name": agent.get("name"),
                                "status": status,
                                "last_activity_at": last_activity,
                            },
                        }
                    )
                )
        return findings

    def scan_approvals(
        self, approvals: Iterable[Any], *, now_ts: float
    ) -> List[Dict[str, Any]]:
        stale_after = self.settings.approval_stale_minutes * 60
        findings: list[dict[str, Any]] = []
        for approval in approvals:
            data = (
                approval.to_dict() if hasattr(approval, "to_dict") else dict(approval)
            )
            if data.get("state") != "pending":
                continue
            requested_at = float(data.get("requested_at") or 0)
            if requested_at and now_ts - requested_at < stale_after:
                continue
            approval_id = str(data.get("id") or "")
            capability = data.get("capability") or "a gated action"
            findings.append(
                self._with_priority(
                    {
                        "finding_type": "stale_approval",
                        "entity_type": "approval",
                        "entity_id": approval_id,
                        "agent_id": data.get("agent_id"),
                        "task_id": data.get("task_id"),
                        "reason": f"Approval for {capability} is waiting.",
                        "recommended_action": (
                            "Notify user if this approval blocks active work; "
                            "route context to Chief."
                        ),
                        "metadata": {"approval": data},
                    }
                )
            )
        return findings

    def scan_job_runs(
        self, jobs: Iterable[Dict[str, Any]], manager: Any
    ) -> List[Dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        for job in jobs:
            for run in manager.list_job_runs(job["id"], limit=5):
                if str(run.get("status") or "").casefold() != "failed":
                    continue
                job_name = job.get("name") or job.get("id")
                findings.append(
                    self._with_priority(
                        {
                            "finding_type": "job_failed",
                            "entity_type": "agent_job_run",
                            "entity_id": str(run.get("id")),
                            "agent_id": str(
                                run.get("agent_id") or job.get("agent_id") or ""
                            ),
                            "reason": f"Agent job {job_name} failed.",
                            "recommended_action": (
                                "Route to Chief for recovery or reassignment."
                            ),
                            "metadata": {"job": job, "run": run},
                        }
                    )
                )
        return findings

    def _project_task_finding(
        self,
        finding_type: str,
        project: Dict[str, Any],
        task: Dict[str, Any],
        reason: str,
        recommended_action: str,
    ) -> Dict[str, Any]:
        return {
            "finding_type": finding_type,
            "entity_type": "project_task",
            "entity_id": str(task.get("id")),
            "project_id": str(task.get("project_id") or project.get("id") or ""),
            "task_id": str(task.get("id")),
            "agent_id": str(task.get("assigned_to") or "") or None,
            "reason": reason,
            "recommended_action": recommended_action,
            "metadata": {
                "project_name": project.get("name"),
                "task_title": task.get("title"),
                "status": task.get("status"),
                "priority": task.get("priority"),
                "due_date": task.get("due_date"),
            },
        }

    def _with_priority(self, finding: Dict[str, Any]) -> Dict[str, Any]:
        finding = dict(finding)
        finding["priority"] = self.priority_engine.classify(
            str(finding.get("finding_type") or ""),
            finding.get("metadata") or {},
        )
        return finding
