import { useEffect, useRef, useState } from 'react';
import { useAppStore } from '../lib/store';
import { checkHealth } from '../lib/api';
import { resolveModelSelection } from '../lib/models';

export type JarvisState = 'offline' | 'idle' | 'thinking';

export interface JarvisStatus {
  state: JarvisState;
  /** Uppercase status word for the panel header. */
  label: 'OFFLINE' | 'ONLINE' | 'THINKING';
  /** Active model id (server-reported, else the user's selection). */
  model: string;
  totalTokens: number;
  totalCalls: number;
  /** Time-of-day greeting, personalised when a display name is known. */
  greeting: string;
  /** One-line status sentence for the J.A.R.V.I.S. panel. */
  statusLine: string;
}

function timeGreeting(name?: string): string {
  const h = new Date().getHours();
  const part = h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
  return name ? `${part}, ${name}.` : `${part}.`;
}

function formatCount(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return String(n);
}

/**
 * Derives the live J.A.R.V.I.S. presence (offline / idle / thinking) from the
 * inference engine's streaming state plus a lightweight health poll, and packs
 * the bits the orb and status panel need to render.
 */
export function useJarvisState(): JarvisStatus {
  const isStreaming = useAppStore((s) => s.streamState.isStreaming);
  const serverInfo = useAppStore((s) => s.serverInfo);
  const models = useAppStore((s) => s.models);
  const defaultModel = useAppStore((s) => s.settings.defaultModel);
  const savings = useAppStore((s) => s.savings);
  const selectedModel = useAppStore((s) => s.selectedModel);
  const displayName = useAppStore((s) => s.optInDisplayName);

  const [reachable, setReachable] = useState<boolean | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    const poll = () =>
      checkHealth()
        .then((ok) => {
          if (mounted.current) setReachable(ok);
        })
        .catch(() => {
          if (mounted.current) setReachable(false);
        });
    poll();
    const id = setInterval(poll, 15000);
    const onFocus = () => poll();
    window.addEventListener('focus', onFocus);
    return () => {
      mounted.current = false;
      clearInterval(id);
      window.removeEventListener('focus', onFocus);
    };
  }, []);

  const offline = reachable === false;
  const state: JarvisState = offline ? 'offline' : isStreaming ? 'thinking' : 'idle';
  const label = offline ? 'OFFLINE' : isStreaming ? 'THINKING' : 'ONLINE';

  const model = resolveModelSelection({
    selectedModel,
    defaultModel,
    serverModel: serverInfo?.model || '',
    models,
  }) || 'no model';
  const totalTokens = savings?.total_tokens ?? 0;
  const totalCalls = savings?.total_calls ?? 0;

  const firstName = displayName ? displayName.trim().split(/\s+/)[0] : undefined;

  let statusLine: string;
  if (offline) {
    statusLine = 'Connection lost — awaiting the inference engine.';
  } else if (isStreaming) {
    statusLine = `Working on it — ${model} is generating a response.`;
  } else if (totalTokens > 0) {
    statusLine = `${model} active · ${formatCount(totalTokens)} tokens served across ${totalCalls} request${totalCalls === 1 ? '' : 's'}.`;
  } else {
    statusLine = `${model} standing by. How can I assist you today?`;
  }

  return {
    state,
    label,
    model,
    totalTokens,
    totalCalls,
    greeting: timeGreeting(firstName),
    statusLine,
  };
}
