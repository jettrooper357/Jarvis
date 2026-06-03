import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import { AppRoutes } from './App';

vi.mock('./components/Layout', async () => {
  const { Outlet } = await import('react-router');
  return {
    Layout: () => (
      <div>
        <Outlet />
      </div>
    ),
  };
});

vi.mock('./components/PendingApprovalsList', () => ({
  PendingApprovalsList: () => <div>Approvals page</div>,
}));

vi.mock('./pages/AgentsPage', () => ({
  AgentsPage: () => <div>Agents page</div>,
}));
vi.mock('./pages/ChatPage', () => ({
  ChatPage: () => <div>Chat page</div>,
}));
vi.mock('./pages/DashboardPage', () => ({
  DashboardPage: () => <div>Mission Control page</div>,
}));
vi.mock('./pages/DataSourcesPage', () => ({
  DataSourcesPage: () => <div>Data Sources page</div>,
}));
vi.mock('./pages/GetStartedPage', () => ({
  GetStartedPage: () => <div>Setup page</div>,
}));
vi.mock('./pages/LibraryPage', () => ({
  LibraryPage: () => <div>Library page</div>,
}));
vi.mock('./pages/LogsPage', () => ({
  LogsPage: () => <div>Logs page</div>,
}));
vi.mock('./pages/PersonalPlanningPage', () => ({
  PersonalPlanningPage: () => <div>Planner page</div>,
}));
vi.mock('./pages/ProjectDashboardPage', () => ({
  ProjectDashboardPage: () => <div>Project dashboard page</div>,
}));
vi.mock('./pages/ProjectDetailPage', () => ({
  ProjectDetailPage: () => <div>Project detail page</div>,
}));
vi.mock('./pages/ProjectTimelinePage', () => ({
  ProjectTimelinePage: () => <div>Project timeline page</div>,
}));
vi.mock('./pages/ProjectsPage', () => ({
  ProjectsPage: () => <div>Projects page</div>,
}));
vi.mock('./pages/SettingsPage', () => ({
  SettingsPage: () => <div>Settings page</div>,
}));

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
      <LocationProbe />
    </MemoryRouter>,
  );
}

describe('AppRoutes workspace compatibility', () => {
  it.each([
    ['/', '/command/today', 'Chat page'],
    ['/chat', '/command/today', 'Chat page'],
    ['/mission-control', '/command/mission-control', 'Mission Control page'],
    ['/dashboard', '/command/mission-control', 'Mission Control page'],
    ['/life-planner', '/command/planner', 'Planner page'],
    ['/agents', '/agents/org-chart', 'Agents page'],
    ['/library', '/knowledge/library', 'Library page'],
    ['/data-sources', '/knowledge/data-sources', 'Data Sources page'],
    ['/logs', '/system/logs', 'Logs page'],
    ['/settings', '/system/settings', 'Settings page'],
    ['/get-started', '/system/setup', 'Setup page'],
  ])('redirects %s to %s', async (oldRoute, newRoute, content) => {
    renderAt(oldRoute);

    await waitFor(() =>
      expect(screen.getByTestId('location')).toHaveTextContent(newRoute),
    );
    expect(screen.getByText(content)).toBeInTheDocument();
  });

  it('keeps protected project detail routes mounted inside Projects', () => {
    renderAt('/projects/abc/timeline');

    expect(screen.getByText('Projects')).toBeInTheDocument();
    expect(screen.getByText('Project timeline page')).toBeInTheDocument();
  });

  it('keeps the Projects workspace tabs concentrated on real project pages', () => {
    renderAt('/projects');

    expect(screen.getByRole('button', { name: 'Overview' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Dashboard' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Tasks' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Files' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Agents' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Notes' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Activity' })).toBeNull();
  });

  it('keeps Agents workspace aliases but does not duplicate protected page tabs', async () => {
    renderAt('/agents/capabilities');

    await waitFor(() =>
      expect(screen.getByTestId('location')).toHaveTextContent('/agents/org-chart'),
    );
    expect(screen.getByText('Agents page')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Org Chart' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Conversations' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Assignments' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Capabilities' })).toBeNull();
  });

  it('aliases /command/chat to Today because those surfaces are the same', async () => {
    renderAt('/command/chat');

    await waitFor(() =>
      expect(screen.getByTestId('location')).toHaveTextContent('/command/today'),
    );
    expect(screen.getByText('Chat page')).toBeInTheDocument();
  });
});
