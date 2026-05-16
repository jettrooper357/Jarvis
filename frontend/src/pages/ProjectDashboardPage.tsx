import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { ChevronLeft } from 'lucide-react';
import { getDashboard } from '../lib/projects-api';
import type { ProjectDashboard } from '../lib/projects-api';
import { ProjectSummaryWidgets } from '../components/Project/ProjectSummaryWidgets';

export function ProjectDashboardPage() {
  const navigate = useNavigate();
  const [data, setData] = useState<ProjectDashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getDashboard()
      .then(setData)
      .catch((e) => setError(e?.message || 'Failed to load dashboard'));
  }, []);

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
        <h1
          className="text-lg font-semibold mb-1"
          style={{ color: 'var(--color-text)' }}
        >
          Project Dashboard
        </h1>
        <p
          className="text-sm mb-6"
          style={{ color: 'var(--color-text-tertiary)' }}
        >
          Portfolio health across all projects and tasks.
        </p>
        {error ? (
          <div className="text-sm" style={{ color: 'var(--color-error)' }}>
            {error}
          </div>
        ) : !data ? (
          <div
            className="text-sm"
            style={{ color: 'var(--color-text-tertiary)' }}
          >
            Loading…
          </div>
        ) : (
          <ProjectSummaryWidgets d={data} />
        )}
      </div>
    </div>
  );
}
