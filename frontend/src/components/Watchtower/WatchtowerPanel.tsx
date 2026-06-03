import { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  Bell,
  Bot,
  CheckCircle2,
  Clock,
  RadioTower,
  RefreshCw,
  ShieldAlert,
  WifiOff,
} from 'lucide-react';
import {
  escalateWatchtowerFinding,
  fetchWatchtowerFindings,
  fetchWatchtowerInternalRoutes,
  fetchWatchtowerStatus,
  resolveWatchtowerFinding,
  scanWatchtowerNow,
  snoozeWatchtowerFinding,
  type WatchtowerFinding,
  type WatchtowerInternalRoute,
  type WatchtowerPriority,
  type WatchtowerStatus,
} from '../../lib/api';

const priorityColor: Record<WatchtowerPriority, string> = {
  info: 'var(--color-text-tertiary)',
  low: 'var(--color-text-secondary)',
  normal: 'var(--color-accent)',
  high: 'var(--color-warning, #d97706)',
  urgent: '#fb7185',
  emergency: 'var(--color-error)',
};

type WatchtowerTab =
  | 'All'
  | 'User Alerts'
  | 'Internal Routes'
  | 'Waiting on Agents'
  | 'Waiting on Me'
  | 'Escalated'
  | 'Deferred';

const tabs: WatchtowerTab[] = [
  'All',
  'User Alerts',
  'Internal Routes',
  'Waiting on Agents',
  'Waiting on Me',
  'Escalated',
  'Deferred',
];

function formatTime(value: number | null | undefined) {
  if (!value) return 'Never';
  return new Date(value * 1000).toLocaleString();
}

function Badge({ children, tone }: { children: React.ReactNode; tone?: string }) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-[10px] font-semibold uppercase"
      style={{
        background: 'var(--color-bg-tertiary)',
        border: '1px solid var(--color-border-subtle)',
        color: tone || 'var(--color-text-secondary)',
      }}
    >
      {children}
    </span>
  );
}

function StatusPill({
  icon: Icon,
  label,
  active,
}: {
  icon: typeof RadioTower;
  label: string;
  active: boolean;
}) {
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded px-2 py-1 text-xs"
      style={{
        background: active ? 'var(--color-accent-subtle)' : 'var(--color-bg-tertiary)',
        color: active ? 'var(--color-accent)' : 'var(--color-text-tertiary)',
        border: '1px solid var(--color-border-subtle)',
      }}
    >
      <Icon size={12} />
      {label}
    </span>
  );
}

function findingMatchesTab(finding: WatchtowerFinding, tab: WatchtowerTab) {
  if (tab === 'All') return true;
  if (tab === 'User Alerts') {
    return ['approval_pending_too_long', 'task_waiting_user_input'].includes(finding.finding_type)
      || ['urgent', 'emergency'].includes(finding.priority);
  }
  if (tab === 'Waiting on Me') {
    return finding.finding_type.includes('approval') || finding.finding_type.includes('user_input');
  }
  if (tab === 'Escalated') return finding.status === 'escalated';
  if (tab === 'Deferred') return finding.status === 'snoozed' || finding.metadata_json?.deferred === true;
  return true;
}

