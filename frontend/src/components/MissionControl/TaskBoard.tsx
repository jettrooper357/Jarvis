import {
  COLUMNS,
  columnFor,
  statusColor,
  priorityColor,
  isOverdue,
  isDueToday,
  fmtDate,
  fmtAgo,
  type FlatTask,
  type ColumnKey,
} from './missionControlUtils';

function TaskCard({
  t,
  selected,
  onSelect,
}: {
  t: FlatTask;
  selected: boolean;
  onSelect: () => void;
}) {
  const overdue = isOverdue(t);
  const dueToday = isDueToday(t);
  const pct = Math.round(t.percent_complete || 0);
  const agent =
    t.linked_agents.find((a) => a.working) || t.linked_agents[0];
  const working = !!agent && !!agent.working;

  return (
    <button
      onClick={onSelect}
      className="hud-panel w-full text-left p-3 transition-colors"
      style={{
        borderColor: selected
          ? 'color-mix(in srgb, var(--color-accent) 55%, transparent)'
          : undefined,
        boxShadow: selected
          ? '0 0 16px -6px var(--color-accent-glow)'
          : undefined,
      }}
    >
      <div className="flex items-center justify-between gap-2 mb-1">
        <span
          className="hud-label truncate"
          style={{ fontSize: '0.6rem', letterSpacing: '0.1em' }}
        >
          {t.projectName}
        </span>
        <span
          className="text-[10px] px-1.5 py-0.5 rounded shrink-0"
          style={{
            color: priorityColor(t.priority),
            background: `color-mix(in srgb, ${priorityColor(
              t.priority,
            )} 14%, transparent)`,
          }}
        >
          {(t.priority || 'Medium').toUpperCase()}
        </span>
      </div>

      <div
        className="text-sm font-medium leading-snug mb-2 line-clamp-2"
        style={{ color: 'var(--color-text)' }}
      >
        {t.title}
      </div>

      <div className="flex items-center gap-2 mb-2">
        <span
          className="w-1.5 h-1.5 rounded-full shrink-0"
          style={{
            background: working
              ? 'var(--color-success)'
              : 'var(--color-text-tertiary)',
            boxShadow: working ? '0 0 6px 1px var(--color-success)' : 'none',
          }}
        />
        <span
          className="text-[11px] truncate flex-1"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          {agent ? agent.agent_name : t.assigned_to || 'Unassigned'}
        </span>
        <span
          className="text-[10px] px-1.5 py-0.5 rounded shrink-0"
          style={{
            color: statusColor(t.status),
            background: `color-mix(in srgb, ${statusColor(
              t.status,
            )} 16%, transparent)`,
          }}
        >
          {t.status || 'Backlog'}
        </span>
      </div>

      <div
        className="h-1.5 rounded-full w-full mb-2"
        style={{ background: 'var(--color-bg-tertiary)' }}
      >
        <div
          style={{
            width: `${pct}%`,
            height: '100%',
            borderRadius: 999,
            background:
              pct >= 100 ? 'var(--color-success)' : 'var(--color-accent)',
            transition: 'width 200ms ease',
          }}
        />
      </div>

      <div
        className="flex items-center justify-between text-[10px]"
        style={{ color: 'var(--color-text-tertiary)' }}
      >
        <span
          style={{
            color: overdue
              ? 'var(--color-error)'
              : dueToday
                ? 'var(--color-warning)'
                : 'var(--color-text-tertiary)',
          }}
        >
          {overdue ? '⚠ ' : ''}Due {fmtDate(t.due_date)}
        </span>
        <span className="hud-mono">{pct}%</span>
        <span>{fmtAgo(t.updated_at)}</span>
      </div>
    </button>
  );
}

export function TaskBoard({
  tasks,
  selectedId,
  onSelect,
}: {
  tasks: FlatTask[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const byColumn: Record<ColumnKey, FlatTask[]> = {
    backlog: [],
    in_progress: [],
    review: [],
    done: [],
  };
  for (const t of tasks) byColumn[columnFor(t.status)].push(t);

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
      {COLUMNS.map((col) => {
        const items = byColumn[col.key];
        return (
          <div
            key={col.key}
            className="hud-panel p-3 flex flex-col min-h-[60px]"
          >
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <span
                  className="w-2 h-2 rounded-full"
                  style={{
                    background: col.accent,
                    boxShadow: `0 0 6px 1px ${col.accent}`,
                  }}
                />
                <span
                  className="hud-label"
                  style={{ letterSpacing: '0.12em', color: 'var(--color-text)' }}
                >
                  {col.label}
                </span>
              </div>
              <span
                className="hud-mono text-xs px-1.5 py-0.5 rounded"
                style={{
                  background: 'var(--color-bg-tertiary)',
                  color: 'var(--color-text-tertiary)',
                }}
              >
                {items.length}
              </span>
            </div>
            <div className="flex flex-col gap-2 overflow-y-auto max-h-[560px] pr-0.5">
              {items.length === 0 ? (
                <div
                  className="text-[11px] py-6 text-center"
                  style={{ color: 'var(--color-text-tertiary)' }}
                >
                  Nothing here
                </div>
              ) : (
                items.map((t) => (
                  <TaskCard
                    key={t.id}
                    t={t}
                    selected={t.id === selectedId}
                    onSelect={() => onSelect(t.id)}
                  />
                ))
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
