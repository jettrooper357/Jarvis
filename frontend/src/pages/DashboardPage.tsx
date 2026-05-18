import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { EnergyDashboard } from '../components/Dashboard/EnergyDashboard';
import { CostComparison } from '../components/Dashboard/CostComparison';
import { TraceDebugger } from '../components/Dashboard/TraceDebugger';
import { JarvisCore } from '../components/Jarvis/JarvisCore';
import { JarvisStatusPanel } from '../components/Jarvis/JarvisStatusPanel';
import { HudFrame } from '../components/Jarvis/HudFrame';
import { MissionControlPanel } from '../components/MissionControl/MissionControlPanel';
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
  const [showTelemetry, setShowTelemetry] = useState(false);

  return (
    <div className="flex-1 overflow-y-auto px-6 py-8">
      <div className="hud-backdrop" aria-hidden="true" />
      <div className="max-w-[1600px] mx-auto relative">
        <HudFrame className="rounded-xl p-6">
          <header className="mb-6 flex items-start justify-between gap-6">
            <div>
              <h1
                className="hud-title text-2xl tracking-[0.18em]"
                style={{ color: 'var(--color-text)' }}
              >
                MISSION CONTROL
              </h1>
              <p
                className="text-sm mt-2 max-w-xl"
                style={{ color: 'var(--color-text-secondary)' }}
              >
                Portfolio, Projects, Tasks, Agents, and Execution Status
              </p>
            </div>

            {/* Compact J.A.R.V.I.S. identity + system status */}
            <div className="flex items-center gap-4 shrink-0">
              <div className="text-right">
                <div
                  className="hud-mono text-xs"
                  style={{ color: 'var(--color-text-tertiary)' }}
                >
                  {stamp}
                </div>
                <div className="flex items-center gap-2 justify-end mt-1">
                  <span
                    className="hud-label"
                    style={{ letterSpacing: '0.16em' }}
                  >
                    J.A.R.V.I.S.
                  </span>
                  <span
                    className="w-2 h-2 rounded-full"
                    style={{
                      background: status.color,
                      boxShadow: `0 0 8px 1px ${status.color}`,
                    }}
                  />
                  <span
                    className="hud-mono text-xs font-semibold"
                    style={{ color: status.color }}
                  >
                    {status.word}
                  </span>
                </div>
              </div>
              <JarvisCore
                state={state}
                size={64}
                onClick={() => navigate('/')}
                label="Open chat with J.A.R.V.I.S."
              />
            </div>
          </header>

          {/* Primary operational focus: projects, tasks, agents */}
          <MissionControlPanel />

          {/* Secondary, collapsed by default: engine telemetry */}
          <div
            className="mt-8 pt-5"
            style={{ borderTop: '1px solid var(--color-border)' }}
          >
            <button
              onClick={() => setShowTelemetry((v) => !v)}
              className="flex items-center gap-2 cursor-pointer"
              style={{ color: 'var(--color-text-tertiary)' }}
            >
              {showTelemetry ? (
                <ChevronDown size={14} />
              ) : (
                <ChevronRight size={14} />
              )}
              <span className="hud-label" style={{ letterSpacing: '0.16em' }}>
                ENGINE TELEMETRY
              </span>
            </button>

            {showTelemetry && (
              <div className="mt-4">
                <div className="grid grid-cols-1 lg:grid-cols-[1.1fr_1fr] gap-4">
                  <EnergyDashboard />
                  <div className="flex flex-col gap-4">
                    <JarvisStatusPanel />
                    <CostComparison />
                  </div>
                </div>
                <div className="mt-4">
                  <TraceDebugger />
                </div>
              </div>
            )}
          </div>
        </HudFrame>
      </div>
    </div>
  );
}
