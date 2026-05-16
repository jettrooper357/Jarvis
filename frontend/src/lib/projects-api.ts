import { getBase } from './api';

export type ProjectStatus =
  | 'Planning'
  | 'Active'
  | 'At Risk'
  | 'Delayed'
  | 'Complete';

export type TaskStatus =
  | 'Backlog'
  | 'Ready'
  | 'In Progress'
  | 'Blocked'
  | 'Review'
  | 'Done'
  | 'Cancelled';

export type TaskPriority = 'Low' | 'Medium' | 'High' | 'Critical';

export interface Project {
  id: string;
  name: string;
  description: string;
  owner: string;
  team: string[];
  start_date: string | null;
  target_date: string | null;
  status: ProjectStatus;
  progress: number;
  tags: string[];
  milestones: unknown[];
  created_at: number;
  updated_at: number;
}

export interface Task {
  id: string;
  project_id: string;
  parent_task_id: string | null;
  title: string;
  description: string;
  type: string;
  status: TaskStatus;
  assigned_to: string;
  owner: string;
  priority: TaskPriority;
  start_date: string | null;
  due_date: string | null;
  percent_complete: number;
  estimate_hours: number | null;
  dependencies: string[];
  sort_order: number;
  created_at: number;
  updated_at: number;
}

export interface Note {
  id: string;
  task_id: string;
  author: string;
  content: string;
  type: string;
  ai_summary: string | null;
  created_at: number;
}

export interface ProjectDashboard {
  projects_total: number;
  projects_active: number;
  projects_at_risk: number;
  tasks_total: number;
  tasks_in_progress: number;
  tasks_overdue: number;
  tasks_blocked: number;
  tasks_done: number;
  avg_completion: number;
  workload_by_assignee: Record<string, number>;
  at_risk_projects: Array<{ id: string; name: string; status: string }>;
}

async function j<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const b = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(b.detail || `Request failed: ${res.status}`);
  }
  return res.json();
}

const base = () => `${getBase()}/v1/projects`;

export async function listProjects(): Promise<Project[]> {
  return (await j<{ projects: Project[] }>(await fetch(base()))).projects;
}

export async function getProject(id: string): Promise<Project> {
  return j<Project>(await fetch(`${base()}/${encodeURIComponent(id)}`));
}

export async function createProject(
  body: Partial<Project>,
): Promise<Project> {
  return j<Project>(
    await fetch(base(), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  );
}

export async function updateProject(
  id: string,
  body: Partial<Project>,
): Promise<Project> {
  return j<Project>(
    await fetch(`${base()}/${encodeURIComponent(id)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  );
}

export async function deleteProject(id: string): Promise<void> {
  await j(
    await fetch(`${base()}/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  );
}

export async function listTasks(projectId: string): Promise<Task[]> {
  return (
    await j<{ tasks: Task[] }>(
      await fetch(`${base()}/${encodeURIComponent(projectId)}/tasks`),
    )
  ).tasks;
}

export async function createTask(
  projectId: string,
  body: Partial<Task>,
): Promise<Task> {
  return j<Task>(
    await fetch(`${base()}/${encodeURIComponent(projectId)}/tasks`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  );
}

export async function updateTask(
  taskId: string,
  body: Partial<Task>,
): Promise<Task> {
  return j<Task>(
    await fetch(`${base()}/tasks/${encodeURIComponent(taskId)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  );
}

export async function deleteTask(taskId: string): Promise<void> {
  await j(
    await fetch(`${base()}/tasks/${encodeURIComponent(taskId)}`, {
      method: 'DELETE',
    }),
  );
}

export async function listNotes(taskId: string): Promise<Note[]> {
  return (
    await j<{ notes: Note[] }>(
      await fetch(`${base()}/tasks/${encodeURIComponent(taskId)}/notes`),
    )
  ).notes;
}

export async function addNote(
  taskId: string,
  body: Partial<Note>,
): Promise<Note> {
  return j<Note>(
    await fetch(`${base()}/tasks/${encodeURIComponent(taskId)}/notes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  );
}

export async function deleteNote(noteId: string): Promise<void> {
  await j(
    await fetch(`${base()}/notes/${encodeURIComponent(noteId)}`, {
      method: 'DELETE',
    }),
  );
}

export async function getDashboard(): Promise<ProjectDashboard> {
  return j<ProjectDashboard>(await fetch(`${base()}/dashboard`));
}

export async function getAiSummary(projectId: string): Promise<string> {
  const r = await j<{ summary: string }>(
    await fetch(`${base()}/${encodeURIComponent(projectId)}/ai-summary`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    }),
  );
  return r.summary;
}
