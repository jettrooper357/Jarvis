import type {
  MissionControlData,
  MissionControlProject,
  MissionControlTask,
} from '../../lib/api';

/** A task flattened out of the project tree, carrying its project context. */
export interface FlatTask extends MissionControlTask {
  projectId: string;
  projectName: string;
}

export type ColumnKey = 'backlog' | 'in_progress' | 'review' | 'done';

export const COLUMNS: { key: ColumnKey; label: string; accent: string }[] = [
  { key: 'backlog', label: 'Backlog', accent: 'var(--color-text-tertiary)' },
  { key: 'in_progress', label: 'In Progress', accent: 'var(--color-accent)' },
  {
    key: 'review',
    label: 'Blocked / Needs Review',
    accent: 'var(--color-error)',
  },
  { key: 'done', label: 'Completed', accent: 'var(--color-success)' },
];

const _REVIEW = new Set([
  'blocked',
  'needs review',
  'in review',
  'review',
  'qa',
]);
const _DONE = new Set(['done', 'completed', 'cancelled', 'closed']);

export function columnFor(status: string): ColumnKey {
  const s = (status || '').trim().toLowerCase();
  if (_DONE.has(s)) return 'done';
  if (_REVIEW.has(s)) return 'review';
  if (s === 'in progress' || s === 'active' || s === 'doing')
    return 'in_progress';
  return 'backlog';
}

/** Colour token for a task/project status badge. */
export function statusColor(status: string): string {
  const s = (status || '').trim().toLowerCase();
  if (_DONE.has(s)) return 'var(--color-success)';
  if (s === 'blocked' || s === 'cancelled') return 'var(--color-error)';
  if (_REVIEW.has(s)) return 'var(--color-warning)';
  if (s === 'in progress' || s === 'active') return 'var(--color-accent)';
  if (s === 'at risk' || s === 'delayed') return 'var(--color-error)';
  return 'var(--color-text-tertiary)';
}

export function priorityColor(priority?: string): string {
  const p = (priority || '').trim().toLowerCase();
  if (p === 'critical' || p === 'urgent' || p === 'high')
    return 'var(--color-error)';
  if (p === 'medium') return 'var(--color-warning)';
  return 'var(--color-text-tertiary)';
}

function _parseDue(due?: string | null): Date | null {
  if (!due) return null;
  const d = new Date(String(due).replace(' ', 'T'));
  return isNaN(d.getTime()) ? null : d;
}

export function isOverdue(t: { due_date?: string | null; status: string }): boolean {
  const d = _parseDue(t.due_date);
  if (!d) return false;
  if (columnFor(t.status) === 'done') return false;
  return d.getTime() < Date.now();
}

export function isDueToday(t: {
  due_date?: string | null;
  status: string;
}): boolean {
  const d = _parseDue(t.due_date);
  if (!d) return false;
  if (columnFor(t.status) === 'done') return false;
  const now = new Date();
  return (
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  );
}

export function fmtDate(due?: string | null): string {
  const d = _parseDue(due);
  if (!d) return '—';
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

export function fmtAgo(ts?: number): string {
  if (!ts) return '';
  const secs = Math.max(0, Date.now() / 1000 - ts);
  if (secs < 60) return 'just now';
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}

/** Depth-first flatten of every task + subtask with project context. */
export function flattenTasks(projects: MissionControlProject[]): FlatTask[] {
  const out: FlatTask[] = [];
  const walk = (p: MissionControlProject, t: MissionControlTask) => {
    out.push({ ...t, projectId: p.id, projectName: p.name });
    t.subtasks?.forEach((st) => walk(p, st));
  };
  projects.forEach((p) => p.tasks?.forEach((t) => walk(p, t)));
  return out;
}

export interface DerivedKpis {
  activeProjects: number;
  openTasks: number;
  inProgress: number;
  blocked: number;
  dueToday: number;
  overdue: number;
  activeAgents: number;
}

export function deriveKpis(
  data: MissionControlData,
  flat: FlatTask[],
  projects: MissionControlProject[] = data.projects,
  agents = data.agents,
): DerivedKpis {
  const openTasks = flat.filter((t) => columnFor(t.status) !== 'done').length;
  const dueToday = flat.filter(isDueToday).length;
  return {
    activeProjects: projects.filter((p) =>
      ['active', 'planning'].includes((p.status || '').trim().toLowerCase()),
    ).length,
    openTasks,
    inProgress: flat.filter((t) => columnFor(t.status) === 'in_progress').length,
    blocked: flat.filter((t) => columnFor(t.status) === 'review').length,
    dueToday,
    overdue: flat.filter(isOverdue).length,
    activeAgents: agents.filter((a) => a.working).length,
  };
}

export interface ProjectStats {
  id: string;
  name: string;
  status: string;
  progress: number;
  openTasks: number;
  inProgress: number;
  blocked: number;
  overdue: number;
  activeAgents: number;
}

export function deriveProjectStats(
  projects: MissionControlProject[],
  agents = [] as MissionControlData['agents'],
): ProjectStats[] {
  const workingAgentIds = new Set(
    agents.filter((agent) => agent.working).map((agent) => agent.id),
  );
  return projects.map((project) => {
    const tasks = flattenTasks([project]);
    const projectAgentIds = new Set<string>();
    for (const task of tasks) {
      for (const linked of task.linked_agents) {
        projectAgentIds.add(linked.agent_id);
      }
    }
    return {
      id: project.id,
      name: project.name,
      status: project.status,
      progress: Math.round(project.progress || 0),
      openTasks: tasks.filter((task) => columnFor(task.status) !== 'done').length,
      inProgress: tasks.filter((task) => columnFor(task.status) === 'in_progress').length,
      blocked: tasks.filter((task) => columnFor(task.status) === 'review').length,
      overdue: tasks.filter(isOverdue).length,
      activeAgents: [...projectAgentIds].filter((id) =>
        workingAgentIds.has(id),
      ).length,
    };
  });
}
