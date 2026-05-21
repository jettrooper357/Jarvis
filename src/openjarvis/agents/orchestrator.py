"""OrchestratorAgent — multi-turn agent with tool-calling loop.

Supports two modes:

- **function_calling** (default): Uses OpenAI-format tool definitions and
  parses ``tool_calls`` from the engine response.
- **structured**: Uses a THOUGHT/TOOL/INPUT/FINAL_ANSWER text format
  (like ReAct) with a canonical system prompt from the orchestrator
  prompt registry.  This is the format used by the SFT/GRPO training
  pipelines, making the Orchestrator a distinctive trainable agent type.
"""

from __future__ import annotations

import concurrent.futures
import itertools
import json
import logging
import re
from typing import Any, Callable, List, Mapping, Optional

from openjarvis.agents._stubs import AgentContext, AgentResult, ToolUsingAgent

_chief_logger = logging.getLogger("openjarvis.agents.chief")
from openjarvis.core.events import EventBus
from openjarvis.core.registry import AgentRegistry
from openjarvis.core.types import Message, Role, ToolCall, ToolResult
from openjarvis.engine._stubs import InferenceEngine
from openjarvis.tools._stubs import BaseTool


@AgentRegistry.register("orchestrator")
class OrchestratorAgent(ToolUsingAgent):
    """Multi-turn agent that routes between tools and the LLM.

    Implements a tool-calling loop:
    1. Send messages with tool definitions to the engine.
    2. If the response contains tool_calls, execute them and loop.
    3. If no tool_calls, return the final answer.
    4. Stop after ``max_turns`` iterations.

    In **structured** mode the agent instead uses a
    ``THOUGHT: / TOOL: / INPUT: / FINAL_ANSWER:`` text protocol
    identical to the format used by the orchestrator SFT/GRPO
    training pipelines.
    """

    agent_id = "orchestrator"
    _default_temperature = 0.7
    _default_max_tokens = 1024
    _default_max_turns = 10

    def __init__(
        self,
        engine: InferenceEngine,
        model: str,
        *,
        tools: Optional[List[BaseTool]] = None,
        bus: Optional[EventBus] = None,
        max_turns: Optional[int] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        mode: str = "function_calling",
        system_prompt: Optional[str] = None,
        parallel_tools: bool = True,
        interactive: bool = False,
        confirm_callback=None,
        delegate_fn: Optional[Callable[[str, str], str]] = None,
        chief_registry: Optional[Mapping[str, Mapping[str, object]]] = None,
    ) -> None:
        super().__init__(
            engine,
            model,
            tools=tools,
            bus=bus,
            max_turns=max_turns,
            temperature=temperature,
            max_tokens=max_tokens,
            interactive=interactive,
            confirm_callback=confirm_callback,
        )
        self._mode = mode
        self._system_prompt = system_prompt
        self._parallel_tools = parallel_tools
        self._delegate_fn = delegate_fn
        self._chief_registry = chief_registry
        self._chief_call_counter = itertools.count(1)

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        if self._mode == "structured":
            return self._run_structured(input, context, **kwargs)
        if self._mode == "chief":
            return self._run_chief(input, context, **kwargs)
        return self._run_function_calling(input, context, **kwargs)

    # ------------------------------------------------------------------
    # Structured mode (THOUGHT/TOOL/INPUT/FINAL_ANSWER)
    # ------------------------------------------------------------------

    def _run_structured(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        self._emit_turn_start(input)

        # Build system prompt
        if self._system_prompt:
            sys_prompt = self._system_prompt
        else:
            from openjarvis.learning.intelligence.orchestrator.prompt_registry import (
                build_system_prompt,
            )

            sys_prompt = build_system_prompt(tools=self._tools)

        messages = self._build_messages(input, context, system_prompt=sys_prompt)

        all_tool_results: list[ToolResult] = []
        turns = 0

        for _turn in range(self._max_turns):
            turns += 1

            if self._loop_guard:
                messages = self._loop_guard.compress_context(messages)

            result = self._generate(messages)
            content = result.get("content", "")

            parsed = self._parse_structured_response(content)

            # FINAL_ANSWER -> done
            if parsed["final_answer"]:
                self._emit_turn_end(turns=turns)
                return AgentResult(
                    content=parsed["final_answer"],
                    tool_results=all_tool_results,
                    turns=turns,
                )

            # TOOL -> execute
            if parsed["tool"]:
                messages.append(Message(role=Role.ASSISTANT, content=content))

                tool_call = ToolCall(
                    id=f"orch_{turns}",
                    name=parsed["tool"],
                    arguments=parsed["input"] or "{}",
                )
                tool_result = self._executor.execute(tool_call)
                all_tool_results.append(tool_result)

                observation = f"Observation: {tool_result.content}"
                messages.append(Message(role=Role.USER, content=observation))
                continue

            # Neither -> treat content as final answer
            self._emit_turn_end(turns=turns)
            return AgentResult(
                content=content,
                tool_results=all_tool_results,
                turns=turns,
            )

        # Max turns exceeded
        return self._max_turns_result(all_tool_results, turns)

    @staticmethod
    def _parse_structured_response(text: str) -> dict:
        """Parse THOUGHT/TOOL/INPUT/FINAL_ANSWER from model output."""
        result = {
            "thought": "",
            "tool": "",
            "input": "",
            "final_answer": "",
        }

        thought_match = re.search(
            r"THOUGHT:\s*(.+?)(?=\nTOOL:|\nFINAL[_ ]?ANSWER:|\Z)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if thought_match:
            result["thought"] = thought_match.group(1).strip()

        final_match = re.search(
            r"FINAL[_ ]?ANSWER:\s*(.+)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if final_match:
            result["final_answer"] = final_match.group(1).strip()
            return result

        tool_match = re.search(r"TOOL:\s*(.+)", text, re.IGNORECASE)
        if tool_match:
            result["tool"] = tool_match.group(1).strip()

        input_match = re.search(
            r"INPUT:\s*(.+?)(?=\nTHOUGHT:|\nTOOL:|\nFINAL|\Z)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if input_match:
            result["input"] = input_match.group(1).strip()

        return result

    # ------------------------------------------------------------------
    # Function-calling mode (original behaviour)
    # ------------------------------------------------------------------

    def _run_function_calling(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        self._emit_turn_start(input)

        # Build initial messages
        messages = self._build_messages(input, context)

        # Get OpenAI-format tool definitions
        openai_tools = self._executor.get_openai_tools() if self._tools else []

        all_tool_results: list[ToolResult] = []
        turns = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0

        for _turn in range(self._max_turns):
            turns += 1

            if self._loop_guard:
                messages = self._loop_guard.compress_context(messages)

            # Build generate kwargs
            gen_kwargs: dict[str, Any] = {}
            if openai_tools:
                gen_kwargs["tools"] = openai_tools

            result = self._generate(messages, **gen_kwargs)

            # Accumulate token usage
            usage = result.get("usage", {})
            total_prompt_tokens += usage.get("prompt_tokens", 0)
            total_completion_tokens += usage.get("completion_tokens", 0)

            content = result.get("content", "")
            raw_tool_calls = result.get("tool_calls", [])

            # No tool calls -> check continuation, then final answer
            if not raw_tool_calls:
                content = self._check_continuation(result, messages)
                content = self._strip_think_tags(content)
                self._emit_turn_end(turns=turns, content_length=len(content))
                return AgentResult(
                    content=content,
                    tool_results=all_tool_results,
                    turns=turns,
                    metadata={
                        "prompt_tokens": total_prompt_tokens,
                        "completion_tokens": total_completion_tokens,
                        "total_tokens": total_prompt_tokens + total_completion_tokens,
                    },
                )

            # Build ToolCall objects from raw dicts
            tool_calls = [
                ToolCall(
                    id=tc.get("id", f"call_{i}"),
                    name=tc.get("name", ""),
                    arguments=tc.get("arguments", "{}"),
                )
                for i, tc in enumerate(raw_tool_calls)
            ]

            # Append assistant message with tool calls
            messages.append(
                Message(
                    role=Role.ASSISTANT,
                    content=content,
                    tool_calls=tool_calls,
                )
            )

            # Execute each tool (with loop guard check) and append results
            if self._parallel_tools and len(tool_calls) > 1:
                # Parallel execution
                def _exec_tool(tc: ToolCall) -> tuple:
                    if self._loop_guard:
                        verdict = self._loop_guard.check_call(
                            tc.name,
                            tc.arguments,
                        )
                        if verdict.blocked:
                            return tc, ToolResult(
                                tool_name=tc.name,
                                content=f"Loop guard: {verdict.reason}",
                                success=False,
                            )
                    return tc, self._executor.execute(tc)

                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=len(tool_calls),
                ) as pool:
                    futures = {pool.submit(_exec_tool, tc): tc for tc in tool_calls}
                    results_map: dict[int, tuple] = {}
                    for future in concurrent.futures.as_completed(futures):
                        tc_orig = futures[future]
                        results_map[id(tc_orig)] = future.result()

                # Append results in original order
                for tc in tool_calls:
                    _, tool_result = results_map[id(tc)]
                    all_tool_results.append(tool_result)
                    messages.append(
                        Message(
                            role=Role.TOOL,
                            content=tool_result.content,
                            tool_call_id=tc.id,
                            name=tc.name,
                        )
                    )
            else:
                # Sequential execution
                for tc in tool_calls:
                    # Loop guard check before execution
                    if self._loop_guard:
                        verdict = self._loop_guard.check_call(
                            tc.name,
                            tc.arguments,
                        )
                        if verdict.blocked:
                            tool_result = ToolResult(
                                tool_name=tc.name,
                                content=f"Loop guard: {verdict.reason}",
                                success=False,
                            )
                            all_tool_results.append(tool_result)
                            messages.append(
                                Message(
                                    role=Role.TOOL,
                                    content=tool_result.content,
                                    tool_call_id=tc.id,
                                    name=tc.name,
                                )
                            )
                            continue

                    tool_result = self._executor.execute(tc)
                    all_tool_results.append(tool_result)

                    # Append tool response message
                    messages.append(
                        Message(
                            role=Role.TOOL,
                            content=tool_result.content,
                            tool_call_id=tc.id,
                            name=tc.name,
                        )
                    )

        # Max turns exceeded
        final_content = self._strip_think_tags(content) if content else ""
        self._emit_turn_end(turns=turns, max_turns_exceeded=True)
        return AgentResult(
            content=final_content or "Maximum turns reached without a final answer.",
            tool_results=all_tool_results,
            turns=turns,
            metadata={
                "max_turns_exceeded": True,
                "prompt_tokens": total_prompt_tokens,
                "completion_tokens": total_completion_tokens,
                "total_tokens": total_prompt_tokens + total_completion_tokens,
            },
        )


    # ------------------------------------------------------------------
    # Chief mode (single-action JSON envelope)
    # ------------------------------------------------------------------

    def _run_chief(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        from openjarvis.agents.templates.chief_prompt import (
            build_chief_system_prompt,
        )

        self._emit_turn_start(input)

        sys_prompt = self._system_prompt or build_chief_system_prompt(
            registry=self._chief_registry,
        )
        messages = self._build_messages(input, context, system_prompt=sys_prompt)
        return self._chief_loop(
            messages=messages,
            all_tool_results=[],
            already_delegated=False,
            turns_so_far=0,
        )

    def resume_chief(
        self,
        *,
        messages: List[Message],
        tool_results: List[ToolResult],
        already_delegated: bool,
        turns_so_far: int,
        user_answer: str,
    ) -> AgentResult:
        """Continue a chief that previously emitted action=ask_user.

        Appends ``user_answer`` as a new user message on top of the
        restored conversation state, then re-enters the chief loop.
        """
        self._emit_turn_start(f"[resume] {str(user_answer)[:120]}")
        new_messages = list(messages)
        new_messages.append(Message(role=Role.USER, content=str(user_answer)))
        return self._chief_loop(
            messages=new_messages,
            all_tool_results=list(tool_results),
            already_delegated=bool(already_delegated),
            turns_so_far=int(turns_so_far),
        )

    def _chief_loop(
        self,
        *,
        messages: List[Message],
        all_tool_results: List[ToolResult],
        already_delegated: bool,
        turns_so_far: int,
    ) -> AgentResult:
        from openjarvis.agents.chief import (
            ActionType,
            ParseError,
            build_delegation_message,
            parse_action,
        )
        from openjarvis.core.types import _message_to_dict

        repair_attempted = False
        turns = turns_so_far

        # Allow at least one more turn on resume even if the original run
        # consumed its quota; without this a chief that paused at its very
        # last turn could never finish.
        remaining = max(1, self._max_turns - turns_so_far)

        for _turn in range(remaining):
            turns += 1
            result = self._generate(messages)
            content = self._strip_think_tags(result.get("content", ""))

            try:
                action = parse_action(content)
            except ParseError as exc:
                _chief_logger.warning(
                    "chief parse failed (attempt=%d): %s\nraw response:\n%s",
                    2 if repair_attempted else 1,
                    exc,
                    content,
                )
                if repair_attempted:
                    self._emit_turn_end(turns=turns, chief_parse_failed=True)
                    return AgentResult(
                        content=(
                            "I could not produce a valid action and stopped "
                            f"rather than guess. Parser error: {exc}"
                        ),
                        tool_results=all_tool_results,
                        turns=turns,
                        metadata={
                            "chief": {
                                "action": "parse_failed",
                                "error": str(exc),
                            },
                        },
                    )
                repair_attempted = True
                messages.append(Message(role=Role.ASSISTANT, content=content))
                messages.append(
                    Message(
                        role=Role.USER,
                        content=(
                            "Your previous response could not be parsed as a "
                            f"valid chief action: {exc}. Re-emit exactly one "
                            "JSON object that matches the schema. No prose, "
                            "no code fences."
                        ),
                    )
                )
                continue

            repair_attempted = False
            messages.append(Message(role=Role.ASSISTANT, content=content))

            if action.action is ActionType.COMPLETE:
                report = action.final_report  # guaranteed present
                assert report is not None
                self._emit_turn_end(turns=turns, chief_action="complete")
                return AgentResult(
                    content=report.summary,
                    tool_results=all_tool_results,
                    turns=turns,
                    metadata={
                        "chief": {
                            "action": "complete",
                            "status": report.status,
                            "reason": action.reason,
                            "artifacts": report.artifacts,
                            "followups_needed": report.followups_needed,
                            "evidence": report.evidence,
                        },
                    },
                )

            if action.action is ActionType.ASK_USER:
                question = action.followup_question
                assert question is not None
                rendered = question.question
                if question.reason:
                    rendered = f"{rendered}\n\n(Why: {question.reason})"
                if question.options:
                    options_block = "\n".join(f"- {o}" for o in question.options)
                    rendered = f"{rendered}\n\nOptions:\n{options_block}"
                checkpoint = {
                    "messages": [_message_to_dict(m) for m in messages],
                    "tool_results": [
                        {
                            "tool_name": tr.tool_name,
                            "content": tr.content,
                            "success": tr.success,
                        }
                        for tr in all_tool_results
                    ],
                    "already_delegated": already_delegated,
                    "turns": turns,
                    "question": {
                        "question": question.question,
                        "reason": question.reason,
                        "expected_response_type": question.expected_response_type,
                        "options": question.options,
                    },
                }
                self._emit_turn_end(turns=turns, chief_action="ask_user")
                return AgentResult(
                    content=rendered,
                    tool_results=all_tool_results,
                    turns=turns,
                    metadata={
                        "chief": {
                            "action": "ask_user",
                            "reason": action.reason,
                            "expected_response_type": question.expected_response_type,
                            "options": question.options,
                            "checkpoint": checkpoint,
                        },
                    },
                )

            if action.action is ActionType.FAIL:
                self._emit_turn_end(turns=turns, chief_action="fail")
                return AgentResult(
                    content=f"Cannot complete this request: {action.reason}",
                    tool_results=all_tool_results,
                    turns=turns,
                    metadata={
                        "chief": {
                            "action": "fail",
                            "reason": action.reason,
                        },
                    },
                )

            if action.action is ActionType.EXECUTE_DIRECT:
                # Don't let the chief silently double-up after a delegate.
                # If we already dispatched a delegation round and the
                # subordinate did the work, an execute_direct here would
                # create a parallel duplicate (the bug the user saw with
                # two Iron Saints tasks). Treat it the same as
                # re-delegation: one forced repair turn, then bail.
                if already_delegated:
                    _chief_logger.warning(
                        "chief tried to execute_direct after a prior "
                        "delegation; forcing repair turn"
                    )
                    if repair_attempted:
                        self._emit_turn_end(
                            turns=turns, chief_redo_blocked=True
                        )
                        return AgentResult(
                            content=(
                                "Stopped: the chief tried to run its own "
                                "tools after a subordinate had already "
                                "handled the task. Aggregation did not "
                                "complete cleanly."
                            ),
                            tool_results=all_tool_results,
                            turns=turns,
                            metadata={"chief": {"action": "redo_blocked"}},
                        )
                    repair_attempted = True
                    messages.append(
                        Message(
                            role=Role.USER,
                            content=(
                                "You already delegated this work and the "
                                "subordinate's results are above. Running "
                                "the same tool yourself now would create a "
                                "duplicate. Emit action=complete and "
                                "synthesize the subordinate's reply -- do "
                                "NOT emit another execute_direct or "
                                "delegate."
                            ),
                        )
                    )
                    continue
                # The chief is invoking its own tools without delegating.
                # Each call goes through the chief's executor (so any
                # waiting_on_tool status / scrubber / vault wiring fires
                # exactly as it does for any other tool call from the
                # chief). Results are fed back as a synthetic user turn
                # so the chief can aggregate on the next iteration.
                already_delegated = True
                tool_results_lines: list[str] = ["Tool results:"]
                for tc_spec in action.tool_calls:
                    call_id = (
                        f"chief_exec_{next(self._chief_call_counter)}"
                    )
                    tool_call = ToolCall(
                        id=call_id,
                        name=tc_spec.name,
                        arguments=tc_spec.arguments or "{}",
                    )
                    delegate_tool = next(
                        (t for t in self._tools if t.spec.name == tc_spec.name),
                        None,
                    )
                    if delegate_tool is None:
                        failure = ToolResult(
                            tool_name=tc_spec.name,
                            content=(
                                f"Tool {tc_spec.name!r} is not available "
                                "to this chief."
                            ),
                            success=False,
                        )
                        all_tool_results.append(failure)
                        tool_results_lines.append(
                            f"- {tc_spec.name} (unavailable):"
                        )
                        tool_results_lines.append(
                            f"    {failure.content}"
                        )
                        continue
                    tool_result = self._executor.execute(tool_call)
                    all_tool_results.append(tool_result)
                    status = "ok" if tool_result.success else "failed"
                    tool_results_lines.append(
                        f"- {tc_spec.name} ({status}):"
                    )
                    for line in (tool_result.content or "").splitlines() or [""]:
                        tool_results_lines.append(f"    {line}")
                messages.append(
                    Message(
                        role=Role.USER,
                        content="\n".join(tool_results_lines),
                    )
                )
                continue

            # action is DELEGATE
            if already_delegated:
                # The chief has already dispatched one round; doing it again
                # is the loop the doc warns against. Force a repair turn,
                # then bail if it persists.
                _chief_logger.warning(
                    "chief tried to delegate again after a prior round; "
                    "forcing repair turn"
                )
                if repair_attempted:
                    self._emit_turn_end(turns=turns, chief_redelegate_blocked=True)
                    return AgentResult(
                        content=(
                            "Stopped: the chief attempted to delegate a "
                            "second time after subordinate results were "
                            "already returned. Aggregation did not "
                            "complete."
                        ),
                        tool_results=all_tool_results,
                        turns=turns,
                        metadata={"chief": {"action": "redelegate_blocked"}},
                    )
                repair_attempted = True
                messages.append(
                    Message(
                        role=Role.USER,
                        content=(
                            "You have already delegated once and received "
                            "the Delegation results above. Re-delegation is "
                            "forbidden. Emit action=complete and synthesize "
                            "the subordinate outputs into a final_report, "
                            "or emit action=ask_user / action=fail with a "
                            "concrete reason. Do NOT emit another delegate."
                        ),
                    )
                )
                continue

            already_delegated = True
            results_lines: list[str] = ["Delegation results:"]
            # Dedupe within a single action: only ONE delegation per agent
            # per action. A chief that emits two delegations to the same
            # subordinate -- even with slightly different wording -- almost
            # always produces duplicate downstream side effects (the
            # two-tasks-from-one-request bug). If the chief genuinely needs
            # the same agent to handle multiple goals, it should batch them
            # into a single delegation message.
            seen_agents: set[str] = set()
            for delegation in action.delegations:
                agent_key = delegation.agent_name_or_id.strip().casefold()
                if agent_key in seen_agents:
                    _chief_logger.warning(
                        "chief emitted duplicate delegation to %s; skipping "
                        "(only one delegation per agent per action)",
                        delegation.agent_name_or_id,
                    )
                    results_lines.append(
                        f"- {delegation.agent_name_or_id} (duplicate "
                        f"delegation to same agent in one action -- "
                        f"skipped to avoid duplicate side effects)"
                    )
                    continue
                seen_agents.add(agent_key)
                payload = build_delegation_message(delegation)
                reply_text, tool_result = self._chief_dispatch_delegation(
                    delegation.agent_name_or_id,
                    payload,
                    tools_allowed=delegation.tools_allowed,
                )
                if tool_result is not None:
                    all_tool_results.append(tool_result)
                status = "ok"
                if tool_result is not None and not tool_result.success:
                    status = "failed"
                header = f"- {delegation.agent_name_or_id}"
                if delegation.task_id:
                    header += f" [{delegation.task_id}]"
                header += f" ({status}):"
                results_lines.append(header)
                for line in (reply_text or "").splitlines() or [""]:
                    results_lines.append(f"    {line}")
            messages.append(
                Message(role=Role.USER, content="\n".join(results_lines))
            )

        # Max turns exceeded
        self._emit_turn_end(turns=turns, chief_max_turns_exceeded=True)
        return AgentResult(
            content=(
                "Maximum chief turns reached without producing a final answer."
            ),
            tool_results=all_tool_results,
            turns=turns,
            metadata={"chief": {"action": "max_turns_exceeded"}},
        )

    def _chief_dispatch_delegation(
        self,
        agent_name_or_id: str,
        message: str,
        *,
        tools_allowed: Optional[List[str]] = None,
    ) -> tuple[str, Optional[ToolResult]]:
        """Send one delegation; return (reply text, tool result if any).

        Prefers an injected ``delegate_fn`` for tests; otherwise dispatches
        through the existing ``managed_agent_delegate`` tool if it is in
        the agent's toolset. When ``tools_allowed`` is supplied it is
        forwarded to the tool so the child runs under a narrowed toolset.
        """
        if self._delegate_fn is not None:
            try:
                # delegate_fn may or may not accept tools_allowed; try the
                # newer signature first and fall back if it can't.
                try:
                    reply = self._delegate_fn(  # type: ignore[call-arg]
                        agent_name_or_id,
                        message,
                        tools_allowed=tools_allowed,
                    )
                except TypeError:
                    reply = self._delegate_fn(agent_name_or_id, message)
                return str(reply), None
            except Exception as exc:  # surface failures as failed tool results
                return (
                    f"Delegation to {agent_name_or_id} failed: {exc}",
                    ToolResult(
                        tool_name="chief.delegate",
                        content=f"Delegation failed: {exc}",
                        success=False,
                    ),
                )

        delegate_tool = next(
            (t for t in self._tools if t.spec.name == "managed_agent_delegate"),
            None,
        )
        if delegate_tool is None:
            failure = ToolResult(
                tool_name="chief.delegate",
                content="no delegate channel available",
                success=False,
            )
            return (
                f"Delegation to {agent_name_or_id} skipped: no delegate channel.",
                failure,
            )

        call_id = f"chief_delegate_{next(self._chief_call_counter)}"
        args: dict[str, Any] = {
            "agent_name_or_id": agent_name_or_id,
            "message": message,
        }
        if tools_allowed is not None:
            args["tools_allowed"] = list(tools_allowed)
        tool_call = ToolCall(
            id=call_id,
            name="managed_agent_delegate",
            arguments=json.dumps(args),
        )
        tool_result = self._executor.execute(tool_call)
        return tool_result.content, tool_result


__all__ = ["OrchestratorAgent"]
