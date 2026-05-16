import type { Project } from '../../lib/projects-api';
import { ProjectCard } from './ProjectCard';

export function ProjectList({
  projects,
  onOpen,
}: {
  projects: Project[];
  onOpen: (id: string) => void;
}) {
  if (projects.length === 0) {
    return (
      <div
        className="text-sm text-center py-12 rounded-lg"
        style={{
          color: 'var(--color-text-tertiary)',
          border: '1px dashed var(--color-border)',
        }}
      >
        No projects yet. Create one to get started.
      </div>
    );
  }
  return (
    <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
      {projects.map((p) => (
        <ProjectCard key={p.id} project={p} onOpen={onOpen} />
      ))}
    </div>
  );
}
