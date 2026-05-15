import { useState, useRef, useCallback, useEffect } from 'react';
import { Send, Square, Paperclip } from 'lucide-react';
import { useAppStore, generateId } from '../../lib/store';
import { streamChat } from '../../lib/sse';
import { fetchSavings, getBase } from '../../lib/api';
import { MicButton } from './MicButton';
import { useSpeech } from '../../hooks/useSpeech';
import { useStreamingSpeech } from '../../hooks/useStreamingSpeech';
import { useTTSPlayer } from '../../hooks/useTTSPlayer';
import { matchWakeWord } from '../../lib/wakeWord';
import type { ChatMessage, ToolCallInfo, TokenUsage, MessageTelemetry } from '../../types';

type ApiMessage = { role: string; content: string };

/**
 * Keep the last `limit` messages verbatim and fold everything older into a
 * single condensed system message. Purely local (no extra LLM round-trip) so
 * it adds no latency — the point is to stop resending an ever-growing
 * transcript on every turn.
 */
function buildContextMessages(messages: ChatMessage[], limit: number): ApiMessage[] {
  if (!Number.isFinite(limit) || limit <= 0 || messages.length <= limit) {
    return messages.map((m) => ({ role: m.role, content: m.content }));
  }
  const split = messages.length - limit;
  const older = messages.slice(0, split);
  const recent = messages.slice(split);
  const summary = older
    .map((m) => `${m.role}: ${m.content.replace(/\s+/g, ' ').trim().slice(0, 160)}`)
    .join('\n')
    .slice(0, 1500);
  return [
    {
      role: 'system',
      content: `Summary of earlier conversation (older turns condensed for brevity):\n${summary}`,
    },
    ...recent.map((m) => ({ role: m.role, content: m.content })),
  ];
}

