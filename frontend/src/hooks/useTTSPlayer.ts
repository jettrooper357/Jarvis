import { useCallback, useEffect, useRef, useState } from 'react';
import { getBase } from '../lib/api';

/** Splits text into sentence-ish chunks suitable for low-latency TTS. */
function splitSentences(text: string): string[] {
  const out: string[] = [];
  let buf = '';
  for (const ch of text) {
    buf += ch;
    if (/[.!?\n]/.test(ch) && buf.trim().length > 4) {
      out.push(buf.trim());
      buf = '';
    }
  }
  if (buf.trim()) out.push(buf.trim());
  return out;
}

interface UseTTSPlayerOptions {
  provider?: string;
  voiceId?: string;
  speed?: number;
  onStart?: () => void;
  onIdle?: () => void;
}

/**
 * Streams text → audio one sentence at a time and plays it back gaplessly.
 *
 * - ``speak(text)`` synthesizes the full text via the streaming endpoint and
 *   plays each chunk as soon as it arrives.
 * - ``feedToken(token)`` accumulates streaming LLM tokens and dispatches them
 *   sentence-by-sentence so playback starts before generation finishes.
 * - ``flush()`` synthesizes any leftover partial sentence.
 * - ``stop()`` aborts playback and any in-flight synthesis.
 */
export function useTTSPlayer(opts: UseTTSPlayerOptions = {}) {
  const [isSpeaking, setIsSpeaking] = useState(false);
  const ctxRef = useRef<AudioContext | null>(null);
  const queueRef = useRef<Promise<void>>(Promise.resolve());
  const abortRef = useRef<AbortController | null>(null);
  const pendingRef = useRef('');
  const pendingJobsRef = useRef(0);
  const currentSourceRef = useRef<AudioBufferSourceNode | null>(null);
  const onStartRef = useRef(opts.onStart);
  const onIdleRef = useRef(opts.onIdle);
  onStartRef.current = opts.onStart;
  onIdleRef.current = opts.onIdle;

  const ensureCtx = (): AudioContext => {
    if (!ctxRef.current) {
      ctxRef.current = new AudioContext();
    }
    return ctxRef.current;
  };

  const playAudio = useCallback(async (audioBytes: ArrayBuffer): Promise<void> => {
    const ctx = ensureCtx();
    if (ctx.state === 'suspended') await ctx.resume();
    const buf = await ctx.decodeAudioData(audioBytes.slice(0));
    return new Promise<void>((resolve) => {
      const src = ctx.createBufferSource();
      src.buffer = buf;
      src.connect(ctx.destination);
      currentSourceRef.current = src;
      src.onended = () => {
        if (currentSourceRef.current === src) currentSourceRef.current = null;
        resolve();
      };
      src.start();
    });
  }, []);

  const synthesizeAudio = useCallback(
    async (text: string, signal: AbortSignal): Promise<ArrayBuffer[]> => {
      if (!text.trim()) return [];
      const res = await fetch(`${getBase()}/v1/speech/synthesize/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text,
          provider: opts.provider || 'auto',
          voice_id: opts.voiceId || '',
          speed: opts.speed ?? 1.0,
          output_format: 'wav',
        }),
        signal,
      });
      if (!res.ok || !res.body) {
        throw new Error(`Synthesize failed: ${res.status}`);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let leftover = '';
      const chunks: ArrayBuffer[] = [];
      while (!signal.aborted) {
        const { value, done } = await reader.read();
        if (done) break;
        leftover += decoder.decode(value, { stream: true });
        const lines = leftover.split('\n');
        leftover = lines.pop() || '';
        for (const raw of lines) {
          if (!raw.startsWith('data:')) continue;
          const data = raw.slice(5).trim();
          if (!data || data === '[DONE]') continue;
          try {
            const payload = JSON.parse(data);
            if (payload.error) throw new Error(payload.error);
            if (payload.audio) {
              const bin = atob(payload.audio);
              const arr = new Uint8Array(bin.length);
              for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
              if (signal.aborted) return chunks;
              chunks.push(arr.buffer);
            }
          } catch (err) {
            if ((err as Error).name !== 'AbortError') throw err;
          }
        }
      }
      return chunks;
    },
    [opts.provider, opts.voiceId, opts.speed],
  );

  const enqueue = useCallback(
    (text: string) => {
      if (!text.trim()) return;
      if (!abortRef.current) abortRef.current = new AbortController();
      const signal = abortRef.current.signal;
      onStartRef.current?.();
      setIsSpeaking(true);
      pendingJobsRef.current += 1;
      // Start synthesis immediately, even while earlier audio is still
      // playing. Playback remains ordered below, but the next sentence is
      // usually ready by the time the current one ends.
      const audioPromise = synthesizeAudio(text, signal);
      audioPromise.catch(() => {});
      queueRef.current = queueRef.current
        .then(async () => {
          const chunks = await audioPromise;
          for (const chunk of chunks) {
            if (signal.aborted) return;
            await playAudio(chunk);
          }
        })
        .catch((err) => {
          if ((err as Error).name !== 'AbortError') {
            console.warn('TTS error', err);
          }
        })
        .finally(() => {
          pendingJobsRef.current = Math.max(0, pendingJobsRef.current - 1);
          if (signal.aborted) return;
          queueMicrotask(() => {
            if (pendingJobsRef.current === 0 && !currentSourceRef.current) {
              setIsSpeaking(false);
              onIdleRef.current?.();
            }
          });
        });
    },
    [playAudio, synthesizeAudio],
  );

  const speak = useCallback((text: string) => enqueue(text), [enqueue]);

  const feedToken = useCallback(
    (token: string) => {
      pendingRef.current += token;
      const sentences = splitSentences(pendingRef.current);
      if (sentences.length > 1) {
        const ready = sentences.slice(0, -1);
        pendingRef.current = sentences[sentences.length - 1];
        for (const s of ready) enqueue(s);
      }
    },
    [enqueue],
  );

  const flush = useCallback(() => {
    const rest = pendingRef.current.trim();
    pendingRef.current = '';
    if (rest) enqueue(rest);
  }, [enqueue]);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    pendingRef.current = '';
    try {
      currentSourceRef.current?.stop();
    } catch {}
    currentSourceRef.current = null;
    queueRef.current = Promise.resolve();
    pendingJobsRef.current = 0;
    setIsSpeaking(false);
    onIdleRef.current?.();
  }, []);

  useEffect(
    () => () => {
      abortRef.current?.abort();
      try {
        ctxRef.current?.close();
      } catch {}
    },
    [],
  );

  return { isSpeaking, speak, feedToken, flush, stop };
}
