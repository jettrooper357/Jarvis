import type { Project } from '../../lib/projects-api';
import { statusColor, fmtDate } from './projectUtils';

export function ProjectCard({
  project,
  onOpen,
}: {
  project: Project;
  onOpen: (id: string) => void;
}) {
  return (
    <button
      onClick={() => onOpen(project.id)}
      className="text-left p-4 rounded-lg cursor-pointer w-full"
      style={{
        background: 'var(--color-bg-secondary)',
        border: '1px solid var(--color-border)',
      }}
    >
      <div className="flex items-start justify-between gap-2 mb-1">
        <span
          className="font-semibold text-sm truncate"
          style={{ color: 'var(--color-text)' }}
        >
          {project.name}
        </span>
        <span
          className="text-xs px-2 py-0.5 rounded shrink-0"
          style={{
            color: statusColor(project.status),
            border: `1px solid ${statusColor(project.status)}`,
          }}
        >
          {project.status}
        </span>
      </div>
      <div
        className="text-xs mb-3 line-clamp-2"
        style={{ color: 'var(--color-text-tertiary)' }}
      >
        {project.description || 'No description'}
      </div>
      <div
        className="h-1.5 rounded-full overflow-hidden mb-2"
        style={{ background: 'var(--color-bg-tertiary)' }}
      >
        <div
          style={{
            width: `${project.progress}%`,
            height: '100%',
            background: 'var(--color-accent)',
          }}
        />
      </div>
      <div
        className="flex items-center justify-between text-xs"
        style={{ color: 'var(--color-text-tertiary)' }}
      >
        <span>{project.progress}% complete</span>
        <span>
          {project.owner || 'unassigned'} · due {fmtDate(project.target_date)}
        </span>
      </div>
    </button>
  );
}