export function WatchtowerPanel() {
  const [status, setStatus] = useState<WatchtowerStatus | null>(null);
  const [findings, setFindings] = useState<WatchtowerFinding[]>([]);
  const [routes, setRoutes] = useState<WatchtowerInternalRoute[]>([]);
  const [activeTab, setActiveTab] = useState<WatchtowerTab>('All');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    setError(null);
    const [nextStatus, nextFindings, nextRoutes] = await Promise.all([
      fetchWatchtowerStatus(),
      fetchWatchtowerFindings('active'),
      fetchWatchtowerInternalRoutes('sent'),
    ]);
    setStatus(nextStatus);
    setFindings(nextFindings);
    setRoutes(nextRoutes);
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    refresh()
      .catch((err) => {
        if (!cancelled) setError((err as Error).message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const visibleFindings = useMemo(() => {
    if (activeTab === 'Internal Routes' || activeTab === 'Waiting on Agents') return [];
    return findings.filter((finding) => findingMatchesTab(finding, activeTab));
  }, [activeTab, findings]);

  const visibleRoutes = useMemo(() => {
    if (activeTab === 'All') return routes.slice(0, 3);
    if (activeTab === 'Internal Routes' || activeTab === 'Waiting on Agents') return routes;
    return [];
  }, [activeTab, routes]);

  const runScan = async () => {
    setLoading(true);
    setError(null);
    try {
      await scanWatchtowerNow();
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const mutateFinding = async (
    action: () => Promise<void>,
  ) => {
    setError(null);
    try {
      await action();
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <section
      className="mt-6 rounded-lg p-4"
      data-testid="watchtower-panel"
      style={{
        background: 'var(--color-surface)',
        border: '1px solid var(--color-border)',
      }}
    >
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <RadioTower size={16} style={{ color: 'var(--color-accent)' }} />
            <h2
              className="hud-label text-sm"
              style={{ color: 'var(--color-text)', letterSpacing: '0.16em' }}
            >
              WATCHTOWER
            </h2>
          </div>
          <p className="mt-1 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
            Proactive monitoring routed through the Chief Orchestrator.
          </p>
        </div>
        <button
          type="button"
          onClick={runScan}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded px-3 py-1.5 text-xs font-medium disabled:opacity-50"
          style={{
            background: 'var(--color-bg-secondary)',
            border: '1px solid var(--color-border)',
            color: 'var(--color-text-secondary)',
          }}
        >
          <RefreshCw size={13} />
          Scan now
        </button>
      </header>

      <div className="mt-3 flex flex-wrap gap-2">
        <StatusPill icon={RadioTower} label={status?.running ? 'Active' : 'Inactive'} active={!!status?.running} />
        <StatusPill icon={Bot} label={status?.rules_fallback_active ? 'Rules Fallback' : 'Local AI'} active={!status?.rules_fallback_active} />
        <StatusPill icon={Clock} label={status?.dnd_active ? 'DND Active' : 'DND Clear'} active={!!status?.dnd_active} />
        <StatusPill icon={Bell} label={status?.telegram_enabled ? 'Telegram On' : 'Telegram Off'} active={!!status?.telegram_enabled} />
      </div>

      <div className="mt-3 flex flex-wrap gap-1">
        {tabs.map((tab) => (
          <button
            key={tab}
            type="button"
            onClick={() => setActiveTab(tab)}
            className="rounded px-2.5 py-1 text-xs font-medium"
            style={{
              background: activeTab === tab ? 'var(--color-accent-subtle)' : 'transparent',
              color: activeTab === tab ? 'var(--color-accent)' : 'var(--color-text-tertiary)',
              border: '1px solid var(--color-border-subtle)',
            }}
          >
            {tab}
          </button>
        ))}
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-[1.2fr_0.8fr]">
        <div className="space-y-2">
          {error && (
            <div className="rounded p-3 text-xs" style={{ color: 'var(--color-error)', background: 'var(--color-bg-tertiary)' }}>
              {error}
            </div>
          )}
          {loading && (
            <div className="rounded p-3 text-xs" style={{ color: 'var(--color-text-tertiary)', background: 'var(--color-bg-tertiary)' }}>
              Loading Watchtower state...
            </div>
          )}
          {!loading && visibleFindings.length === 0 && visibleRoutes.length === 0 && (
            <div className="rounded p-3 text-xs" style={{ color: 'var(--color-text-tertiary)', background: 'var(--color-bg-tertiary)' }}>
              No active Watchtower items for this view.
            </div>
          )}
          {visibleFindings.map((finding) => (
            <article
              key={finding.finding_id}
              className="rounded p-3"
              style={{
                background: 'var(--color-bg-secondary)',
                border: '1px solid var(--color-border-subtle)',
              }}
            >
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={priorityColor[finding.priority]}>{finding.priority}</Badge>
                <Badge>Chief Routed</Badge>
                {finding.last_notified_at ? <Badge tone="#fb7185">User Alert</Badge> : <Badge>Internal</Badge>}
                {finding.metadata_json?.rules_fallback_used ? <Badge>Rules Fallback</Badge> : <Badge>Local AI</Badge>}
              </div>
              <h3 className="mt-2 text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
                {finding.finding_type.replace(/_/g, ' ')}
              </h3>
              <p className="mt-1 text-xs leading-relaxed" style={{ color: 'var(--color-text-secondary)' }}>
                {finding.reason}
              </p>
              <p className="mt-1 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                {finding.recommended_action}
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => mutateFinding(() => resolveWatchtowerFinding(finding.finding_id))}
                  className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs"
                  style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text-secondary)' }}
                >
                  <CheckCircle2 size={12} />
                  Resolve
                </button>
                <button
                  type="button"
                  onClick={() => mutateFinding(() => snoozeWatchtowerFinding(finding.finding_id))}
                  className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs"
                  style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text-secondary)' }}
                >
                  <Clock size={12} />
                  Snooze
                </button>
                <button
                  type="button"
                  onClick={() => mutateFinding(() => escalateWatchtowerFinding(finding.finding_id))}
                  className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs"
                  style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-error)' }}
                >
                  <ShieldAlert size={12} />
                  Escalate
                </button>
              </div>
            </article>
          ))}

          {visibleRoutes.map((route) => (
            <article
              key={route.route_id}
              className="rounded p-3"
              style={{
                background: 'var(--color-bg-secondary)',
                border: '1px solid var(--color-border-subtle)',
              }}
            >
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={priorityColor[route.priority]}>{route.priority}</Badge>
                <Badge>Watchtower-triggered</Badge>
                <Badge>Waiting Response</Badge>
              </div>
              <h3 className="mt-2 text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
                {route.message_type.replace(/_/g, ' ')}
              </h3>
              <p className="mt-1 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                {route.from_agent_id} to {route.to_agent_id}
              </p>
              <p className="mt-1 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                Response due: {formatTime(route.response_due_at)}
              </p>
            </article>
          ))}
        </div>

        <aside
          className="rounded p-3 text-xs"
          style={{
            background: 'var(--color-bg-secondary)',
            border: '1px solid var(--color-border-subtle)',
            color: 'var(--color-text-secondary)',
          }}
        >
          <div className="flex items-center gap-2 font-semibold" style={{ color: 'var(--color-text)' }}>
            {status?.running ? <AlertTriangle size={14} /> : <WifiOff size={14} />}
            Current scan state
          </div>
          <dl className="mt-3 space-y-2">
            <div className="flex justify-between gap-3">
              <dt>Active findings</dt>
              <dd>{status?.active_findings ?? findings.length}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt>Internal routes</dt>
              <dd>{status?.pending_internal_routes ?? routes.length}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt>Last scan</dt>
              <dd className="text-right">{formatTime(status?.last_scan_at)}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt>AI status</dt>
              <dd className="text-right">{status?.local_ai_status || 'unknown'}</dd>
            </div>
          </dl>
        </aside>
      </div>
    </section>
  );
}
