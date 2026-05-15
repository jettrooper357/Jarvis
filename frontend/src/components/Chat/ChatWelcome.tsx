import { useEffect, useState } from 'react';
import { ScanSearch, GitCompareArrows, FileText, Rocket, Activity, ChevronRight } from 'lucide-react';
import { JarvisCore } from '../Jarvis/JarvisCore';
import { useJarvisState } from '../../hooks/useJarvisState';

const STATUS_COLOR: Record<string, string> = {
  ONLINE: 'var(--color-success)',
  THINKING: 'var(--color-accent)',
  OFFLINE: 'var(--color-error)',
};

const ACTIONS = [
  { icon: ScanSearch, title: 'Analyze', sub: 'Run system analysis', prompt: 'Run a full system analysis and summarize the health of my setup.' },
  { icon: GitCompareArrows, title: 'Compare', sub: 'Cost & energy', prompt: 'Compare my local inference cost and energy use against the major cloud APIs.' },
  { icon: FileText, title: 'Report', sub: 'Generate insights', prompt: 'Generate an insights report from my recent activity and connected data sources.' },
  { icon: Rocket, title: 'Optimize', sub: 'Find savings', prompt: 'Suggest ways to lower my cost and energy use without sacrificing answer quality.' },
  { icon: Activity, title: 'Monitor', sub: 'Live telemetry', prompt: 'Show me live telemetry: current power draw, token throughput, and recent traces.' },
];

const SUGGESTED = [
  "Show me today's energy consumption trends",
  'Compare local vs GPT-5.3 costs',
  'What were the top 5 token usage spikes?',
  'Optimize for lower cost without sacrificing performance',
];

function sendPrompt(text: string) {
  window.dispatchEvent(new CustomEvent('jarvis-send', { detail: text }));
}

function useUtcClock() {
  const [stamp, setStamp] = useState(() => new Date().toISOString().replace('T', ' ').slice(0, 19) + ' UTC');
  useEffect(() => {
    const id = setInterval(
      () => setStamp(new Date().toISOString().replace('T', ' ').slice(0, 19) + ' UTC'),
      1000,
    );
    return () => clearInterval(id);
  }, []);
  return stamp;
}

/**
 * Frozen chat header: status line, the J.A.R.V.I.S. orb, greeting, and the
 * quick-action tiles. Rendered as a non-scrolling block in ChatArea so the
 * conversation (or suggested prompts) scrolls underneath it.
 */
export function ChatHero() {
  const { state, label, greeting } = useJarvisState();
  const stamp = useUtcClock();

  return (
    <div
      className="shrink-0 relative z-[1]"
      style={{
        borderBottom: '1px solid color-mix(in srgb, var(--color-accent) 12%, transparent)',
        boxShadow: '0 12px 24px -18px rgba(0,0,0,0.6)',
      }}
    >
      <div className="max-w-3xl mx-auto px-6 pt-4 pb-6">
        {/* Status row */}
        <div className="flex items-start justify-between mb-5">
          <div>
            <h1 className="hud-title text-xl tracking-[0.16em]" style={{ color: 'var(--color-text)' }}>
              J.A.R.V.I.S. <span style={{ color: STATUS_COLOR[label] }}>{label}</span>
            </h1>
            <p className="text-sm mt-1" style={{ color: 'var(--color-text-secondary)' }}>
              Your AI assistant is at your service.
            </p>
          </div>
          <div className="hud-mono text-xs pt-1" style={{ color: 'var(--color-text-tertiary)' }}>
            {stamp}
          </div>
        </div>

        {/* Hero orb + greeting */}
        <div className="flex flex-col items-center text-center">
          <JarvisCore state={state} size={148} />
          <h2 className="text-2xl font-semibold mt-6" style={{ color: 'var(--color-text)' }}>
            {greeting}
          </h2>
          <p className="text-sm mt-1.5" style={{ color: 'var(--color-text-secondary)' }}>
            How can I help you today?
          </p>
        </div>

        {/* Action tiles */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 mt-7">
          {ACTIONS.map((a) => {
            const Icon = a.icon;
            return (
              <button
                key={a.title}
                onClick={() => sendPrompt(a.prompt)}
                className="hud-panel flex flex-col items-center text-center gap-1.5 px-3 py-4 cursor-pointer"
                style={{ color: 'var(--color-text)' }}
              >
                <Icon size={20} style={{ color: 'var(--color-accent)' }} />
                <span className="text-sm font-medium mt-1">{a.title}</span>
                <span className="text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>
                  {a.sub}
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/**
 * Scrollable companion to ChatHero — the suggested-prompt list shown only
 * while the conversation is empty.
 */
export function SuggestedPrompts() {
  return (
    <div className="max-w-3xl mx-auto px-6 pt-8 pb-10">
      <h3 className="hud-label mb-3" style={{ letterSpacing: '0.18em' }}>
        SUGGESTED PROMPTS
      </h3>
      <div className="flex flex-col gap-2">
        {SUGGESTED.map((p) => (
          <button
            key={p}
            onClick={() => sendPrompt(p)}
            className="hud-panel flex items-center justify-between gap-3 px-4 py-3 text-left cursor-pointer"
          >
            <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
              {p}
            </span>
            <ChevronRight size={16} style={{ color: 'var(--color-accent)' }} className="shrink-0" />
          </button>
        ))}
      </div>
    </div>
  );
}
