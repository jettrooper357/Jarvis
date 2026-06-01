import { useEffect, useMemo, useState } from 'react';
import {
  Activity,
  BookOpen,
  BriefcaseBusiness,
  CalendarClock,
  CalendarDays,
  CheckCircle2,
  Church,
  CircleAlert,
  GraduationCap,
  HeartPulse,
  Home,
  Landmark,
  Loader2,
  RefreshCw,
  Target,
  Users,
  WalletCards,
} from 'lucide-react';
import {
  fetchAgentJobs,
  fetchManagedAgents,
  fetchMissionControl,
  type AgentJob,
  type ManagedAgent,
  type MissionControlData,
} from '../lib/api';
import { HudFrame } from '../components/Jarvis/HudFrame';
import { priorityColor, statusColor } from '../components/MissionControl/missionControlUtils';
import {
  buildPlanningJobs,
  buildPlanningTasks,
  itemHorizon,
  isHabitOrRoutine,
  LIFE_DOMAINS,
  sortPlanningItems,
  summarizePlanning,
  type LifeDomain,
  type PlanningHorizon,
  type PlanningItem,
} from './personalPlanningUtils';

const HORIZONS: { id: PlanningHorizon | 'all'; label: string }[] = [
  { id: 'today', label: 'Today' },
  { id: 'week', label: 'This week' },
  { id: 'month', label: 'This month' },
  { id: 'long_term', label: 'Long-term goals' },
  { id: 'all', label: 'All' },
];

const DOMAIN_ICONS: Record<LifeDomain, typeof BriefcaseBusiness> = {
  work: BriefcaseBusiness,
  church: Church,
  family: Users,
  health: HeartPulse,
  finances: WalletCards,
  learning: GraduationCap,
  home: Home,
  goals: Target,
};

function fmtDate(date?: Date | null): string {
  if (!date) return 'Unscheduled';
  return date.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: date.getFullYear() === new Date().getFullYear() ? undefined : 'numeric',
  });
}

function horizonLabel(horizon: PlanningHorizon): string {
  if (horizon === 'today') return 'Today';
  if (horizon === 'week') return 'This week';
  if (horizon === 'month') return 'This month';
  return 'Long-term';
}

function domainLabel(domain: LifeDomain): string {
  return LIFE_DOMAINS.find((entry) => entry.id === domain)?.label || domain;
}

function Metric({
  label,
  value,
  icon: Icon,
  accent,
}: {
  label: string;
  value: number;
  icon: typeof CalendarDays;
  accent: string;
}) {
  return (
    <div
      className="rounded-lg px-4 py-3 min-w-0"
      style={{
        background: 'var(--color-bg-secondary)',
        border: '1px solid var(--color-border)',
      }}
    >
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs hud-label" style={{ color: 'var(--color-text-tertiary)' }}>
          {label}
        </span>
        <Icon size={15} style={{ color: accent }} />
      </div>
      <div className="mt-2 text-2xl font-semibold" style={{ color: 'var(--color-text)' }}>
        {value}
      </div>
    </div>
  );
}

function FilterButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className="px-3 py-2 rounded-md text-sm transition-colors"
      style={{
        background: active ? 'var(--color-accent-subtle)' : 'transparent',
        color: active ? 'var(--color-text)' : 'var(--color-text-secondary)',
        border: `1px solid ${active ? 'color-mix(in srgb, var(--color-accent) 38%, transparent)' : 'var(--color-border)'}`,
      }}
    >
      {children}
    </button>
  );
}

function ItemRow({ item, now }: { item: PlanningItem; now: Date }) {
  const domain = domainLabel(item.domain);
  const DomainIcon = DOMAIN_ICONS[item.domain];
  const horizon = itemHorizon(item, now);
  const date = item.source === 'task' ? item.dueDate : item.nextRunAt;
  const status = item.status || 'unknown';
  return (
    <div
      className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_150px_150px_130px] gap-3 px-4 py-3"
      style={{ borderTop: '1px solid var(--color-border)' }}
    >
      <div className="min-w-0">
        <div className="flex items-center gap-2 min-w-0">
          <DomainIcon size={15} style={{ color: 'var(--color-accent)' }} />
          <span className="font-medium truncate" style={{ color: 'var(--color-text)' }}>
            {item.title}
          </span>
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-2 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
          <span>{domain}</span>
          <span aria-hidden="true">/</span>
          <span>{item.source === 'task' ? item.projectName : item.agentName}</span>
          {item.source === 'task' && item.linkedAgentNames.length > 0 && (
            <>
              <span aria-hidden="true">/</span>
              <span>{item.linkedAgentNames.join(', ')}</span>
            </>
          )}
        </div>
      </div>

      <div className="flex items-center xl:justify-start gap-2">
        <span
          className="w-2 h-2 rounded-full"
          style={{ background: statusColor(status) }}
        />
        <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
          {status}
        </span>
      </div>

      <div className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
        {horizonLabel(horizon)}
        <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
          {fmtDate(date)}
        </div>
      </div>

      <div className="flex items-center gap-2 xl:justify-end">
        {item.source === 'task' && item.priority && (
          <span
            className="text-xs px-2 py-1 rounded"
            style={{
              color: priorityColor(item.priority),
              border: '1px solid var(--color-border)',
            }}
          >
            {item.priority}
          </span>
        )}
        {item.source === 'job' && (
          <span
            className="text-xs px-2 py-1 rounded"
            style={{
              color: 'var(--color-accent)',
              border: '1px solid var(--color-border)',
            }}
          >
            {item.jobType}
          </span>
        )}
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="px-4 py-10 text-center" style={{ color: 'var(--color-text-tertiary)' }}>
      <CheckCircle2 size={24} className="mx-auto mb-3" style={{ color: 'var(--color-success)' }} />
      No matching planning items.
    </div>
  );
}

