import { useJarvisState } from '../../hooks/useJarvisState';
import { JarvisWaveform } from './JarvisWaveform';

const DOT_COLOR: Record<string, string> = {
  ONLINE: 'var(--color-success)',
  THINKING: 'var(--color-accent)',
  OFFLINE: 'var(--color-error)',
};

/**
 * The "J.A.R.V.I.S. ONLINE" presence card — status header with a live dot, a
 * reactive voice waveform, and a one-line situation report driven by real
 * engine / savings state.
 */
export function JarvisStatusPanel() {
  const { label, statusLine, greeting, state } = useJarvisState();
  const waveMode = state === 'offline' ? 'off' : state === 'thinking' ? 'active' : 'idle';

  return (
    <div className="hud-panel p-5">
      <div className="flex items-center gap-2 mb-4">
        <span
          className="w-2 h-2 rounded-full shrink-0"
          style={{
            background: DOT_COLOR[label],
            boxShadow: `0 0 8px 1px ${DOT_COLOR[label]}`,
          }}
        />
        <span
          className="hud-title text-sm tracking-[0.16em]"
          style={{ color: 'var(--color-text)' }}
        >
          J.A.R.V.I.S. <span style={{ color: DOT_COLOR[label] }}>{label}</span>
        </span>
      </div>

      <JarvisWaveform mode={waveMode} bars={40} height={44} className="mb-4" />

      <p className="text-sm leading-relaxed" style={{ color: 'var(--color-text-secondary)' }}>
        {statusLine}
      </p>
      <p className="text-xs mt-2 hud-mono" style={{ color: 'var(--color-text-tertiary)' }}>
        {greeting}
      </p>
    </div>
  );
}
