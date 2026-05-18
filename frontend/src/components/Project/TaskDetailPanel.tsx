import { useEffect, useState } from 'react';
import { Trash2 } from 'lucide-react';
import type { Task } from '../../lib/projects-api';
import { fetchManagedAgents } from '../../lib/api';
import {
  TASK_STATUSES,
  TASK_PRIORITIES,
  TASK_TYPES,
} from './projectUtils';
import { TaskNotesPanel } from './TaskNotesPanel';

const inputStyle = {
  width: '100%',
  padding: '6px 8px',
  background: 'var(--color-bg-secondary)',
  border: '1px solid var(--color-border)',
  borderRadius: 4,
  color: 'var(--color-text)',
  fontSize: 13,
  boxSizing: 'border-box' as const,
};

const labelCls = 'text-[11px] mb-1 block';

function toDateTimeLocal(value: string | null | undefined): string {
  if (!value) return '';
  const dt = new Date(value);
  if (isNaN(dt.getTime())) return value.length === 10 ? `${value}T00:00` : value;
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${dt.getFullYear()}-${pad(dt.getMonth() + 1)}-${pad(dt.getDate())}T${pad(dt.getHours())}:${pad(dt.getMinutes())}`;
}

function fromDateTimeLocal(value: string): string | null {
  return value ? value : null;
}

export function TaskDetailPanel({
  task,
  onSave,
  onDelete,
}: {
  task: Task;
  onSave: (patch: Partial<Task>) => void;
  onDelete: (id: string) => void;
}) {
  const [draft, setDraft] = useState<Task>(task);
  useEffect(() => setDraft(task), [task]);

  const [agents, setAgents] = useState<{ id: string; name: string }[]>([]);
  useEffect(() => {
    fetchManagedAgents()
      .then((a) => setAgents(a.map((x) => ({ id: x.id, name: x.name }))))
      .catch(() => {});
  }, []);

  const set = (k: keyof Task, v: unknown) =>
    setDraft((d) => ({ ...d, [k]: v }) as Task);

  const dirty = JSON.stringify(draft) !== JSON.stringify(task);

  return (
    <div className="flex flex-col h-full overflow-y-auto" style={{ gap: 10 }}>
      <input
        value={draft.title}
        onChange={(e) => set('title', e.target.value)}
        style={{ ...inputStyle, fontSize: 15, fontWeight: 600 }}
      />
      <textarea
        value={draft.description}
        onChange={(e) => set('description', e.target.value)}
        placeholder="Description"
        rows={3}
        style={{ ...inputStyle, resize: 'vertical' }}
      />
      <div className="grid grid-cols-2 gap-2">
        <div>
          <span className={labelCls} style={{ color: 'var(--color-text-tertiary)' }}>
            Status
          </span>
          <select
            value={draft.status}
            onChange={(e) => set('status', e.target.value)}
            style={inputStyle}
          >
            {TASK_STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <div>
          <span className={labelCls} style={{ color: 'var(--color-text-tertiary)' }}>
            Priority
          </span>
          <select
            value={draft.priority}
            onChange={(e) => set('priority', e.target.value)}
            style={inputStyle}
          >
            {TASK_PRIORITIES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <div>
          <span className={labelCls} style={{ color: 'var(--color-text-tertiary)' }}>
            Type
          </span>
          <select
            value={draft.type}
            onChange={(e) => set('type', e.target.value)}
            style={inputStyle}
          >
            {TASK_TYPES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <div>
          <span className={labelCls} style={{ color: 'var(--color-text-tertiary)' }}>
            Assigned to
          </span>
          <select
            value={draft.assigned_to || ''}
            onChange={(e) => set('assigned_to', e.target.value)}
            style={inputStyle}
          >
            <option value="">— Unassigned —</option>
            {draft.assigned_to &&
              !agents.some((a) => a.name === draft.assigned_to) && (
                <option value={draft.assigned_to}>
                  {draft.assigned_to} (not an agent)
                </option>
              )}
            {agents.map((a) => (
              <option key={a.id} value={a.name}>
                {a.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <span className={labelCls} style={{ color: 'var(--color-text-tertiary)' }}>
            Start date/time
          </span>
          <input
            type="datetime-local"
            value={toDateTimeLocal(draft.start_date)}
            onChange={(e) => set('start_date', fromDateTimeLocal(e.target.value))}
            style={inputStyle}
          />
        </div>
        <div>
          <span className={labelCls} style={{ color: 'var(--color-text-tertiary)' }}>
            Due date/time
          </span>
          <input
            type="datetime-local"
            value={toDateTimeLocal(draft.due_date)}
            onChange={(e) => set('due_date', fromDateTimeLocal(e.target.value))}
            style={inputStyle}
          />
        </div>
      </div>
      <div>
        <span className={labelCls} style={{ color: 'var(--color-text-tertiary)' }}>
          Percent complete: {draft.percent_complete}%
        </span>
        <input
          type="range"
          min={0}
          max={100}
          value={draft.percent_complete}
          onChange={(e) => set('percent_complete', Number(e.target.value))}
          style={{ width: '100%' }}
        />
      </div>

      <div className="flex gap-2">
        <button
          onClick={() => onSave(draft)}
          disabled={!dirty}
          className="flex-1 py-2 rounded-lg text-xs cursor-pointer disabled:opacity-50"
          style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}
        >
          {dirty ? 'Save changes' : 'Saved'}
        </button>
        <button
          onClick={() => onDelete(task.id)}
          className="px-3 py-2 rounded-lg text-xs cursor-pointer"
          style={{
            background: 'var(--color-bg-secondary)',
            border: '1px solid var(--color-border)',
            color: 'var(--color-error)',
          }}
        >
          <Trash2 size={14} />
        </button>
      </div>

      <div
        className="pt-3 mt-1"
        style={{ borderTop: '1px solid var(--color-border)' }}
      >
        <TaskNotesPanel taskId={task.id} />
      </div>
    </div>
  );
}