export function PersonalPlanningPage() {
  const [missionControl, setMissionControl] = useState<MissionControlData | null>(null);
  const [agents, setAgents] = useState<ManagedAgent[]>([]);
  const [jobsByAgent, setJobsByAgent] = useState<Record<string, AgentJob[]>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [horizon, setHorizon] = useState<PlanningHorizon | 'all'>('today');
  const [domain, setDomain] = useState<LifeDomain | 'all'>('all');
  const now = useMemo(() => new Date(), [missionControl, jobsByAgent]);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [mission, managedAgents] = await Promise.all([
        fetchMissionControl(),
        fetchManagedAgents(),
      ]);
      const jobPairs = await Promise.all(
        managedAgents.map(async (agent) => {
          try {
            const jobs = await fetchAgentJobs(agent.id);
            return [agent.id, jobs] as const;
          } catch {
            return [agent.id, []] as const;
          }
        }),
      );
      setMissionControl(mission);
      setAgents(managedAgents);
      setJobsByAgent(Object.fromEntries(jobPairs));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load planning data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const tasks = useMemo(
    () => (missionControl ? buildPlanningTasks(missionControl) : []),
    [missionControl],
  );
  const jobs = useMemo(
    () => buildPlanningJobs(agents, jobsByAgent),
    [agents, jobsByAgent],
  );
  const summary = useMemo(
    () => summarizePlanning(tasks, jobs, now),
    [tasks, jobs, now],
  );
  const allItems = useMemo(() => sortPlanningItems([...tasks, ...jobs]), [tasks, jobs]);
  const filteredItems = useMemo(
    () =>
      allItems.filter((item) => {
        const horizonMatch = horizon === 'all' || itemHorizon(item, now) === horizon;
        const domainMatch = domain === 'all' || item.domain === domain;
        return horizonMatch && domainMatch;
      }),
    [allItems, horizon, domain, now],
  );
  const routines = useMemo(
    () => sortPlanningItems(allItems.filter(isHabitOrRoutine)).slice(0, 8),
    [allItems],
  );

  return (
    <div className="flex-1 overflow-y-auto px-6 py-8">
      <div className="max-w-[1600px] mx-auto">
        <HudFrame className="rounded-xl p-6">
          <header className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <h1 className="hud-title text-2xl tracking-[0.16em]" style={{ color: 'var(--color-text)' }}>
                PERSONAL PLANNING
              </h1>
              <p className="text-sm mt-2 max-w-2xl" style={{ color: 'var(--color-text-secondary)' }}>
                Life domains, routines, reminders, and goals derived from durable Jarvis tasks and agent jobs.
              </p>
            </div>
            <button
              onClick={load}
              disabled={loading}
              className="inline-flex items-center gap-2 px-3 py-2 rounded-md text-sm disabled:opacity-60"
              style={{
                color: 'var(--color-text)',
                background: 'var(--color-bg-secondary)',
                border: '1px solid var(--color-border)',
              }}
            >
              {loading ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />}
              Refresh
            </button>
          </header>

          {error && (
            <div
              className="mt-5 flex items-center gap-2 rounded-lg px-4 py-3 text-sm"
              style={{
                color: 'var(--color-error)',
                background: 'color-mix(in srgb, var(--color-error) 8%, transparent)',
                border: '1px solid color-mix(in srgb, var(--color-error) 22%, transparent)',
              }}
            >
              <CircleAlert size={16} />
              {error}
            </div>
          )}

          <section className="mt-6 grid grid-cols-2 lg:grid-cols-6 gap-3">
            <Metric label="Open tasks" value={summary.totalOpenTasks} icon={CheckCircle2} accent="var(--color-accent)" />
            <Metric label="Today" value={summary.dueToday} icon={CalendarDays} accent="var(--color-warning)" />
            <Metric label="This week" value={summary.dueThisWeek} icon={CalendarClock} accent="var(--color-accent)" />
            <Metric label="This month" value={summary.dueThisMonth} icon={Activity} accent="var(--color-success)" />
            <Metric label="Long-term" value={summary.longTerm} icon={Target} accent="var(--color-text-tertiary)" />
            <Metric label="Active jobs" value={summary.activeJobs} icon={RefreshCw} accent="var(--color-accent)" />
          </section>

          <section className="mt-6 grid grid-cols-1 xl:grid-cols-[280px_minmax(0,1fr)] gap-5">
            <aside className="space-y-5">
              <div>
                <div className="hud-label mb-2" style={{ color: 'var(--color-text-tertiary)' }}>
                  HORIZON
                </div>
                <div className="grid grid-cols-1 gap-2">
                  {HORIZONS.map((entry) => (
                    <FilterButton
                      key={entry.id}
                      active={horizon === entry.id}
                      onClick={() => setHorizon(entry.id)}
                    >
                      {entry.label}
                    </FilterButton>
                  ))}
                </div>
              </div>

              <div>
                <div className="hud-label mb-2" style={{ color: 'var(--color-text-tertiary)' }}>
                  LIFE DOMAINS
                </div>
                <div className="grid grid-cols-1 gap-2">
                  <FilterButton active={domain === 'all'} onClick={() => setDomain('all')}>
                    All domains
                  </FilterButton>
                  {LIFE_DOMAINS.map((entry) => {
                    const Icon = DOMAIN_ICONS[entry.id];
                    return (
                      <FilterButton
                        key={entry.id}
                        active={domain === entry.id}
                        onClick={() => setDomain(entry.id)}
                      >
                        <span className="inline-flex items-center gap-2">
                          <Icon size={14} />
                          {entry.label}
                        </span>
                      </FilterButton>
                    );
                  })}
                </div>
              </div>
            </aside>

            <div
              className="rounded-lg overflow-hidden"
              style={{
                background: 'var(--color-bg-secondary)',
                border: '1px solid var(--color-border)',
              }}
            >
              <div className="px-4 py-3 flex items-center justify-between gap-3">
                <div>
                  <div className="font-semibold" style={{ color: 'var(--color-text)' }}>
                    Planning Queue
                  </div>
                  <div className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>
                    {filteredItems.length} item{filteredItems.length === 1 ? '' : 's'} from tasks and jobs
                  </div>
                </div>
                {summary.blocked > 0 && (
                  <div className="inline-flex items-center gap-2 text-sm" style={{ color: 'var(--color-error)' }}>
                    <CircleAlert size={15} />
                    {summary.blocked} blocked
                  </div>
                )}
              </div>

              {loading ? (
                <div className="px-4 py-10 flex items-center justify-center gap-3" style={{ color: 'var(--color-text-secondary)' }}>
                  <Loader2 size={18} className="animate-spin" />
                  Loading planning data
                </div>
              ) : filteredItems.length === 0 ? (
                <EmptyState />
              ) : (
                filteredItems.map((item) => <ItemRow key={`${item.source}:${item.id}`} item={item} now={now} />)
              )}
            </div>
          </section>

          <section className="mt-5 grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_360px] gap-5">
            <div
              className="rounded-lg px-4 py-4"
              style={{
                background: 'var(--color-bg-secondary)',
                border: '1px solid var(--color-border)',
              }}
            >
              <div className="flex items-center gap-2 mb-3">
                <BookOpen size={16} style={{ color: 'var(--color-accent)' }} />
                <h2 className="font-semibold" style={{ color: 'var(--color-text)' }}>
                  Study / Knowledge Notebook
                </h2>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-sm">
                {[
                  ['Sermon research', 'church'],
                  ['Programming notes', 'learning'],
                  ['Evidence folders', 'goals'],
                ].map(([label, domainId]) => {
                  const count = allItems.filter((item) => item.domain === domainId).length;
                  return (
                    <div key={label} className="rounded-md p-3" style={{ border: '1px solid var(--color-border)' }}>
                      <div style={{ color: 'var(--color-text)' }}>{label}</div>
                      <div className="mt-1 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                        {count} related planning item{count === 1 ? '' : 's'}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            <div
              className="rounded-lg px-4 py-4"
              style={{
                background: 'var(--color-bg-secondary)',
                border: '1px solid var(--color-border)',
              }}
            >
              <div className="flex items-center gap-2 mb-3">
                <Landmark size={16} style={{ color: 'var(--color-accent)' }} />
                <h2 className="font-semibold" style={{ color: 'var(--color-text)' }}>
                  Habits / Routines
                </h2>
              </div>
              <div className="space-y-2">
                {routines.length === 0 ? (
                  <div className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
                    No recurring routines found yet.
                  </div>
                ) : (
                  routines.map((item) => (
                    <div key={`routine:${item.source}:${item.id}`} className="flex items-center justify-between gap-3 text-sm">
                      <span className="truncate" style={{ color: 'var(--color-text-secondary)' }}>
                        {item.title}
                      </span>
                      <span className="text-xs shrink-0" style={{ color: 'var(--color-text-tertiary)' }}>
                        {horizonLabel(itemHorizon(item, now))}
                      </span>
                    </div>
                  ))
                )}
              </div>
            </div>
          </section>
        </HudFrame>
      </div>
    </div>
  );
}
