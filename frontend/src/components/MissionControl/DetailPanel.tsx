import { useEffect, useState } from 'react';
import { fetchTaskNotes, type ProjectTaskNote } from '../../lib/api';
import {
  statusColor,
  fmtDate,
  fmtAgo,
  columnFor,
  type FlatTask,
} from './missionControlUtils';

function nextAction(t: FlatTask): string {
  const col = columnFor(t.status);
  if (col === 'review')
    return `Resolve blockers / review: ${t.title}`;
  if (col === 'done') return 'Completed — no action required';
  if (col === 'in_progress') return `Continue: ${t.title}`;
  return `Start: ${t.title}`;
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div
        className="hud-label mb-1.5"
        style={{ letterSpacing: '0.12em' }}
      >
        {title}
      </div>
      {children}
    </div>
  );
}

export function DetailPanel({
  task,
  subtasks,
  projectDescription,
}: {
  task: FlatTask | null;
  subtasks: FlatTask[];
  projectDescription: string;
}) {
  const [notes, setNotes] = useState<ProjectTaskNote[]>([]);

  useEffect(() => {
    let alive = true;
    if (!task) {
      setNotes([]);
      return;
    }
    fetchTaskNotes(task.id).then((n) => {
      if (alive) setNotes(n);
    });
    return () => {
      alive = false;
    };
  }, [task?.id]);

  if (!task) {
    return (
      <div className="hud-panel p-4 h-full flex items-center justify-center">
        <span
          className="text-xs"
          style={{ color: 'var(--color-text-tertiary)' }}
        >
          Select a task on the board to inspect it.
        </span>
      </div>
    );
  }

  const blockers = [
    ...subtasks.filter((s) => columnFor(s.status) === 'review'),
  ];
  const blockerNotes = notes.filter((n) =>
    /block/i.test(n.type) || /block|fail/i.test(n.content),
  );
  const recent = [...notes].sort((a, b) => b.created_at - a.created_at).slice(0, 6);

  return (
    <div className="hud-panel p-4 flex flex-col gap-4 h-full overflow-y-auto">
      <div>
        <div className="flex items-center gap-2 mb-1">
          <span
            className="hud-label truncate"
            style={{ fontSize: '0.6rem', letterSpacing: '0.1em' }}
          >
            {task.projectName}
          </span>
          <span
            className="text-[10px] px-1.5 py-0.5 rounded ml-auto shrink-0"
            style={{
              color: statusColor(task.status),
              background: `color-mix(in srgb, ${statusColor(
                task.status,
              )} 16%, transparent)`,
            }}
          >
            {task.status || 'Backlog'}
          </span>
        </div>
        <div
          className="text-base font-semibold leading-snug"
          style={{ color: 'var(--color-text)' }}
        >
          {task.title}
        </div>
      </div>

      <Section title="DESCRIPTION">
        <p
          className="text-xs leading-relaxed"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          {task.description ||
            projectDescription ||
            'No description provided.'}
        </p>
      </Section>

      <div className="grid grid-cols-2 gap-3">
        <Section title="CURRENT STAGE">
          <span className="text-xs" style={{ color: 'var(--color-text)' }}>
            {task.status || 'Backlog'} · {Math.round(task.percent_complete || 0)}%
          </span>
        </Section>
        <Section title="DUE">
          <span className="text-xs" style={{ color: 'var(--color-text)' }}>
            {fmtDate(task.due_date)}
          </span>
        </Section>
      </div>

      <Section title="NEXT REQUIRED ACTION">
        <div
          className="text-xs rounded-lg px-3 py-2"
          style={{
            background: 'color-mix(in srgb, var(--color-accent) 12%, transparent)',
            color: 'var(--color-text)',
            border: '1px solid color-mix(in srgb, var(--color-accent) 30%, transparent)',
          }}
        >
          {nextAction(task)}
        </div>
      </Section>

      <Section title={`SUBTASKS (${subtasks.length})`}>
        {subtasks.length === 0 ? (
          <span
            className="text-[11px]"
            style={{ color: 'var(--color-text-tertiary)' }}
          >
            No subtasks.
          </span>
        ) : (
          <div className="space-y-1">
            {subtasks.map((s) => (
              <div key={s.id} className="flex items-center gap-2">
                <span
                  className="w-1.5 h-1.5 rounded-full shrink-0"
                  style={{ background: statusColor(s.status) }}
                />
                <span
                  className="text-[11px] truncate flex-1"
                  style={{ color: 'var(--color-text-secondary)' }}
                >
                  {s.title}
                </span>
                <span
                  className="text-[10px] hud-mono"
                  style={{ color: 'var(--color-text-tertiary)' }}
                >
                  {Math.round(s.percent_complete || 0)}%
                </span>
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section title="BLOCKERS">
        {blockers.length === 0 && blockerNotes.length === 0 ? (
          <span
            className="text-[11px]"
            style={{ color: 'var(--color-success)' }}
          >
            No blockers.
          </span>
        ) : (
          <ul className="space-y-1">
            {blockers.map((b) => (
              <li
                key={b.id}
                className="text-[11px]"
                style={{ color: 'var(--color-error)' }}
              >
                ⚠ {b.title} — {b.status}
              </li>
            ))}
            {blockerNotes.map((n) => (
              <li
                key={n.id}
                className="text-[11px]"
                style={{ color: 'var(--color-error)' }}
              >
                ⚠ {n.content}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="RECENT ACTIVITY">
        {recent.length === 0 ? (
          <span
            className="text-[11px]"
            style={{ color: 'var(--color-text-tertiary)' }}
          >
            No activity logged yet.
          </span>
        ) : (
          <div className="space-y-1.5">
            {recent.map((n) => (
              <div key={n.id} className="text-[11px]">
                <span style={{ color: 'var(--color-text)' }}>
                  {n.author || 'system'}
                </span>{' '}
                <span style={{ color: 'var(--color-text-tertiary)' }}>
                  · {fmtAgo(n.created_at)}
                </span>
                <div style={{ color: 'var(--color-text-secondary)' }}>
                  {n.content}
                </div>
              </div>
            ))}
          </div>
        )}
      </Section>
    </div>
  );
}
