import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  escalateWatchtowerFinding,
  fetchWatchtowerFindings,
  fetchWatchtowerInternalRoutes,
  fetchWatchtowerSettings,
  fetchWatchtowerStatus,
  patchWatchtowerSettings,
  resolveWatchtowerFinding,
  snoozeWatchtowerFinding,
} from '../../lib/api';
import { WatchtowerPanel } from './WatchtowerPanel';
import { WatchtowerSettingsSection } from './WatchtowerSettingsSection';

vi.mock('../../lib/api', () => ({
  escalateWatchtowerFinding: vi.fn(),
  fetchWatchtowerFindings: vi.fn(),
  fetchWatchtowerInternalRoutes: vi.fn(),
  fetchWatchtowerSettings: vi.fn(),
  fetchWatchtowerStatus: vi.fn(),
  patchWatchtowerSettings: vi.fn(),
  resolveWatchtowerFinding: vi.fn(),
  scanWatchtowerNow: vi.fn().mockResolvedValue({ findings: [] }),
  snoozeWatchtowerFinding: vi.fn(),
}));

const status = {
  enabled: true,
  running: true,
  last_scan_at: 1_785_000_000,
  local_ai_status: 'rules_fallback',
  local_ai_only: true,
  local_ai_provider: 'ollama',
  rules_fallback_active: true,
  dnd_active: true,
  telegram_enabled: true,
  active_findings: 1,
  pending_internal_routes: 1,
};

const finding = {
  finding_id: 'finding-1',
  finding_type: 'approval_pending_too_long',
  entity_type: 'approval',
  entity_id: 'approval-1',
  project_id: 'project-1',
  task_id: 'task-1',
  agent_id: 'agent-1',
  priority: 'urgent',
  status: 'active',
  reason: 'Approval has been pending for too long.',
  recommended_action: 'Ask the user to approve or reject the request.',
  created_at: 1,
  updated_at: 1,
  resolved_at: null,
  last_notified_at: 2,
  notification_count: 1,
  dedupe_key: 'approval:approval-1',
  metadata_json: { rules_fallback_used: true },
};

const route = {
  route_id: 'route-1',
  finding_id: 'finding-1',
  source: 'watchtower',
  from_agent_id: 'watchtower',
  to_agent_id: 'chief_orchestrator',
  route_type: 'send_to_chief',
  priority: 'urgent',
  message_type: 'approval_needed',
  requires_response: true,
  response_due_at: 1_785_000_300,
  status: 'sent',
  created_at: 1,
  responded_at: null,
  escalated_at: null,
  metadata_json: {},
};

const settings = {
  enabled: true,
  loop_interval_seconds: 60,
  local_ai_only: true,
  local_model_required: true,
  fallback_to_rules_if_local_ai_unavailable: true,
  dnd_enabled: true,
  quiet_hours_start: '22:00',
  quiet_hours_end: '07:00',
  dnd_timezone: 'local',
  allow_emergency_bypass: true,
  allow_urgent_bypass: false,
  defer_low_priority: true,
  defer_normal_priority: true,
  defer_high_priority: false,
  in_app_enabled: true,
  telegram_enabled: true,
  in_app_min_priority: 'info',
  telegram_min_priority: 'high',
  both_min_priority: 'urgent',
  default_cooldown_minutes: 30,
  emergency_cooldown_minutes: 5,
  digest_interval_minutes: 60,
  internal_route_timeout_minutes: 30,
  local_ai_provider: 'ollama',
};

describe('WatchtowerPanel', () => {
  beforeEach(() => {
    vi.mocked(fetchWatchtowerStatus).mockResolvedValue(status as any);
    vi.mocked(fetchWatchtowerFindings).mockResolvedValue([finding as any]);
    vi.mocked(fetchWatchtowerInternalRoutes).mockResolvedValue([route as any]);
    vi.mocked(resolveWatchtowerFinding).mockResolvedValue(undefined);
    vi.mocked(snoozeWatchtowerFinding).mockResolvedValue(undefined);
    vi.mocked(escalateWatchtowerFinding).mockResolvedValue(undefined);
    vi.mocked(fetchWatchtowerSettings).mockResolvedValue(settings as any);
    vi.mocked(patchWatchtowerSettings).mockResolvedValue(settings as any);
  });

  it('renders findings, DND state, priority badges, and fallback status', async () => {
    render(<WatchtowerPanel />);

    expect(await screen.findByTestId('watchtower-panel')).toBeInTheDocument();
    expect(screen.getByText('DND Active')).toBeInTheDocument();
    expect(screen.getAllByText('Rules Fallback').length).toBeGreaterThan(0);
    expect(screen.getAllByText('urgent').length).toBeGreaterThan(0);
    expect(screen.getByText('Approval has been pending for too long.')).toBeInTheDocument();
  });

  it('renders internal routes tab with Watchtower-triggered labels', async () => {
    render(<WatchtowerPanel />);

    await userEvent.click(await screen.findByRole('button', { name: 'Internal Routes' }));

    expect(screen.getByText('Watchtower-triggered')).toBeInTheDocument();
    expect(screen.getByText('approval needed')).toBeInTheDocument();
    expect(screen.getByText('watchtower to chief_orchestrator')).toBeInTheDocument();
  });

  it('calls snooze, resolve, and escalate APIs', async () => {
    render(<WatchtowerPanel />);

    await userEvent.click(await screen.findByRole('button', { name: 'Snooze' }));
    await userEvent.click(screen.getByRole('button', { name: 'Resolve' }));
    await userEvent.click(screen.getByRole('button', { name: 'Escalate' }));

    await waitFor(() => expect(snoozeWatchtowerFinding).toHaveBeenCalledWith('finding-1'));
    expect(resolveWatchtowerFinding).toHaveBeenCalledWith('finding-1');
    expect(escalateWatchtowerFinding).toHaveBeenCalledWith('finding-1');
  });
});

describe('WatchtowerSettingsSection', () => {
  beforeEach(() => {
    vi.mocked(fetchWatchtowerSettings).mockResolvedValue(settings as any);
    vi.mocked(patchWatchtowerSettings).mockResolvedValue({ ...settings, telegram_min_priority: 'urgent' } as any);
  });

  it('saves DND and priority routing settings', async () => {
    render(<WatchtowerSettingsSection />);

    await userEvent.selectOptions(
      await screen.findByDisplayValue('high'),
      'urgent',
    );

    await waitFor(() =>
      expect(patchWatchtowerSettings).toHaveBeenCalledWith({
        telegram_min_priority: 'urgent',
      }),
    );
  });
});
