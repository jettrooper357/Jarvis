import {
  type MouseEvent as ReactMouseEvent,
  createContext,
  useContext,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { useNavigate } from 'react-router';
import {
  Activity,
  AlertTriangle,
  Bot,
  BriefcaseBusiness,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleDot,
  DatabaseZap,
  Filter,
  FolderKanban,
  Gauge,
  GitBranch,
  Info,
  GanttChartSquare,
  ListChecks,
  MoreVertical,
  Plus,
  Search,
  Sparkles,
  Tag,
  Target,
  Trash2,
  Zap,
} from 'lucide-react';
import {
  createProject,
  createTask,
  deleteProject,
  deleteTask,
  getDashboard,
  getProjectBundle,
  updateProject,
  updateTask,
} from '../lib/projects-api';
import type {
  Milestone as ApiMilestone,
  Project,
  ProjectDashboard,
  ProjectStatus,
  Task,
  TaskStatus,
} from '../lib/projects-api';
import { PROJECT_STATUSES } from '../components/Project/projectUtils';
import { checkHealth, fetchManagedAgents, type ManagedAgent } from '../lib/api';

type Status = 'In Progress' | 'Done' | 'At Risk' | 'Blocked' | 'Pending';
type Accent = 'cyan' | 'green' | 'amber' | 'red' | 'purple';
type Milestone = { id: string; name: string; date: string; done: boolean };

type GanttItem = {
  id: string;
  projectId: string;
  name: string;
  agent: string;
  status: Status;
  progress: number;
  start: number;
  end: number;
  accent: Accent;
  level: number;
  type: 'project' | 'task';
  parentId?: string;
  blocker?: boolean;
  milestone?: number;
  // Optional grouping label for tasks/subtasks. null/undefined = uncategorized.
  category?: string;
  // Raw ISO date strings from the store so the edit dialog shows real
  // values instead of hard-coded placeholders and round-trips them on save.
  startDate?: string | null;
  dueDate?: string | null;
  // Project-only: filesystem path where agents do work for this project.
  workingFolder?: string;
};

const weeks = [
  'Apr 14',
  'Apr 21',
  'Apr 28',
  'May 5',
  'May 12',
  'May 19',
  'May 26',
  'Jun 2',
  'Jun 9',
  'Jun 16',
  'Jun 23',
];

// --- Live data layer: SQLite ProjectStore (via REST) → Gantt model ------
//
// The Projects Command Center reads the same store as Mission Control and
// the agent tools, so the three never disagree. The Gantt's time axis is
// derived from the real task/project dates instead of a fixed window.

type Axis = {
  labels: string[];
  // Denominator for bar math; kept at 11 to preserve the original scale.
  denom: number;
  pos: (iso?: string | null, fallback?: number) => number;
  todayPos: number;
};

const _AXIS_MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];
const _DAY = 86_400_000;
const _clamp = (n: number, lo: number, hi: number) =>
  Math.max(lo, Math.min(hi, n));
const _fmtAxis = (t: number) => {
  const d = new Date(t);
  return `${_AXIS_MONTHS[d.getMonth()]} ${d.getDate()}`;
};

function buildAxis(times: number[]): Axis {
  const valid = times.filter((t) => Number.isFinite(t));
  let min = valid.length ? Math.min(...valid) : Date.now() - 7 * _DAY;
  let max = valid.length ? Math.max(...valid) : Date.now() + 63 * _DAY;
  if (!(max > min)) {
    min = Date.now() - 7 * _DAY;
    max = Date.now() + 63 * _DAY;
  }
  const pad = (max - min) * 0.04 || _DAY;
  min -= pad;
  max += pad;
  const span = max - min;
  const labels = Array.from({ length: 11 }, (_, i) =>
    _fmtAxis(min + span * (i / 10)),
  );
  const pos = (iso?: string | null, fallback = 0) => {
    if (!iso) return fallback;
    const t = Date.parse(iso);
    if (!Number.isFinite(t)) return fallback;
    return _clamp(((t - min) / span) * 10, 0, 10);
  };
  return { labels, denom: 11, pos, todayPos: pos(new Date().toISOString(), 4) };
}

const DEFAULT_AXIS: Axis = {
  labels: weeks,
  denom: 11,
  pos: (_iso, fallback = 0) => fallback,
  todayPos: 4.15,
};
const AxisContext = createContext<Axis>(DEFAULT_AXIS);
const useAxis = () => useContext(AxisContext);

const PROJECT_STATUS_MAP: Record<ProjectStatus, Status> = {
  Planning: 'Pending',
  Active: 'In Progress',
  'At Risk': 'At Risk',
  Delayed: 'Blocked',
  Complete: 'Done',
};
const TASK_STATUS_MAP: Record<TaskStatus, Status> = {
  Backlog: 'Pending',
  Ready: 'Pending',
  'In Progress': 'In Progress',
  Blocked: 'Blocked',
  Review: 'At Risk',
  Done: 'Done',
  Cancelled: 'Done',
};
const STATUS_ACCENT: Record<Status, Accent> = {
  'In Progress': 'cyan',
  Done: 'green',
  'At Risk': 'amber',
  Blocked: 'red',
  Pending: 'purple',
};
const STATUS_TO_TASK: Record<Status, TaskStatus> = {
  'In Progress': 'In Progress',
  Done: 'Done',
  Blocked: 'Blocked',
  'At Risk': 'Review',
  Pending: 'Backlog',
};
const STATUS_TO_PROJECT: Record<Status, ProjectStatus> = {
  'In Progress': 'Active',
  Done: 'Complete',
  'At Risk': 'At Risk',
  Blocked: 'Delayed',
  Pending: 'Planning',
};

function buildGanttData(
  projects: Project[],
  tasksByProject: Record<string, Task[]>,
): {
  items: GanttItem[];
  milestonesByProject: Record<string, Milestone[]>;
  axis: Axis;
} {
  const times: number[] = [];
  const pushTime = (iso?: string | null) => {
    if (iso) {
      const t = Date.parse(iso);
      if (Number.isFinite(t)) times.push(t);
    }
  };
  for (const p of projects) {
    pushTime(p.start_date);
    pushTime(p.target_date);
    for (const t of tasksByProject[p.id] ?? []) {
      pushTime(t.start_date);
      pushTime(t.due_date);
    }
  }
  const axis = buildAxis(times);
  const items: GanttItem[] = [];
  const milestonesByProject: Record<string, Milestone[]> = {};
  for (const p of projects) {
    const pStatus = PROJECT_STATUS_MAP[p.status] ?? 'Pending';
    const pStart = axis.pos(p.start_date, 0);
    const pEnd = Math.max(pStart + 0.5, axis.pos(p.target_date, 10));
    items.push({
      id: p.id,
      projectId: p.id,
      name: p.name,
      agent: p.owner || 'Unassigned',
      status: pStatus,
      progress: p.progress ?? 0,
      start: pStart,
      end: pEnd,
      accent: STATUS_ACCENT[pStatus],
      level: 0,
      type: 'project',
      startDate: p.start_date,
      dueDate: p.target_date,
      workingFolder: p.working_folder ?? '',
    });
    const tasks = tasksByProject[p.id] ?? [];
    const byId = new Map(tasks.map((t) => [t.id, t]));
    const depthCache = new Map<string, number>();
    const depth = (t: Task): number => {
      if (!t.parent_task_id) return 1;
      const cached = depthCache.get(t.id);
      if (cached) return cached;
      const parent = byId.get(t.parent_task_id);
      const d = parent ? depth(parent) + 1 : 1;
      depthCache.set(t.id, d);
      return d;
    };
    for (const t of tasks) {
      const tStatus = TASK_STATUS_MAP[t.status] ?? 'Pending';
      const start = axis.pos(t.start_date, pStart);
      const end = Math.max(start + 0.4, axis.pos(t.due_date, pEnd));
      items.push({
        id: t.id,
        projectId: p.id,
        name: t.title,
        agent: t.assigned_to || t.owner || 'Unassigned',
        status: tStatus,
        progress: t.percent_complete ?? 0,
        start,
        end,
        accent: STATUS_ACCENT[tStatus],
        level: depth(t),
        type: 'task',
        parentId: t.parent_task_id || p.id,
        blocker: t.status === 'Blocked',
        category: (t.category || '').trim() || undefined,
        startDate: t.start_date,
        dueDate: t.due_date,
      });
    }
    milestonesByProject[p.id] = (p.milestones ?? []).map(
      (m: ApiMilestone, i: number) => ({
        id: m.id || `ms-${p.id}-${i}`,
        name: m.name || 'Milestone',
        date: m.date || 'TBD',
        done: Boolean(m.done),
      }),
    );
  }
  return { items, milestonesByProject, axis };
}

const accentMap: Record<Accent, { text: string; bg: string; glow: string }> = {
  cyan: {
    text: '#24d9ff',
    bg: 'linear-gradient(90deg, rgba(28,210,255,.92), rgba(24,124,176,.56))',
    glow: 'rgba(28,210,255,.36)',
  },
  green: {
    text: '#28f0a0',
    bg: 'linear-gradient(90deg, rgba(18,182,112,.9), rgba(23,215,125,.55))',
    glow: 'rgba(40,240,160,.28)',
  },
  amber: {
    text: '#ffb22c',
    bg: 'linear-gradient(90deg, rgba(255,177,38,.92), rgba(185,111,24,.52))',
    glow: 'rgba(255,178,44,.3)',
  },
  red: {
    text: '#ff4e61',
    bg: 'linear-gradient(90deg, rgba(255,70,84,.9), rgba(151,38,52,.52))',
    glow: 'rgba(255,78,97,.3)',
  },
  purple: {
    text: '#a78bfa',
    bg: 'linear-gradient(90deg, rgba(139,92,246,.88), rgba(40,216,255,.32))',
    glow: 'rgba(167,139,250,.28)',
  },
};

const panelStyle = {
  background:
    'linear-gradient(180deg, rgba(13,22,34,.86), rgba(5,10,18,.9))',
  border: '1px solid rgba(55, 211, 255, .16)',
  boxShadow: '0 18px 40px rgba(0,0,0,.22), inset 0 1px 0 rgba(255,255,255,.04)',
};

const inputBox = {
  background: 'rgba(0,0,0,.34)',
  border: '1px solid rgba(74,210,255,.18)',
};

function StatusBadge({ status }: { status: Status }) {
  const accent =
    status === 'Done'
      ? 'green'
      : status === 'Blocked'
        ? 'red'
        : status === 'At Risk'
          ? 'amber'
          : status === 'Pending'
            ? 'purple'
            : 'cyan';
  return (
    <span
      className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px]"
      style={{
        color: accentMap[accent].text,
        background: `${accentMap[accent].glow}`,
        border: `1px solid ${accentMap[accent].glow}`,
      }}
    >
      <span
        className="h-1.5 w-1.5 rounded-full"
        style={{ background: accentMap[accent].text }}
      />
      {status}
    </span>
  );
}

