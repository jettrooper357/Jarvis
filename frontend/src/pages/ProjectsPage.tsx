import { useEffect, useMemo, useState } from 'react';
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
  Target,
  Trash2,
  Zap,
} from 'lucide-react';
import { createProject } from '../lib/projects-api';
import type { Project } from '../lib/projects-api';
import { PROJECT_STATUSES } from '../components/Project/projectUtils';
import { fetchManagedAgents, type ManagedAgent } from '../lib/api';

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

const initialGanttItems: GanttItem[] = [
  {
    id: 'signal84',
    projectId: 'signal84',
    name: 'Signal84 Core',
    agent: 'Atlas',
    status: 'In Progress',
    progress: 72,
    start: 0,
    end: 6.2,
    accent: 'cyan',
    level: 0,
    type: 'project',
    milestone: 8.1,
  },
  {
    id: 'requirements',
    projectId: 'signal84',
    name: 'Requirements & Design',
    agent: 'Atlas',
    status: 'Done',
    progress: 100,
    start: 0,
    end: 2.5,
    accent: 'green',
    level: 1,
    type: 'task',
    parentId: 'signal84',
  },
  {
    id: 'core-engine',
    projectId: 'signal84',
    name: 'Core Engine Development',
    agent: 'Aether',
    status: 'In Progress',
    progress: 70,
    start: 1.4,
    end: 5.4,
    accent: 'cyan',
    level: 1,
    type: 'task',
    parentId: 'signal84',
    milestone: 7.6,
  },
  {
    id: 'engine-parser',
    projectId: 'signal84',
    name: 'Event Parser Module',
    agent: 'Aether',
    status: 'Done',
    progress: 100,
    start: 1.5,
    end: 3.0,
    accent: 'green',
    level: 2,
    type: 'task',
    parentId: 'core-engine',
  },
  {
    id: 'engine-api',
    projectId: 'signal84',
    name: 'API Orchestration Layer',
    agent: 'Aether',
    status: 'In Progress',
    progress: 54,
    start: 3.0,
    end: 5.5,
    accent: 'cyan',
    level: 2,
    type: 'task',
    parentId: 'core-engine',
  },
  {
    id: 'integration',
    projectId: 'signal84',
    name: 'Integration & Testing',
    agent: 'Orion',
    status: 'In Progress',
    progress: 45,
    start: 3.2,
    end: 7.1,
    accent: 'cyan',
    level: 1,
    type: 'task',
    parentId: 'signal84',
    blocker: true,
    milestone: 8.8,
  },
  {
    id: 'integration-harness',
    projectId: 'signal84',
    name: 'Integration Harness',
    agent: 'Orion',
    status: 'In Progress',
    progress: 38,
    start: 3.6,
    end: 6.1,
    accent: 'cyan',
    level: 2,
    type: 'task',
    parentId: 'integration',
  },
  {
    id: 'rate-limit-tests',
    projectId: 'signal84',
    name: 'Rate-limit Test Scenarios',
    agent: 'Orion',
    status: 'Blocked',
    progress: 20,
    start: 5.8,
    end: 7.2,
    accent: 'red',
    level: 2,
    type: 'task',
    parentId: 'integration',
    blocker: true,
  },
  {
    id: 'launch',
    projectId: 'signal84',
    name: 'Launch',
    agent: 'Nova',
    status: 'Pending',
    progress: 0,
    start: 8.2,
    end: 10.2,
    accent: 'purple',
    level: 1,
    type: 'task',
    parentId: 'signal84',
  },
  {
    id: 'esp',
    projectId: 'esp',
    name: 'ESP Web Modernization',
    agent: 'Icarus',
    status: 'In Progress',
    progress: 58,
    start: 0.1,
    end: 5.7,
    accent: 'cyan',
    level: 0,
    type: 'project',
    milestone: 6.7,
  },
  {
    id: 'invoice',
    projectId: 'invoice',
    name: 'Invoice Service',
    agent: 'Nyx',
    status: 'At Risk',
    progress: 35,
    start: 0.9,
    end: 5.3,
    accent: 'amber',
    level: 0,
    type: 'project',
    blocker: true,
  },
  {
    id: 'mapping',
    projectId: 'invoice',
    name: 'Data Mapping',
    agent: 'Nyx',
    status: 'At Risk',
    progress: 42,
    start: 1.1,
    end: 3.8,
    accent: 'amber',
    level: 1,
    type: 'task',
    parentId: 'invoice',
  },
  {
    id: 'stored-proc',
    projectId: 'invoice',
    name: 'Stored Procedure Refactor',
    agent: 'Icarus',
    status: 'Pending',
    progress: 15,
    start: 5.1,
    end: 8.4,
    accent: 'amber',
    level: 1,
    type: 'task',
    parentId: 'invoice',
    milestone: 9.1,
  },
  {
    id: 'commcore',
    projectId: 'commcore',
    name: 'CommCore Migration',
    agent: 'Orion',
    status: 'Blocked',
    progress: 20,
    start: 1.0,
    end: 4.9,
    accent: 'red',
    level: 0,
    type: 'project',
    blocker: true,
    milestone: 9.2,
  },
  {
    id: 'api-review',
    projectId: 'commcore',
    name: 'API Contract Review',
    agent: 'Atlas',
    status: 'Blocked',
    progress: 25,
    start: 5.1,
    end: 7.7,
    accent: 'red',
    level: 1,
    type: 'task',
    parentId: 'commcore',
  },
  {
    id: 'jarvisux',
    projectId: 'jarvisux',
    name: 'Jarvis UX',
    agent: 'Nova',
    status: 'In Progress',
    progress: 82,
    start: 0.4,
    end: 10.0,
    accent: 'green',
    level: 0,
    type: 'project',
    milestone: 10.6,
  },
  {
    id: 'regression',
    projectId: 'jarvisux',
    name: 'Regression Testing',
    agent: 'Orion',
    status: 'In Progress',
    progress: 64,
    start: 6.1,
    end: 9.0,
    accent: 'cyan',
    level: 1,
    type: 'task',
    parentId: 'jarvisux',
  },
];

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
  const colors = accentMap[item.accent];
  const left = (item.start / 11) * 100;
  const width = Math.max(4, ((item.end - item.start) / 11) * 100);
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
            left: `${(item.milestone / 11) * 100}%`,
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
  onSave,
  onClose,
}: {
  item: GanttItem;
  agents: ManagedAgent[];
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
              defaultValue="2025-04-22"
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
              defaultValue="2025-05-23"
              className="w-full rounded-md px-3 py-2 text-sm text-slate-100"
              style={{
                background: 'rgba(0,0,0,.34)',
                border: '1px solid rgba(74,210,255,.18)',
              }}
            />
          </label>
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
}: {
  item: GanttItem;
  selected: boolean;
  onSelect: (item: GanttItem) => void;
  onEdit: (item: GanttItem) => void;
  hasChildren: boolean;
  expanded: boolean;
  onToggle: (id: string) => void;
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

function GanttChart({
  items,
  selectedId,
  onSelect,
  onEdit,
  view,
  onViewChange,
}: {
  items: GanttItem[];
  selectedId: string;
  onSelect: (item: GanttItem) => void;
  onEdit: (item: GanttItem) => void;
  view: string;
  onViewChange: (value: string) => void;
}) {
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
  const visibleItems = useMemo(() => {
    if (viewFilter === 'blocked') {
      // Show every blocked row regardless of collapse state — the point
      // of this view is to surface blockers directly.
      return items.filter((item) => item.status === 'Blocked');
    }
    const scoped =
      viewFilter === 'all'
        ? items
        : items.filter((item) => item.projectId === viewFilter);
    const visible: GanttItem[] = [];
    const isVisible = (item: GanttItem) => {
      let parentId = item.parentId;
      while (parentId) {
        if (!expanded[parentId]) return false;
        parentId = scoped.find((candidate) => candidate.id === parentId)
          ?.parentId;
      }
      return true;
    };
    for (const item of scoped) {
      if (isVisible(item)) visible.push(item);
    }
    return visible;
  }, [expanded, items, viewFilter]);
  const toggleExpanded = (id: string) =>
    setExpanded((current) => ({ ...current, [id]: !current[id] }));

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
      <div className="overflow-x-auto">
        <div className="min-w-[920px]">
          <div
            className="grid border-b text-[11px]"
            style={{
              gridTemplateColumns: '250px 92px 108px 54px minmax(430px,1fr)',
              borderColor: 'rgba(74, 210, 255, .12)',
              color: '#9eb0bf',
            }}
          >
            <div className="px-3 py-2">Project / Task</div>
            <div className="py-2">Owner / Agent</div>
            <div className="py-2">Status</div>
            <div className="py-2">%</div>
            <div className="relative grid grid-cols-11 border-l" style={{ borderColor: 'rgba(74, 210, 255, .12)' }}>
              {weeks.map((week, idx) => (
                <div
                  key={week}
                  className="border-r px-1 py-2 text-center"
                  style={{
                    borderColor: 'rgba(74, 210, 255, .08)',
                    color: idx === 4 ? '#27d9ff' : '#9eb0bf',
                  }}
                >
                  {week}
                </div>
              ))}
              <div
                className="absolute bottom-0 top-0 w-px"
                style={{
                  left: `${(4.15 / 11) * 100}%`,
                  background: '#1bcfff',
                  boxShadow: '0 0 14px rgba(27,207,255,.7)',
                }}
              />
            </div>
          </div>
          {visibleItems.map((item) => (
            <GanttRow
              key={item.id}
              item={item}
              selected={selectedId === item.id}
              onSelect={onSelect}
              onEdit={onEdit}
              hasChildren={Boolean(childCountByParent[item.id])}
              expanded={expanded[item.id] ?? false}
              onToggle={toggleExpanded}
            />
          ))}
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
}: {
  project: GanttItem | undefined;
  agents: ManagedAgent[];
  milestones: Milestone[];
  onAddMilestone: (name: string, date: string) => void;
  onToggleMilestone: (id: string) => void;
  onDeleteMilestone: (id: string) => void;
}) {
  const visibleAgents = agents.slice(0, 3);
  const [newName, setNewName] = useState('');
  const [newDate, setNewDate] = useState('');
  const dueDate = project
    ? `${weeks[Math.min(Math.round(project.end), weeks.length - 1)]}, 2025`
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
        <ProgressRing value={project?.progress ?? 0} />
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
  return (
    <section className="rounded-lg p-4" style={panelStyle}>
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-white">Task Inspector</h3>
        <MoreVertical size={15} className="text-slate-500" />
      </div>
      <div className="space-y-3 text-xs">
        <label className="block">
          <span className="mb-1 block text-slate-500">Task</span>
          <input value={selected.name} readOnly className="w-full rounded-md px-2 py-1.5 text-slate-100" style={{ background: 'rgba(0,0,0,.28)', border: '1px solid rgba(74,210,255,.16)' }} />
        </label>
        <div className="grid grid-cols-2 gap-2">
          <label>
            <span className="mb-1 block text-slate-500">Status</span>
            <select value={selected.status} onChange={() => {}} className="w-full rounded-md px-2 py-1.5" style={{ background: 'rgba(0,0,0,.28)', border: '1px solid rgba(74,210,255,.16)', color: accentMap[selected.accent].text }}>
              <option>{selected.status}</option>
            </select>
          </label>
          <label>
            <span className="mb-1 block text-slate-500">Priority</span>
            <select value={selected.blocker ? 'High' : 'Medium'} onChange={() => {}} className="w-full rounded-md px-2 py-1.5 text-slate-100" style={{ background: 'rgba(0,0,0,.28)', border: '1px solid rgba(74,210,255,.16)' }}>
              <option>{selected.blocker ? 'High' : 'Medium'}</option>
            </select>
          </label>
          <label>
            <span className="mb-1 block text-slate-500">Assignee</span>
            <select value={selected.agent} onChange={() => {}} className="w-full rounded-md px-2 py-1.5 text-slate-100" style={{ background: 'rgba(0,0,0,.28)', border: '1px solid rgba(74,210,255,.16)' }}>
              <option>{selected.agent}</option>
            </select>
          </label>
          <label>
            <span className="mb-1 block text-slate-500">Start</span>
            <input value="Apr 22, 2025" readOnly className="w-full rounded-md px-2 py-1.5 text-slate-100" style={{ background: 'rgba(0,0,0,.28)', border: '1px solid rgba(74,210,255,.16)' }} />
          </label>
          <label>
            <span className="mb-1 block text-slate-500">End</span>
            <input value="May 23, 2025" readOnly className="w-full rounded-md px-2 py-1.5 text-slate-100" style={{ background: 'rgba(0,0,0,.28)', border: '1px solid rgba(74,210,255,.16)' }} />
          </label>
        </div>
        <div>
          <div className="mb-1 flex justify-between text-slate-500">
            <span>Progress</span>
            <span style={{ color: accentMap[selected.accent].text }}>{selected.progress}%</span>
          </div>
          <div className="h-2 rounded-full bg-slate-800">
            <div className="h-full rounded-full" style={{ width: `${selected.progress}%`, background: accentMap[selected.accent].text }} />
          </div>
        </div>
        <label className="block">
          <span className="mb-1 block text-slate-500">Notes</span>
          <textarea
            readOnly
            value="Develop core processing engine and API contracts. Confirm rate-limit mitigation before integration hardening."
            className="h-16 w-full resize-none rounded-md px-2 py-1.5 text-slate-200"
            style={{ background: 'rgba(0,0,0,.28)', border: '1px solid rgba(74,210,255,.16)' }}
          />
        </label>
        <div className="flex flex-wrap items-center gap-2">
          <button className="rounded px-2 py-1 text-[11px] text-slate-200" style={{ background: 'rgba(255,255,255,.06)' }}>
            Requirements & Design x
          </button>
          <button className="flex items-center gap-1 rounded px-2 py-1 text-[11px] text-cyan-200" style={{ border: '1px solid rgba(74,210,255,.22)' }}>
            <Plus size={12} /> Add dependency
          </button>
        </div>
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

function MilestoneTimeline() {
  return (
    <section className="rounded-lg p-4" style={panelStyle}>
      <div className="mb-4 flex justify-between">
        <h3 className="text-sm font-semibold text-white">Milestones</h3>
        <button className="text-xs text-cyan-300">View all</button>
      </div>
      <div className="relative flex justify-between px-2 pt-5 text-center text-[11px] text-slate-400">
        <div className="absolute left-8 right-8 top-7 h-px bg-slate-700" />
        {[
          ['Apr 21', 'Requirements Complete', true],
          ['May 23', 'Core Engine MVP', true],
          ['Jun 13', 'Integration Complete', false],
          ['Jun 27', 'Production Launch', false],
        ].map(([date, name, done]) => (
          <button key={String(name)} className="relative max-w-[92px]">
            <span className="mx-auto mb-3 block h-4 w-4 rotate-45" style={{ background: done ? '#28f0a0' : '#8793a1', boxShadow: done ? '0 0 16px rgba(40,240,160,.28)' : undefined }} />
            <span className="block text-slate-300">{date}</span>
            <span className="block">{name}</span>
          </button>
        ))}
      </div>
    </section>
  );
}

function RiskList() {
  return (
    <section className="rounded-lg p-4" style={panelStyle}>
      <div className="mb-3 flex justify-between">
        <h3 className="text-sm font-semibold text-white">Dependencies & Risks</h3>
        <button className="text-xs text-cyan-300">View all</button>
      </div>
      <div className="mb-3 text-xs">
        <div className="mb-1 text-slate-500">Critical Path</div>
        {[
          'Core Engine Development -> Integration & Testing',
          'Invoice Service -> Shared Library',
          'CommCore Migration -> Data Migration',
        ].map((item) => (
          <button key={item} className="mb-1 block w-full rounded px-2 py-1 text-left text-slate-300 hover:bg-cyan-400/10">
            <GitBranch size={12} className="mr-1 inline text-cyan-300" />
            {item}
          </button>
        ))}
      </div>
      {[
        ['3rd-party API rate limits', 'High', 'red'],
        ['Data migration complexity', 'Medium', 'amber'],
      ].map(([risk, severity, accent]) => (
        <button key={risk} className="mb-1 flex w-full items-center justify-between rounded px-2 py-1 text-xs hover:bg-cyan-400/10">
          <span className="text-slate-300">{risk}</span>
          <span style={{ color: accentMap[accent as Accent].text }}>{severity}</span>
        </button>
      ))}
    </section>
  );
}

function RecentActivity() {
  return (
    <section className="rounded-lg p-4" style={panelStyle}>
      <div className="mb-3 flex justify-between">
        <h3 className="text-sm font-semibold text-white">Recent Activity</h3>
        <button className="text-xs text-cyan-300">View all</button>
      </div>
      {[
        ['Aether updated Core Engine Development progress to 70%', '2m ago'],
        ['Orion completed task Requirements & Design', '1h ago'],
        ['Atlas added milestone Core Engine MVP', '3h ago'],
        ['Nyx flagged risk on Invoice Service', '4h ago'],
      ].map(([text, time]) => (
        <button key={text} className="mb-2 flex w-full gap-2 rounded text-left text-xs hover:bg-cyan-400/10">
          <Activity size={13} className="mt-0.5 text-cyan-300" />
          <span className="flex-1 text-slate-300">{text}</span>
          <span className="text-[10px] text-slate-500">{time}</span>
        </button>
      ))}
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
}: {
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const [name, setName] = useState('');
  const [owner, setOwner] = useState('');
  const [status, setStatus] = useState<Project['status']>('Planning');
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      const project = await createProject({
        name: name.trim(),
        owner: owner.trim(),
        status,
      });
      onClose();
      navigate(`/projects/${project.id}`);
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

export function ProjectsPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState<GanttItem[]>(initialGanttItems);
  const [agents, setAgents] = useState<ManagedAgent[]>([]);
  const [selected, setSelected] = useState<GanttItem>(
    initialGanttItems.find((item) => item.id === 'core-engine') ||
      initialGanttItems[0],
  );
  const [editing, setEditing] = useState<GanttItem | null>(null);
  const [creating, setCreating] = useState(false);
  // Gantt scope filter, shared so the details panel tracks the dropdown.
  const [ganttView, setGanttView] = useState<string>('all');
  const [milestonesByProject, setMilestonesByProject] = useState<
    Record<string, Milestone[]>
  >({
    signal84: [
      { id: 'sig-m1', name: 'Requirements Complete', date: 'Apr 21', done: true },
      { id: 'sig-m2', name: 'Core Engine MVP', date: 'May 23', done: true },
      { id: 'sig-m3', name: 'Integration Complete', date: 'Jun 13', done: false },
      { id: 'sig-m4', name: 'Production Launch', date: 'Jun 27', done: false },
    ],
  });

  const projects = useMemo(
    () => items.filter((item) => item.type === 'project'),
    [items],
  );
  // The details panel follows the Gantt dropdown; for "All"/"Blocked"
  // it falls back to the project of the currently selected row.
  const activeProject = useMemo(() => {
    if (ganttView !== 'all' && ganttView !== 'blocked') {
      const byView = projects.find((p) => p.projectId === ganttView);
      if (byView) return byView;
    }
    return (
      projects.find((p) => p.projectId === selected.projectId) || projects[0]
    );
  }, [projects, ganttView, selected.projectId]);
  const activeProjectId = activeProject?.projectId ?? '';
  const activeMilestones = milestonesByProject[activeProjectId] ?? [];

  const addMilestone = (name: string, date: string) => {
    if (!activeProjectId) return;
    setMilestonesByProject((current) => ({
      ...current,
      [activeProjectId]: [
        ...(current[activeProjectId] ?? []),
        { id: `ms-${Date.now()}`, name, date, done: false },
      ],
    }));
  };
  const toggleMilestone = (id: string) => {
    if (!activeProjectId) return;
    setMilestonesByProject((current) => ({
      ...current,
      [activeProjectId]: (current[activeProjectId] ?? []).map((m) =>
        m.id === id ? { ...m, done: !m.done } : m,
      ),
    }));
  };
  const deleteMilestone = (id: string) => {
    if (!activeProjectId) return;
    setMilestonesByProject((current) => ({
      ...current,
      [activeProjectId]: (current[activeProjectId] ?? []).filter(
        (m) => m.id !== id,
      ),
    }));
  };

  useEffect(() => {
    fetchManagedAgents()
      .then((loadedAgents) => {
        const activeAgents = loadedAgents.filter(
          (agent) => agent.status !== 'archived',
        );
        setAgents(activeAgents);
        if (activeAgents.length) {
          setItems((current) => {
            const realNames = new Set(activeAgents.map((agent) => agent.name));
            const remapped = current.map((item, index) =>
              realNames.has(item.agent)
                ? item
                : {
                    ...item,
                    agent: activeAgents[index % activeAgents.length].name,
                  },
            );
            setSelected((selectedItem) => {
              const next = remapped.find((item) => item.id === selectedItem.id);
              return next || selectedItem;
            });
            return remapped;
          });
        }
      })
      .catch(() => setAgents([]));
  }, []);

  const saveEditedItem = (next: GanttItem) => {
    setItems((current) =>
      current.map((item) => (item.id === next.id ? next : item)),
    );
    setSelected((current) => (current.id === next.id ? next : current));
  };

  const stats = useMemo(
    () => [
      {
        label: 'Active Projects',
        value: '5',
        support: '+1 this week',
        accent: 'cyan' as Accent,
        icon: <BriefcaseBusiness size={18} />,
      },
      {
        label: 'Total Tasks',
        value: '128',
        support: '+14 this week',
        accent: 'cyan' as Accent,
        icon: <ListChecks size={18} />,
      },
      {
        label: 'In Progress',
        value: '68',
        support: '53% of tasks',
        accent: 'green' as Accent,
        icon: <Activity size={18} />,
      },
      {
        label: 'Blocked',
        value: '7',
        support: '5% of tasks',
        accent: 'red' as Accent,
        icon: <AlertTriangle size={18} />,
      },
      {
        label: 'Due This Week',
        value: '18',
        support: '14% of tasks',
        accent: 'amber' as Accent,
        icon: <CalendarDays size={18} />,
      },
      {
        label: 'Active Agents',
        value: String(agents.length),
        support: agents.length ? 'Real managed agents' : 'No agents loaded',
        accent: 'purple' as Accent,
        icon: <Bot size={18} />,
      },
    ],
    [agents.length],
  );

  return (
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
                <span className="grid h-10 w-10 place-items-center rounded-full" style={{ border: '2px solid #24d9ff', boxShadow: '0 0 24px rgba(36,217,255,.75)' }}>
                  <Gauge size={20} style={{ color: '#24d9ff' }} />
                </span>
                <div>
                  <div className="text-xs font-semibold text-cyan-300">
                    J.A.R.V.I.S. ONLINE
                  </div>
                  <div className="flex items-center gap-1 text-[11px] text-slate-400">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                    Systems nominal
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
          {creating && <CreateProjectPanel onClose={() => setCreating(false)} />}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-6">
            {stats.map((stat) => (
              <ProjectKpiCard key={stat.label} {...stat} />
            ))}
          </div>
        </header>

        <main className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="min-w-0 space-y-4">
            <GanttChart
              items={items}
              selectedId={selected.id}
              onSelect={setSelected}
              onEdit={setEditing}
              view={ganttView}
              onViewChange={setGanttView}
            />
            <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-4">
              <MilestoneTimeline />
              <RiskList />
              <RecentActivity />
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
            />
            <TaskInspectorPanel selected={selected} />
            <AgentActivityPanel agents={agents} />
          </aside>
        </main>
      </div>
      {editing && (
        <EditItemModal
          item={editing}
          agents={agents}
          onSave={saveEditedItem}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
}
