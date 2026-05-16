import { useState } from 'react';
import { ChevronRight, ChevronDown, Plus } from 'lucide-react';
import type { Task } from '../../lib/projects-api';
import {
  buildTaskTree,
  statusColor,
  priorityColor,
  isOverdue,
} from './projectUtils';

function TaskRow({
  task,
  depth,
  childrenOf,
  selectedId,
  onSelect,
  onAddSubtask,
}: {
  task: Task;
  depth: number;
  childrenOf: (id: string) => Task[];
  selectedId: string | null;
  onSelect: (t: Task) => void;
  onAddSubtask: (parentId: string) => void;
}) {
  const [open, setOpen] = useState(true);
  const kids = childrenOf(task.id);
  const overdue = isOverdue(task);

  return (
    <div>
      <div
        className="flex items-center gap-2 px-2 py-1.5 rounded cursor-pointer"
        style={{
          paddingLeft: 8 + depth * 18,
          background:
            selectedId === task.id
              ? 'var(--color-accent-subtle)'
              : 'transparent',
        }}
        onClick={() => onSelect(task)}
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
        >
          {task.title}
        </span>
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
        roots.map((r) => (
          <TaskRow
            key={r.id}
            task={r}
            depth={0}
            childrenOf={childrenOf}
            selectedId={selectedId}
            onSelect={onSelect}
            onAddSubtask={onAddSubtask}
          />
        ))
      )}
    </div>
  );
}
