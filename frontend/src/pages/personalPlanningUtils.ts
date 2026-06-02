import type {
  AgentJob,
  ManagedAgent,
  MissionControlData,
} from '../lib/api';
import {
  columnFor,
  flattenTasks,
  type FlatTask,
} from '../components/MissionControl/missionControlUtils';

export type LifeDomain =
  | 'work'
  | 'church'
  | 'family'
  | 'health'
  | 'finances'
  | 'learning'
  | 'home'
  | 'goals';

export type PlanningHorizon = 'today' | 'week' | 'month' | 'long_term';

export interface DomainDefinition {
  id: LifeDomain;
  label: string;
  keywords: string[];
}

export const LIFE_DOMAINS: DomainDefinition[] = [
  {
    id: 'work',
    label: 'Work',
    keywords: ['work', 'client', 'meeting', 'project', 'review', 'deadline'],
  },
  {
    id: 'church',
    label: 'Church',
    keywords: ['church', 'sermon', 'bible', 'study', 'ministry', 'theology'],
  },
  {
    id: 'family',
    label: 'Family',
    keywords: ['family', 'kids', 'school', 'parent', 'spouse', 'homework'],
  },
  {
    id: 'health',
    label: 'Health',
    keywords: ['health', 'workout', 'exercise', 'wellness', 'doctor', 'appointment'],
  },
  {
    id: 'finances',
    label: 'Finances',
    keywords: ['finance', 'bill', 'budget', 'payment', 'tax', 'bank'],
  },
  {
    id: 'learning',
    label: 'Learning',
    keywords: ['learning', 'course', 'programming', 'notes', 'study', 'read'],
  },
  {
    id: 'home',
    label: 'Home',
    keywords: ['home', 'house', 'household', 'repair', 'shopping', 'chores'],
  },
  {
    id: 'goals',
    label: 'Personal goals',
    keywords: ['goal', 'habit', 'routine', 'personal', 'plan', 'milestone'],
  },
];

export interface PlanningTaskItem {
  id: string;
  title: string;
  status: string;
  priority?: string;
  dueDate?: Date | null;
  projectName: string;
  assignedTo?: string;
  domain: LifeDomain;
  source: 'task';
  linkedAgentNames: string[];
}

export interface PlanningJobItem {
  id: string;
  agentId: string;
  title: string;
  status: string;
  jobType: AgentJob['job_type'];
  nextRunAt?: Date | null;
  lastRunAt?: Date | null;
  agentName: string;
  domain: LifeDomain;
  source: 'job';
}

export type PlanningItem = PlanningTaskItem | PlanningJobItem;

export interface PlanningSummary {
  totalOpenTasks: number;
  dueToday: number;
  dueThisWeek: number;
  dueThisMonth: number;
  longTerm: number;
  activeJobs: number;
  blocked: number;
}

function parseDate(value?: string | number | null): Date | null {
  if (value == null || value === '') return null;
  const date =
    typeof value === 'number'
      ? new Date(value * 1000)
      : new Date(String(value).replace(' ', 'T'));
  return Number.isNaN(date.getTime()) ? null : date;
}

function startOfDay(date: Date): Date {
  const copy = new Date(date);
  copy.setHours(0, 0, 0, 0);
  return copy;
}

function endOfDay(date: Date): Date {
  const copy = new Date(date);
  copy.setHours(23, 59, 59, 999);
  return copy;
}

function addDays(date: Date, days: number): Date {
  const copy = new Date(date);
  copy.setDate(copy.getDate() + days);
  return copy;
}

function addMonths(date: Date, months: number): Date {
  const copy = new Date(date);
  copy.setMonth(copy.getMonth() + months);
  return copy;
}

export function inferDomain(text: string): LifeDomain {
  const haystack = text.toLowerCase();
  let best: { id: LifeDomain; score: number } = { id: 'goals', score: 0 };
  for (const domain of LIFE_DOMAINS) {
    const score = domain.keywords.reduce(
      (count, keyword) => count + (haystack.includes(keyword) ? 1 : 0),
      0,
    );
    if (score > best.score) best = { id: domain.id, score };
  }
  return best.id;
}

function textForTask(task: FlatTask): string {
  return [
    task.title,
    task.description,
    task.projectName,
    task.assigned_to,
    task.priority,
    task.linked_agents?.map((agent) => agent.agent_name).join(' '),
  ]
    .filter(Boolean)
    .join(' ');
}

