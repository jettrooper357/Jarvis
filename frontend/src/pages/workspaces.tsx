import { PendingApprovalsList } from '../components/PendingApprovalsList';
import { WorkspaceShell } from '../components/Workspace/WorkspaceShell';
import { useParams } from 'react-router';
import {
  agentTabs,
  commandTabs,
  knowledgeTabs,
  projectDetailTabs,
  projectTabs,
  systemTabs,
} from '../navigation/workspaces';
import { AgentsPage } from './AgentsPage';
import { ChatPage } from './ChatPage';
import { DashboardPage } from './DashboardPage';
import { DataSourcesPage } from './DataSourcesPage';
import { GetStartedPage } from './GetStartedPage';
import { LibraryPage } from './LibraryPage';
import { LogsPage } from './LogsPage';
import { PersonalPlanningPage } from './PersonalPlanningPage';
import { ProjectDashboardPage } from './ProjectDashboardPage';
import { ProjectDetailPage } from './ProjectDetailPage';
import { ProjectTimelinePage } from './ProjectTimelinePage';
import { ProjectsPage } from './ProjectsPage';
import { SettingsPage } from './SettingsPage';

function WorkspacePlaceholder({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="flex-1 overflow-y-auto px-6 py-10">
      <div className="max-w-4xl mx-auto">
        <h2
          className="text-lg font-semibold"
          style={{ color: 'var(--color-text)' }}
        >
          {title}
        </h2>
        <p
          className="text-sm mt-2 max-w-2xl"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          {description}
        </p>
      </div>
    </div>
  );
}

export function CommandTodayWorkspace() {
  return (
    <WorkspaceShell title="Command Center" tabs={commandTabs}>
      <ChatPage />
    </WorkspaceShell>
  );
}

export function CommandMissionControlWorkspace() {
  return (
    <WorkspaceShell title="Command Center" tabs={commandTabs}>
      <DashboardPage />
    </WorkspaceShell>
  );
}

export function CommandPlannerWorkspace() {
  return (
    <WorkspaceShell title="Command Center" tabs={commandTabs}>
      <PersonalPlanningPage />
    </WorkspaceShell>
  );
}

export function CommandApprovalsWorkspace() {
  return (
    <WorkspaceShell title="Command Center" tabs={commandTabs}>
      <div className="flex-1 overflow-y-auto px-6 py-10">
        <div className="max-w-5xl mx-auto">
          <PendingApprovalsList />
        </div>
      </div>
    </WorkspaceShell>
  );
}

export function CommandActivityWorkspace() {
  return (
    <WorkspaceShell title="Command Center" tabs={commandTabs}>
      <LogsPage />
    </WorkspaceShell>
  );
}

export function ProjectsOverviewWorkspace() {
  return (
    <WorkspaceShell title="Projects" tabs={projectTabs}>
      <ProjectsPage />
    </WorkspaceShell>
  );
}

export function ProjectDashboardWorkspace() {
  return (
    <WorkspaceShell title="Projects" tabs={projectTabs}>
      <ProjectDashboardPage />
    </WorkspaceShell>
  );
}

export function ProjectDetailWorkspace() {
  const { projectId = '' } = useParams();

  return (
    <WorkspaceShell title="Projects" tabs={projectDetailTabs(projectId)}>
      <ProjectDetailPage />
    </WorkspaceShell>
  );
}

export function ProjectTimelineWorkspace() {
  const { projectId = '' } = useParams();

  return (
    <WorkspaceShell title="Projects" tabs={projectDetailTabs(projectId)}>
      <ProjectTimelinePage />
    </WorkspaceShell>
  );
}

export function AgentsWorkspace() {
  return (
    <WorkspaceShell title="Agents" tabs={agentTabs}>
      <AgentsPage />
    </WorkspaceShell>
  );
}

export function KnowledgeLibraryWorkspace() {
  return (
    <WorkspaceShell title="Knowledge" tabs={knowledgeTabs}>
      <LibraryPage />
    </WorkspaceShell>
  );
}

export function KnowledgeDataSourcesWorkspace() {
  return (
    <WorkspaceShell title="Knowledge" tabs={knowledgeTabs}>
      <DataSourcesPage />
    </WorkspaceShell>
  );
}

export function KnowledgePlaceholderWorkspace({
  section,
}: {
  section: string;
}) {
  return (
    <WorkspaceShell title="Knowledge" tabs={knowledgeTabs}>
      <WorkspacePlaceholder
        title={section}
        description="This workspace section is reserved for the existing capability catalog surfaces. Agent-specific capability editing remains available in the protected Agents capability inspector."
      />
    </WorkspaceShell>
  );
}

export function SystemSettingsWorkspace() {
  return (
    <WorkspaceShell title="System" tabs={systemTabs}>
      <SettingsPage />
    </WorkspaceShell>
  );
}

export function SystemLogsWorkspace() {
  return (
    <WorkspaceShell title="System" tabs={systemTabs}>
      <LogsPage />
    </WorkspaceShell>
  );
}

export function SystemSetupWorkspace() {
  return (
    <WorkspaceShell title="System" tabs={systemTabs}>
      <GetStartedPage />
    </WorkspaceShell>
  );
}

export function SystemPlaceholderWorkspace({
  section,
}: {
  section: string;
}) {
  return (
    <WorkspaceShell title="System" tabs={systemTabs}>
      <WorkspacePlaceholder
        title={section}
        description="This system section is reserved for diagnostics, telemetry, security, and audit surfaces while existing settings, logs, and setup pages remain unchanged."
      />
    </WorkspaceShell>
  );
}
