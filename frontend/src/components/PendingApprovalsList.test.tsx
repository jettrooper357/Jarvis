import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PendingApprovalsList } from './PendingApprovalsList';
import * as api from '../lib/api';
import type { ApprovalRequest } from '../lib/api';

vi.mock('../lib/api');
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

function approval(over: Partial<ApprovalRequest> = {}): ApprovalRequest {
  return {
    id: 'appr-1',
    agent_id: 'agent-1',
    task_id: 'task-1',
    capability: 'delete_files',
    args: { path: '/tmp/x' },
    args_hash: 'abc123',
    summary: 'Gated agent wants to delete files',
    state: 'pending',
    requested_by: 'agent-1',
    requested_at: 0,
    resolved_by: null,
    resolved_at: null,
    consumed_at: null,
    decision: null,
    reason: null,
    ...over,
  };
}

describe('PendingApprovalsList', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders nothing when there are no pending approvals', async () => {
    vi.mocked(api.listApprovals).mockResolvedValue([]);
    const { container } = render(<PendingApprovalsList />);
    await waitFor(() => expect(api.listApprovals).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it('renders a pending approval with capability, agent name and args', async () => {
    vi.mocked(api.listApprovals).mockResolvedValue([approval()]);
    render(
      <PendingApprovalsList agentNameById={{ 'agent-1': 'Gated Agent' }} />,
    );
    expect(await screen.findByText('delete_files')).toBeInTheDocument();
    expect(screen.getByText(/1 action awaiting approval/)).toBeInTheDocument();
    expect(screen.getByText(/Gated Agent/)).toBeInTheDocument();
    expect(
      screen.getByText('Gated agent wants to delete files'),
    ).toBeInTheDocument();
    expect(screen.getByText(/"path":"\/tmp\/x"/)).toBeInTheDocument();
  });

  it('pluralises the header for multiple approvals', async () => {
    vi.mocked(api.listApprovals).mockResolvedValue([
      approval({ id: 'a1' }),
      approval({ id: 'a2', capability: 'shell_exec' }),
    ]);
    render(<PendingApprovalsList />);
    expect(
      await screen.findByText(/2 actions awaiting approval/),
    ).toBeInTheDocument();
  });

  it('grants an approval and refreshes the list', async () => {
    vi.mocked(api.listApprovals)
      .mockResolvedValueOnce([approval()])
      .mockResolvedValueOnce([]);
    vi.mocked(api.grantApproval).mockResolvedValue(
      approval({ state: 'granted' }),
    );

    render(<PendingApprovalsList />);
    const grantBtn = await screen.findByRole('button', { name: /Grant/ });
    await userEvent.click(grantBtn);

    expect(api.grantApproval).toHaveBeenCalledWith('appr-1', {
      resolvedBy: 'human',
    });
    await waitFor(() =>
      expect(screen.queryByText('delete_files')).not.toBeInTheDocument(),
    );
  });

  it('denies an approval via the deny endpoint', async () => {
    vi.mocked(api.listApprovals)
      .mockResolvedValueOnce([approval()])
      .mockResolvedValueOnce([]);
    vi.mocked(api.denyApproval).mockResolvedValue(
      approval({ state: 'denied' }),
    );

    render(<PendingApprovalsList />);
    const denyBtn = await screen.findByRole('button', { name: /Deny/ });
    await userEvent.click(denyBtn);

    expect(api.denyApproval).toHaveBeenCalledWith('appr-1', {
      resolvedBy: 'human',
    });
  });

  it('renders nothing when the approvals lookup fails', async () => {
    vi.mocked(api.listApprovals).mockRejectedValue(new Error('boom'));
    const { container } = render(<PendingApprovalsList />);
    await waitFor(() => expect(api.listApprovals).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
