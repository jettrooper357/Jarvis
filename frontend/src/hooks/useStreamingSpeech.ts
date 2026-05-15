import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchSpeechHealth } from '../lib/api';

export type StreamingSpeechState = 'idle' | 'listening' | 'transcribing';

interface UseStreamingSpeechOptions {
  /** Called every time the server emits a `final` transcript (VAD silence). */
  onFinal?: (text: string) => void;
  /**
   * Called the instant VAD detects speech onset, before any transcription.
   * Used for barge-in: stop the assistant the moment the user starts talking.
   */
  onSpeechStart?: () => void;
  /** Optional language hint (e.g. 'en'). Omit for auto-detect. */
  language?: string;
}

function wsUrl(): string {
  const base =
    (typeof window !== 'undefined' && window.localStorage?.getItem('openjarvis-settings')
      ? (() => {
          try {
            const s = JSON.parse(window.localStorage.getItem('openjarvis-settings') || '{}');
            return s.apiUrl || '';
          } catch {
            return '';
          }
        })()
      : '') || (import.meta.env.VITE_API_URL as string | undefined) || '';
  if (base) return base.replace(/^http/, 'ws') + '/v1/speech/stream';
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}/v1/speech/stream`;
}

export function useStreamingSpeech(opts: UseStreamingSpeechOptions = {}) {
  const [state, setState] = useState<StreamingSpeechState>('idle');
  const [interim, setInterim] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [available, setAvailable] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const nodeRef = useRef<AudioWorkletNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const onFinalRef = useRef(opts.onFinal);
  onFinalRef.current = opts.onFinal;
  const onSpeechStartRef = useRef(opts.onSpeechStart);
  onSpeechStartRef.current = opts.onSpeechStart;

  useEffect(() => {
    fetchSpeechHealth()
      .then((h) => setAvailable(!!h.available))
      .catch(() => setAvailable(false));
  }, []);

  const cleanup = useCallback(() => {
    try {
      nodeRef.current?.disconnect();
    } catch {}
    nodeRef.current = null;
    try {
      ctxRef.current?.close();
    } catch {}
    ctxRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (wsRef.current) {
      try {
        if (wsRef.current.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({ type: 'flush' }));
        }
      } catch {}
      try {
        wsRef.current.close();
      } catch {}
      wsRef.current = null;
    }
  }, []);

  const start = useCallback(async () => {
    setError(null);
    setInterim('');

    if (!navigator.mediaDevices?.getUserMedia || typeof AudioWorkletNode === 'undefined') {
      setError('Real-time mic capture not supported in this browser');
      return;
    }

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch {
      setError('Microphone access denied');
      return;
    }
    streamRef.current = stream;

    const ctx = new AudioContext({ sampleRate: 16000 });
    ctxRef.current = ctx;
    try {
      await ctx.audioWorklet.addModule('/audio/pcm-worklet.js');
    } catch (err) {
      setError(`Failed to load audio worklet: ${(err as Error).message}`);
      cleanup();
      return;
    }

    let url = wsUrl();
    if (opts.language) url += `?language=${encodeURIComponent(opts.language)}`;
    const ws = new WebSocket(url);
    ws.binaryType = 'arraybuffer';
    wsRef.current = ws;

    // Attach message/close handlers *before* awaiting open. The backend can
    // accept the socket and then immediately emit an error + close (e.g.
    // streaming STT unsupported). If we attached these after the await, those
    // events would dispatch into the gap and be lost, leaving the UI stuck in
    // "listening" with no transcript and no error.
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === 'speech_start') {
          setState('listening');
          onSpeechStartRef.current?.();
        } else if (msg.type === 'partial' && msg.text) {
          setInterim(msg.text);
          setState('listening');
        } else if (msg.type === 'final' && msg.text) {
          setInterim('');
          onFinalRef.current?.(msg.text);
        } else if (msg.type === 'speech_end') {
          setState('transcribing');
        } else if (msg.type === 'error') {
          setError(msg.detail || 'Streaming error');
        }
      } catch {}
    };
    ws.onclose = () => {
      setState('idle');
    };

    let opened = false;
    await new Promise<void>((resolve, reject) => {
      ws.onopen = () => {
        opened = true;
        resolve();
      };
      ws.onerror = () => {
        if (!opened) reject(new Error('WebSocket connection failed'));
      };
    }).catch((err) => {
      setError(err.message);
    });
    if (!opened) {
      cleanup();
      return;
    }

    const source = ctx.createMediaStreamSource(stream);
    const node = new AudioWorkletNode(ctx, 'pcm-worklet');
    nodeRef.current = node;
    node.port.onmessage = (ev) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(ev.data as ArrayBuffer);
      }
    };
    source.connect(node);
    setState('listening');
  }, [cleanup, opts.language]);

  const stop = useCallback(() => {
    setState('idle');
    cleanup();
    setInterim('');
  }, [cleanup]);

  useEffect(() => () => cleanup(), [cleanup]);

  return {
    state,
    interim,
    error,
    available,
    start,
    stop,
    isListening: state === 'listening' || state === 'transcribing',
  };
}
