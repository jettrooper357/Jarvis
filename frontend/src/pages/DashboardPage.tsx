import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { EnergyDashboard } from '../components/Dashboard/EnergyDashboard';
import { CostComparison } from '../components/Dashboard/CostComparison';
import { TraceDebugger } from '../components/Dashboard/TraceDebugger';
import { JarvisCore } from '../components/Jarvis/JarvisCore';
import { JarvisStatusPanel } from '../components/Jarvis/JarvisStatusPanel';
import { HudFrame } from '../components/Jarvis/HudFrame';
import { useJarvisState } from '../hooks/useJarvisState';

const STATUS_META: Record<string, { word: string; color: string }> = {
  ONLINE: { word: 'OPTIMAL', color: 'var(--color-success)' },
  THINKING: { word: 'WORKING', color: 'var(--color-accent)' },
  OFFLINE: { word: 'OFFLINE', color: 'var(--color-error)' },
};

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

export function DashboardPage() {
  const navigate = useNavigate();
  const stamp = useUtcClock();
  const { state, label } = useJarvisState();
  const status = STATUS_META[label];

  return (
    <div className="flex-1 overflow-y-auto px-6 py-8">
      <div className="max-w-7xl mx-auto">
        <HudFrame className="rounded-xl p-6">
          <header className="mb-6 flex items-start justify-between gap-6">
            <div>
              <h1
                className="hud-title text-xl tracking-[0.18em]"
                style={{ color: 'var(--color-text)' }}
              >
                SYSTEM OVERVIEW
              </h1>
              <p
                className="text-sm mt-2 max-w-xl"
                style={{ color: 'var(--color-text-secondary)' }}
              >
                Live telemetry for the on-device inference engine — power draw,
                token throughput, and cost savings versus cloud APIs.
              </p>
            </div>
            <div className="text-right shrink-0">
              <div className="hud-mono text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                {stamp}
              </div>
              <div className="flex items-center gap-2 justify-end mt-1">
                <span className="hud-label" style={{ letterSpacing: '0.16em' }}>
                  SYSTEM STATUS
                </span>
                <span
                  className="w-2 h-2 rounded-full"
                  style={{ background: status.color, boxShadow: `0 0 8px 1px ${status.color}` }}
                />
                <span
                  className="hud-mono text-xs font-semibold"
                  style={{ color: status.color }}
                >
                  {status.word}
                </span>
              </div>
            </div>
          </header>

          <div className="grid grid-cols-1 lg:grid-cols-[1.1fr_1fr] gap-4">
            <EnergyDashboard />

            <div className="flex flex-col gap-4">
              <div className="hud-panel flex items-center justify-center py-6">
                <JarvisCore
                  state={state}
                  size={210}
                  onClick={() => navigate('/')}
                  label="Open chat with J.A.R.V.I.S."
                />
              </div>
              <JarvisStatusPanel />
              <CostComparison />
            </div>
          </div>

          <div className="mt-4">
            <TraceDebugger />
          </div>
        </HudFrame>
      </div>
    </div>
  );
}
