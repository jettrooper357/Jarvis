import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router';
import { ChevronLeft } from 'lucide-react';
import { getProject, listTasks } from '../lib/projects-api';
import type { Project, Task } from '../lib/projects-api';
import { GanttChart } from '../components/Project/GanttChart';

export function ProjectTimelinePage() {
  const { projectId = '' } = useParams();
  const navigate = useNavigate();
  const [project, setProject] = useState<Project | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);

  useEffect(() => {
    getProject(projectId).then(setProject).catch(() => setProject(null));
    listTasks(projectId).then(setTasks).catch(() => setTasks([]));
  }, [projectId]);

  return (
    <div className="flex-1 overflow-y-auto px-6 py-8">
      <div className="max-w-5xl mx-auto">
        <button
          onClick={() => navigate(`/projects/${projectId}`)}
          className="flex items-center gap-1 text-xs mb-3 cursor-pointer"
          style={{ color: 'var(--color-text-tertiary)' }}
        >
          <ChevronLeft size={14} /> Back to project
        </button>
        <h1
          className="text-lg font-semibold mb-1"
          style={{ color: 'var(--color-text)' }}
        >
          {project ? `${project.name} — Timeline` : 'Timeline'}
        </h1>
        <p
          className="text-sm mb-5"
          style={{ color: 'var(--color-text-tertiary)' }}
        >
          Gantt view. Bars show start→due; the lighter fill is percent
          complete; red bars are overdue.
        </p>
        <GanttChart tasks={tasks} />
      </div>
    </div>
  );
}
