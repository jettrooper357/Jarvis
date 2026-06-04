import { useEffect, useState, useCallback, useRef } from 'react';
import { Navigate, Routes, Route } from 'react-router';
import { Layout } from './components/Layout';
import {
  AgentsWorkspace,
  CommandActivityWorkspace,
  CommandApprovalsWorkspace,
  CommandMissionControlWorkspace,
  CommandPlannerWorkspace,
  CommandTodayWorkspace,
  KnowledgeDataSourcesWorkspace,
  KnowledgeLibraryWorkspace,
  KnowledgePlaceholderWorkspace,
  ProjectDashboardWorkspace,
  ProjectDetailWorkspace,
  ProjectTimelineWorkspace,
  ProjectsOverviewWorkspace,
  SystemLogsWorkspace,
  SystemPlaceholderWorkspace,
  SystemSettingsWorkspace,
  SystemSetupWorkspace,
} from './pages/workspaces';
import { CommandPalette } from './components/CommandPalette';
import { SetupScreen } from './components/SetupScreen';
import { Toaster } from './components/ui/sonner';
import { WatchtowerNotifier } from './components/Watchtower/WatchtowerNotifier';
import { useAppStore } from './lib/store';
import { fetchModels, fetchServerInfo, fetchSavings, submitSavings, isTauri } from './lib/api';
import { resolveModelSelection } from './lib/models';
import { OptInModal } from './components/OptInModal';

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/command/today" replace />} />
        <Route path="chat" element={<Navigate to="/command/today" replace />} />
        <Route
          path="dashboard"
          element={<Navigate to="/command/mission-control" replace />}
        />
        <Route
          path="mission-control"
          element={<Navigate to="/command/mission-control" replace />}
        />
        <Route
          path="life-planner"
          element={<Navigate to="/command/planner" replace />}
        />
        <Route path="settings" element={<Navigate to="/system/settings" replace />} />
        <Route path="get-started" element={<Navigate to="/system/setup" replace />} />
        <Route
          path="data-sources"
          element={<Navigate to="/knowledge/data-sources" replace />}
        />
        <Route path="agents" element={<Navigate to="/agents/org-chart" replace />} />
        <Route path="library" element={<Navigate to="/knowledge/library" replace />} />
        <Route path="logs" element={<Navigate to="/system/logs" replace />} />

        <Route path="command" element={<Navigate to="/command/today" replace />} />
        <Route path="command/today" element={<CommandTodayWorkspace />} />
        <Route path="command/chat" element={<Navigate to="/command/today" replace />} />
        <Route
          path="command/mission-control"
          element={<CommandMissionControlWorkspace />}
        />
        <Route path="command/planner" element={<CommandPlannerWorkspace />} />
        <Route path="command/approvals" element={<CommandApprovalsWorkspace />} />
        <Route path="command/activity" element={<CommandActivityWorkspace />} />

        <Route path="projects" element={<ProjectsOverviewWorkspace />} />
        <Route path="projects/dashboard" element={<ProjectDashboardWorkspace />} />
        <Route path="projects/:projectId" element={<ProjectDetailWorkspace />} />
        <Route
          path="projects/:projectId/timeline"
          element={<ProjectTimelineWorkspace />}
        />

        <Route path="agents/org-chart" element={<AgentsWorkspace />} />
        <Route path="agents/list" element={<Navigate to="/agents/org-chart" replace />} />
        <Route path="agents/conversations" element={<Navigate to="/agents/org-chart" replace />} />
        <Route path="agents/assignments" element={<Navigate to="/agents/org-chart" replace />} />
        <Route path="agents/capabilities" element={<Navigate to="/agents/org-chart" replace />} />

        <Route path="knowledge" element={<Navigate to="/knowledge/library" replace />} />
        <Route path="knowledge/library" element={<KnowledgeLibraryWorkspace />} />
        <Route
          path="knowledge/data-sources"
          element={<KnowledgeDataSourcesWorkspace />}
        />
        <Route
          path="knowledge/skills"
          element={<KnowledgePlaceholderWorkspace section="Skills" />}
        />
        <Route
          path="knowledge/presets"
          element={<KnowledgePlaceholderWorkspace section="Presets" />}
        />
        <Route
          path="knowledge/tools"
          element={<KnowledgePlaceholderWorkspace section="Tools" />}
        />
        <Route
          path="knowledge/search"
          element={<KnowledgePlaceholderWorkspace section="Knowledge Search" />}
        />

        <Route path="system" element={<Navigate to="/system/settings" replace />} />
        <Route path="system/settings" element={<SystemSettingsWorkspace />} />
        <Route path="system/logs" element={<SystemLogsWorkspace />} />
        <Route
          path="system/diagnostics"
          element={<SystemPlaceholderWorkspace section="Diagnostics" />}
        />
        <Route path="system/setup" element={<SystemSetupWorkspace />} />
        <Route
          path="system/security"
          element={<SystemPlaceholderWorkspace section="Security / Audit" />}
        />
      </Route>
    </Routes>
  );
}