function ProjectKpiCard({
  icon,
  label,
  value,
  support,
  accent,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  support: string;
  accent: Accent;
}) {
  const colors = accentMap[accent];
  return (
    <button
      className="group min-h-[78px] rounded-lg p-3 text-left transition"
      style={panelStyle}
    >
      <div className="flex items-center gap-3">
        <span
          className="flex h-9 w-9 items-center justify-center rounded-full"
          style={{
            color: colors.text,
            background: colors.glow,
            border: `1px solid ${colors.glow}`,
            boxShadow: `0 0 18px ${colors.glow}`,
          }}
        >
          {icon}
        </span>
        <div className="min-w-0">
          <div
            className="text-[11px]"
            style={{ color: 'var(--color-text-tertiary)' }}
          >
            {label}
          </div>
          <div className="text-xl font-semibold" style={{ color: '#f7fbff' }}>
            {value}
          </div>
          <div className="text-[11px]" style={{ color: colors.text }}>
            {support}
          </div>
        </div>
      </div>
    </button>
  );
}

function TaskBar({ item }: { item: GanttItem }) {
  const axis = useAxis();
  const colors = accentMap[item.accent];
  const left = (item.start / axis.denom) * 100;
  const width = Math.max(4, ((item.end - item.start) / axis.denom) * 100);
  return (
    <>
      <button
        className="absolute top-2 h-5 rounded-sm transition hover:brightness-125"
        title={`${item.name}: ${item.progress}% complete`}
        style={{
          left: `${left}%`,
          width: `${width}%`,
          background: colors.bg,
          boxShadow: `0 0 18px ${colors.glow}`,
          border: `1px solid ${colors.glow}`,
        }}
      >
        <span
          className="absolute left-0 top-0 h-full rounded-sm"
          style={{
            width: `${item.progress}%`,
            background: 'rgba(255,255,255,.2)',
          }}
        />
        <span className="absolute -right-7 top-0 text-[10px] text-slate-200">
          {item.progress}%
        </span>
      </button>
      {item.milestone !== undefined && (
        <button
          className="absolute top-[9px] h-4 w-4 rotate-45 transition hover:scale-110"
          title={`${item.name} milestone`}
          style={{
            left: `${(item.milestone / axis.denom) * 100}%`,
            background: colors.text,
            boxShadow: `0 0 18px ${colors.glow}`,
          }}
        />
      )}
    </>
  );
}

