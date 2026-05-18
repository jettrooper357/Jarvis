import {
  FolderKanban,
  ListTodo,
  Loader2,
  Ban,
  CalendarClock,
  AlertTriangle,
  Bot,
} from 'lucide-react';
import type { DerivedKpis } from './missionControlUtils';

interface KpiDef {
  label: string;
  value: number;
  icon: typeof FolderKanban;
  accent: string;
  alert?: boolean;
}

function KpiCard({ d }: { d: KpiDef }) {
  const Icon = d.icon;
  const hot = d.alert && d.value > 0;
  return (
    <div
      className="hud-panel px-4 py-3 flex items-center gap-3"
      style={
        hot
          ? {
              borderColor:
                'color-mix(in srgb, ' + d.accent + ' 45%, transparent)',
              boxShadow: `0 0 18px -8px ${d.accent}`,
            }
          : undefined
      }
    >
      <div
        className="flex items-center justify-center w-9 h-9 rounded-lg shrink-0"
        style={{
          background: `color-mix(in srgb, ${d.accent} 14%, transparent)`,
          color: d.accent,
        }}
      >
        <Icon size={18} />
      </div>
      <div className="min-w-0">
        <div
          className="hud-mono text-2xl font-semibold leading-none"
          style={{ color: hot ? d.accent : 'var(--color-text)' }}
        >
          {d.value}
        </div>
        <div
          className="hud-label mt-1 truncate"
          style={{ letterSpacing: '0.08em', fontSize: '0.65rem' }}
        >
          {d.label}
        </div>
      </div>
    </div>
  );
}

export function KpiRow({ k }: { k: DerivedKpis }) {
  const cards: KpiDef[] = [
    {
      label: 'ACTIVE PROJECTS',
      value: k.activeProjects,
      icon: FolderKanban,
      accent: 'var(--color-accent)',
    },
    {
      label: 'OPEN TASKS',
      value: k.openTasks,
      icon: ListTodo,
      accent: 'var(--color-text-secondary)',
    },
    {
      label: 'IN PROGRESS',
      value: k.inProgress,
      icon: Loader2,
      accent: 'var(--color-accent)',
    },
    {
      label: 'BLOCKED',
      value: k.blocked,
      icon: Ban,
      accent: 'var(--color-error)',
      alert: true,
    },
    {
      label: 'DUE TODAY',
      value: k.dueToday,
      icon: CalendarClock,
      accent: 'var(--color-warning)',
      alert: true,
    },
    {
      label: 'OVERDUE',
      value: k.overdue,
      icon: AlertTriangle,
      accent: 'var(--color-error)',
      alert: true,
    },
    {
      label: 'ACTIVE AGENTS',
      value: k.activeAgents,
      icon: Bot,
      accent: 'var(--color-success)',
    },
  ];
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-7 gap-3">
      {cards.map((c) => (
        <KpiCard key={c.label} d={c} />
      ))}
    </div>
  );
}