function textForJob(job: AgentJob, agentName: string): string {
  return [
    job.name,
    job.description,
    job.prompt,
    job.job_type,
    agentName,
    Object.values(job.trigger || {}).join(' '),
  ]
    .filter(Boolean)
    .join(' ');
}

export function buildPlanningTasks(
  data: MissionControlData,
): PlanningTaskItem[] {
  return flattenTasks(data.projects)
    .filter((task) => columnFor(task.status) !== 'done')
    .map((task) => ({
      id: task.id,
      title: task.title,
      status: task.status,
      priority: task.priority,
      dueDate: parseDate(task.due_date),
      projectName: task.projectName,
      assignedTo: task.assigned_to,
      domain: inferDomain(textForTask(task)),
      source: 'task' as const,
      linkedAgentNames: (task.linked_agents || []).map(
        (agent) => agent.agent_name,
      ),
    }));
}

export function buildPlanningJobs(
  agents: ManagedAgent[],
  jobsByAgent: Record<string, AgentJob[]>,
): PlanningJobItem[] {
  const agentById = new Map(agents.map((agent) => [agent.id, agent.name]));
  return Object.entries(jobsByAgent).flatMap(([agentId, jobs]) => {
    const agentName = agentById.get(agentId) || 'Unassigned agent';
    return jobs.filter((job) => job.status !== 'completed').map((job) => ({
      id: job.id,
      agentId,
      title: job.name,
      status: job.status,
      jobType: job.job_type,
      nextRunAt: parseDate(job.next_run_at),
      lastRunAt: parseDate(job.last_run_at),
      agentName,
      domain: inferDomain(textForJob(job, agentName)),
      source: 'job' as const,
    }));
  });
}

export function horizonForDate(
  date: Date | null | undefined,
  now = new Date(),
): PlanningHorizon {
  if (!date) return 'long_term';
  const start = startOfDay(now);
  const todayEnd = endOfDay(now);
  const weekEnd = endOfDay(addDays(now, 7));
  const monthEnd = endOfDay(addMonths(now, 1));
  if (date < start) return 'today';
  if (date <= todayEnd) return 'today';
  if (date <= weekEnd) return 'week';
  if (date <= monthEnd) return 'month';
  return 'long_term';
}

export function itemHorizon(
  item: PlanningItem,
  now = new Date(),
): PlanningHorizon {
  return item.source === 'task'
    ? horizonForDate(item.dueDate, now)
    : horizonForDate(item.nextRunAt, now);
}

export function isHabitOrRoutine(item: PlanningItem): boolean {
  const text =
    item.source === 'task'
      ? `${item.title} ${item.projectName} ${item.priority || ''}`
      : `${item.title} ${item.jobType} ${item.agentName}`;
  const normalized = text.toLowerCase();
  return (
    normalized.includes('habit') ||
    normalized.includes('routine') ||
    normalized.includes('workout') ||
    normalized.includes('bible study') ||
    normalized.includes('sermon prep') ||
    normalized.includes('project review') ||
    normalized.includes('household') ||
    (item.source === 'job' &&
      ['cron', 'interval', 'if_this_then_that'].includes(item.jobType))
  );
}

export function sortPlanningItems(items: PlanningItem[]): PlanningItem[] {
  return [...items].sort((a, b) => {
    const aDate =
      a.source === 'task' ? a.dueDate?.getTime() : a.nextRunAt?.getTime();
    const bDate =
      b.source === 'task' ? b.dueDate?.getTime() : b.nextRunAt?.getTime();
    if (aDate != null && bDate != null) return aDate - bDate;
    if (aDate != null) return -1;
    if (bDate != null) return 1;
    return a.title.localeCompare(b.title);
  });
}

export function summarizePlanning(
  tasks: PlanningTaskItem[],
  jobs: PlanningJobItem[],
  now = new Date(),
): PlanningSummary {
  const all = [...tasks, ...jobs];
  return {
    totalOpenTasks: tasks.length,
    dueToday: all.filter((item) => itemHorizon(item, now) === 'today').length,
    dueThisWeek: all.filter((item) => itemHorizon(item, now) === 'week').length,
    dueThisMonth: all.filter((item) => itemHorizon(item, now) === 'month').length,
    longTerm: all.filter((item) => itemHorizon(item, now) === 'long_term').length,
    activeJobs: jobs.filter((job) => job.status === 'active').length,
    blocked: tasks.filter((task) => columnFor(task.status) === 'review').length,
  };
}
