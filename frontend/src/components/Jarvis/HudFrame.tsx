import type { ReactNode } from 'react';

interface HudFrameProps {
  children: ReactNode;
  className?: string;
}

/**
 * Wraps content with the four animated HUD corner brackets used across the
 * J.A.R.V.I.S. surfaces. The wrapper itself is layout-neutral (display:contents
 * would drop the positioning context, so it's a relative block instead).
 */
export function HudFrame({ children, className }: HudFrameProps) {
  return (
    <div className={`hud-frame${className ? ` ${className}` : ''}`}>
      <span className="hud-corner hud-corner--tl" aria-hidden="true" />
      <span className="hud-corner hud-corner--tr" aria-hidden="true" />
      <span className="hud-corner hud-corner--bl" aria-hidden="true" />
      <span className="hud-corner hud-corner--br" aria-hidden="true" />
      {children}
    </div>
  );
}
