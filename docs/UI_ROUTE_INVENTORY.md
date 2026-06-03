# UI Route Inventory

Status: navigation consolidation audit, generated 2026-06-03.

This inventory supports the additive workspace reorganization. Existing
protected pages remain mounted through compatibility redirects or aliases.
No API contract, persistence shape, or protected workflow is changed by this
route layer update.

## Workspace Routes

| Workspace | Route | Composed surface |
| --- | --- | --- |
| Command Center | `/command/today` | Chat page / Chief-facing task entry |
| Command Center | `/command/chat` | Redirect alias to `/command/today` |
| Command Center | `/command/mission-control` | Mission Control dashboard |
| Command Center | `/command/planner` | Personal planning page |
| Command Center | `/command/approvals` | Pending approvals surface |
| Command Center | `/command/activity` | Logs/activity feed |
| Projects | `/projects` | ProjectsPage |
| Projects | `/projects/dashboard` | ProjectDashboardPage |
| Projects | `/projects/:projectId` | ProjectDetailPage with project-specific Project / Timeline tabs |
| Projects | `/projects/:projectId/timeline` | ProjectTimelinePage with project-specific Project / Timeline tabs |
| Agents | `/agents/org-chart` | AgentsPage |
| Agents | `/agents/list` | Redirect alias to `/agents/org-chart` |
| Agents | `/agents/conversations` | Redirect alias to `/agents/org-chart` |
| Agents | `/agents/assignments` | Redirect alias to `/agents/org-chart` |
| Agents | `/agents/capabilities` | Redirect alias to `/agents/org-chart` |
| Knowledge | `/knowledge/library` | LibraryPage |
| Knowledge | `/knowledge/data-sources` | DataSourcesPage |
| Knowledge | `/knowledge/skills` | Knowledge catalog placeholder |
| Knowledge | `/knowledge/presets` | Knowledge catalog placeholder |
| Knowledge | `/knowledge/tools` | Knowledge catalog placeholder |
| Knowledge | `/knowledge/search` | Knowledge catalog placeholder |
| System | `/system/settings` | SettingsPage |
| System | `/system/logs` | LogsPage |
| System | `/system/diagnostics` | Diagnostics placeholder |
| System | `/system/setup` | GetStartedPage |
| System | `/system/security` | Security/audit placeholder |

## Compatibility Redirects

| Old route | New route |
| --- | --- |
| `/` | `/command/today` |
| `/chat` | `/command/today` |
| `/dashboard` | `/command/mission-control` |
| `/mission-control` | `/command/mission-control` |
| `/life-planner` | `/command/planner` |
| `/agents` | `/agents/org-chart` |
| `/library` | `/knowledge/library` |
| `/data-sources` | `/knowledge/data-sources` |
| `/logs` | `/system/logs` |
| `/settings` | `/system/settings` |
| `/get-started` | `/system/setup` |

## Protected Feature Notes

- Mission Control continues to use `DashboardPage` and the existing
  `MissionControlPanel` fetcher/UI path.
- Project pages continue to use the existing `ProjectsPage`,
  `ProjectDashboardPage`, `ProjectDetailPage`, and `ProjectTimelinePage`.
- Agents workspace routes compose the existing `AgentsPage`, preserving the
  org chart, inter-agent activity sidebar, and agent detail tabs.
- Library, Data Sources, Logs, Settings, and Get Started remain mounted from
  their existing page components.
