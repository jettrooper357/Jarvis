"""AgentExecutor — runs a single agent tick."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from openjarvis.agents._stubs import AgentResult
from openjarvis.agents.capabilities import build_agent_tool_instances
from openjarvis.agents.errors import (
    AgentTickError,
    EscalateError,
    FatalError,
    classify_error,
    retry_delay,
)
from openjarvis.core.events import EventBus, EventType

if TYPE_CHECKING:
    from openjarvis.agents.manager import AgentManager

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3

def _format_open_task(task: dict[str, Any]) -> str:
    parts = [
        f"id={task.get('id', '')}",
        f"status={task.get('status', 'unknown')}",
        f"description={str(task.get('description', '') or '').strip()}",
    ]
    progress = task.get("progress") or {}
    if progress:
        parts.append(f"progress={progress}")
    findings = task.get("findings") or []
    if findings:
        parts.append(f"findings={len(findings)}")
    return " | ".join(parts)


def _truncate_task_feedback(value: str, limit: int = 400) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


class AgentExecutor:
    """Executes a single tick for a managed agent.

    Constructor receives a JarvisSystem reference for access to engine,
    tools, config, memory backends, and all other primitives.
    """

    def __init__(
        self,
        manager: AgentManager,
        event_bus: EventBus,
        system: Any = None,
        trace_store: Any = None,
    ) -> None:
        self._system = system
        self._manager = manager
        self._bus = event_bus
        self._trace_store = trace_store

    def set_system(self, system: Any) -> None:
        """Deferred system injection — called after JarvisSystem is constructed."""
        self._system = system

    def _set_activity(self, agent_id: str, activity: str) -> None:
        """Update the agent's current_activity for progress visibility."""
        try:
            self._manager.update_agent(agent_id, current_activity=activity)
        except Exception:
            pass  # Non-critical

    def _inject_tool_deps(self, tool: Any) -> None:
        """Inject runtime dependencies into a tool instance.

        Mirrors SystemBuilder._inject_tool_deps (system.py:920-945)
        but uses the lightweight system's references.
        """
        if self._system is None:
            return
        name = getattr(getattr(tool, "spec", None), "name", "")
        if name == "llm":
            if hasattr(tool, "_engine"):
                tool._engine = self._system.engine
            if hasattr(tool, "_model"):
                tool._model = self._system.model
        elif name == "retrieval" or name.startswith("memory_"):
            if hasattr(tool, "_backend"):
                tool._backend = getattr(self._system, "memory_backend", None)
        elif name.startswith("channel_"):
            if hasattr(tool, "_channel"):
                tool._channel = getattr(self._system, "channel_backend", None)

    @staticmethod
    def _fallback_response_from_tool_results(tool_results: list[Any]) -> str:
        if not tool_results:
            return ""
        last = tool_results[-1]
        content = str(getattr(last, "content", "") or "").strip()
        if content:
            return content
        tool_name = str(getattr(last, "tool_name", "") or "tool")
        success = bool(getattr(last, "success", False))
        if success:
            return (
                f"{tool_name} completed successfully, but no final response "
                "was produced."
            )
        return f"{tool_name} failed, and no final response was produced."

    def _sync_response_to_single_open_task(
        self, agent_id: str, response_text: str
    ) -> None:
        text = str(response_text or "").strip()
        if not text:
            return
        open_tasks = [
            task
            for task in self._manager.list_tasks(agent_id)
            if str(task.get("status", "")).strip() != "completed"
        ]
        if len(open_tasks) != 1:
            return
        task = open_tasks[0]
        progress = dict(task.get("progress") or {})
        progress["note"] = _truncate_task_feedback(text, 400)
        findings = list(task.get("findings") or [])
        summary = _truncate_task_feedback(text, 240)
        if not any(
            isinstance(entry, dict)
            and str(entry.get("summary", "")).strip() == summary
            for entry in findings
        ):
            findings.append(
                {
                    "source": "agent_response",
                    "summary": summary,
                }
            )
        self._manager.update_task(task["id"], progress=progress, findings=findings)

    def run_ephemeral(
        self,
        agent_type: str,
        system_prompt: str,
        input_text: str,
        tools: list[str] | None = None,
    ) -> Any:
        """Run a one-shot agent turn with no lifecycle tracking."""
        from openjarvis.core.registry import AgentRegistry

        agent_cls = AgentRegistry.get(agent_type)
        agent = agent_cls(
            engine=getattr(self._manager, "_engine", None),
            system_prompt=system_prompt,
            bus=self._bus,
        )
        return agent.run(input_text)

    def execute_tick(self, agent_id: str) -> None:
        """Run one tick for the given agent.

        1. Acquire concurrency guard (start_tick)
        2. Invoke agent with retry logic
        3. Update stats
        4. Release guard (end_tick)
        """
        has_linked_open_task = (
            self._manager.has_open_linked_task(agent_id)
            if hasattr(self._manager, "has_open_linked_task")
            else False
        )
        has_runnable_task = (
            self._manager.has_runnable_task(agent_id)
            if hasattr(self._manager, "has_runnable_task")
            else True
        )
        if has_linked_open_task and not has_runnable_task:
            logger.info(
                "Agent %s only has future-scheduled tasks; skipping tick",
                agent_id,
            )
            return
        if not has_runnable_task and not self._manager.get_pending_messages(agent_id):
            logger.info(
                "Agent %s has no due linked task or pending message; skipping tick",
                agent_id,
            )
            return
        try:
            self._manager.start_tick(agent_id)
            self._set_activity(agent_id, "Preparing tick...")
        except ValueError:
            logger.warning("Agent %s already running, skipping tick", agent_id)
            return

        agent = self._manager.get_agent(agent_id)
        if agent is None:
            logger.error("Agent %s not found", agent_id)
            return

        self._bus.publish(
            EventType.AGENT_TICK_START,
            {
                "agent_id": agent_id,
                "agent_name": agent["name"],
            },
        )

        # Activity tracking: subscribe to tool/inference events
        def _on_activity(event: Any) -> None:
            if event.data.get("agent") == agent_id:
                self._manager.update_agent(agent_id, last_activity_at=time.time())

        self._bus.subscribe(EventType.TOOL_CALL_START, _on_activity)
        self._bus.subscribe(EventType.INFERENCE_START, _on_activity)

        # Trace recording: collect tool call steps
        trace_steps: list[dict[str, Any]] = []

        def _on_tool_start(event: Any) -> None:
            if event.data.get("agent") == agent_id:
                trace_steps.append(
                    {
                        "type": "tool_call",
                        "input": {
                            "tool": event.data.get("tool"),
                            "args": event.data.get("args"),
                        },
                        "start_time": event.timestamp,
                    }
                )

        def _on_tool_end(event: Any) -> None:
            if event.data.get("agent") == agent_id and trace_steps:
                for step in reversed(trace_steps):
                    if step["type"] == "tool_call" and "output" not in step:
                        step["output"] = {
                            "result": str(event.data.get("result", ""))[:4096],
                        }
                        step["duration"] = event.data.get("duration", 0)
                        break

        if self._trace_store:
            self._bus.subscribe(EventType.TOOL_CALL_START, _on_tool_start)
            self._bus.subscribe(EventType.TOOL_CALL_END, _on_tool_end)

        tick_start = time.time()
        result = None
        error_info = None

        try:
            result = self._run_with_retries(agent)
        except AgentTickError as e:
            error_info = e
        finally:
            self._bus.unsubscribe(EventType.TOOL_CALL_START, _on_activity)
            self._bus.unsubscribe(EventType.INFERENCE_START, _on_activity)

            if self._trace_store:
                self._bus.unsubscribe(EventType.TOOL_CALL_START, _on_tool_start)
                self._bus.unsubscribe(EventType.TOOL_CALL_END, _on_tool_end)

            tick_duration = time.time() - tick_start
            self._finalize_tick(agent_id, result, error_info, tick_duration)

            if self._trace_store:
                self._save_trace(
                    agent_id,
                    agent,
                    result,
                    error_info,
                    tick_start,
                    tick_duration,
                    trace_steps,
                )

    def _run_with_retries(self, agent: dict) -> AgentResult:
        """Invoke the agent, retrying on RetryableError up to _MAX_RETRIES."""
        last_error: AgentTickError | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                return self._invoke_agent(agent)
            except AgentTickError as e:
                if not e.retryable or attempt == _MAX_RETRIES - 1:
                    raise
                last_error = e
                delay = retry_delay(attempt)
                logger.info(
                    "Agent %s tick retry %d/%d in %ds: %s",
                    agent["id"],
                    attempt + 1,
                    _MAX_RETRIES,
                    delay,
                    e,
                )
                time.sleep(delay)
            except Exception as e:
                classified = classify_error(e)
                if not classified.retryable or attempt == _MAX_RETRIES - 1:
                    raise classified from e
                delay = retry_delay(attempt)
                logger.info(
                    "Agent %s tick retry %d/%d in %ds: %s",
                    agent["id"],
                    attempt + 1,
                    _MAX_RETRIES,
                    delay,
                    e,
                )
                time.sleep(delay)

        # Should not reach here, but just in case
        raise last_error or FatalError("max retries exhausted")

    def _invoke_agent(self, agent: dict) -> AgentResult:
        """Invoke the actual agent run. Tests mock this method."""
        from openjarvis.agents import AgentRegistry

        agent_type = agent.get("agent_type", "monitor_operative")
        agent_cls = AgentRegistry.get(agent_type)
        if agent_cls is None:
            raise FatalError(f"Unknown agent type: {agent_type}")

        config = agent.get("config", {})

        # Resolve engine + model from JarvisSystem
        engine = self._system.engine if self._system else None
        if engine is None:
            raise FatalError("No engine available in JarvisSystem")
        model = config.get("model") or (self._system.model if self._system else "")
        if not model:
            raise FatalError("No model configured for agent")

        logger.info(
            "Agent %s [%s]: using model=%s, engine=%s",
            agent["name"],
            agent["id"],
            model,
            type(engine).__name__,
        )
        self._set_activity(agent["id"], f"Loading model {model}...")

        # Optionally override model via router policy
        router_policy_key = config.get("router_policy")
        if router_policy_key and self._system:
            try:
                from openjarvis.core.registry import RouterPolicyRegistry
                from openjarvis.learning.routing.router import (
                    build_routing_context,
                )

                policy = RouterPolicyRegistry.create(
                    router_policy_key,
                    available_models=[model],
                )
                instruction = config.get("instruction", "")
                ctx = build_routing_context(instruction)
                selected = policy.select_model(ctx)
                if selected:
                    model = selected
            except Exception:
                pass  # Fall back to configured model

        tool_instances: list[Any] = []
        try:
            tool_instances = build_agent_tool_instances(
                agent,
                engine=engine,
                model=model,
                bus=self._bus,
                capability_policy=(
                    getattr(self._system, "capability_policy", None)
                    if self._system
                    else None
                ),
                interactive=True,
                confirm_callback=lambda _prompt: True,
                inject_tool=self._inject_tool_deps,
            )
        except Exception:
            logger.exception("Failed to resolve tools for agent %s", agent["name"])
            tool_instances = []
        if tool_instances:
            logger.info(
                "Agent %s: resolved %d tools",
                agent["name"],
                len(tool_instances),
            )

        # Construct agent instance
        agent_kwargs: dict[str, Any] = {}
        sys_prompt = config.get("system_prompt")
        if sys_prompt is not None:
            agent_kwargs["system_prompt"] = sys_prompt
        if getattr(agent_cls, "accepts_tools", False) and tool_instances:
            agent_kwargs["tools"] = tool_instances
        try:
            agent_instance = agent_cls(engine, model, **agent_kwargs)
        except TypeError:
            agent_instance = agent_cls(engine, model)

        # Build input from instruction + summary_memory + pending messages
        import datetime

        today = datetime.date.today().strftime("%A, %B %d, %Y")
        instruction = config.get("instruction", "")
        memory = agent.get("summary_memory", "")
        if instruction:
            input_text = f"Current date: {today}\n\nStanding instruction: {instruction}"
            if memory:
                input_text += f"\n\nPrevious context: {memory}"
        else:
            base = memory or "Continue your assigned task."
            input_text = f"Current date: {today}\n\n{base}"
        pending = self._manager.get_pending_messages(agent["id"])
        if hasattr(self._manager, "list_runnable_tasks"):
            open_tasks = self._manager.list_runnable_tasks(agent["id"])
        else:
            open_tasks = self._manager.list_tasks(agent["id"])
        actionable_tasks = [
            task
            for task in open_tasks
            if str(task.get("status", "")).strip() != "completed"
        ]
        if actionable_tasks:
            task_lines = "\n".join(
                _format_open_task(task) for task in actionable_tasks[:10]
            )
            input_text = f"{input_text}\n\nOpen tasks:\n{task_lines}"
        if pending:
            user_msgs = "\n".join(f"User: {m['content']}" for m in pending)
            input_text = f"{input_text}\n\nNew instructions:\n{user_msgs}"
            for m in pending:
                self._manager.mark_message_delivered(m["id"])
            logger.info(
                "Agent %s: delivering %d pending message(s)",
                agent["name"],
                len(pending),
            )
            self._set_activity(
                agent["id"],
                f"Delivering {len(pending)} message(s)...",
            )
        else:
            logger.info(
                "Agent %s: no pending messages, running with instruction%s",
                agent["name"],
                " and open tasks" if actionable_tasks else " only",
            )

        # Build AgentContext with memory results from FTS5 backend
        from openjarvis.agents._stubs import AgentContext

        agent_ctx = AgentContext()
        memory_results = []

        if (
            self._system
            and getattr(self._system, "memory_backend", None)
            and getattr(self._system, "config", None)
            and self._system.config.agent.context_from_memory
        ):
            try:
                from openjarvis.tools.storage.context import (
                    ContextConfig,
                    format_context,
                )

                sys_cfg = self._system.config
                ctx_cfg = ContextConfig(
                    top_k=sys_cfg.memory.context_top_k,
                    min_score=sys_cfg.memory.context_min_score,
                    max_context_tokens=sys_cfg.memory.context_max_tokens,
                )
                # Use pending user messages as query, fall back to instruction
                query = ""
                if pending:
                    query = " ".join(m["content"] for m in pending)
                elif instruction:
                    query = instruction

                if query:
                    results = self._system.memory_backend.retrieve(
                        query,
                        top_k=ctx_cfg.top_k,
                    )
                    memory_results = [
                        r for r in results if r.score >= ctx_cfg.min_score
                    ]
                    if memory_results:
                        # Prepend retrieved context to input for agents
                        # that don't inspect AgentContext.memory_results
                        retrieved = format_context(memory_results)
                        input_text = (
                            f"Retrieved context from knowledge base:\n"
                            f"{retrieved}\n\n{input_text}"
                        )
            except Exception:
                pass  # Don't break agent tick if memory retrieval fails

        agent_ctx.memory_results = memory_results
        self._set_activity(agent["id"], "Generating response...")
        logger.info(
            "Agent %s: calling agent.run() with %d chars input",
            agent["name"],
            len(input_text),
        )
        _t0 = time.time()
        result = agent_instance.run(input_text, context=agent_ctx)

        # Retry once if the model returned empty content (common with
        # Qwen3.5 thinking mode consuming all tokens).
        if not (result.content or "").strip():
            self._set_activity(
                agent["id"],
                "Retrying (empty response)...",
            )
            logger.warning(
                "Agent %s: empty content, retrying once",
                agent["name"],
            )
            result = agent_instance.run(input_text, context=agent_ctx)
            if not (result.content or "").strip():
                fallback = self._fallback_response_from_tool_results(
                    result.tool_results
                )
                if fallback:
                    result.content = fallback

        _elapsed = time.time() - _t0
        logger.info(
            "Agent %s: agent.run() completed in %.1fs, "
            "content_len=%d, turns=%d, tokens=%s",
            agent["name"],
            _elapsed,
            len(result.content or ""),
            result.turns,
            result.metadata.get("total_tokens", "?"),
        )
        return result

    def _build_error_detail(self, error: AgentTickError) -> dict[str, Any]:
        """Build structured error detail for trace metadata."""
        import traceback

        from openjarvis.agents.errors import (
            EscalateError,
            FatalError,
            suggest_action,
        )

        if isinstance(error, EscalateError):
            error_type = "escalate"
        elif isinstance(error, FatalError):
            error_type = "fatal"
        else:
            error_type = "retryable"

        return {
            "error_type": error_type,
            "error_message": str(error)[:2000],
            "suggested_action": suggest_action(error),
            "stack_trace_summary": "".join(
                traceback.format_exception(type(error), error, error.__traceback__)[-3:]
            )[:1000]
            if error.__traceback__
            else "",
        }

    def _finalize_tick(
        self,
        agent_id: str,
        result: AgentResult | None,
        error: AgentTickError | None,
        duration: float,
    ) -> None:
        """Update agent state after tick completion or failure."""
        self._set_activity(agent_id, "Finalizing...")
        if error is None:
            # Success
            logger.info(
                "Tick succeeded for agent %s in %.1fs, response_len=%d",
                agent_id,
                duration,
                len(result.content or "") if result else 0,
            )
            self._manager.end_tick(agent_id)
            self._manager.update_agent(agent_id, total_runs_increment=1)

            # Accumulate budget metrics from AgentResult metadata
            if result:
                tokens = (
                    result.metadata.get("total_tokens")
                    or result.metadata.get("tokens_used")
                    or 0
                )
                in_tokens = result.metadata.get("prompt_tokens", 0)
                out_tokens = result.metadata.get(
                    "completion_tokens",
                    0,
                )
                cost = result.metadata.get("cost", 0.0)
                budget_kwargs: dict[str, Any] = {"stall_retries": 0}
                if tokens > 0:
                    budget_kwargs["total_tokens_increment"] = tokens
                if in_tokens > 0:
                    budget_kwargs["input_tokens_increment"] = in_tokens
                if out_tokens > 0:
                    budget_kwargs["output_tokens_increment"] = out_tokens
                if cost > 0:
                    budget_kwargs["total_cost_increment"] = cost
                self._manager.update_agent(agent_id, **budget_kwargs)

                self._manager.update_summary_memory(
                    agent_id,
                    result.content[:2000],
                )
                self._manager.store_agent_response(agent_id, result.content[:2000])
                self._sync_response_to_single_open_task(agent_id, result.content)

            # Budget enforcement (post-tick check)
            agent_data = self._manager.get_agent(agent_id)
            if agent_data:
                config = agent_data.get("config", {})
                max_cost = config.get("max_cost", 0)
                max_tokens = config.get("max_tokens", 0)
                exceeded = False
                if max_cost > 0 and agent_data["total_cost"] > max_cost:
                    exceeded = True
                if max_tokens > 0 and agent_data["total_tokens"] > max_tokens:
                    exceeded = True
                if exceeded:
                    self._manager.update_agent(agent_id, status="budget_exceeded")
                    self._bus.publish(
                        EventType.AGENT_BUDGET_EXCEEDED,
                        {
                            "agent_id": agent_id,
                            "total_cost": agent_data["total_cost"],
                            "total_tokens": agent_data["total_tokens"],
                            "max_cost": max_cost,
                            "max_tokens": max_tokens,
                        },
                    )
            self._bus.publish(
                EventType.AGENT_TICK_END,
                {
                    "agent_id": agent_id,
                    "duration": duration,
                    "status": "ok",
                },
            )
        elif isinstance(error, EscalateError):
            logger.warning(
                "Tick escalated for agent %s after %.1fs: %s",
                agent_id,
                duration,
                error,
            )
            self._manager.end_tick(agent_id)
            self._manager.update_agent(agent_id, status="needs_attention")
            self._bus.publish(
                EventType.AGENT_TICK_ERROR,
                {
                    "agent_id": agent_id,
                    "error": str(error),
                    "error_type": "escalate",
                    "duration": duration,
                },
            )
        else:
            logger.error(
                "Tick failed for agent %s after %.1fs: %s",
                agent_id,
                duration,
                error,
                exc_info=error,
            )
            self._manager.end_tick(agent_id)
            self._manager.update_agent(agent_id, status="error")
            # Write error detail to summary_memory so frontend can display it
            error_msg = str(error)[:2000]
            self._manager.update_summary_memory(agent_id, f"ERROR: {error_msg}")
            self._bus.publish(
                EventType.AGENT_TICK_ERROR,
                {
                    "agent_id": agent_id,
                    "error": str(error),
                    "error_type": (
                        "fatal"
                        if isinstance(error, FatalError)
                        else "retryable_exhausted"
                    ),
                    "duration": duration,
                },
            )

    def _save_trace(
        self,
        agent_id: str,
        agent: dict,
        result: AgentResult | None,
        error: AgentTickError | None,
        tick_start: float,
        tick_duration: float,
        trace_steps: list[dict[str, Any]],
    ) -> None:
        """Persist an execution trace to the trace store."""
        from openjarvis.core.types import StepType, Trace, TraceStep

        steps = []
        for s in trace_steps:
            steps.append(
                TraceStep(
                    step_type=(
                        StepType.TOOL_CALL
                        if s["type"] == "tool_call"
                        else StepType.GENERATE
                    ),
                    input=s.get("input", {}),
                    output=s.get("output", {}),
                    duration_seconds=s.get("duration", 0),
                    timestamp=s.get("start_time", tick_start),
                )
            )

        metadata: dict[str, Any] = {}
        if error is not None:
            metadata["error_detail"] = self._build_error_detail(error)

        outcome = "success" if error is None else "error"
        trace = Trace(
            agent=agent_id,
            query=agent.get("summary_memory", "")[:200],
            result=result.content[:200] if result else "",
            model=agent.get("config", {}).get("model", ""),
            outcome=outcome,
            steps=steps,
            started_at=tick_start,
            ended_at=tick_start + tick_duration,
            total_latency_seconds=tick_duration,
            metadata=metadata,
        )
        try:
            self._trace_store.save(trace)
        except Exception:
            logger.warning(
                "Failed to save trace for agent %s",
                agent_id,
                exc_info=True,
            )
