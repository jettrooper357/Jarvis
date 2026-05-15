interface JarvisWaveformProps {
  /** active = lively (speaking/thinking), idle = gentle, off = flat. */
  mode?: 'active' | 'idle' | 'off';
  bars?: number;
  className?: string;
  height?: number;
}

// Fixed per-bar delay/scale offsets so the waveform looks organic but stays
// deterministic across renders (no layout thrash from random() each paint).
const SEED = [0.15, 0.42, 0.7, 0.95, 0.6, 0.3, 0.5, 0.85, 0.4, 0.2, 0.65, 0.9, 0.55, 0.25, 0.75, 0.45];

/**
 * Decorative audio-style waveform. Pure CSS animation — `mode` only swaps the
 * data attribute the stylesheet keys off, so it's cheap to leave mounted.
 */
export function JarvisWaveform({ mode = 'idle', bars = 32, className, height = 40 }: JarvisWaveformProps) {
  return (
    <div
      className={`jarvis-wave${className ? ` ${className}` : ''}`}
      data-mode={mode}
      style={{ height }}
      aria-hidden="true"
    >
      {Array.from({ length: bars }).map((_, i) => {
        const s = SEED[i % SEED.length];
        return (
          <span
            key={i}
            style={{
              animationDelay: `${(s * 0.9).toFixed(2)}s`,
              animationDuration: `${(0.8 + s * 0.9).toFixed(2)}s`,
            }}
          />
        );
      })}
    </div>
  );
}
