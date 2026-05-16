import { useCallback, useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router';
import { ChevronLeft, Plus, GanttChartSquare, Sparkles } from 'lucide-react';
import {
  getProject,
  listTasks,
  createTask,
  updateTask,
  deleteTask,
  getAiSummary,
} from '../lib/projects-api';
import type { Project, Task } from '../lib/projects-api';
import { TaskTree } from '../components/Project/TaskTree';
import { TaskDetailPanel } from '../components/Project/TaskDetailPanel';
import { statusColor } from '../components/Project/projectUtils';

export function ProjectDetailPage() {
  const { projectId = '' } = useParams();
  const navigate = useNavigate();
  const [project, setProject] = useState<Project | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selected, setSelected] = useState<Task | null>(null);
  const [summary, setSummary] = useState<string | null>(null);
  const [summarizing, setSummarizing] = useState(false);

  const loadTasks = useCallback(() => {
    listTasks(projectId)
      .then((ts) => {
        setTasks(ts);
        setSelected((cur) =>
          cur ? ts.find((t) => t.id === cur.id) || null : null,
        );
      })
      .catch(() => setTasks([]));
  }, [projectId]);

  useEffect(() => {
    getProject(projectId).then(setProject).catch(() => setProject(null));
    loadTasks();
  }, [projectId, loadTasks]);

  const addTask = async (parentId: string | null) => {
    const t = await createTask(projectId, {
      title: parentId ? 'New subtask' : 'New task',
      parent_task_id: parentId,
    });
    await loadTasks();
    setSelected(t);
  };

  const saveTask = async (patch: Partial<Task>) => {
    await updateTask(patch.id as string, patch);
    loadTasks();
    getProject(projectId).then(setProject).catch(() => {});
  };

  const removeTask = async (id: string) => {
    await deleteTask(id);
    setSelected(null);
    loadTasks();
  };

  const runSummary = async () => {
    setSummarizing(true);
    try {
      setSummary(await getAiSummary(projectId));
    } catch (e: any) {
      setSummary(e?.message || 'Failed to generate summary');
    } finally {
      setSummarizing(false);
    }
  };

  if (!project) {
    return (
      <div className="flex-1 px-6 py-10">
        <div style={{ color: 'var(--color-text-tertiary)' }}>Loading…</div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto px-6 py-8">
      <div className="max-w-5xl mx-auto">
        <button
          onClick={() => navigate('/projects')}
          className="flex items-center gap-1 text-xs mb-3 cursor-pointer"
          style={{ color: 'var(--color-text-tertiary)' }}
        >
          <ChevronLeft size={14} /> All projects
        </button>

        <header className="flex items-start justify-between gap-3 mb-5">
          <div>
            <div className="flex items-center gap-2">
              <h1
                className="text-lg font-semibold"
                style={{ color: 'var(--color-text)' }}
              >
                {project.name}
              </h1>
              <span
                className="text-xs px-2 py-0.5 rounded"
                style={{
                  color: statusColor(project.status),
                  border: `1px solid ${statusColor(project.status)}`,
                }}
              >
                {project.status}
              </span>
            </div>
            <p
              className="text-sm mt-1"
              style={{ color: 'var(--color-text-tertiary)' }}
            >
              {project.description || 'No description'} · {project.progress}%
              complete
            </p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={runSummary}
              disabled={summarizing}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs cursor-pointer disabled:opacity-50"
              style={{
                background: 'var(--color-bg-secondary)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text-secondary)',
              }}
            >
              <Sparkles size={14} />
              {summarizing ? 'Summarizing…' : 'AI summary'}
            </button>
            <button
              onClick={() => navigate(`/projects/${projectId}/timeline`)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs cursor-pointer"
              style={{
                background: 'var(--color-bg-secondary)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text-secondary)',
              }}
            >
              <GanttChartSquare size={14} /> Timeline
            </button>
          </div>
        </header>

        {summary && (
          <div
            className="mb-5 p-3 rounded-lg text-sm"
            style={{
              background: 'var(--color-accent-subtle)',
              border: '1px solid var(--color-border)',
              color: 'var(--color-text-secondary)',
            }}
          >
            {summary}
          </div>
        )}

        <div className="grid grid-cols-2 gap-4">
          <div
            className="rounded-lg p-2"
            style={{
              background: 'var(--color-bg-secondary)',
              border: '1px solid var(--color-border)',
            }}
          >
            <div className="flex items-center justify-between px-2 py-1 mb-1">
              <span
                className="text-xs font-semibold"
                style={{ color: 'var(--color-text)' }}
              >
                Task tree
              </span>
              <button
                onClick={() => addTask(null)}
                className="flex items-center gap-1 text-xs cursor-pointer"
                style={{ color: 'var(--color-accent)' }}
              >
                <Plus size={13} /> Task
              </button>
            </div>
            <TaskTree
              tasks={tasks}
              selectedId={selected?.id || null}
              onSelect={setSelected}
              onAddSubtask={addTask}
            />
          </div>

          <div
            className="rounded-lg p-3"
            style={{
              background: 'var(--color-bg-secondary)',
              border: '1px solid var(--color-border)',
              minHeight: 320,
            }}
          >
            {selected ? (
              <TaskDetailPanel
                key={selected.id}
                task={selected}
                onSave={saveTask}
                onDelete={removeTask}
              />
            ) : (
              <div
                className="h-full flex items-center justify-center text-sm text-center px-6"
                style={{ color: 'var(--color-text-tertiary)' }}
              >
                Select a task to view and edit its details, assignment,
                status, dates, and notes.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
