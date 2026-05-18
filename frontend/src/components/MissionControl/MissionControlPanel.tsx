import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  fetchMissionControl,
  type MissionControlData,
} from '../../lib/api';
import { useAgentEvents } from '../../lib/useAgentEvents';
import { KpiRow } from './KpiRow';
import { TaskBoard } from './TaskBoard';
import { DetailPanel } from './DetailPanel';
import { AgentRail } from './AgentRail';
import {
  flattenTasks,
  deriveKpis,
  deriveProjectStats,
  columnFor,
  statusColor,
  type ProjectStats,
} from './missionControlUtils';

function ProjectStatsStrip({
  stats,
  selectedProjectId,
  onSelectProject,
}: {
  stats: ProjectStats[];
  selectedProjectId: string;
  onSelectProject: (id: string) => void;
}) {
  if (stats.length === 0) return null;
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
      {stats.map((project) => {
        const selected = selectedProjectId === project.id;
        return (
          <button
            key={project.id}
            onClick={() => onSelectProject(project.id)}
            className="hud-panel text-left px-3 py-3"
            style={{
              borderColor: selected
                ? 'color-mix(in srgb, var(--color-accent) 55%, transparent)'
                : undefined,
              boxShadow: selected
                ? '0 0 16px -6px var(--color-accent-glow)'
                : undefined,
            }}
          >
            <div className="flex items-center justify-between gap-2 mb-2">
              <span
                className="text-sm font-medium truncate"
                style={{ color: 'var(--color-text)' }}
              >
                {project.name}
              </span>
              <span
                className="text-[10px] px-1.5 py-0.5 rounded shrink-0"
                style={{
                  color: statusColor(project.status),
                  background: `color-mix(in srgb, ${statusColor(
                    project.status,
                  )} 14%, transparent)`,
                }}
              >
                {project.status || 'Planning'}
              </span>
            </div>
            <div
              className="h-1.5 rounded-full w-full mb-2"
              style={{ background: 'var(--color-bg-tertiary)' }}
            >
              <div
                style={{
                  width: `${project.progress}%`,
                  height: '100%',
                  borderRadius: 999,
                  background:
                    project.progress >= 100
                      ? 'var(--color-success)'
                      : 'var(--color-accent)',
                }}
              />
            </div>
            <div
              className="grid grid-cols-4 gap-2 text-[10px]"
              style={{ color: 'var(--color-text-tertiary)' }}
            >
              <span>
                <b style={{ color: 'var(--color-text)' }}>{project.openTasks}</b>{' '}
                open
              </span>
              <span>
                <b style={{ color: 'var(--color-accent)' }}>
                  {project.inProgress}
                </b>{' '}
                active
              </span>
              <span>
                <b style={{ color: 'var(--color-error)' }}>{project.blocked}</b>{' '}
                blocked
              </span>
              <span>
                <b style={{ color: 'var(--color-success)' }}>
                  {project.activeAgents}
                </b>{' '}
                agents
              </span>
            </div>
          </button>
        );
      })}
    </div>
  );
}

