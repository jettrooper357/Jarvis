import { useState } from 'react';
import { ChevronRight, ChevronDown, Plus } from 'lucide-react';
import type { Task } from '../../lib/projects-api';
import {
  buildTaskTree,
  statusColor,
  priorityColor,
  isOverdue,
  fmtDateTime,
} from './projectUtils';

const DAY = 86400000;

function taskTime(task: Task, field: 'start_date' | 'due_date'): number | null {
  const raw = task[field];
  if (!raw) return null;
  const value = new Date(raw).getTime();
  return Number.isFinite(value) ? value : null;
}

function TaskRow({
  task,
  depth,
  childrenOf,
  selectedId,
  onSelect,
  onAddSubtask,
  timeline,
}: {
  task: Task;
  depth: number;
  childrenOf: (id: string) => Task[];
  selectedId: string | null;
  onSelect: (t: Task) => void;
  onAddSubtask: (parentId: string) => void;
  timeline: { min: number; span: number };
}) {
  const [open, setOpen] = useState(true);
  const kids = childrenOf(task.id);
  const overdue = isOverdue(task);
  const start = taskTime(task, 'start_date') ?? taskTime(task, 'due_date');
  const due = taskTime(task, 'due_date');
  const barStart = start ?? Date.now();
  const barEnd = due ?? barStart + DAY;
  const left = Math.max(0, ((barStart - timeline.min) / timeline.span) * 100);
  const width = Math.max(
    1.5,
    Math.min(100 - left, ((barEnd - barStart) / timeline.span) * 100),
  );
  const waiting = Boolean(start && start > Date.now());

  return (
    <div>
      <div
        className="grid items-center gap-2 px-2 py-1.5 rounded cursor-pointer"
        style={{
          gridTemplateColumns:
            'minmax(210px, 1.1fr) minmax(180px, 1fr) 90px 54px 44px 24px',
          background:
            selectedId === task.id
              ? 'var(--color-accent-subtle)'
              : 'transparent',
        }}
        onClick={() => onSelect(task)}
      >
        <div
          className="flex items-center gap-2 min-w-0"
          style={{ paddingLeft: depth * 18 }}
        >
          {kids.length > 0 ? (
            <button
              onClick={(e) => {
                e.stopPropagation();
                setOpen((o) => !o);
              }}
              style={{ color: 'var(--color-text-tertiary)' }}
            >
              {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </button>
          ) : (
            <span style={{ width: 14, display: 'inline-block' }} />
          )}
          <span
            className="w-2 h-2 rounded-full shrink-0"
            style={{ background: statusColor(task.status) }}
          />
          <span
            className="text-sm flex-1 truncate"
            style={{ color: 'var(--color-text)' }}
            title={task.title}
          >
            {task.title}
          </span>
        </div>
        <button
          className="relative h-6 rounded text-left overflow-hidden"
          onClick={(e) => {
            e.stopPropagation();
            onSelect(task);
          }}
          title={`${fmtDateTime(task.start_date)} to ${fmtDateTime(task.due_date)}`}
          style={{ background: 'var(--color-bg-secondary)' }}
        >
          <span
            className="absolute top-1 h-4 rounded"
            style={{
              left: `${left}%`,
              width: `${width}%`,
              background: overdue ? 'var(--color-error)' : statusColor(task.status),
              opacity: waiting ? 0.45 : 0.9,
            }}
          />
          <span
            className="absolute top-1 h-4 rounded-l"
            style={{
              left: `${left}%`,
              width: `${Math.max(0, (width * task.percent_complete) / 100)}%`,
              background: 'rgba(255,255,255,0.35)',
            }}
          />
        </button>
        {overdue && (
          <span
            className="text-[10px] px-1.5 rounded"
            style={{
              color: 'var(--color-error)',
              border: '1px solid var(--color-error)',
            }}
          >
            overdue
          </span>
        )}
        {!overdue && waiting && (
          <span
            className="text-[10px] px-1.5 rounded"
            style={{
              color: 'var(--color-warning)',
              border: '1px solid var(--color-warning)',
            }}
          >
            scheduled
          </span>
        )}
        {!overdue && !waiting && (
          <span
            className="text-[10px] truncate"
            style={{ color: 'var(--color-text-tertiary)' }}
            title={fmtDateTime(task.start_date)}
          >
            {fmtDateTime(task.start_date)}
          </span>
        )}
        <span
          className="text-[10px]"
          style={{ color: priorityColor(task.priority) }}
        >
          {task.priority}
        </span>
        <span
          className="text-[10px] w-9 text-right"
          style={{ color: 'var(--color-text-tertiary)' }}
        >
          {task.percent_complete}%
        </span>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onAddSubtask(task.id);
          }}
          title="Add subtask"
          style={{ color: 'var(--color-text-tertiary)' }}
        >
          <Plus size={13} />
        </button>
      </div>
      {open &&
        kids.map((k) => (
          <TaskRow
            key={k.id}
            task={k}
            depth={depth + 1}
            childrenOf={childrenOf}
            selectedId={selectedId}
            onSelect={onSelect}
            onAddSubtask={onAddSubtask}
            timeline={timeline}
          />
        ))}
    </div>
  );
}

export function TaskTree({
  tasks,
  selectedId,
  onSelect,
  onAddSubtask,
}: {
  tasks: Task[];
  selectedId: string | null;
  onSelect: (t: Task) => void;
  onAddSubtask: (parentId: string | null) => void;
}) {
  const { roots, childrenOf } = buildTaskTree(tasks);
  const timeline = (() => {
    const stamps = tasks.flatMap((task) =>
      [taskTime(task, 'start_date'), taskTime(task, 'due_date')].filter(
        (value): value is number => value !== null,
      ),
    );
    const now = Date.now();
    const min = stamps.length ? Math.min(...stamps, now) - DAY : now - DAY;
    const max = stamps.length ? Math.max(...stamps, now) + DAY : now + DAY;
    return { min, span: Math.max(max - min, DAY) };
  })();
  return (
    <div>
      {roots.length === 0 ? (
        <div
          className="text-sm py-6 text-center"
          style={{ color: 'var(--color-text-tertiary)' }}
        >
          No tasks yet.
        </div>
      ) : (
        <>
          <div
            className="grid gap-2 px-2 pb-2 text-[10px]"
            style={{
              gridTemplateColumns:
                'minmax(210px, 1.1fr) minmax(180px, 1fr) 90px 54px 44px 24px',
              color: 'var(--color-text-tertiary)',
            }}
          >
            <span>Task</span>
            <span>Schedule</span>
            <span>Start</span>
            <span>Priority</span>
            <span>%</span>
            <span />
          </div>
          {roots.map((r) => (
            <TaskRow
              key={r.id}
              task={r}
              depth={0}
              childrenOf={childrenOf}
              selectedId={selectedId}
              onSelect={onSelect}
              onAddSubtask={onAddSubtask}
              timeline={timeline}
            />
          ))}
        </>
      )}
    </div>
  );
}
