import type { TaskStatus, TaskPriority, ProjectStatus, Task } from '../../lib/projects-api';

export const PROJECT_STATUSES: ProjectStatus[] = [
  'Planning',
  'Active',
  'At Risk',
  'Delayed',
  'Complete',
];

export const TASK_STATUSES: TaskStatus[] = [
  'Backlog',
  'Ready',
  'In Progress',
  'Blocked',
  'Review',
  'Done',
  'Cancelled',
];

export const TASK_PRIORITIES: TaskPriority[] = [
  'Low',
  'Medium',
  'High',
  'Critical',
];

export const TASK_TYPES = ['Feature', 'Bug', 'Improvement', 'Research'];

export function statusColor(status: string): string {
  switch (status) {
    case 'Active':
    case 'In Progress':
    case 'Ready':
      return 'var(--color-accent)';
    case 'Complete':
    case 'Done':
      return 'var(--color-success)';
    case 'At Risk':
    case 'Blocked':
      return 'var(--color-error)';
    case 'Delayed':
    case 'Review':
      return 'var(--color-warning)';
    case 'Cancelled':
      return 'var(--color-text-tertiary)';
    default:
      return 'var(--color-text-secondary)';
  }
}

export function priorityColor(priority: string): string {
  switch (priority) {
    case 'Critical':
      return 'var(--color-error)';
    case 'High':
      return 'var(--color-warning)';
    case 'Medium':
      return 'var(--color-accent)';
    default:
      return 'var(--color-text-tertiary)';
  }
}

export function isOverdue(t: Task): boolean {
  if (!t.due_date || t.status === 'Done' || t.status === 'Cancelled') {
    return false;
  }
  const d = new Date(t.due_date);
  return !isNaN(d.getTime()) && d.getTime() < Date.now();
}

export function fmtDate(d: string | null): string {
  if (!d) return '—';
  const dt = new Date(d);
  if (isNaN(dt.getTime())) return d;
  return dt.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

export function fmtDateTime(d: string | null): string {
  if (!d) return 'Now';
  const dt = new Date(d);
  if (isNaN(dt.getTime())) return d;
  return dt.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

/** Build a parent→children map and return root tasks in sort order. */
export function buildTaskTree(tasks: Task[]): {
  roots: Task[];
  childrenOf: (id: string) => Task[];
} {
  const byParent = new Map<string | null, Task[]>();
  for (const t of tasks) {
    const key = t.parent_task_id || null;
    if (!byParent.has(key)) byParent.set(key, []);
    byParent.get(key)!.push(t);
  }
  return {
    roots: byParent.get(null) || [],
    childrenOf: (id: string) => byParent.get(id) || [],
  };
}
