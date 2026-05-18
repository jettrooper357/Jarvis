import type { MissionControlAgent } from '../../lib/api';
import { fmtAgo, type FlatTask } from './missionControlUtils';

const TIER_LABEL: Record<MissionControlAgent['role_tier'], string> = {
  manager: 'PM',
  worker: 'Worker',
  qa: 'QA',
};

export function AgentRail({
  agents,
  flat,
}: {
  agents: MissionControlAgent[];
  flat: FlatTask[];
}) {
  // Title for a task id + per-agent queue counts (active/pending links).
  const titleById = new Map(flat.map((t) => [t.id, t.title]));
  const queue = new Map<string, number>();
  for (const t of flat) {
    for (const la of t.linked_agents) {
      if (
        la.agent_task_status === 'pending' ||
        la.agent_task_status === 'active'
      ) {
        queue.set(la.agent_id, (queue.get(la.agent_id) || 0) + 1);
      }
    }
  }

  const working = agents.filter((a) => a.working);
  const idle = agents.filter((a) => !a.working);
  const ordered = [...working, ...idle];

  return (
    <div className="hud-panel p-3">
      <div className="flex items-center justify-between mb-3">
        <span
          className="hud-label"
          style={{ letterSpacing: '0.12em', color: 'var(--color-text)' }}
        >
          AGENTS &amp; STATUS
        </span>
        <span
          className="text-[10px]"
          style={{ color: 'var(--color-text-tertiary)' }}
        >
          {working.length} active · {idle.length} idle
        </span>
      </div>

      {ordered.length === 0 ? (
        <div
          className="text-[11px] py-3"
          style={{ color: 'var(--color-text-tertiary)' }}
        >
          No managed agents.
        </div>
      ) : (
        <div className="space-y-2 max-h-[420px] overflow-y-auto pr-0.5">
          {ordered.map((a) => {
            const assignment = a.linked_project_task_id
              ? titleById.get(a.linked_project_task_id) || 'Linked task'
              : 'Unassigned';
            return (
              <div
                key={a.id}
                className="rounded-lg p-2"
                style={{
                  background: 'var(--color-bg-secondary)',
                  border: '1px solid var(--color-border)',
                }}
              >
                <div className="flex items-center gap-2">
                  <span
                    className="w-1.5 h-1.5 rounded-full shrink-0"
                    style={{
                      background: a.working
                        ? 'var(--color-success)'
                        : a.stale
                          ? 'var(--color-warning)'
                          : 'var(--color-text-tertiary)',
                      boxShadow: a.working
                        ? '0 0 6px 1px var(--color-success)'
                        : 'none',
                    }}
                  />
                  <span
                    className="text-xs font-medium truncate flex-1"
                    style={{ color: 'var(--color-text)' }}
                  >
                    {a.name}
                  </span>
                  <span
                    className="text-[10px] px-1.5 py-0.5 rounded shrink-0"
                    style={{
                      background: 'var(--color-bg-tertiary)',
                      color: 'var(--color-text-tertiary)',
                    }}
                  >
                    {a.org_role || TIER_LABEL[a.role_tier]}
                  </span>
                </div>
                <div
                  className="text-[10px] mt-1 truncate"
                  style={{ color: 'var(--color-text-secondary)' }}
                  title={assignment}
                >
                  ▸ {assignment}
                </div>
                <div
                  className="flex items-center justify-between text-[10px] mt-1"
                  style={{ color: 'var(--color-text-tertiary)' }}
                >
                  <span
                    style={{
                      color: a.working
                        ? 'var(--color-accent)'
                        : a.stale
                          ? 'var(--color-warning)'
                          : 'var(--color-text-tertiary)',
                    }}
                  >
                    {a.working
                      ? a.current_activity || 'working…'
                      : a.stale
                        ? 'stale — no heartbeat'
                        : a.status === 'running'
                          ? 'idle'
                          : a.status || 'idle'}
                  </span>
                  <span>queue {queue.get(a.id) || 0}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