function EditItemModal({
  item,
  agents,
  categories,
  onSave,
  onClose,
}: {
  item: GanttItem;
  agents: ManagedAgent[];
  categories: string[];
  onSave: (item: GanttItem) => void;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState<GanttItem>(item);
  const itemKind =
    item.type === 'project' ? 'Project' : item.level > 1 ? 'Subtask' : 'Task';
  const agentOptions = agents.map((agent) => agent.name);
  const set = <K extends keyof GanttItem>(key: K, value: GanttItem[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl rounded-xl p-5"
        style={{
          ...panelStyle,
          border: '1px solid rgba(74, 210, 255, .32)',
          boxShadow: '0 24px 80px rgba(0,0,0,.55), 0 0 36px rgba(36,217,255,.16)',
        }}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <div className="text-xs uppercase tracking-[0.18em] text-cyan-300">
              Edit {itemKind}
            </div>
            <h2 className="mt-1 text-lg font-semibold text-white">
              {item.name}
            </h2>
          </div>
          <button
            className="rounded-md px-2 py-1 text-xs text-slate-300 hover:bg-cyan-400/10"
            onClick={onClose}
          >
            Close
          </button>
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          <label className="md:col-span-2">
            <span className="mb-1 block text-xs text-slate-500">
              {itemKind} name
            </span>
            <input
              value={draft.name}
              onChange={(event) => set('name', event.target.value)}
              className="w-full rounded-md px-3 py-2 text-sm text-slate-100"
              style={{
                background: 'rgba(0,0,0,.34)',
                border: '1px solid rgba(74,210,255,.18)',
              }}
            />
          </label>
          <label>
            <span className="mb-1 block text-xs text-slate-500">
              Owner / Agent
            </span>
            <select
              value={draft.agent || 'Unassigned'}
              onChange={(event) => set('agent', event.target.value)}
              className="w-full rounded-md px-3 py-2 text-sm text-slate-100"
              style={{
                background: 'rgba(0,0,0,.34)',
                border: '1px solid rgba(74,210,255,.18)',
              }}
            >
              {!agents.some((agent) => agent.name === draft.agent) &&
                draft.agent &&
                draft.agent !== 'Unassigned' && (
                  <option value={draft.agent}>{draft.agent} (legacy)</option>
                )}
              <option value="Unassigned">Unassigned</option>
              {agentOptions.map((agent) => (
                <option key={agent} value={agent}>
                  {agent}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span className="mb-1 block text-xs text-slate-500">Status</span>
            <select
              value={draft.status}
              onChange={(event) => set('status', event.target.value as Status)}
              className="w-full rounded-md px-3 py-2 text-sm text-slate-100"
              style={{
                background: 'rgba(0,0,0,.34)',
                border: '1px solid rgba(74,210,255,.18)',
              }}
            >
              {['In Progress', 'Done', 'At Risk', 'Blocked', 'Pending'].map(
                (status) => (
                  <option key={status}>{status}</option>
                ),
              )}
            </select>
          </label>
          <label>
            <span className="mb-1 block text-xs text-slate-500">Priority</span>
            <select
              defaultValue={item.blocker ? 'High' : 'Medium'}
              className="w-full rounded-md px-3 py-2 text-sm text-slate-100"
              style={{
                background: 'rgba(0,0,0,.34)',
                border: '1px solid rgba(74,210,255,.18)',
              }}
            >
              {['Low', 'Medium', 'High', 'Critical'].map((priority) => (
                <option key={priority}>{priority}</option>
              ))}
            </select>
          </label>
          {item.type === 'task' && (
            <label className="md:col-span-2">
              <span className="mb-1 block text-xs text-slate-500">
                Category
              </span>
              <CategorySelect
                value={draft.category ?? ''}
                categories={categories}
                onChange={(next) =>
                  set('category', next ? next : undefined)
                }
              />
            </label>
          )}
          <label>
            <span className="mb-1 block text-xs text-slate-500">
              Progress
            </span>
            <input
              type="number"
              min={0}
              max={100}
              value={draft.progress}
              onChange={(event) =>
                set(
                  'progress',
                  Math.max(0, Math.min(100, Number(event.target.value) || 0)),
                )
              }
              className="w-full rounded-md px-3 py-2 text-sm text-slate-100"
              style={{
                background: 'rgba(0,0,0,.34)',
                border: '1px solid rgba(74,210,255,.18)',
              }}
            />
          </label>
          <label>
            <span className="mb-1 block text-xs text-slate-500">
              Start date
            </span>
            <input
              type="date"
              value={(draft.startDate ?? '').slice(0, 10)}
              onChange={(event) =>
                set('startDate', event.target.value || null)
              }
              className="w-full rounded-md px-3 py-2 text-sm text-slate-100"
              style={{
                background: 'rgba(0,0,0,.34)',
                border: '1px solid rgba(74,210,255,.18)',
              }}
            />
          </label>
          <label>
            <span className="mb-1 block text-xs text-slate-500">End date</span>
            <input
              type="date"
              value={(draft.dueDate ?? '').slice(0, 10)}
              onChange={(event) =>
                set('dueDate', event.target.value || null)
              }
              className="w-full rounded-md px-3 py-2 text-sm text-slate-100"
              style={{
                background: 'rgba(0,0,0,.34)',
                border: '1px solid rgba(74,210,255,.18)',
              }}
            />
          </label>
          {item.type === 'project' && (
            <label className="md:col-span-2">
              <span className="mb-1 block text-xs text-slate-500">
                Working folder
              </span>
              <input
                type="text"
                value={draft.workingFolder ?? ''}
                onChange={(event) =>
                  set('workingFolder', event.target.value)
                }
                placeholder="e.g. F:\\Work\\my-project"
                className="w-full rounded-md px-3 py-2 text-sm text-slate-100"
                style={{
                  background: 'rgba(0,0,0,.34)',
                  border: '1px solid rgba(74,210,255,.18)',
                }}
              />
              <span className="mt-1 block text-[10px] text-slate-500">
                Agents working on this project are sandboxed to this
                folder for file, shell, and patch tools. Auto-created
                if missing.
              </span>
            </label>
          )}
          <label className="md:col-span-2">
            <span className="mb-1 block text-xs text-slate-500">Notes</span>
            <textarea
              defaultValue={
                item.blocker
                  ? 'Blocked by external dependency. Confirm mitigation owner and next checkpoint.'
                  : 'Track execution notes, current findings, and next action for this work item.'
              }
              rows={4}
              className="w-full resize-none rounded-md px-3 py-2 text-sm text-slate-100"
              style={{
                background: 'rgba(0,0,0,.34)',
                border: '1px solid rgba(74,210,255,.18)',
              }}
            />
          </label>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button
            className="rounded-md px-4 py-2 text-xs text-slate-300"
            style={{ border: '1px solid rgba(74,210,255,.18)' }}
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            className="rounded-md px-4 py-2 text-xs font-semibold"
            style={{
              background: 'linear-gradient(180deg, #2be1ff, #1398c8)',
              color: '#031018',
            }}
            onClick={() => {
              onSave(draft);
              onClose();
            }}
          >
            Save changes
          </button>
        </div>
      </div>
    </div>
  );
}

function GanttRow({
  item,
  selected,
  onSelect,
  onEdit,
  hasChildren,
  expanded,
  onToggle,
  onContextMenu,
}: {
  item: GanttItem;
  selected: boolean;
  onSelect: (item: GanttItem) => void;
  onEdit: (item: GanttItem) => void;
  hasChildren: boolean;
  expanded: boolean;
  onToggle: (id: string) => void;
  onContextMenu: (event: ReactMouseEvent, item: GanttItem) => void;
}) {
  const isProject = item.type === 'project';
  return (
    <div
      className="grid min-w-[920px] cursor-pointer items-center border-t transition hover:bg-cyan-400/5"
      style={{
        gridTemplateColumns: '250px 92px 108px 54px minmax(430px,1fr)',
        minHeight: isProject ? 38 : 32,
        borderColor: 'rgba(74, 210, 255, .09)',
        background: selected ? 'rgba(20, 216, 255, .08)' : 'transparent',
      }}
      onClick={() => onSelect(item)}
      onDoubleClick={() => onEdit(item)}
      onContextMenu={(event) => onContextMenu(event, item)}
      draggable={!isProject}
      onDragStart={(event) => {
        event.dataTransfer.setData('text/plain', item.id);
        event.dataTransfer.effectAllowed = 'move';
      }}
    >
      <div
        className="flex min-w-0 items-center gap-2 px-3 text-xs"
        style={{ paddingLeft: 10 + item.level * 18 }}
      >
        {hasChildren ? (
          <button
            className="rounded p-0.5 transition hover:bg-cyan-300/10"
            onClick={(event) => {
              event.stopPropagation();
              onToggle(item.id);
            }}
            title={expanded ? 'Collapse row' : 'Expand row'}
            style={{ color: '#9edff5' }}
          >
            {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          </button>
        ) : (
          <span className="inline-block w-[17px]" />
        )}
        <FolderKanban
          size={13}
          style={{ color: isProject ? '#24d9ff' : '#9aa8b6' }}
        />
        <span
          className={isProject ? 'font-semibold' : ''}
          style={{ color: isProject ? '#eaf7ff' : '#c6d1dd' }}
        >
          {item.name}
        </span>
        {item.category && (
          <span
            className="shrink-0 rounded px-1.5 py-0.5 text-[10px]"
            style={{ background: 'rgba(74,210,255,.12)', color: '#9edff5' }}
          >
            {item.category}
          </span>
        )}
        {item.blocker && <AlertTriangle size={12} className="text-red-400" />}
        <Info size={11} style={{ color: 'rgba(148, 220, 255, .55)' }} />
      </div>
      <div className="text-xs" style={{ color: '#d6e2ef' }}>
        {item.agent}
      </div>
      <div>
        <StatusBadge status={item.status} />
      </div>
      <div className="text-xs" style={{ color: '#d6e2ef' }}>
        {item.progress}%
      </div>
      <div
        className="relative h-full border-l"
        style={{ borderColor: 'rgba(74, 210, 255, .12)' }}
        onDoubleClick={(event) => {
          event.stopPropagation();
          onEdit(item);
        }}
      >
        <TaskBar item={item} />
      </div>
    </div>
  );
}

// Inline editor for renaming a category. Self-contained state so it always
// starts from the current name; the doneRef guard stops Enter/Escape from
// double-firing with the blur handler.
function CategoryNameEditor({
  initial,
  onCommit,
  onCancel,
}: {
  initial: string;
  onCommit: (next: string) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState(initial);
  const doneRef = useRef(false);
  const finish = (commit: boolean) => {
    if (doneRef.current) return;
    doneRef.current = true;
    if (commit) onCommit(value);
    else onCancel();
  };
  return (
    <input
      autoFocus
      value={value}
      onClick={(event) => event.stopPropagation()}
      onChange={(event) => setValue(event.target.value)}
      onKeyDown={(event) => {
        if (event.key === 'Enter') {
          event.preventDefault();
          finish(true);
        }
        if (event.key === 'Escape') {
          event.preventDefault();
          finish(false);
        }
      }}
      onBlur={() => finish(true)}
      placeholder="Category name"
      className="rounded px-1.5 py-0.5 text-[11px] uppercase tracking-[0.12em] text-slate-100"
      style={inputBox}
    />
  );
}

// Slim collapsible group header that clusters a project's tasks by category.
function CategoryRow({
  label,
  editInitial,
  count,
  open,
  editing,
  onToggle,
  onContextMenu,
  onRename,
  onCancelRename,
  onDropItem,
}: {
  label: string;
  editInitial: string;
  count: number;
  open: boolean;
  editing: boolean;
  onToggle: () => void;
  onContextMenu: (event: ReactMouseEvent) => void;
  onRename: (next: string) => void;
  onCancelRename: () => void;
  onDropItem: (itemId: string) => void;
}) {
  const [over, setOver] = useState(false);
  return (
    <div
      className="flex min-w-[920px] items-center gap-2 border-t px-3 py-1.5 text-[11px] transition"
      style={{
        paddingLeft: 28,
        borderColor: 'rgba(74, 210, 255, .09)',
        background: over ? 'rgba(36,217,255,.22)' : 'rgba(28,210,255,.06)',
        boxShadow: over ? 'inset 0 0 0 1px rgba(36,217,255,.6)' : undefined,
        color: '#9edff5',
        cursor: editing ? 'default' : 'pointer',
      }}
      onClick={editing ? undefined : onToggle}
      onContextMenu={onContextMenu}
      onDragOver={(event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = 'move';
        if (!over) setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(event) => {
        event.preventDefault();
        setOver(false);
        const itemId = event.dataTransfer.getData('text/plain');
        if (itemId) onDropItem(itemId);
      }}
    >
      {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
      <Tag size={12} />
      {editing ? (
        <CategoryNameEditor
          initial={editInitial}
          onCommit={onRename}
          onCancel={onCancelRename}
        />
      ) : (
        <>
          <span className="font-semibold uppercase tracking-[0.12em]">
            {label}
          </span>
          <span className="text-slate-500">({count})</span>
        </>
      )}
    </div>
  );
}

type GanttMenuTarget =
  | { kind: 'item'; item: GanttItem }
  | { kind: 'category'; project: GanttItem; category: string; label: string };
type GanttMenuState = { x: number; y: number; target: GanttMenuTarget };

type GanttDisplayRow =
  | { kind: 'item'; item: GanttItem }
  | {
      kind: 'category';
      id: string;
      project: GanttItem;
      category: string;
      label: string;
      count: number;
    };

function GanttContextMenu({
  state,
  onClose,
  onAction,
}: {
  state: GanttMenuState;
  onClose: () => void;
  onAction: (action: string) => void;
}) {
  const { target } = state;
  const actions: { key: string; label: string; danger?: boolean }[] =
    target.kind === 'category'
      ? [
          ...(target.category
            ? [
                { key: 'rename-cat', label: 'Edit name' },
                { key: 'delete-category', label: `Delete Category…`, danger: true },
              ]
            : []),
          { key: 'add-task-cat', label: `Add Task in “${target.label}”` },
        ]
      : target.item.type === 'project'
        ? [
            { key: 'add-task', label: 'Add Task' },
            { key: 'add-category', label: 'Add Category' },
            { key: 'add-milestone', label: 'Add Milestone' },
            { key: 'edit', label: 'Edit…' },
            { key: 'delete-project', label: 'Delete Project…', danger: true },
          ]
        : [
            { key: 'add-subtask', label: 'Add Subtask' },
            { key: 'add-milestone', label: 'Add Milestone' },
            { key: 'edit', label: 'Edit…' },
            { key: 'delete-task', label: 'Delete Task…', danger: true },
          ];
  return (
    <div
      className="fixed inset-0 z-50"
      onClick={onClose}
      onContextMenu={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <div
        className="absolute min-w-[180px] rounded-lg p-1 text-xs"
        style={{
          left: Math.min(state.x, window.innerWidth - 210),
          top: Math.min(state.y, window.innerHeight - 170),
          ...panelStyle,
          border: '1px solid rgba(74,210,255,.32)',
          boxShadow:
            '0 18px 50px rgba(0,0,0,.55), 0 0 28px rgba(36,217,255,.14)',
        }}
        onClick={(event) => event.stopPropagation()}
      >
        {actions.map((action) => (
          <button
            key={action.key}
            className={
              action.danger
                ? 'flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-red-300 hover:bg-red-500/10'
                : 'flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-slate-200 hover:bg-cyan-400/10'
            }
            onClick={() => onAction(action.key)}
          >
            {action.key === 'delete-project' || action.key === 'delete-task' || action.key === 'delete-category' ? (
              <Trash2 size={12} className="text-red-300" />
            ) : action.key === 'edit' || action.key === 'rename-cat' ? (
              <Info size={12} className="text-cyan-300" />
            ) : action.key === 'add-category' ? (
              <Tag size={12} className="text-cyan-300" />
            ) : (
              <Plus size={12} className="text-cyan-300" />
            )}
            {action.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function GanttChart({
  items,
  selectedId,
  onSelect,
  onEdit,
  view,
  onViewChange,
  onRequestAdd,
  onRequestAddMilestone,
  onRequestAddCategory,
  onRenameCategory,
  onAssignCategory,
  onDeleteItem,
  onDeleteCategory,
  onDeleteProject,
  extraCategoriesByProject,
}: {
  items: GanttItem[];
  selectedId: string;
  onSelect: (item: GanttItem) => void;
  onEdit: (item: GanttItem) => void;
  view: string;
  onViewChange: (value: string) => void;
  onRequestAdd: (
    parent: GanttItem,
    kind: 'task' | 'subtask',
    presetCategory?: string,
  ) => void;
  onRequestAddMilestone: (projectId: string) => void;
  onRequestAddCategory: (projectId: string) => void;
  onRenameCategory: (
    project: GanttItem,
    oldName: string,
    newName: string,
  ) => void;
  onAssignCategory: (
    itemId: string,
    project: GanttItem,
    category: string,
  ) => void;
  onDeleteItem: (item: GanttItem) => void;
  onDeleteCategory: (project: GanttItem, category: string, label: string) => void;
  onDeleteProject: (project: GanttItem) => void;
  extraCategoriesByProject: Record<string, string[]>;
}) {
  const axis = useAxis();
  // Projects collapsed by default — only top-level project rows show on
  // load; expanding a project reveals its tasks.
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  // Gantt scope filter (controlled by the page): 'all', a specific
  // projectId, or 'blocked'.
  const viewFilter = view;
  const projectOptions = useMemo(
    () => items.filter((item) => item.type === 'project'),
    [items],
  );
  const childCountByParent = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const item of items) {
      if (item.parentId) {
        counts[item.parentId] = (counts[item.parentId] || 0) + 1;
      }
    }
    return counts;
  }, [items]);
  // Build the rendered row list: project → category headers → tasks/subtasks.
  // Tasks/subtasks keep their parent→child nesting; top-level tasks of a
  // project are clustered under collapsible category headers.
  const rows = useMemo<GanttDisplayRow[]>(() => {
    if (viewFilter === 'blocked') {
      // Blocked view stays a flat surfacing of every blocker.
      return items
        .filter((item) => item.status === 'Blocked')
        .map((item) => ({ kind: 'item' as const, item }));
    }
    const scoped =
      viewFilter === 'all'
        ? items
        : items.filter((item) => item.projectId === viewFilter);
    const childrenOf = (id: string) =>
      scoped.filter((candidate) => candidate.parentId === id);
    const out: GanttDisplayRow[] = [];
    const pushSubtree = (task: GanttItem) => {
      out.push({ kind: 'item', item: task });
      if (expanded[task.id] ?? false) {
        for (const child of childrenOf(task.id)) pushSubtree(child);
      }
    };
    for (const project of scoped.filter((i) => i.type === 'project')) {
      out.push({ kind: 'item', item: project });
      if (!(expanded[project.id] ?? false)) continue;
      const topTasks = scoped.filter(
        (i) => i.parentId === project.id && i.type === 'task',
      );
      const order: string[] = [];
      const groups = new Map<string, GanttItem[]>();
      for (const task of topTasks) {
        const key = (task.category && task.category.trim()) || '';
        if (!groups.has(key)) {
          groups.set(key, []);
          order.push(key);
        }
        groups.get(key)!.push(task);
      }
      // Explicitly-created categories show as empty headers until tasks
      // are added or dragged into them.
      for (const name of extraCategoriesByProject[project.projectId] ?? []) {
        const key = name.trim();
        if (key && !groups.has(key)) {
          groups.set(key, []);
          order.push(key);
        }
      }
      const named = order.filter((key) => key !== '');
      const finalOrder = groups.has('') ? [...named, ''] : named;
      for (const key of finalOrder) {
        const group = groups.get(key)!;
        const catId = `cat:${project.id}:${key || '__uncat__'}`;
        out.push({
          kind: 'category',
          id: catId,
          project,
          category: key,
          label: key || 'Uncategorized',
          count: group.length,
        });
        // Categories default to open so tasks are visible once a project
        // is expanded.
        if (!(expanded[catId] ?? true)) continue;
        for (const task of group) pushSubtree(task);
      }
    }
    return out;
  }, [expanded, items, viewFilter, extraCategoriesByProject]);
  const toggleExpanded = (id: string) =>
    setExpanded((current) => ({ ...current, [id]: !current[id] }));
  const toggleCategory = (id: string) =>
    setExpanded((current) => ({ ...current, [id]: !(current[id] ?? true) }));
  const openRow = (id: string) =>
    setExpanded((current) => ({ ...current, [id]: true }));

  const [menu, setMenu] = useState<GanttMenuState | null>(null);
  const [editingCatId, setEditingCatId] = useState<string | null>(null);
  const closeMenu = () => setMenu(null);
  const handleRowContextMenu = (event: ReactMouseEvent, item: GanttItem) => {
    event.preventDefault();
    setMenu({
      x: event.clientX,
      y: event.clientY,
      target: { kind: 'item', item },
    });
  };
  const handleMenuAction = (action: string) => {
    if (!menu) return;
    const { target } = menu;
    if (target.kind === 'category') {
      if (action === 'rename-cat') {
        openRow(target.project.id);
        setEditingCatId(
          `cat:${target.project.id}:${target.category || '__uncat__'}`,
        );
      } else if (action === 'add-task-cat') {
        openRow(target.project.id);
        onRequestAdd(target.project, 'task', target.category || undefined);
      } else if (action === 'delete-category') {
        onDeleteCategory(target.project, target.category, target.label);
      }
    } else if (action === 'edit') {
      onEdit(target.item);
    } else if (action === 'add-milestone') {
      onRequestAddMilestone(target.item.projectId);
    } else if (action === 'add-category') {
      openRow(target.item.id);
      onRequestAddCategory(target.item.projectId);
    } else if (action === 'add-task') {
      openRow(target.item.id);
      onRequestAdd(target.item, 'task');
    } else if (action === 'add-subtask') {
      openRow(target.item.id);
      onRequestAdd(target.item, 'subtask');
    } else if (action === 'delete-task') {
      onDeleteItem(target.item);
    } else if (action === 'delete-project') {
      onDeleteProject(target.item);
    }
    closeMenu();
  };

  return (
    <section className="rounded-lg" style={panelStyle}>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3" style={{ borderColor: 'rgba(74, 210, 255, .14)' }}>
        <div>
          <h2 className="text-sm font-semibold" style={{ color: '#eef9ff' }}>
            Project Timeline (Gantt)
          </h2>
          <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
            Live schedule across projects, subtasks, dependencies, and agent execution.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button className="rounded-md px-2 py-1 text-xs" style={{ border: '1px solid rgba(74,210,255,.22)', color: '#cdefff' }}>
            Today
          </button>
          <select
            className="rounded-md px-2 py-1 text-xs"
            style={{ background: 'rgba(5,10,18,.9)', border: '1px solid rgba(74,210,255,.22)', color: '#cdefff' }}
            value={viewFilter}
            onChange={(event) => onViewChange(event.target.value)}
          >
            <option value="all">View: All Projects</option>
            {projectOptions.map((project) => (
              <option key={project.id} value={project.projectId}>
                {project.name}
              </option>
            ))}
            <option value="blocked">Blocked only</option>
          </select>
          <button className="rounded-md p-1.5" style={{ border: '1px solid rgba(74,210,255,.22)', color: '#cdefff' }}>
            <Search size={14} />
          </button>
          <button className="rounded-md p-1.5" style={{ border: '1px solid rgba(74,210,255,.22)', color: '#cdefff' }}>
            <MoreVertical size={14} />
          </button>
        </div>
      </div>
      <div className="max-h-[56vh] overflow-auto">
        <div className="min-w-[920px]">
          <div
            className="sticky top-0 z-10 grid border-b text-[11px]"
            style={{
              gridTemplateColumns: '250px 92px 108px 54px minmax(430px,1fr)',
              borderColor: 'rgba(74, 210, 255, .12)',
              color: '#9eb0bf',
              background: 'rgba(9,15,25,.98)',
            }}
          >
            <div className="px-3 py-2">Project / Task</div>
            <div className="py-2">Owner / Agent</div>
            <div className="py-2">Status</div>
            <div className="py-2">%</div>
            <div className="relative grid grid-cols-11 border-l" style={{ borderColor: 'rgba(74, 210, 255, .12)' }}>
              {axis.labels.map((week, idx) => (
                <div
                  key={`${week}-${idx}`}
                  className="border-r px-1 py-2 text-center"
                  style={{
                    borderColor: 'rgba(74, 210, 255, .08)',
                    color:
                      Math.round(axis.todayPos) === idx ? '#27d9ff' : '#9eb0bf',
                  }}
                >
                  {week}
                </div>
              ))}
              <div
                className="absolute bottom-0 top-0 w-px"
                style={{
                  left: `${(axis.todayPos / axis.denom) * 100}%`,
                  background: '#1bcfff',
                  boxShadow: '0 0 14px rgba(27,207,255,.7)',
                }}
              />
            </div>
          </div>
          {rows.map((row) =>
            row.kind === 'category' ? (
              <CategoryRow
                key={row.id}
                label={row.label}
                editInitial={row.category}
                count={row.count}
                open={expanded[row.id] ?? true}
                editing={editingCatId === row.id}
                onRename={(next) => {
                  setEditingCatId(null);
                  const trimmed = next.trim();
                  if (trimmed && trimmed !== row.category) {
                    onRenameCategory(row.project, row.category, trimmed);
                  }
                }}
                onCancelRename={() => setEditingCatId(null)}
                onDropItem={(itemId) =>
                  onAssignCategory(itemId, row.project, row.category)
                }
                onToggle={() => toggleCategory(row.id)}
                onContextMenu={(event) => {
                  event.preventDefault();
                  setMenu({
                    x: event.clientX,
                    y: event.clientY,
                    target: {
                      kind: 'category',
                      project: row.project,
                      category: row.category,
                      label: row.label,
                    },
                  });
                }}
              />
            ) : (
              <GanttRow
                key={row.item.id}
                item={row.item}
                selected={selectedId === row.item.id}
                onSelect={onSelect}
                onEdit={onEdit}
                hasChildren={Boolean(childCountByParent[row.item.id])}
                expanded={expanded[row.item.id] ?? false}
                onToggle={toggleExpanded}
                onContextMenu={handleRowContextMenu}
              />
            ),
          )}
        </div>
      </div>
      <div className="flex flex-wrap gap-4 border-t px-4 py-3 text-[11px]" style={{ borderColor: 'rgba(74, 210, 255, .12)', color: '#b8c7d5' }}>
        {[
          ['On Track', 'cyan'],
          ['At Risk', 'amber'],
          ['Blocked', 'red'],
          ['Completed', 'green'],
          ['Milestone', 'purple'],
          ['Today', 'cyan'],
        ].map(([label, accent]) => (
          <span key={label} className="flex items-center gap-1.5">
            <span
              className={label === 'Milestone' ? 'h-2.5 w-2.5 rotate-45' : 'h-2 w-5 rounded-sm'}
              style={{ background: accentMap[accent as Accent].text }}
            />
            {label}
          </span>
        ))}
      </div>
      {menu && (
        <GanttContextMenu
          state={menu}
          onClose={closeMenu}
          onAction={handleMenuAction}
        />
      )}
    </section>
  );
}

function ProgressRing({ value }: { value: number }) {
  return (
    <div
      className="grid h-24 w-24 place-items-center rounded-full"
      style={{
        background: `conic-gradient(#24d9ff ${value * 3.6}deg, rgba(255,255,255,.08) 0deg)`,
        boxShadow: '0 0 22px rgba(36,217,255,.22)',
      }}
    >
      <div className="grid h-[78px] w-[78px] place-items-center rounded-full bg-[#07101a]">
        <div className="text-center">
          <div className="text-xl font-semibold text-white">{value}%</div>
          <div className="text-[10px] text-slate-400">Complete</div>
        </div>
      </div>
    </div>
  );
}

function AgentChip({ name, role }: { name: string; role: string }) {
  return (
    <button className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-left transition hover:bg-cyan-400/10" style={{ border: '1px solid rgba(74,210,255,.16)' }}>
      <Bot size={14} style={{ color: '#24d9ff' }} />
      <span>
        <span className="block text-xs text-slate-100">{name}</span>
        <span className="block text-[10px] text-slate-500">{role}</span>
      </span>
    </button>
  );
}

function ProjectDetailsPanel({
  project,
  agents,
  milestones,
  onAddMilestone,
  onToggleMilestone,
  onDeleteMilestone,
  onDeleteProject,
}: {
  project: GanttItem | undefined;
  agents: ManagedAgent[];
  milestones: Milestone[];
  onAddMilestone: (name: string, date: string) => void;
  onToggleMilestone: (id: string) => void;
  onDeleteMilestone: (id: string) => void;
  onDeleteProject: (project: GanttItem) => void;
}) {
  const axis = useAxis();
  const visibleAgents = agents.slice(0, 3);
  const [newName, setNewName] = useState('');
  const [newDate, setNewDate] = useState('');
  const dueDate = project
    ? axis.labels[
        _clamp(Math.round(project.end), 0, axis.labels.length - 1)
      ] || '—'
    : '—';
  const submitMilestone = () => {
    const name = newName.trim();
    if (!name) return;
    onAddMilestone(name, newDate.trim() || 'TBD');
    setNewName('');
    setNewDate('');
  };
  return (
    <section className="rounded-lg p-4" style={panelStyle}>
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <div className="mb-2 flex items-center gap-2">
            <FolderKanban size={15} style={{ color: '#24d9ff' }} />
            <h3 className="text-sm font-semibold text-white">
              {project?.name || 'No project selected'}
            </h3>
            {project && <StatusBadge status={project.status} />}
          </div>
          <div className="grid grid-cols-2 gap-3 text-xs">
            <div>
              <div className="text-slate-500">Owner / Lead</div>
              <div className="text-slate-200">
                {project?.agent || visibleAgents[0]?.name || 'Unassigned'}
              </div>
            </div>
            <div>
              <div className="text-slate-500">Due Date</div>
              <div className="text-slate-200">{dueDate}</div>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {project && (
            <button
              type="button"
              onClick={() => onDeleteProject(project)}
              className="rounded-md p-2 text-slate-500 transition hover:bg-red-500/10 hover:text-red-300"
              title="Delete project"
            >
              <Trash2 size={15} />
            </button>
          )}
          <ProgressRing value={project?.progress ?? 0} />
        </div>
      </div>
      <div className="space-y-4">
        <div>
          <div className="mb-2 flex items-center justify-between text-xs text-slate-300">
            <span>Key Milestones</span>
            <button className="text-cyan-300">View all</button>
          </div>
          {milestones.length === 0 && (
            <div className="mb-2 rounded px-1 py-1 text-xs text-slate-500">
              No milestones yet.
            </div>
          )}
          {milestones.map((milestone) => (
            <div
              key={milestone.id}
              className="group mb-1 flex w-full items-center justify-between rounded px-1 py-1 text-xs hover:bg-cyan-400/10"
            >
              <button
                type="button"
                onClick={() => onToggleMilestone(milestone.id)}
                className="flex flex-1 items-center gap-2 text-left text-slate-300"
                title="Toggle complete"
              >
                {milestone.done ? (
                  <CheckCircle2 size={13} className="text-emerald-400" />
                ) : (
                  <CircleDot size={13} className="text-slate-500" />
                )}
                {milestone.name}
              </button>
              <span className="flex items-center gap-2">
                <span className="text-slate-500">{milestone.date}</span>
                <button
                  type="button"
                  onClick={() => onDeleteMilestone(milestone.id)}
                  className="text-slate-600 opacity-0 transition group-hover:opacity-100 hover:text-red-400"
                  title="Delete milestone"
                >
                  <Trash2 size={12} />
                </button>
              </span>
            </div>
          ))}
          <div className="mt-2 flex items-center gap-1">
            <input
              value={newName}
              onChange={(event) => setNewName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') submitMilestone();
              }}
              placeholder="New milestone"
              className="min-w-0 flex-1 rounded px-2 py-1 text-xs text-slate-100"
              style={{ background: 'rgba(5,10,18,.9)', border: '1px solid rgba(74,210,255,.18)' }}
            />
            <input
              value={newDate}
              onChange={(event) => setNewDate(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') submitMilestone();
              }}
              placeholder="Date"
              className="w-16 rounded px-2 py-1 text-xs text-slate-100"
              style={{ background: 'rgba(5,10,18,.9)', border: '1px solid rgba(74,210,255,.18)' }}
            />
            <button
              type="button"
              onClick={submitMilestone}
              disabled={!newName.trim()}
              className="rounded p-1 text-cyan-300 disabled:opacity-40"
              style={{ border: '1px solid rgba(74,210,255,.22)' }}
              title="Add milestone"
            >
              <Plus size={13} />
            </button>
          </div>
        </div>
        <div className="rounded-lg p-3" style={{ background: 'rgba(255,78,97,.08)', border: '1px solid rgba(255,78,97,.18)' }}>
          <div className="mb-1 flex items-center gap-2 text-xs text-red-300">
            <AlertTriangle size={14} /> 3rd-party API rate limits may impact testing
          </div>
          <div className="text-[11px] text-slate-400">Mitigation: In progress</div>
        </div>
        <div>
          <div className="mb-2 text-xs text-slate-300">Assigned Agents</div>
          <div className="grid grid-cols-2 gap-2">
            {visibleAgents.length ? (
              visibleAgents.map((agent) => (
                <AgentChip
                  key={agent.id}
                  name={agent.name}
                  role={agent.org_role || agent.agent_type}
                />
              ))
            ) : (
              <div className="col-span-2 rounded-md px-2 py-2 text-xs text-slate-500" style={{ border: '1px solid rgba(74,210,255,.12)' }}>
                No agents assigned yet.
              </div>
            )}
          </div>
        </div>
        <button className="w-full rounded-md px-3 py-2 text-xs font-medium" style={{ background: 'rgba(36,217,255,.12)', border: '1px solid rgba(36,217,255,.24)', color: '#8eeeff' }}>
          Next Action: Review integration blocker
        </button>
      </div>
    </section>
  );
}

function TaskInspectorPanel({ selected }: { selected: GanttItem }) {
  const fieldStyle = {
    background: 'rgba(0,0,0,.28)',
    border: '1px solid rgba(74,210,255,.16)',
  };
  const accent = accentMap[selected.accent];
  return (
    <section className="rounded-lg p-4" style={panelStyle}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <h3 className="text-sm font-semibold text-white">Task Inspector</h3>
          <span
            className="truncate rounded-full px-2 py-0.5 text-[11px]"
            style={{
              color: accent.text,
              background: accent.glow,
              border: `1px solid ${accent.glow}`,
            }}
          >
            {selected.name}
          </span>
          <span className="hidden text-[11px] text-slate-500 sm:inline">
            selected from timeline
          </span>
        </div>
        <MoreVertical size={15} className="text-slate-500" />
      </div>
      <div className="grid gap-3 text-xs sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        <label className="block">
          <span className="mb-1 block text-slate-500">Task</span>
          <input value={selected.name} readOnly className="w-full rounded-md px-2 py-1.5 text-slate-100" style={fieldStyle} />
        </label>
        <label className="block">
          <span className="mb-1 block text-slate-500">Status</span>
          <select value={selected.status} onChange={() => {}} className="w-full rounded-md px-2 py-1.5" style={{ ...fieldStyle, color: accent.text }}>
            <option>{selected.status}</option>
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-slate-500">Priority</span>
          <select value={selected.blocker ? 'High' : 'Medium'} onChange={() => {}} className="w-full rounded-md px-2 py-1.5 text-slate-100" style={fieldStyle}>
            <option>{selected.blocker ? 'High' : 'Medium'}</option>
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-slate-500">Assignee</span>
          <select value={selected.agent} onChange={() => {}} className="w-full rounded-md px-2 py-1.5 text-slate-100" style={fieldStyle}>
            <option>{selected.agent}</option>
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-slate-500">Start</span>
          <input value="Apr 22, 2025" readOnly className="w-full rounded-md px-2 py-1.5 text-slate-100" style={fieldStyle} />
        </label>
        <label className="block">
          <span className="mb-1 block text-slate-500">End</span>
          <input value="May 23, 2025" readOnly className="w-full rounded-md px-2 py-1.5 text-slate-100" style={fieldStyle} />
        </label>
      </div>
      <div className="mt-3 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
        <div className="space-y-3 text-xs">
          <div>
            <div className="mb-1 flex justify-between text-slate-500">
              <span>Progress</span>
              <span style={{ color: accent.text }}>{selected.progress}%</span>
            </div>
            <div className="h-2 rounded-full bg-slate-800">
              <div className="h-full rounded-full" style={{ width: `${selected.progress}%`, background: accent.text }} />
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button className="rounded px-2 py-1 text-[11px] text-slate-200" style={{ background: 'rgba(255,255,255,.06)' }}>
              Requirements & Design x
            </button>
            <button className="flex items-center gap-1 rounded px-2 py-1 text-[11px] text-cyan-200" style={{ border: '1px solid rgba(74,210,255,.22)' }}>
              <Plus size={12} /> Add dependency
            </button>
          </div>
        </div>
        <label className="block text-xs">
          <span className="mb-1 block text-slate-500">Notes</span>
          <textarea
            readOnly
            value="Develop core processing engine and API contracts. Confirm rate-limit mitigation before integration hardening."
            className="h-[4.5rem] w-full resize-none rounded-md px-2 py-1.5 text-slate-200"
            style={fieldStyle}
          />
        </label>
      </div>
    </section>
  );
}

function AgentActivityPanel({ agents }: { agents: ManagedAgent[] }) {
  const rows = agents.slice(0, 3).map((agent, index) => [
    agent.name,
    agent.current_activity ||
      ['Reviewing assigned work', 'Waiting for next runnable task', 'Idle'][index],
    `${index * 2 + 2}m ago`,
  ]);
  return (
    <section className="rounded-lg p-4" style={panelStyle}>
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-white">Agent Activity</h3>
        <span className="flex items-center gap-1 text-[11px] text-emerald-300">
          Live <span className="h-1.5 w-1.5 rounded-full bg-emerald-300" />
        </span>
      </div>
      {(rows.length ? rows : [['No agent assigned', 'No live activity', '']]).map(([agent, action, time]) => (
        <button key={agent} className="mb-2 flex w-full items-center gap-3 rounded-md px-2 py-1.5 text-left hover:bg-cyan-400/10">
          <Bot size={16} style={{ color: '#24d9ff' }} />
          <span className="min-w-0 flex-1">
            <span className="block text-xs text-slate-100">{agent}</span>
            <span className="block truncate text-[11px] text-slate-400">{action}</span>
          </span>
          <span className="text-[10px] text-slate-500">{time}</span>
        </button>
      ))}
    </section>
  );
}

function _relTime(epochSeconds: number): string {
  const secs = Date.now() / 1000 - epochSeconds;
  if (!Number.isFinite(secs) || secs < 0) return '';
  if (secs < 60) return 'just now';
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}

function MilestoneTimeline({ milestones }: { milestones: Milestone[] }) {
  const shown = milestones.slice(0, 6);
  return (
    <section className="rounded-lg p-4" style={panelStyle}>
      <div className="mb-4 flex justify-between">
        <h3 className="text-sm font-semibold text-white">Milestones</h3>
        <span className="text-xs text-slate-500">{milestones.length} total</span>
      </div>
      {shown.length === 0 ? (
        <div className="px-2 py-4 text-xs text-slate-500">
          No milestones for this project yet.
        </div>
      ) : (
        <div className="relative flex justify-between px-2 pt-5 text-center text-[11px] text-slate-400">
          <div className="absolute left-8 right-8 top-7 h-px bg-slate-700" />
          {shown.map((m) => (
            <div key={m.id} className="relative max-w-[92px]">
              <span
                className="mx-auto mb-3 block h-4 w-4 rotate-45"
                style={{
                  background: m.done ? '#28f0a0' : '#8793a1',
                  boxShadow: m.done ? '0 0 16px rgba(40,240,160,.28)' : undefined,
                }}
              />
              <span className="block text-slate-300">{m.date || 'TBD'}</span>
              <span className="block">{m.name}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function RiskList({
  items,
  atRiskProjects,
}: {
  items: GanttItem[];
  atRiskProjects: { id: string; name: string; status: string }[];
}) {
  const blocked = items.filter(
    (i) => i.type === 'task' && i.status === 'Blocked',
  );
  const atRiskTasks = items.filter(
    (i) => i.type === 'task' && i.status === 'At Risk',
  );
  const empty =
    blocked.length === 0 &&
    atRiskTasks.length === 0 &&
    atRiskProjects.length === 0;
  return (
    <section className="rounded-lg p-4" style={panelStyle}>
      <div className="mb-3 flex justify-between">
        <h3 className="text-sm font-semibold text-white">
          Dependencies & Risks
        </h3>
        <span className="text-xs text-slate-500">
          {blocked.length + atRiskTasks.length + atRiskProjects.length}
        </span>
      </div>
      {empty && (
        <div className="px-2 py-3 text-xs text-slate-500">
          No blocked or at-risk work. 🎉
        </div>
      )}
      {blocked.length > 0 && (
        <div className="mb-3 text-xs">
          <div className="mb-1 text-slate-500">Blocked</div>
          {blocked.slice(0, 5).map((t) => (
            <div
              key={t.id}
              className="mb-1 flex w-full items-center justify-between rounded px-2 py-1 hover:bg-cyan-400/10"
            >
              <span className="flex min-w-0 items-center gap-1 text-slate-300">
                <GitBranch
                  size={12}
                  className="shrink-0 text-cyan-300"
                />
                <span className="truncate">{t.name}</span>
              </span>
              <span style={{ color: accentMap.red.text }}>High</span>
            </div>
          ))}
        </div>
      )}
      {(atRiskTasks.length > 0 || atRiskProjects.length > 0) && (
        <div className="text-xs">
          <div className="mb-1 text-slate-500">At risk</div>
          {atRiskProjects.map((p) => (
            <div
              key={`p-${p.id}`}
              className="mb-1 flex w-full items-center justify-between rounded px-2 py-1 hover:bg-cyan-400/10"
            >
              <span className="truncate text-slate-300">
                {p.name} (project)
              </span>
              <span style={{ color: accentMap.amber.text }}>{p.status}</span>
            </div>
          ))}
          {atRiskTasks.slice(0, 5).map((t) => (
            <div
              key={t.id}
              className="mb-1 flex w-full items-center justify-between rounded px-2 py-1 hover:bg-cyan-400/10"
            >
              <span className="truncate text-slate-300">{t.name}</span>
              <span style={{ color: accentMap.amber.text }}>Medium</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function RecentActivity({
  tasks,
  projectName,
}: {
  tasks: Task[];
  projectName: (id: string) => string;
}) {
  const recent = [...tasks]
    .filter((t) => Number.isFinite(t.updated_at))
    .sort((a, b) => b.updated_at - a.updated_at)
    .slice(0, 6);
  return (
    <section className="rounded-lg p-4" style={panelStyle}>
      <div className="mb-3 flex justify-between">
        <h3 className="text-sm font-semibold text-white">Recent Activity</h3>
        <span className="text-xs text-slate-500">live</span>
      </div>
      {recent.length === 0 ? (
        <div className="px-2 py-3 text-xs text-slate-500">
          No recent task activity.
        </div>
      ) : (
        recent.map((t) => (
          <div
            key={t.id}
            className="mb-2 flex w-full gap-2 rounded text-left text-xs"
          >
            <Activity size={13} className="mt-0.5 shrink-0 text-cyan-300" />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-slate-300">
                {(t.assigned_to || t.owner || 'Unassigned')} · {t.title}
              </span>
              <span className="block truncate text-[10px] text-slate-500">
                {t.status} · {projectName(t.project_id)}
              </span>
            </span>
            <span className="shrink-0 text-[10px] text-slate-500">
              {_relTime(t.updated_at)}
            </span>
          </div>
        ))
      )}
    </section>
  );
}

function WorkloadChart({
  agents,
  items,
}: {
  agents: ManagedAgent[];
  items: GanttItem[];
}) {
  const rows = useMemo(() => {
    const realAgents = agents.filter((agent) => agent.status !== 'archived');
    if (!realAgents.length) {
      return [{ name: 'Unassigned', pct: 0, accent: 'cyan' as Accent }];
    }
    return realAgents.map((agent) => {
      const activeItems = items.filter(
        (item) =>
          item.agent === agent.name &&
          item.type === 'task' &&
          item.status !== 'Done',
      );
      const pct = Math.min(120, activeItems.length * 22);
      return {
        name: agent.name,
        pct,
        accent: pct >= 100 ? ('amber' as Accent) : ('cyan' as Accent),
      };
    });
  }, [agents, items]);
  return (
    <section className="rounded-lg p-4" style={panelStyle}>
      <div className="mb-3 flex justify-between">
        <h3 className="text-sm font-semibold text-white">Workload by Agent</h3>
        <button className="text-xs text-cyan-300">View all</button>
      </div>
      <div className="space-y-2">
        {rows.map(({ name, pct, accent }) => (
          <button key={name} className="grid w-full grid-cols-[58px_1fr_36px] items-center gap-2 text-xs">
            <span className="text-left text-slate-300">{name}</span>
            <span className="h-2 rounded-full bg-slate-800">
              <span
                className="block h-full rounded-full"
                style={{
                  width: `${Math.min(Number(pct), 120)}%`,
                  background: accentMap[accent].text,
                }}
              />
            </span>
            <span style={{ color: accentMap[accent].text }}>
              {pct}%
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}

function CreateProjectPanel({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const [name, setName] = useState('');
  const [owner, setOwner] = useState('');
  const [status, setStatus] = useState<Project['status']>('Planning');
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      await createProject({
        name: name.trim(),
        owner: owner.trim(),
        status,
      });
      onCreated();
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="mb-4 grid gap-3 rounded-lg p-4 md:grid-cols-[1fr_220px_180px_auto]" style={panelStyle}>
      <input
        autoFocus
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Project name"
        className="rounded-md px-3 py-2 text-sm text-slate-100"
        style={{ background: 'rgba(0,0,0,.32)', border: '1px solid rgba(74,210,255,.18)' }}
      />
      <input
        value={owner}
        onChange={(e) => setOwner(e.target.value)}
        placeholder="Owner / lead agent"
        className="rounded-md px-3 py-2 text-sm text-slate-100"
        style={{ background: 'rgba(0,0,0,.32)', border: '1px solid rgba(74,210,255,.18)' }}
      />
      <select
        value={status}
        onChange={(e) => setStatus(e.target.value as Project['status'])}
        className="rounded-md px-3 py-2 text-sm text-slate-100"
        style={{ background: 'rgba(0,0,0,.32)', border: '1px solid rgba(74,210,255,.18)' }}
      >
        {PROJECT_STATUSES.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
      <button
        onClick={submit}
        disabled={busy || !name.trim()}
        className="rounded-md px-4 py-2 text-sm disabled:opacity-50"
        style={{ background: '#24d9ff', color: '#031018' }}
      >
        Create
      </button>
    </section>
  );
}

// Category picker shared by the quick-add and edit dialogs. Lists the
// project's existing categories and lets the user define a new one inline.
function CategorySelect({
  value,
  categories,
  onChange,
}: {
  value: string;
  categories: string[];
  onChange: (next: string) => void;
}) {
  const ADD = '__add__';
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState('');
  const commit = () => {
    const next = draft.trim();
    if (next) onChange(next);
    setAdding(false);
    setDraft('');
  };
  if (adding) {
    return (
      <div className="flex items-center gap-1">
        <input
          autoFocus
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault();
              commit();
            }
            if (event.key === 'Escape') setAdding(false);
          }}
          placeholder="New category name"
          className="w-full rounded-md px-3 py-2 text-sm text-slate-100"
          style={inputBox}
        />
        <button
          type="button"
          onClick={commit}
          className="rounded-md px-3 py-2 text-xs text-cyan-200"
          style={{ border: '1px solid rgba(74,210,255,.22)' }}
        >
          Add
        </button>
      </div>
    );
  }
  return (
    <select
      value={value}
      onChange={(event) => {
        if (event.target.value === ADD) {
          setDraft('');
          setAdding(true);
          return;
        }
        onChange(event.target.value);
      }}
      className="w-full rounded-md px-3 py-2 text-sm text-slate-100"
      style={inputBox}
    >
      <option value="">Uncategorized</option>
      {categories.map((category) => (
        <option key={category} value={category}>
          {category}
        </option>
      ))}
      <option value={ADD}>+ Add new category…</option>
    </select>
  );
}

// Lightweight modal for manually adding a task, subtask, or milestone from
// the Gantt right-click menu. Keeps the polished look of the other dialogs.
function QuickAddModal({
  mode,
  parentName,
  categories,
  presetCategory,
  onSubmit,
  onClose,
}: {
  mode: 'task' | 'subtask' | 'milestone' | 'category';
  parentName: string;
  categories: string[];
  presetCategory?: string;
  onSubmit: (data: { name: string; category?: string; date?: string }) => void;
  onClose: () => void;
}) {
  const noun =
    mode === 'milestone'
      ? 'Milestone'
      : mode === 'subtask'
        ? 'Subtask'
        : mode === 'category'
          ? 'Category'
          : 'Task';
  const [name, setName] = useState('');
  const [category, setCategory] = useState(presetCategory ?? '');
  const [date, setDate] = useState('');
  const submit = () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    onSubmit(
      mode === 'milestone'
        ? { name: trimmed, date: date.trim() || 'TBD' }
        : mode === 'category'
          ? { name: trimmed }
          : { name: trimmed, category: category.trim() || undefined },
    );
    onClose();
  };
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-xl p-5"
        style={{
          ...panelStyle,
          border: '1px solid rgba(74, 210, 255, .32)',
          boxShadow:
            '0 24px 80px rgba(0,0,0,.55), 0 0 36px rgba(36,217,255,.16)',
        }}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-1 text-xs uppercase tracking-[0.18em] text-cyan-300">
          New {noun}
        </div>
        <h2 className="mb-4 truncate text-base font-semibold text-white">
          in {parentName}
        </h2>
        <div className="space-y-3">
          <label className="block">
            <span className="mb-1 block text-xs text-slate-500">
              {noun} name
            </span>
            <input
              autoFocus
              value={name}
              onChange={(event) => setName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault();
                  submit();
                }
              }}
              className="w-full rounded-md px-3 py-2 text-sm text-slate-100"
              style={inputBox}
            />
          </label>
          {(mode === 'task' || mode === 'subtask') && (
            <label className="block">
              <span className="mb-1 block text-xs text-slate-500">
                Category
              </span>
              <CategorySelect
                value={category}
                categories={categories}
                onChange={setCategory}
              />
            </label>
          )}
          {mode === 'milestone' && (
            <label className="block">
              <span className="mb-1 block text-xs text-slate-500">Date</span>
              <input
                value={date}
                onChange={(event) => setDate(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault();
                    submit();
                  }
                }}
                placeholder="e.g. Jun 13"
                className="w-full rounded-md px-3 py-2 text-sm text-slate-100"
                style={inputBox}
              />
            </label>
          )}
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button
            className="rounded-md px-4 py-2 text-xs text-slate-300"
            style={{ border: '1px solid rgba(74,210,255,.18)' }}
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            className="rounded-md px-4 py-2 text-xs font-semibold"
            style={{
              background: 'linear-gradient(180deg, #2be1ff, #1398c8)',
              color: '#031018',
            }}
            onClick={submit}
          >
            Add {noun}
          </button>
        </div>
      </div>
    </div>
  );
}

export function ProjectsPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState<GanttItem[]>([]);
  const [rawProjects, setRawProjects] = useState<Project[]>([]);
  const [rawTasks, setRawTasks] = useState<Task[]>([]);
  const [agents, setAgents] = useState<ManagedAgent[]>([]);
  const [selected, setSelected] = useState<GanttItem | null>(null);
  const [editing, setEditing] = useState<GanttItem | null>(null);
  const [creating, setCreating] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dash, setDash] = useState<ProjectDashboard | null>(null);
  const [axis, setAxis] = useState<Axis>(DEFAULT_AXIS);
  const [apiReachable, setApiReachable] = useState<boolean | null>(null);
  // Pending "quick add" request from the Gantt right-click menu.
  const [addReq, setAddReq] = useState<{
    mode: 'task' | 'subtask' | 'milestone' | 'category';
    parent?: GanttItem;
    projectId: string;
    presetCategory?: string;
  } | null>(null);
  // Gantt scope filter, shared so the details panel tracks the dropdown.
  const [ganttView, setGanttView] = useState<string>('all');
  const [milestonesByProject, setMilestonesByProject] = useState<
    Record<string, Milestone[]>
  >({});
  const selectedIdRef = useRef<string | null>(null);

  // Single source of truth: load projects/tasks from the SQLite store
  // (same data Mission Control and the agent tools use).
  const reload = useCallback(async (preferId?: string) => {
    try {
      const bundle = await getProjectBundle();
      // Hide the backend's "Unassigned Work" system catch-all (and any project
      // tagged "system") from the Projects section. Backend routing and Mission
      // Control still use it; it is simply not surfaced here.
      const hiddenProjectIds = new Set(
        bundle.projects
          .filter((p) => p.name === 'Unassigned Work' || (p.tags || []).includes('system'))
          .map((p) => p.id),
      );
      const projs = bundle.projects.filter((p) => !hiddenProjectIds.has(p.id));
      const tasksByProject = Object.fromEntries(
        Object.entries(bundle.tasks_by_project).filter(([pid]) => !hiddenProjectIds.has(pid)),
      ) as typeof bundle.tasks_by_project;
      const built = buildGanttData(projs, tasksByProject);
      setRawProjects(projs);
      setRawTasks(Object.values(tasksByProject).flat());
      setItems(built.items);
      setMilestonesByProject(built.milestonesByProject);
      setAxis(built.axis);
      const wantId = preferId ?? selectedIdRef.current;
      const nextSel =
        built.items.find((i) => i.id === wantId) ??
        built.items.find((i) => i.type === 'project') ??
        built.items[0] ??
        null;
      selectedIdRef.current = nextSel?.id ?? null;
      setSelected(nextSel);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load projects');
    } finally {
      setLoading(false);
    }
    try {
      setDash(await getDashboard());
    } catch {
      /* KPIs are best-effort */
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    reload();
    fetchManagedAgents()
      .then((loaded) =>
        setAgents(loaded.filter((a) => a.status !== 'archived')),
      )
      .catch(() => setAgents([]));
  }, [reload]);

  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      const reachable = await checkHealth();
      if (!cancelled) setApiReachable(reachable);
    };
    check();
    const interval = window.setInterval(check, 30000);
    const onFocus = () => check();
    window.addEventListener('focus', onFocus);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
      window.removeEventListener('focus', onFocus);
    };
  }, []);

  // Run a write, surface any error, then re-sync from the DB so the page
  // always matches the store (and Mission Control).
  const mutate = useCallback(
    async (op: () => Promise<unknown>, selectId?: string) => {
      try {
        await op();
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Action failed');
      } finally {
        await reload(selectId);
      }
    },
    [reload],
  );

  const handleSelect = useCallback((it: GanttItem) => {
    selectedIdRef.current = it.id;
    setSelected(it);
  }, []);

  const projects = useMemo(
    () => items.filter((item) => item.type === 'project'),
    [items],
  );
  const activeProject = useMemo(() => {
    if (ganttView !== 'all' && ganttView !== 'blocked') {
      const byView = projects.find((p) => p.projectId === ganttView);
      if (byView) return byView;
    }
    return (
      projects.find((p) => p.projectId === selected?.projectId) || projects[0]
    );
  }, [projects, ganttView, selected]);
  const activeProjectId = activeProject?.projectId ?? '';
  const activeMilestones = milestonesByProject[activeProjectId] ?? [];

  const extraCategoriesByProject = useMemo(() => {
    const map: Record<string, string[]> = {};
    for (const p of rawProjects) map[p.id] = p.categories ?? [];
    return map;
  }, [rawProjects]);
  const categoriesForProject = (projectId: string) =>
    Array.from(
      new Set([
        ...items
          .filter(
            (item) =>
              item.projectId === projectId &&
              item.type === 'task' &&
              item.category &&
              item.category.trim(),
          )
          .map((item) => item.category!.trim()),
        ...(extraCategoriesByProject[projectId] ?? []),
      ]),
    ).sort((a, b) => a.localeCompare(b));

  const persistMilestones = (projectId: string, list: Milestone[]) =>
    mutate(() => updateProject(projectId, { milestones: list }));
  const addProjectMilestone = (
    projectId: string,
    name: string,
    date: string,
  ) =>
    persistMilestones(projectId, [
      ...(milestonesByProject[projectId] ?? []),
      { id: `ms-${Date.now()}`, name, date, done: false },
    ]);
  const addMilestone = (name: string, date: string) =>
    addProjectMilestone(activeProjectId, name, date);
  const toggleMilestone = (id: string) => {
    if (!activeProjectId) return;
    persistMilestones(
      activeProjectId,
      (milestonesByProject[activeProjectId] ?? []).map((m) =>
        m.id === id ? { ...m, done: !m.done } : m,
      ),
    );
  };
  const deleteMilestone = (id: string) => {
    if (!activeProjectId) return;
    persistMilestones(
      activeProjectId,
      (milestonesByProject[activeProjectId] ?? []).filter((m) => m.id !== id),
    );
  };

  const addCategory = (projectId: string, name: string) => {
    const trimmed = name.trim();
    if (!trimmed) return;
    const existing = extraCategoriesByProject[projectId] ?? [];
    if (existing.includes(trimmed)) return;
    mutate(() =>
      updateProject(projectId, { categories: [...existing, trimmed] }),
    );
  };

  const requestAdd = (
    parent: GanttItem,
    kind: 'task' | 'subtask',
    presetCategory?: string,
  ) =>
    setAddReq({
      mode: kind,
      parent,
      projectId: parent.projectId,
      presetCategory,
    });
  const requestAddMilestone = (projectId: string) =>
    setAddReq({ mode: 'milestone', projectId });
  const requestAddCategory = (projectId: string) =>
    setAddReq({ mode: 'category', projectId });

  const submitQuickAdd = (data: {
    name: string;
    category?: string;
    date?: string;
  }) => {
    if (!addReq) return;
    if (addReq.mode === 'milestone') {
      addProjectMilestone(addReq.projectId, data.name, data.date || 'TBD');
      return;
    }
    if (addReq.mode === 'category') {
      addCategory(addReq.projectId, data.name);
      return;
    }
    const parent = addReq.parent;
    if (!parent) return;
    mutate(async () => {
      const created = await createTask(parent.projectId, {
        title: data.name,
        parent_task_id: parent.type === 'task' ? parent.id : null,
        category: data.category || addReq.presetCategory || '',
      });
      selectedIdRef.current = created.id;
    }, undefined);
  };

  const renameProjectCategory = (
    project: GanttItem,
    oldName: string,
    newName: string,
  ) => {
    const existing = extraCategoriesByProject[project.projectId] ?? [];
    const rebuilt = Array.from(
      new Set(
        [
          ...existing.map((c) => (c === oldName ? newName : c)),
          newName,
        ].filter((n) => n.trim()),
      ),
    );
    const tasksToMove = items.filter(
      (i) =>
        i.type === 'task' &&
        i.projectId === project.projectId &&
        (i.category?.trim() ?? '') === oldName,
    );
    mutate(async () => {
      await updateProject(project.projectId, { categories: rebuilt });
      await Promise.all(
        tasksToMove.map((t) => updateTask(t.id, { category: newName })),
      );
    });
  };

  // Drag-and-drop: move a task/subtask into the dropped-on category.
  // Dropping on the "Uncategorized" header clears the category.
  const assignItemCategory = (
    itemId: string,
    _project: GanttItem,
    category: string,
  ) => {
    mutate(
      () => updateTask(itemId, { category: category.trim() }),
      itemId,
    );
  };

  const deleteSelectedItem = (item: GanttItem) => {
    if (item.type === 'project') {
      deleteSelectedProject(item);
      return;
    }
    const descendantIds = new Set<string>();
    const collectDescendants = (parentId: string) => {
      for (const candidate of items) {
        if (candidate.type === 'task' && candidate.parentId === parentId) {
          descendantIds.add(candidate.id);
          collectDescendants(candidate.id);
        }
      }
    };
    collectDescendants(item.id);
    const childText = descendantIds.size
      ? ` This will also delete ${descendantIds.size} subtask${descendantIds.size === 1 ? '' : 's'}.`
      : '';
    const kind = item.level > 1 ? 'subtask' : 'task';
    const ok = window.confirm(`Delete ${kind} "${item.name}"?${childText}`);
    if (!ok) return;
    selectedIdRef.current = null;
    setSelected(null);
    mutate(() => deleteTask(item.id));
  };

  const deleteProjectCategory = (
    project: GanttItem,
    category: string,
    label: string,
  ) => {
    const tasksInCategory = items.filter(
      (item) =>
        item.type === 'task' &&
        item.projectId === project.projectId &&
        (item.category?.trim() ?? '') === category,
    );
    const taskText = tasksInCategory.length
      ? ` ${tasksInCategory.length} task${tasksInCategory.length === 1 ? '' : 's'} will move to Uncategorized.`
      : '';
    const ok = window.confirm(`Delete category "${label}"?${taskText}`);
    if (!ok) return;
    const remaining = (extraCategoriesByProject[project.projectId] ?? []).filter(
      (name) => name.trim() !== category,
    );
    mutate(async () => {
      await updateProject(project.projectId, { categories: remaining });
      await Promise.all(
        tasksInCategory.map((task) => updateTask(task.id, { category: '' })),
      );
    }, project.id);
  };

  const saveEditedItem = (next: GanttItem) => {
    if (next.type === 'project') {
      mutate(
        () =>
          updateProject(next.id, {
            name: next.name,
            owner: next.agent === 'Unassigned' ? '' : next.agent,
            progress: next.progress,
            status: STATUS_TO_PROJECT[next.status],
            start_date: next.startDate ?? null,
            target_date: next.dueDate ?? null,
            working_folder: next.workingFolder ?? '',
          }),
        next.id,
      );
      return;
    }
    mutate(
      () =>
        updateTask(next.id, {
          title: next.name,
          status: STATUS_TO_TASK[next.status],
          assigned_to: next.agent === 'Unassigned' ? '' : next.agent,
          percent_complete: next.progress,
          category: next.category ?? '',
          start_date: next.startDate ?? null,
          due_date: next.dueDate ?? null,
        }),
      next.id,
    );
  };

  const deleteSelectedProject = (project: GanttItem) => {
    const ok = window.confirm(
      `Delete "${project.name}" and all of its tasks, subtasks, notes, and milestones?`,
    );
    if (!ok) return;
    selectedIdRef.current = null;
    if (ganttView === project.projectId) setGanttView('all');
    setSelected(null);
    mutate(() => deleteProject(project.projectId));
  };

  const stats = useMemo(() => {
    const d = dash;
    const pct = (n: number, total: number) =>
      total ? `${Math.round((n / total) * 100)}% of tasks` : '—';
    return [
      {
        label: 'Active Projects',
        value: String(d?.projects_active ?? rawProjects.length),
        support: `${d?.projects_total ?? rawProjects.length} total`,
        accent: 'cyan' as Accent,
        icon: <BriefcaseBusiness size={18} />,
      },
      {
        label: 'Total Tasks',
        value: String(d?.tasks_total ?? 0),
        support: d ? `${d.projects_total} projects` : '—',
        accent: 'cyan' as Accent,
        icon: <ListChecks size={18} />,
      },
      {
        label: 'In Progress',
        value: String(d?.tasks_in_progress ?? 0),
        support: d ? pct(d.tasks_in_progress, d.tasks_total) : '—',
        accent: 'green' as Accent,
        icon: <Activity size={18} />,
      },
      {
        label: 'Blocked',
        value: String(d?.tasks_blocked ?? 0),
        support: d ? pct(d.tasks_blocked, d.tasks_total) : '—',
        accent: 'red' as Accent,
        icon: <AlertTriangle size={18} />,
      },
      {
        label: 'Overdue',
        value: String(d?.tasks_overdue ?? 0),
        support: d ? pct(d.tasks_overdue, d.tasks_total) : '—',
        accent: 'amber' as Accent,
        icon: <CalendarDays size={18} />,
      },
      {
        label: 'Active Agents',
        value: String(agents.length),
        support: agents.length ? 'Managed agents' : 'No agents loaded',
        accent: 'purple' as Accent,
        icon: <Bot size={18} />,
      },
    ];
  }, [dash, rawProjects.length, agents.length]);

  const jarvisOnline = apiReachable === true;
  const jarvisUnknown = apiReachable === null;

  return (
    <AxisContext.Provider value={axis}>
    <div
      className="flex-1 overflow-y-auto px-5 py-6 lg:px-7"
      style={{
        background:
          'radial-gradient(circle at 18% 8%, rgba(23,216,255,.12), transparent 28%), radial-gradient(circle at 88% 18%, rgba(28,101,255,.1), transparent 26%)',
      }}
    >
      <div className="mx-auto max-w-[1680px]">
        <header className="mb-5">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-4">
            <div>
              <div className="mb-2 flex items-center gap-2 text-xs text-slate-500">
                <button onClick={() => navigate('/projects')}>All projects</button>
                <span>/</span>
                <span>Projects</span>
              </div>
              <h1 className="text-2xl font-semibold text-white">
                Projects Command Center
              </h1>
              <p className="mt-1 text-sm text-slate-400">
                J.A.R.V.I.S. coordinates work across projects, tasks, milestones,
                dependencies, and agent execution.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <div className="flex items-center gap-3 rounded-lg px-3 py-2" style={panelStyle}>
                <span
                  className="grid h-10 w-10 place-items-center rounded-full"
                  style={{
                    border: `2px solid ${jarvisOnline ? '#24d9ff' : jarvisUnknown ? '#94a3b8' : '#ff4e61'}`,
                    boxShadow: jarvisOnline
                      ? '0 0 24px rgba(36,217,255,.75)'
                      : jarvisUnknown
                        ? '0 0 18px rgba(148,163,184,.24)'
                        : '0 0 24px rgba(255,78,97,.48)',
                  }}
                >
                  <Gauge
                    size={20}
                    style={{ color: jarvisOnline ? '#24d9ff' : jarvisUnknown ? '#94a3b8' : '#ff4e61' }}
                  />
                </span>
                <div>
                  <div
                    className="text-xs font-semibold"
                    style={{ color: jarvisOnline ? '#67e8f9' : jarvisUnknown ? '#cbd5e1' : '#fda4af' }}
                  >
                    {jarvisOnline ? 'J.A.R.V.I.S. ONLINE' : jarvisUnknown ? 'J.A.R.V.I.S. CHECKING' : 'J.A.R.V.I.S. OFFLINE'}
                  </div>
                  <div className="flex items-center gap-1 text-[11px] text-slate-400">
                    <span
                      className="h-1.5 w-1.5 rounded-full"
                      style={{ background: jarvisOnline ? '#34d399' : jarvisUnknown ? '#94a3b8' : '#fb7185' }}
                    />
                    {jarvisOnline ? 'Systems nominal' : jarvisUnknown ? 'Checking backend' : 'Backend unreachable'}
                  </div>
                </div>
              </div>
              <button className="flex items-center gap-2 rounded-lg px-3 py-2 text-xs text-slate-200" style={panelStyle}>
                <Sparkles size={14} /> AI Summary
              </button>
              <button onClick={() => navigate('/projects/dashboard')} className="flex items-center gap-2 rounded-lg px-3 py-2 text-xs text-slate-200" style={panelStyle}>
                <GanttChartSquare size={14} /> Timeline
              </button>
              <button className="flex items-center gap-2 rounded-lg px-3 py-2 text-xs text-slate-200" style={panelStyle}>
                <Filter size={14} /> Filters
              </button>
              <button
                onClick={() => setCreating((value) => !value)}
                className="flex items-center gap-2 rounded-lg px-4 py-2 text-xs font-semibold"
                style={{
                  background: 'linear-gradient(180deg, #2be1ff, #1398c8)',
                  color: '#031018',
                  boxShadow: '0 0 22px rgba(36,217,255,.42)',
                }}
              >
                <Plus size={15} /> New Project
              </button>
            </div>
          </div>
          {creating && (
            <CreateProjectPanel
              onClose={() => setCreating(false)}
              onCreated={() => {
                setCreating(false);
                reload();
              }}
            />
          )}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-6">
            {stats.map((stat) => (
              <ProjectKpiCard key={stat.label} {...stat} />
            ))}
          </div>
          {error && (
            <div
              className="mt-3 rounded-lg px-4 py-2 text-xs"
              style={{
                background: 'rgba(255,78,97,.1)',
                border: '1px solid rgba(255,78,97,.32)',
                color: '#ff9aa6',
              }}
            >
              {error}
            </div>
          )}
          {loading && !items.length && (
            <div className="mt-3 text-xs text-slate-400">
              Loading projects from the database…
            </div>
          )}
          {!loading && !error && !projects.length && (
            <div className="mt-3 text-xs text-slate-400">
              No projects yet. Use “New Project” to create one — it’s stored
              in the shared project database.
            </div>
          )}
        </header>

        <main className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="min-w-0 space-y-4">
            <GanttChart
              items={items}
              selectedId={selected?.id ?? ''}
              onSelect={handleSelect}
              onEdit={setEditing}
              view={ganttView}
              onViewChange={setGanttView}
              onRequestAdd={requestAdd}
              onRequestAddMilestone={requestAddMilestone}
              onRequestAddCategory={requestAddCategory}
              onRenameCategory={renameProjectCategory}
              onAssignCategory={assignItemCategory}
              onDeleteItem={deleteSelectedItem}
              onDeleteCategory={deleteProjectCategory}
              onDeleteProject={deleteSelectedProject}
              extraCategoriesByProject={extraCategoriesByProject}
            />
            {selected ? (
              <TaskInspectorPanel selected={selected} />
            ) : (
              <section className="rounded-lg p-4" style={panelStyle}>
                <h3 className="text-sm font-semibold text-white">
                  Task Inspector
                </h3>
                <p className="mt-2 text-xs text-slate-400">
                  {loading
                    ? 'Loading project data…'
                    : 'Select a task in the timeline to inspect it.'}
                </p>
              </section>
            )}
            <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-4">
              <MilestoneTimeline milestones={activeMilestones} />
              <RiskList
                items={items}
                atRiskProjects={dash?.at_risk_projects ?? []}
              />
              <RecentActivity
                tasks={rawTasks}
                projectName={(id) =>
                  rawProjects.find((p) => p.id === id)?.name || 'Project'
                }
              />
              <WorkloadChart agents={agents} items={items} />
            </div>
          </div>
          <aside className="space-y-4">
            <ProjectDetailsPanel
              project={activeProject}
              agents={agents}
              milestones={activeMilestones}
              onAddMilestone={addMilestone}
              onToggleMilestone={toggleMilestone}
              onDeleteMilestone={deleteMilestone}
              onDeleteProject={deleteSelectedProject}
            />
            <AgentActivityPanel agents={agents} />
          </aside>
        </main>
      </div>
      {editing && (
        <EditItemModal
          item={editing}
          agents={agents}
          categories={categoriesForProject(editing.projectId)}
          onSave={saveEditedItem}
          onClose={() => setEditing(null)}
        />
      )}
      {addReq && (
        <QuickAddModal
          mode={addReq.mode}
          parentName={
            addReq.mode === 'milestone' || addReq.mode === 'category'
              ? projects.find((p) => p.projectId === addReq.projectId)?.name ||
                'project'
              : addReq.parent?.name || 'project'
          }
          categories={categoriesForProject(addReq.projectId)}
          presetCategory={addReq.presetCategory}
          onSubmit={submitQuickAdd}
          onClose={() => setAddReq(null)}
        />
      )}
    </div>
    </AxisContext.Provider>
  );
}
