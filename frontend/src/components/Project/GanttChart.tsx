import { useMemo } from 'react';
import type { Task } from '../../lib/projects-api';
import { statusColor, isOverdue, fmtDate } from './projectUtils';

const DAY = 86400000;

export function GanttChart({ tasks }: { tasks: Task[] }) {
  const dated = useMemo(
    () => tasks.filter((t) => t.start_date || t.due_date),
    [tasks],
  );

  const { min, max } = useMemo(() => {
    const stamps: number[] = [];
    for (const t of dated) {
      if (t.start_date) stamps.push(new Date(t.start_date).getTime());
      if (t.due_date) stamps.push(new Date(t.due_date).getTime());
    }
    const now = Date.now();
    if (stamps.length === 0) return { min: now - 7 * DAY, max: now + 7 * DAY };
    return {
      min: Math.min(...stamps) - DAY,
      max: Math.max(...stamps) + DAY,
    };
  }, [dated]);

  const span = Math.max(max - min, DAY);

  if (dated.length === 0) {
    return (
      <div
        className="text-sm text-center py-12 rounded-lg"
        style={{
          color: 'var(--color-text-tertiary)',
          border: '1px dashed var(--color-border)',
        }}
      >
        No tasks with start/due dates yet. Add dates to see the timeline.
      </div>
    );
  }

  const pct = (ts: number) => ((ts - min) / span) * 100;

  return (
    <div
      className="rounded-lg p-3 overflow-x-auto"
      style={{ border: '1px solid var(--color-border)' }}
    >
      <div
        className="flex justify-between text-[10px] mb-2"
        style={{ color: 'var(--color-text-tertiary)' }}
      >
        <span>{fmtDate(new Date(min).toISOString())}</span>
        <span>{fmtDate(new Date(max).toISOString())}</span>
      </div>
      <div className="space-y-1.5" style={{ minWidth: 480 }}>
        {dated.map((t) => {
          const s = t.start_date
            ? new Date(t.start_date).getTime()
            : new Date(t.due_date!).getTime() - DAY;
          const e = t.due_date
            ? new Date(t.due_date).getTime()
            : s + DAY;
          const left = pct(s);
          const width = Math.max(pct(e) - left, 1.5);
          const overdue = isOverdue(t);
          return (
            <div key={t.id} className="flex items-center gap-2">
              <span
                className="text-[11px] truncate"
                style={{ width: 140, color: 'var(--color-text-secondary)' }}
                title={t.title}
              >
                {t.title}
              </span>
              <div
                className="relative flex-1 h-5 rounded"
                style={{ background: 'var(--color-bg-secondary)' }}
              >
                <div
                  className="absolute top-0 h-5 rounded flex items-center"
                  style={{
                    left: `${left}%`,
                    width: `${width}%`,
                    background: overdue
                      ? 'var(--color-error)'
                      : statusColor(t.status),
                    opacity: 0.85,
                  }}
                >
                  <div
                    className="h-full rounded-l"
                    style={{
                      width: `${t.percent_complete}%`,
                      background: 'rgba(255,255,255,0.35)',
                    }}
                  />
                  <span
                    className="absolute text-[9px] px-1 whitespace-nowrap"
                    style={{ color: 'var(--color-on-accent)', left: 4 }}
                  >
                    {t.percent_complete}%
                  </span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