export function MissionControlPanel() {
  const [data, setData] = useState<MissionControlData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedProjectId, setSelectedProjectId] = useState('all');
  const loadingRef = useRef(false);

  const load = useCallback(async () => {
    if (loadingRef.current) return;
    loadingRef.current = true;
    try {
      setData(await fetchMissionControl());
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      loadingRef.current = false;
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 15000);
    return () => clearInterval(id);
  }, [load]);

  useAgentEvents('*', load);

  const visibleProjects = useMemo(() => {
    if (!data) return [];
    if (selectedProjectId === 'all') return data.projects;
    return data.projects.filter((p) => p.id === selectedProjectId);
  }, [data, selectedProjectId]);

  const flat = useMemo(() => flattenTasks(visibleProjects), [visibleProjects]);

  const visibleAgents = useMemo(() => {
    if (!data || selectedProjectId === 'all') return data?.agents || [];
    const taskIds = new Set(flat.map((t) => t.id));
    const agentIds = new Set<string>();
    for (const task of flat) {
      for (const linked of task.linked_agents) {
        agentIds.add(linked.agent_id);
      }
    }
    return data.agents.filter(
      (agent) =>
        agentIds.has(agent.id) ||
        (agent.linked_project_task_id &&
          taskIds.has(agent.linked_project_task_id)),
    );
  }, [data, flat, selectedProjectId]);

  const projectStats = useMemo(
    () => (data ? deriveProjectStats(data.projects, data.agents) : []),
    [data],
  );

  // Default/sticky selection: keep current if still present, else first
  // in-progress task, else first task.
  useEffect(() => {
    if (!flat.length) {
      setSelectedId(null);
      return;
    }
    if (selectedId && flat.some((t) => t.id === selectedId)) return;
    const inProg = flat.find((t) => columnFor(t.status) === 'in_progress');
    setSelectedId((inProg || flat[0]).id);
  }, [flat, selectedId]);

  if (error && !data) {
    return (
      <div
        className="hud-panel p-4 text-sm"
        style={{ color: 'var(--color-error)' }}
      >
        Mission Control unavailable: {error}
      </div>
    );
  }
  if (!data) {
    return (
      <div
        className="hud-panel p-4 text-sm"
        style={{ color: 'var(--color-text-tertiary)' }}
      >
        Loading Mission Control…
      </div>
    );
  }

  const k = deriveKpis(data, flat, visibleProjects, visibleAgents);
  const selected = flat.find((t) => t.id === selectedId) || null;
  const subtasks = selected
    ? flat.filter((t) => t.parent_task_id === selected.id)
    : [];
  const projectDescription =
    (selected &&
      data.projects.find((p) => p.id === selected.projectId)?.description) ||
    '';

  return (
    <div className="flex flex-col gap-5">
      <div className="hud-panel px-3 py-3 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div
            className="hud-label"
            style={{ letterSpacing: '0.12em', color: 'var(--color-text)' }}
          >
            MISSION CONTROL SCOPE
          </div>
          <div
            className="text-xs mt-1"
            style={{ color: 'var(--color-text-tertiary)' }}
          >
            {selectedProjectId === 'all'
              ? 'All projects, portfolio stats, and active agent coverage.'
              : 'Focused task board and stats for the selected project.'}
          </div>
        </div>
        <select
          value={selectedProjectId}
          onChange={(event) => setSelectedProjectId(event.target.value)}
          className="text-sm px-3 py-2 rounded-lg outline-none min-w-[240px]"
          style={{
            background: 'var(--color-bg-secondary)',
            border: '1px solid var(--color-border)',
            color: 'var(--color-text)',
          }}
        >
          <option value="all">All projects</option>
          {data.projects.map((project) => (
            <option key={project.id} value={project.id}>
              {project.name}
            </option>
          ))}
        </select>
      </div>

      <KpiRow k={k} />

      {selectedProjectId === 'all' && (
        <ProjectStatsStrip
          stats={projectStats}
          selectedProjectId={selectedProjectId}
          onSelectProject={setSelectedProjectId}
        />
      )}

      <div className="grid grid-cols-1 xl:grid-cols-[1fr_340px] gap-4">
        <div className="min-w-0">
          <div
            className="hud-label mb-2"
            style={{ letterSpacing: '0.16em' }}
          >
            PROJECT TASK BOARD
          </div>
          <TaskBoard
            tasks={flat}
            selectedId={selectedId}
            onSelect={setSelectedId}
          />
        </div>
        <AgentRail agents={visibleAgents} flat={flat} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[1fr_340px] gap-4">
        <DetailPanel
          task={selected}
          subtasks={subtasks}
          projectDescription={projectDescription}
        />
        <div />
      </div>
    </div>
  );
}
