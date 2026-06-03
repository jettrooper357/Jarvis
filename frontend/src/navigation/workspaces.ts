import {
  Bot,
  Brain,
  Command,
  FolderKanban,
  Settings,
  type LucideIcon,
} from 'lucide-react';

export type WorkspaceId =
  | 'command'
  | 'projects'
  | 'agents'
  | 'knowledge'
  | 'system';

export type WorkspaceNavItem = {
  id: WorkspaceId;
  label: string;
  path: string;
  icon: LucideIcon;
  match: (pathname: string) => boolean;
};

export const workspaceNavItems: WorkspaceNavItem[] = [
  {
    id: 'command',
    label: 'Command Center',
    path: '/command/today',
    icon: Command,
    match: (pathname) => pathname === '/' || pathname.startsWith('/command'),
  },
  {
    id: 'projects',
    label: 'Projects',
    path: '/projects',
    icon: FolderKanban,
    match: (pathname) => pathname.startsWith('/projects'),
  },
  {
    id: 'agents',
    label: 'Agents',
    path: '/agents/org-chart',
    icon: Bot,
    match: (pathname) => pathname.startsWith('/agents'),
  },
  {
    id: 'knowledge',
    label: 'Knowledge',
    path: '/knowledge/library',
    icon: Brain,
    match: (pathname) =>
      pathname.startsWith('/knowledge') ||
      pathname === '/library' ||
      pathname === '/data-sources',
  },
  {
    id: 'system',
    label: 'System',
    path: '/system/settings',
    icon: Settings,
    match: (pathname) =>
      pathname.startsWith('/system') ||
      pathname === '/settings' ||
      pathname === '/logs' ||
      pathname === '/get-started',
  },
];

export type WorkspaceTab = {
  label: string;
  path: string;
};

export const commandTabs: WorkspaceTab[] = [
  { label: 'Today', path: '/command/today' },
  { label: 'Mission Control', path: '/command/mission-control' },
  { label: 'Planner', path: '/command/planner' },
  { label: 'Approvals', path: '/command/approvals' },
  { label: 'Activity', path: '/command/activity' },
];

export const projectTabs: WorkspaceTab[] = [
  { label: 'Overview', path: '/projects' },
  { label: 'Dashboard', path: '/projects/dashboard' },
];

export function projectDetailTabs(projectId: string): WorkspaceTab[] {
  return [
    { label: 'Project', path: `/projects/${projectId}` },
    { label: 'Timeline', path: `/projects/${projectId}/timeline` },
  ];
}

export const agentTabs: WorkspaceTab[] = [];

export const knowledgeTabs: WorkspaceTab[] = [
  { label: 'Library', path: '/knowledge/library' },
  { label: 'Data Sources', path: '/knowledge/data-sources' },
  { label: 'Skills', path: '/knowledge/skills' },
  { label: 'Presets', path: '/knowledge/presets' },
  { label: 'Tools', path: '/knowledge/tools' },
  { label: 'Search', path: '/knowledge/search' },
];

export const systemTabs: WorkspaceTab[] = [
  { label: 'Settings', path: '/system/settings' },
  { label: 'Logs', path: '/system/logs' },
  { label: 'Diagnostics', path: '/system/diagnostics' },
  { label: 'Setup', path: '/system/setup' },
  { label: 'Security', path: '/system/security' },
];
