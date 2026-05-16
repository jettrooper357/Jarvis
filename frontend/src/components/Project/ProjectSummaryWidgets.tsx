import type { ProjectDashboard } from '../../lib/projects-api';

function Kpi({
  label,
  value,
  accent,
}: {
  label: string;
  value: number | string;
  accent?: string;
}) {
  return (
    <div
      className="p-4 rounded-lg"
      style={{
        background: 'var(--color-bg-secondary)',
        border: '1px solid var(--color-border)',
      }}
    >
      <div
        className="text-2xl font-semibold"
        style={{ color: accent || 'var(--color-text)' }}
      >
        {value}
      </div>
      <div
        className="text-xs mt-1"
        style={{ color: 'var(--color-text-tertiary)' }}
      >
        {label}
      </div>
    </div>
  );
}

export function ProjectSummaryWidgets({ d }: { d: ProjectDashboard }) {
  const workload = Object.entries(d.workload_by_assignee || {}).sort(
    (a, b) => b[1] - a[1],
  );
  const maxLoad = workload.length ? workload[0][1] : 1;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Kpi label="Active projects" value={d.projects_active} />
        <Kpi
          label="At-risk projects"
          value={d.projects_at_risk}
          accent={d.projects_at_risk ? 'var(--color-error)' : undefined}
        />
        <Kpi label="Tasks in progress" value={d.tasks_in_progress} />
        <Kpi label="Avg completion" value={`${d.avg_completion}%`} />
        <Kpi
          label="Overdue tasks"
          value={d.tasks_overdue}
          accent={d.tasks_overdue ? 'var(--color-error)' : undefined}
        />
        <Kpi
          label="Blocked tasks"
          value={d.tasks_blocked}
          accent={d.tasks_blocked ? 'var(--color-warning)' : undefined}
        />
        <Kpi label="Tasks done" value={d.tasks_done} accent="var(--color-success)" />
        <Kpi label="Total projects" value={d.projects_total} />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div
          className="p-4 rounded-lg"
          style={{
            background: 'var(--color-bg-secondary)',
            border: '1px solid var(--color-border)',
          }}
        >
          <div
            className="text-sm font-semibold mb-3"
            style={{ color: 'var(--color-text)' }}
          >
            Workload by assignee
          </div>
          {workload.length === 0 ? (
            <div
              className="text-xs"
              style={{ color: 'var(--color-text-tertiary)' }}
            >
              No open tasks assigned.
            </div>
          ) : (
            <div className="space-y-2">
              {workload.map(([who, n]) => (
                <div key={who}>
                  <div
                    className="flex justify-between text-xs mb-0.5"
                    style={{ color: 'var(--color-text-secondary)' }}
                  >
                    <span>{who}</span>
                    <span>{n}</span>
                  </div>
                  <div
                    className="h-1.5 rounded-full"
                    style={{ background: 'var(--color-bg-tertiary)' }}
                  >
                    <div
                      style={{
                        width: `${(n / maxLoad) * 100}%`,
                        height: '100%',
                        background: 'var(--color-accent)',
                        borderRadius: 999,
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div
          className="p-4 rounded-lg"
          style={{
            background: 'var(--color-bg-secondary)',
            border: '1px solid var(--color-border)',
          }}
        >
          <div
            className="text-sm font-semibold mb-3"
            style={{ color: 'var(--color-text)' }}
          >
            AI signal
          </div>
          {d.at_risk_projects.length === 0 ? (
            <div
              className="text-xs"
              style={{ color: 'var(--color-success)' }}
            >
              No projects flagged at risk. Portfolio looks healthy.
            </div>
          ) : (
            <ul className="space-y-1.5">
              {d.at_risk_projects.map((p) => (
                <li
                  key={p.id}
                  className="text-xs"
                  style={{ color: 'var(--color-error)' }}
                >
                  ⚠ {p.name} — {p.status}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
