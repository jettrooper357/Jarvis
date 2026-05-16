import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { Plus, LayoutDashboard } from 'lucide-react';
import { listProjects, createProject } from '../lib/projects-api';
import type { Project } from '../lib/projects-api';
import { ProjectList } from '../components/Project/ProjectList';
import { PROJECT_STATUSES } from '../components/Project/projectUtils';

export function ProjectsPage() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [owner, setOwner] = useState('');
  const [status, setStatus] = useState('Planning');
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    listProjects()
      .then(setProjects)
      .catch(() => setProjects([]))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const submit = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      const p = await createProject({
        name: name.trim(),
        owner: owner.trim(),
        status: status as Project['status'],
      });
      setName('');
      setOwner('');
      setCreating(false);
      load();
      navigate(`/projects/${p.id}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex-1 overflow-y-auto px-6 py-10">
      <div className="max-w-5xl mx-auto">
        <header className="mb-6 flex items-start justify-between gap-3">
          <div>
            <h1
              className="text-lg font-semibold"
              style={{ color: 'var(--color-text)' }}
            >
              Projects
            </h1>
            <p
              className="text-sm mt-1"
              style={{ color: 'var(--color-text-tertiary)' }}
            >
              Portfolio of projects, tasks, and timelines. Shared with AI
              agents via the project_management data source.
            </p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => navigate('/projects/dashboard')}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs cursor-pointer"
              style={{
                background: 'var(--color-bg-secondary)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text-secondary)',
              }}
            >
              <LayoutDashboard size={14} /> Dashboard
            </button>
            <button
              onClick={() => setCreating((c) => !c)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs cursor-pointer"
              style={{
                background: 'var(--color-accent)',
                color: 'var(--color-on-accent)',
              }}
            >
              <Plus size={14} /> New project
            </button>
          </div>
        </header>

        {creating && (
          <div
            className="mb-6 p-4 rounded-lg grid grid-cols-3 gap-2 items-end"
            style={{
              background: 'var(--color-bg-secondary)',
              border: '1px solid var(--color-border)',
            }}
          >
            <input
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Project name"
              className="px-3 py-2 rounded text-sm"
              style={{
                background: 'var(--color-bg)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text)',
              }}
            />
            <input
              value={owner}
              onChange={(e) => setOwner(e.target.value)}
              placeholder="Owner"
              className="px-3 py-2 rounded text-sm"
              style={{
                background: 'var(--color-bg)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text)',
              }}
            />
            <div className="flex gap-2">
              <select
                value={status}
                onChange={(e) => setStatus(e.target.value)}
                className="px-2 py-2 rounded text-sm flex-1"
                style={{
                  background: 'var(--color-bg)',
                  border: '1px solid var(--color-border)',
                  color: 'var(--color-text)',
                }}
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
                className="px-3 py-2 rounded-lg text-xs cursor-pointer disabled:opacity-50"
                style={{
                  background: 'var(--color-accent)',
                  color: 'var(--color-on-accent)',
                }}
              >
                Create
              </button>
            </div>
          </div>
        )}

        {loading ? (
          <div
            className="text-sm"
            style={{ color: 'var(--color-text-tertiary)' }}
          >
            Loading…
          </div>
        ) : (
          <ProjectList
            projects={projects}
            onOpen={(id) => navigate(`/projects/${id}`)}
          />
        )}
      </div>
    </div>
  );
}
