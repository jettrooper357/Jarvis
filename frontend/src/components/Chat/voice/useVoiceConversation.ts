import { useCallback, useRef, useState } from 'react';
import { reduce, initialContext } from './voiceConversationMachine';
import type { VoiceConfig, VoiceContext, VoiceEffect, VoiceEvent } from './voiceTypes';
import { voiceLog } from './voiceLog';

export interface VoiceDeps {
  config: VoiceConfig;
  startListening: () => Promise<void>;
  stopListening: () => void;
  stopTts: () => void;
  sendMessage: (text: string) => Promise<void>;
  abortLlm: () => void;
  markLastAssistantInterrupted: () => void;
}

export function useVoiceConversation(deps: VoiceDeps) {
  const ctxRef = useRef<VoiceContext>(initialContext);
  const [context, setContext] = useState<VoiceContext>(initialContext);
  // Timestamp playback started, to guard against echo self-interruption.
  const playbackStartedAt = useRef<number>(0);

  const runEffects = useCallback(
    (effects: VoiceEffect[]) => {
      for (const e of effects) {
        voiceLog.debug('effect', e);
        switch (e) {
          case 'START_LISTENING':
          case 'RECOVER_TO_LISTENING':
            void deps.startListening();
            break;
          case 'STOP_LISTENING':
          case 'RECOVER_TO_IDLE':
            deps.stopListening();
            break;
          case 'ABORT_LLM':
            deps.abortLlm();
            break;
          case 'STOP_TTS':
            deps.stopTts();
            break;
          case 'MARK_INTERRUPTED':
            deps.markLastAssistantInterrupted();
            break;
        }
      }
    },
    [deps],
  );

  const dispatch = useCallback(
    (ev: VoiceEvent) => {
      const { context: nextCtx, effects } = reduce(ctxRef.current, ev);
      if (nextCtx.state !== ctxRef.current.state) {
        voiceLog.info('state', `${ctxRef.current.state} -> ${nextCtx.state} (${ev.type})`);
      }
      ctxRef.current = nextCtx;
      setContext(nextCtx);
      runEffects(effects);
      // INTERRUPTED is transient: immediately recover to LISTENING.
      if (nextCtx.state === 'INTERRUPTED') {
        const r = reduce(ctxRef.current, { type: 'RESET' });
        ctxRef.current = r.context;
        setContext(r.context);
        runEffects(r.effects);
      }
      // ERROR is transient: log and recover to LISTENING.
      if (nextCtx.state === 'ERROR') {
        voiceLog.error('error', nextCtx.error ?? 'unknown');
        const r = reduce(ctxRef.current, { type: 'RESET' });
        ctxRef.current = r.context;
        setContext(r.context);
        runEffects(r.effects);
      }
    },
    [runEffects],
  );

  // ---- Public API: callbacks the InputArea wires to the real primitives ----
  const start = useCallback(async () => {
    dispatch({ type: 'START' });
  }, [dispatch]);

  const stop = useCallback(() => {
    dispatch({ type: 'STOP' });
  }, [dispatch]);

  // From useStreamingSpeech.onSpeechStart. Doubles as barge-in: the reducer
  // decides whether this is a new turn (LISTENING) or an interruption (while
  // producing/playing). We additionally suppress echo self-interrupts for the
  // first ~300ms of playback.
  const handleSpeechStart = useCallback(() => {
    voiceLog.debug('mic', 'speech_start');
    const s = ctxRef.current.state;
    const producing =
      s === 'GENERATING_RESPONSE' ||
      s === 'PROCESSING_TTS' ||
      s === 'PLAYING_RESPONSE' ||
      s === 'PROCESSING_STT';
    if (producing) {
      if (!deps.config.allowInterruption) return; // half-duplex: ignore
      // Echo guard: ignore mic onset for the first `minSpeechMs` of playback so
      // the assistant's own audio (on speakers without perfect AEC) can't
      // self-interrupt. Configurable via the "minimum speech duration" setting.
      if (s === 'PLAYING_RESPONSE' && Date.now() - playbackStartedAt.current < deps.config.minSpeechMs) return;
      dispatch({ type: 'INTERRUPT' });
      return;
    }
    dispatch({ type: 'SPEECH_START' });
  }, [dispatch, deps.config.allowInterruption, deps.config.minSpeechMs]);

  const handlePartial = useCallback(
    (text: string) => {
      dispatch({ type: 'PARTIAL', text });
    },
    [dispatch],
  );

  // From useStreamingSpeech.onFinal. Sends the turn to the LLM.
  const handleFinal = useCallback(
    (text: string) => {
      const spoken = text.trim();
      if (!spoken) return;
      voiceLog.info('stt', `final: ${spoken}`);
      dispatch({ type: 'FINAL', text: spoken });
      deps.sendMessage(spoken).catch((err) => {
        dispatch({ type: 'LLM_ERROR', message: String(err) });
      });
    },
    [dispatch, deps],
  );

  const handleTtsStart = useCallback(() => {
    playbackStartedAt.current = Date.now();
    voiceLog.info('tts', 'playback start');
    dispatch({ type: 'TTS_START' });
  }, [dispatch]);

  const handlePlaybackDone = useCallback(() => {
    voiceLog.info('tts', 'playback done');
    dispatch({ type: 'PLAYBACK_DONE' });
  }, [dispatch]);

  const handleLlmDone = useCallback(() => {
    dispatch({ type: 'LLM_DONE' });
  }, [dispatch]);

  const handleLlmError = useCallback(
    (message: string) => {
      dispatch({ type: 'LLM_ERROR', message });
    },
    [dispatch],
  );

  const handleSttError = useCallback(
    (message: string) => {
      dispatch({ type: 'STT_ERROR', message });
    },
    [dispatch],
  );

  return {
    state: context.state,
    partial: context.partial,
    transcript: context.transcript,
    error: context.error,
    start,
    stop,
    handleSpeechStart,
    handlePartial,
    handleFinal,
    handleTtsStart,
    handlePlaybackDone,
    handleLlmDone,
    handleLlmError,
    handleSttError,
  };
}