export function InputArea() {
  const [input, setInput] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const activeId = useAppStore((s) => s.activeId);
  const selectedModel = useAppStore((s) => s.selectedModel);
  const streamState = useAppStore((s) => s.streamState);
  const messages = useAppStore((s) => s.messages);
  const speechEnabled = useAppStore((s) => s.settings.speechEnabled);
  const speechStreaming = useAppStore((s) => s.settings.speechStreaming);
  const ttsAutoplay = useAppStore((s) => s.settings.ttsAutoplay);
  const ttsVoice = useAppStore((s) => s.settings.ttsVoice);
  const ttsSpeed = useAppStore((s) => s.settings.ttsSpeed);
  const wakeWords = useAppStore((s) => s.settings.wakeWords);
  const maxTokens = useAppStore((s) => s.settings.maxTokens);
  const temperature = useAppStore((s) => s.settings.temperature);
  const createConversation = useAppStore((s) => s.createConversation);
  const addMessage = useAppStore((s) => s.addMessage);
  const updateLastAssistant = useAppStore((s) => s.updateLastAssistant);
  const setStreamState = useAppStore((s) => s.setStreamState);
  const resetStream = useAppStore((s) => s.resetStream);
  const modelLoading = useAppStore((s) => s.modelLoading);

  const { state: speechState, available: speechAvailable, startRecording, stopRecording } = useSpeech();
  const sendRef = useRef<((override?: string) => Promise<void>) | null>(null);
  // tts is declared before `streaming` so the barge-in callback can reference it.
  const tts = useTTSPlayer({ voiceId: ttsVoice, speed: ttsSpeed });
  const streaming = useStreamingSpeech({
    onFinal: (text) => {
      const filtered = matchWakeWord(text, wakeWords);
      if (filtered === null) return;
      if (filtered.trim()) sendRef.current?.(filtered);
    },
    // Barge-in: the moment VAD hears the user, cut the assistant off.
    onSpeechStart: () => tts.stop(),
  });

  // Wake-word mode: when any wake phrase is configured, keep the mic open
  // continuously so the user can speak to the chat hands-free. The streaming
  // hook's onFinal already drops non-matching utterances, so passing nothing
  // through happens silently. Only auto-start when speech is fully wired up.
  const hasWakeWords = wakeWords.length > 0;
  useEffect(() => {
    if (!hasWakeWords) return;
    if (!speechEnabled || !speechStreaming) return;
    if (!streaming.available) return;
    if (streaming.state !== 'idle') return;
    streaming.start();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasWakeWords, speechEnabled, speechStreaming, streaming.available]);

  // Abort in-flight stream when the user switches models mid-generation.
  // This prevents errors from trying to continue a stream with a stale model.
  const prevModelRef = useRef(selectedModel);
  useEffect(() => {
    if (prevModelRef.current !== selectedModel && streamState.isStreaming) {
      abortRef.current?.abort();
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      resetStream();
      abortRef.current = null;
    }
    prevModelRef.current = selectedModel;
  }, [selectedModel, streamState.isStreaming, resetStream]);

  const effectiveMicAvailable = speechStreaming ? streaming.available : speechAvailable;
  const micDisabled = !speechEnabled || !effectiveMicAvailable || streamState.isStreaming;
  const micReason: 'not-enabled' | 'no-backend' | 'streaming' | undefined =
    !speechEnabled ? 'not-enabled'
    : !effectiveMicAvailable ? 'no-backend'
    : streamState.isStreaming ? 'streaming'
    : undefined;

  const micState: 'idle' | 'recording' | 'transcribing' = speechStreaming
    ? (streaming.state === 'listening' ? 'recording'
      : streaming.state === 'transcribing' ? 'transcribing' : 'idle')
    : speechState;

  const handleMicClick = useCallback(async () => {
    if (speechStreaming) {
      if (streaming.state === 'idle') {
        await streaming.start();
      } else {
        streaming.stop();
      }
      return;
    }
    if (speechState === 'recording') {
      try {
        const text = await stopRecording();
        if (text) {
          setInput((prev) => (prev ? prev + ' ' + text : text));
        }
      } catch {
        // Error is captured in useSpeech
      }
    } else {
      await startRecording();
    }
  }, [speechStreaming, streaming, speechState, startRecording, stopRecording]);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 200) + 'px';
  }, [input]);

  const stopStreaming = useCallback(() => {
    abortRef.current?.abort();
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    resetStream();
  }, [resetStream]);

  const sendMessage = useCallback(async (override?: string) => {
    const content = (override ?? input).trim();
    if (!content || streamState.isStreaming) return;

    if (override === undefined) setInput('');
    if (ttsAutoplay) tts.stop();

    let convId = activeId;
    if (!convId) {
      convId = createConversation(selectedModel);
    }

    const userMsg: ChatMessage = {
      id: generateId(),
      role: 'user',
      content,
      timestamp: Date.now(),
    };
    addMessage(convId, userMsg);

    // Build API messages before adding assistant placeholder. Older turns are
    // condensed into one summary message so latency/token cost stays flat as
    // the conversation grows, instead of resending the whole transcript.
    const currentMessages = useAppStore.getState().messages;
    const contextLimit = useAppStore.getState().settings.contextMaxMessages;
    const apiMessages = buildContextMessages(currentMessages, contextLimit);

    const assistantMsg: ChatMessage = {
      id: generateId(),
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
    };
    addMessage(convId, assistantMsg);

    // Start streaming
    const startTime = Date.now();
    const timer = setInterval(() => {
      setStreamState({ elapsedMs: Date.now() - startTime });
    }, 100);
    timerRef.current = timer;

    const controller = new AbortController();
    abortRef.current = controller;

    let accumulatedContent = '';
    let usage: TokenUsage | undefined;
    let complexity: { score: number; tier: string; suggested_max_tokens: number } | undefined;
    const toolCalls: ToolCallInfo[] = [];
    let lastFlush = 0;
    let ttftMs: number | undefined;

    setStreamState({
      isStreaming: true,
      phase: 'Generating...',
      elapsedMs: 0,
      activeToolCalls: [],
      content: '',
    });
    useAppStore.getState().addLogEntry({
      timestamp: Date.now(),
      level: 'info',
      category: 'chat',
      message: `Request: "${content.slice(0, 80)}${content.length > 80 ? '...' : ''}" → ${selectedModel}`,
    });

    try {
      for await (const sseEvent of streamChat(
        { model: selectedModel, messages: apiMessages, stream: true, temperature, max_tokens: maxTokens },
        controller.signal,
      )) {
        const eventName = sseEvent.event;

        if (eventName === 'agent_turn_start') {
          setStreamState({ phase: 'Agent thinking...' });
        } else if (eventName === 'inference_start') {
          setStreamState({ phase: 'Generating...' });
          useAppStore.getState().addLogEntry({
            timestamp: Date.now(), level: 'info', category: 'chat',
            message: `Generating with ${selectedModel}...`,
          });
        } else if (eventName === 'tool_call_start') {
          try {
            const data = JSON.parse(sseEvent.data);
            const tc: ToolCallInfo = {
              id: generateId(),
              tool: data.tool,
              arguments: data.arguments || '',
              status: 'running',
            };
            toolCalls.push(tc);
            setStreamState({
              phase: `Calling ${data.tool}...`,
              activeToolCalls: [...toolCalls],
            });
            updateLastAssistant(convId, accumulatedContent, [...toolCalls]);
            useAppStore.getState().addLogEntry({
              timestamp: Date.now(), level: 'info', category: 'tool',
              message: `Calling ${data.tool}(${data.arguments || ''})`,
            });
          } catch {}
        } else if (eventName === 'tool_call_end') {
          try {
            const data = JSON.parse(sseEvent.data);
            const tc = toolCalls.find(
              (t) => t.tool === data.tool && t.status === 'running',
            );
            if (tc) {
              tc.status = data.success ? 'success' : 'error';
              tc.latency = data.latency;
              tc.result = data.result;
            }
            setStreamState({
              phase: 'Generating...',
              activeToolCalls: [...toolCalls],
            });
            updateLastAssistant(convId, accumulatedContent, [...toolCalls]);
          } catch {}
        } else {
          try {
            const data = JSON.parse(sseEvent.data);
            const delta = data.choices?.[0]?.delta;
            if (data.usage) usage = data.usage;
            if (data.complexity) complexity = data.complexity;
            if (delta?.content) {
              if (!ttftMs) ttftMs = Date.now() - startTime;
              accumulatedContent += delta.content;
              setStreamState({ content: accumulatedContent, phase: '' });
              if (ttsAutoplay) tts.feedToken(delta.content);

              const now = Date.now();
              if (now - lastFlush >= 80) {
                updateLastAssistant(
                  convId,
                  accumulatedContent,
                  toolCalls.length > 0 ? [...toolCalls] : undefined,
                );
                lastFlush = now;
              }
            }
            if (data.choices?.[0]?.finish_reason === 'stop') break;
          } catch {}
        }
      }
    } catch (err: any) {
      if (err.name === 'AbortError') {
        // User cancelled or model switch — keep whatever was accumulated
        if (!accumulatedContent) accumulatedContent = '(Generation stopped)';
      } else {
        const errMsg = err?.message || String(err);
        accumulatedContent =
          accumulatedContent || `Error: ${errMsg}`;
        useAppStore.getState().addLogEntry({
          timestamp: Date.now(), level: 'error', category: 'chat',
          message: `Stream error: ${errMsg}`,
        });
      }
    } finally {
      if (!accumulatedContent) {
        accumulatedContent = 'No response was generated. Please try again.';
      }
      const totalMs = Date.now() - startTime;
      const _CLOUD_PREFIXES = ['gpt-', 'o1-', 'o3-', 'o4-', 'claude-', 'gemini-', 'openrouter/', 'MiniMax-', 'chatgpt-'];
      const engineLabel = _CLOUD_PREFIXES.some(p => selectedModel.startsWith(p)) ? 'cloud' : 'ollama';
      const telemetry: MessageTelemetry = {
        engine: engineLabel,
        model_id: selectedModel,
        total_ms: totalMs,
        ttft_ms: ttftMs,
        tokens_per_sec: usage?.completion_tokens
          ? usage.completion_tokens / (totalMs / 1000)
          : undefined,
        complexity_score: complexity?.score,
        complexity_tier: complexity?.tier,
        suggested_max_tokens: complexity?.suggested_max_tokens,
      };
      // Check if the response has digest audio available
      let audioMeta: { url: string } | undefined;
      try {
        const digestRes = await fetch(`${getBase()}/api/digest`);
        if (digestRes.ok) {
          const digest = await digestRes.json();
          if (digest.audio_available) {
            audioMeta = { url: `${getBase()}/api/digest/audio` };
          }
        }
      } catch {
        // Not a digest response or server unavailable — skip
      }

      updateLastAssistant(
        convId,
        accumulatedContent,
        toolCalls.length > 0 ? toolCalls : undefined,
        usage,
        telemetry,
        audioMeta,
      );
      if (ttsAutoplay) tts.flush();
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      resetStream();
      useAppStore.getState().addLogEntry({
        timestamp: Date.now(), level: 'info', category: 'chat',
        message: `Response: ${accumulatedContent.length} chars`,
      });
      abortRef.current = null;

      fetchSavings()
        .then((data) => useAppStore.getState().setSavings(data))
        .catch(() => {});
    }
  }, [
    input,
    activeId,
    selectedModel,
    streamState.isStreaming,
    createConversation,
    addMessage,
    updateLastAssistant,
    setStreamState,
    resetStream,
    ttsAutoplay,
    tts,
    temperature,
    maxTokens,
  ]);

  useEffect(() => {
    sendRef.current = sendMessage;
  }, [sendMessage]);

  // Welcome-screen action tiles / suggested prompts submit through here.
  useEffect(() => {
    const onSend = (e: Event) => {
      const text = (e as CustomEvent<string>).detail;
      if (text && text.trim()) sendRef.current?.(text);
    };
    window.addEventListener('jarvis-send', onSend as EventListener);
    return () => window.removeEventListener('jarvis-send', onSend as EventListener);
  }, []);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <div className="px-4 pb-4 pt-2" style={{ maxWidth: 'var(--chat-max-width)', margin: '0 auto', width: '100%' }}>
      {speechStreaming && (streaming.isListening || streaming.interim) && (
        <div
          className="mb-2 px-3 py-2 rounded-xl text-sm italic"
          style={{
            background: 'var(--color-bg-tertiary)',
            color: 'var(--color-text-secondary)',
            border: '1px solid var(--color-input-border)',
          }}
        >
          {streaming.interim ||
            (streaming.state === 'listening'
              ? hasWakeWords
                ? `Listening for "${wakeWords[0]}"…`
                : 'Listening…'
              : 'Transcribing…')}
        </div>
      )}
      {streaming.error && (
        <div
          className="mb-2 px-3 py-2 rounded-xl text-xs"
          style={{ background: 'var(--color-error)', color: 'white' }}
        >
          {streaming.error}
        </div>
      )}
      <div
        className="flex items-center gap-2 rounded-2xl px-4 py-3 transition-shadow"
        style={{
          background: 'var(--color-input-bg)',
          border: '1px solid color-mix(in srgb, var(--color-accent) 45%, transparent)',
          boxShadow: '0 0 0 1px color-mix(in srgb, var(--color-accent) 10%, transparent), 0 0 20px -6px var(--color-accent-glow)',
        }}
      >
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Message J.A.R.V.I.S..."
          rows={1}
          className="flex-1 bg-transparent outline-none resize-none text-sm leading-relaxed"
          style={{ color: 'var(--color-text)', maxHeight: '200px' }}
          disabled={streamState.isStreaming || modelLoading}
        />
        {streamState.isStreaming ? (
          <button
            onClick={stopStreaming}
            className="p-2 rounded-xl transition-colors shrink-0 cursor-pointer"
            style={{ background: 'var(--color-error)', color: 'var(--color-on-accent)' }}
            title="Stop generating"
          >
            <Square size={16} />
          </button>
        ) : (
          <div className="flex items-center gap-1">
            <MicButton
              state={micState}
              onClick={handleMicClick}
              disabled={micDisabled}
              reason={micReason}
            />
            <button
              onClick={() => sendMessage()}
              disabled={!input.trim() || modelLoading}
              className="p-2 rounded-xl transition-colors shrink-0 cursor-pointer disabled:opacity-30 disabled:cursor-default"
              style={{
                background: input.trim() ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
                color: input.trim() ? 'white' : 'var(--color-text-tertiary)',
              }}
              title="Send message"
            >
              <Send size={16} />
            </button>
          </div>
        )}
      </div>
      <div className="flex items-center justify-center mt-2 text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>
        <span>
          <kbd className="font-mono">Enter</kbd> to send &middot;{' '}
          <kbd className="font-mono">Shift+Enter</kbd> for new line
        </span>
      </div>
    </div>
  );
}
