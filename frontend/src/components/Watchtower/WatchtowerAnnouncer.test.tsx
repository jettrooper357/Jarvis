import { render, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { toast } from 'sonner';
import { fetchWatchtowerFindings, fetchWatchtowerStatus } from '../../lib/api';
import type { WatchtowerFinding, WatchtowerStatus } from '../../lib/api';
import { WatchtowerAnnouncer } from './WatchtowerAnnouncer';

const speak = vi.fn();

vi.mock('sonner', () => ({
  toast: { info: vi.fn(), warning: vi.fn() },
}));
vi.mock('../../hooks/useTTSPlayer', () => ({
  useTTSPlayer: () => ({ speak, isSpeaking: false, feedToken: vi.fn(), flush: vi.fn(), stop: vi.fn() }),
}));
let mockUnlocked = true;
vi.mock('../../hooks/useAudioUnlock', () => ({
  useAudioUnlock: () => ({ unlocked: mockUnlocked }),
}));
vi.mock('../../lib/api', () => ({
  fetchWatchtowerFindings: vi.fn(),
  fetchWatchtowerStatus: vi.fn(),
}));

function finding(over: Partial<WatchtowerFinding> = {}): WatchtowerFinding {
  return {
    finding_id: 'f1',
    finding_type: 'overdue_task',
    entity_type: 'project_task',
    entity_id: 'task-1',
    priority: 'normal',
    status: 'active',
    reason: 'Task overdue.',
    recommended_action: 'Check.',
    created_at: 1,
    updated_at: 1,
    notification_count: 0,
    dedupe_key: 'k',
    metadata_json: {},
    ...over,
  };
}

function status(over: Partial<WatchtowerStatus> = {}): WatchtowerStatus {
  return {
    enabled: true,
    running: true,
    last_scan_at: 1,
    local_ai_status: 'rules_fallback',
    local_ai_only: true,
    local_ai_provider: 'ollama',
    rules_fallback_active: true,
    dnd_active: false,
    telegram_enabled: false,
    speech_enabled: true,
    active_findings: 0,
    pending_internal_routes: 0,
    ...over,
  } as WatchtowerStatus;
}

function renderAnnouncer() {
  return render(
    <MemoryRouter>
      <WatchtowerAnnouncer />
    </MemoryRouter>,
  );
}

describe('WatchtowerAnnouncer', () => {
  beforeEach(() => {
    mockUnlocked = true;
    localStorage.clear();
    sessionStorage.clear();
    speak.mockClear();
    vi.mocked(toast.info).mockClear();
    vi.mocked(toast.warning).mockClear();
    vi.mocked(fetchWatchtowerStatus).mockResolvedValue(status());
  });
  afterEach(() => vi.mocked(fetchWatchtowerFindings).mockReset());

  it('greets once and does NOT speak the backlog on login', async () => {
    vi.mocked(fetchWatchtowerFindings).mockResolvedValue([finding({ finding_id: 'backlog' })]);
    renderAnnouncer();
    await waitFor(() => expect(toast.info).toHaveBeenCalledWith('Jarvis online', expect.any(Object)));
    await waitFor(() => expect(speak).toHaveBeenCalledWith('Jarvis online. Monitoring active.'));
    expect(toast.warning).not.toHaveBeenCalled();
    expect(speak).toHaveBeenCalledTimes(1);
  });

  it('announces a new finding that appears after login', async () => {
    vi.mocked(fetchWatchtowerFindings).mockResolvedValue([finding({ finding_id: 'backlog' })]);
    renderAnnouncer();
    await waitFor(() => expect(toast.info).toHaveBeenCalled());

    vi.mocked(fetchWatchtowerFindings).mockResolvedValue([
      finding({ finding_id: 'backlog' }),
      finding({ finding_id: 'new', finding_type: 'stale_approval', reason: 'Sign-off needed.' }),
    ]);
    window.dispatchEvent(new Event('focus'));

    await waitFor(() =>
      expect(toast.warning).toHaveBeenCalledWith('Watchtower: stale approval', expect.objectContaining({ description: 'Sign-off needed.' })),
    );
    expect(speak).toHaveBeenCalledWith('Jarvis Watchtower. stale approval. Sign-off needed.');
  });

  it('toasts but does not speak when speech is disabled', async () => {
    vi.mocked(fetchWatchtowerStatus).mockResolvedValue(status({ speech_enabled: false }));
    vi.mocked(fetchWatchtowerFindings).mockResolvedValueOnce([]);
    renderAnnouncer();
    await waitFor(() => expect(toast.info).toHaveBeenCalled());

    vi.mocked(fetchWatchtowerFindings).mockResolvedValue([finding({ finding_id: 'new' })]);
    window.dispatchEvent(new Event('focus'));
    await waitFor(() => expect(toast.warning).toHaveBeenCalled());
    expect(speak).not.toHaveBeenCalledWith(expect.stringContaining('Jarvis Watchtower.'));
  });

  it('toasts but does not speak findings during DnD', async () => {
    vi.mocked(fetchWatchtowerStatus).mockResolvedValue(status({ dnd_active: true }));
    vi.mocked(fetchWatchtowerFindings).mockResolvedValueOnce([]);
    renderAnnouncer();
    await waitFor(() => expect(toast.info).toHaveBeenCalled());

    vi.mocked(fetchWatchtowerFindings).mockResolvedValue([finding({ finding_id: 'new' })]);
    window.dispatchEvent(new Event('focus'));
    await waitFor(() => expect(toast.warning).toHaveBeenCalled());
    expect(speak).not.toHaveBeenCalledWith(expect.stringContaining('Jarvis Watchtower.'));
  });

  it('does nothing when proactive announcements are disabled', async () => {
    localStorage.setItem('watchtower-proactive-enabled', 'false');
    vi.mocked(fetchWatchtowerFindings).mockResolvedValue([finding()]);
    renderAnnouncer();
    await new Promise((r) => setTimeout(r, 50));
    expect(toast.info).not.toHaveBeenCalled();
    expect(speak).not.toHaveBeenCalled();
  });

  it('defers the spoken greeting until audio unlocks', async () => {
    mockUnlocked = false;
    vi.mocked(fetchWatchtowerFindings).mockResolvedValue([]);
    const { rerender } = renderAnnouncer();

    await waitFor(() =>
      expect(toast.info).toHaveBeenCalledWith('Jarvis online', expect.any(Object)),
    );
    expect(speak).not.toHaveBeenCalled();
    expect(toast.info).toHaveBeenCalledWith(
      'Click anywhere to enable Jarvis voice',
      expect.any(Object),
    );

    mockUnlocked = true;
    rerender(
      <MemoryRouter>
        <WatchtowerAnnouncer />
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(speak).toHaveBeenCalledWith('Jarvis online. Monitoring active.'),
    );
  });
});
