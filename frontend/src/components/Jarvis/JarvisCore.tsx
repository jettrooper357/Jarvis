import type { JarvisState } from '../../hooks/useJarvisState';

interface JarvisCoreProps {
  state: JarvisState;
  /** Diameter in px. */
  size?: number;
  /** When provided the orb becomes an interactive button. */
  onClick?: () => void;
  /** Accessible label / tooltip for the button form. */
  label?: string;
  className?: string;
}

function Rings() {
  return (
    <>
      <span className="jarvis-ring jarvis-ring--1" aria-hidden="true" />
      <span className="jarvis-ring jarvis-ring--2" aria-hidden="true" />
      <span className="jarvis-ring jarvis-ring--3" aria-hidden="true" />
      <span className="jarvis-core-dot" aria-hidden="true" />
    </>
  );
}

/**
 * The animated J.A.R.V.I.S. "arc reactor" — concentric counter-rotating rings
 * around a pulsing core. Pulse speed and colour are driven by `state`
 * (idle / thinking / offline) via CSS custom properties; continuous motion is
 * CSS-only so it costs nothing on the JS thread.
 */
export function JarvisCore({ state, size = 220, onClick, label, className }: JarvisCoreProps) {
  const style = { width: size, height: size } as const;
  const cls = `jarvis-core${className ? ` ${className}` : ''}`;

  if (onClick) {
    return (
      <button
        type="button"
        className={cls}
        data-state={state}
        style={style}
        onClick={onClick}
        aria-label={label ?? 'Open chat with J.A.R.V.I.S.'}
        title={label ?? 'Open chat'}
      >
        <Rings />
      </button>
    );
  }

  return (
    <div className={cls} data-state={state} style={style} role="img" aria-label={label ?? 'J.A.R.V.I.S. core'}>
      <Rings />
    </div>
  );
}