export default function App() {
  const [setupDone, setSetupDone] = useState(!isTauri());
  const handleSetupReady = useCallback(() => setSetupDone(true), []);
  const setModels = useAppStore((s) => s.setModels);
  const setModelsLoading = useAppStore((s) => s.setModelsLoading);
  const setSelectedModel = useAppStore((s) => s.setSelectedModel);
  const selectedModel = useAppStore((s) => s.selectedModel);
  const setServerInfo = useAppStore((s) => s.setServerInfo);
  const setSavings = useAppStore((s) => s.setSavings);
  const settings = useAppStore((s) => s.settings);
  const commandPaletteOpen = useAppStore((s) => s.commandPaletteOpen);
  const setCommandPaletteOpen = useAppStore((s) => s.setCommandPaletteOpen);
  const optInEnabled = useAppStore((s) => s.optInEnabled);
  const optInDisplayName = useAppStore((s) => s.optInDisplayName);
  const optInEmail = useAppStore((s) => s.optInEmail);
  const optInAnonId = useAppStore((s) => s.optInAnonId);
  const optInModalSeen = useAppStore((s) => s.optInModalSeen);
  const optInModalOpen = useAppStore((s) => s.optInModalOpen);
  const setOptInModalOpen = useAppStore((s) => s.setOptInModalOpen);
  const markOptInModalSeen = useAppStore((s) => s.markOptInModalSeen);
  const savings = useAppStore((s) => s.savings);

  // Apply theme class to <html>
  useEffect(() => {
    const root = document.documentElement;
    root.classList.remove('dark', 'light');
    if (settings.theme === 'dark') root.classList.add('dark');
    else if (settings.theme === 'light') root.classList.add('light');
  }, [settings.theme]);

  // Sync overlay conversations into the main app
  const importOverlay = useAppStore((s) => s.importOverlayConversation);
  useEffect(() => {
    if (!isTauri()) return;
    importOverlay();
    const interval = setInterval(importOverlay, 5000);
    return () => clearInterval(interval);
  }, [importOverlay]);

  // Fetch models on mount
  useEffect(() => {
    fetchModels()
      .then((m) => {
        setModels(m);
        if (m.length === 0) return;
        const resolvedModel = resolveModelSelection({
          selectedModel,
          defaultModel: settings.defaultModel,
          models: m,
        });
        if (resolvedModel && resolvedModel !== selectedModel) {
          setSelectedModel(resolvedModel);
        }
      })
      .catch(() => setModels([]))
      .finally(() => setModelsLoading(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch server info
  useEffect(() => {
    fetchServerInfo().then(setServerInfo).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Poll savings and optionally share to Supabase
  useEffect(() => {
    const refresh = () =>
      fetchSavings()
        .then((data) => {
          setSavings(data);
          if (optInEnabled && optInDisplayName && data) {
            const claudeEntry = data.per_provider.find(
              (p) => p.provider === 'claude-opus-4.6',
            );
            const dollarSavings = claudeEntry ? claudeEntry.total_cost : 0;
            const energySaved = data.per_provider.reduce(
              (sum, p) => sum + (p.energy_wh || 0),
              0,
            );
            const flopsSaved = data.per_provider.reduce(
              (sum, p) => sum + (p.flops || 0),
              0,
            );
            submitSavings({
              anon_id: optInAnonId,
              display_name: optInDisplayName,
              email: optInEmail,
              total_calls: data.total_calls,
              total_tokens: data.total_tokens,
              dollar_savings: dollarSavings,
              energy_wh_saved: energySaved,
              flops_saved: flopsSaved,
              token_counting_version: data.token_counting_version ?? 1,
            });
          }
        })
        .catch(() => {});
    refresh();
    const interval = setInterval(refresh, 30000);
    return () => clearInterval(interval);
  }, [optInEnabled, optInDisplayName, optInAnonId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Show opt-in modal on first visit
  useEffect(() => {
    if (!optInModalSeen) {
      setOptInModalOpen(true);
      markOptInModalSeen();
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const toggleSystemPanel = useAppStore((s) => s.toggleSystemPanel);

  // Global keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setCommandPaletteOpen(!commandPaletteOpen);
      }
      if ((e.metaKey || e.ctrlKey) && e.key === 'i') {
        e.preventDefault();
        toggleSystemPanel();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [commandPaletteOpen, setCommandPaletteOpen, toggleSystemPanel]);

  // Desktop auto-update check — disabled during local development.
  // Re-enable for production releases by uncommenting below.
  // const updateChecked = useRef(false);
  // useEffect(() => {
  //   if (!isTauri() || updateChecked.current) return;
  //   updateChecked.current = true;
  //   (async () => {
  //     try {
  //       const { check } = await import('@tauri-apps/plugin-updater');
  //       const update = await check();
  //       if (update) {
  //         await update.downloadAndInstall();
  //         const { toast } = await import('sonner');
  //         toast.info('Update ready', {
  //           description: 'A new version has been downloaded. Restart to apply.',
  //           duration: Infinity,
  //           action: {
  //             label: 'Restart Now',
  //             onClick: async () => {
  //               const { relaunch } = await import('@tauri-apps/plugin-process');
  //               await relaunch();
  //             },
  //           },
  //         });
  //       }
  //     } catch {}
  //   })();
  // }, []);

  if (!setupDone) {
    return <SetupScreen onReady={handleSetupReady} />;
  }

  return (
    <>
      <AppRoutes />
      <WatchtowerNotifier />
      <Toaster position="bottom-right" />
      {commandPaletteOpen && <CommandPalette />}
      {optInModalOpen && (
        <OptInModal onClose={() => setOptInModalOpen(false)} />
      )}
    </>
  );
}
