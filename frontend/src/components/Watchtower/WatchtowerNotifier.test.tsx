import { render, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { toast } from 'sonner';
import { fetchWatchtowerBrief } from '../../lib/api';
import { WatchtowerNotifier } from './WatchtowerNotifier';

vi.mock('sonner', () => ({
  toast: {
    warning: vi.fn(),
  },
}));

vi.mock('../../lib/api', () => ({
  fetchWatchtowerBrief: vi.fn(),
}));

describe('WatchtowerNotifier', () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.mocked(toast.warning).mockClear();
    vi.mocked(fetchWatchtowerBrief).mockResolvedValue({
      status: {
        enabled: true,
        running: true,
        last_scan_at: 1,
        local_ai_status: 'rules_fallback',
        local_ai_only: true,
        local_ai_provider: 'ollama',
        rules_fallback_active: true,
        dnd_active: false,
        telegram_enabled: true,
        speech_enabled: true,
        active_findings: 1,
        pending_internal_routes: 1,
      },
      active_count: 1,
      actionable_count: 1,
      items: [
        {
          finding_id: 'finding-1',
          finding_type: 'overdue_task',
          entity_type: 'project_task',
          entity_id: 'task-1',
          priority: 'high',
          status: 'active',
          reason: 'Project task is overdue.',
          recommended_action: 'Check status.',
          created_at: 1,
          updated_at: 1,
          notification_count: 1,
          dedupe_key: 'overdue_task:project_task:task-1:high',
          metadata_json: {},
        },
      ],
      recent_notifications: [],
      recent_speech: [],
      pending_routes: [],
    });
  });

  it('shows a proactive Watchtower toast for actionable findings', async () => {
    render(
      <MemoryRouter>
        <WatchtowerNotifier />
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(toast.warning).toHaveBeenCalledWith(
        'Watchtower: overdue task',
        expect.objectContaining({
          description: 'Project task is overdue.',
        }),
      ),
    );
  });
});
