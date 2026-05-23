import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { ShieldCheck, Check, X } from 'lucide-react';
import { listApprovals, grantApproval, denyApproval } from '../lib/api';
import type { ApprovalRequest } from '../lib/api';

/**
 * Phase 2D — pending human-approval requests.
 *
 * Surfaces rows from `GET /v1/approvals?state=pending`; Grant/Deny call
 * the existing `/v1/approvals/{id}/grant|deny` endpoints. Renders nothing
 * when there are no pending approvals (the common case — approval gating
 * is opt-in and off by default), so it is safe to mount unconditionally.
 */
export function PendingApprovalsList({
  agentId,
  agentNameById,
  variant = 'panel',
}: {
  agentId?: string;
  agentNameById?: Record<string, string>;
  variant?: 'panel' | 'card';
}) {
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setApprovals(await listApprovals({ state: 'pending', agentId }));
    } catch {
      setApprovals([]);
    }
  }, [agentId]);

  useEffect(() => {
    load();
    const interval = window.setInterval(load, 20000);
    return () => window.clearInterval(interval);
  }, [load]);

  const resolve = useCallback(
    async (id: string, action: 'grant' | 'deny') => {
      setBusyId(id);
      try {
        if (action === 'grant') {
          await grantApproval(id, { resolvedBy: 'human' });
          toast.success('Approval granted');
        } else {
          await denyApproval(id, { resolvedBy: 'human' });
          toast.success('Approval denied');
        }
        await load();
      } catch (err: unknown) {
        toast.error('Could not resolve approval', {
          description: err instanceof Error ? err.message : 'Unknown error',
        });
      } finally {
        setBusyId(null);
      }
    },
    [load],
  );

  if (approvals.length === 0) return null;

  return (
    <div
      className={variant === 'card' ? 'mb-4 p-4 rounded-lg' : 'mb-4 p-3 rounded-xl'}
      style={{
        background: 'var(--color-bg-secondary)',
        border: '1px solid color-mix(in srgb, var(--color-warning) 40%, var(--color-border))',
      }}
    >
      <div className="mb-2 flex items-center gap-2">
        <ShieldCheck size={15} style={{ color: 'var(--color-warning)' }} />
        <span className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
          {approvals.length} action{approvals.length === 1 ? '' : 's'} awaiting approval
        </span>
      </div>
      <div className="space-y-2">
        {approvals.map((req) => {
          const name = agentNameById?.[req.agent_id] || req.agent_id;
          const argsText = (() => {
            try {
              const s = JSON.stringify(req.args);
              return s && s !== '{}' ? s : '';
            } catch {
              return '';
            }
          })();
          return (
            <div
              key={req.id}
              className="rounded-lg p-2.5"
              style={{
                background: 'var(--color-bg)',
                border: '1px solid var(--color-border)',
              }}
            >
              <div className="text-xs font-semibold" style={{ color: 'var(--color-text)' }}>
                {name} → <span style={{ color: 'var(--color-warning)' }}>{req.capability}</span>
              </div>
              {req.summary && (
                <div className="mt-0.5 text-[11px]" style={{ color: 'var(--color-text-secondary)' }}>
                  {req.summary}
                </div>
              )}
              {argsText && (
                <div
                  className="mt-1 truncate font-mono text-[10px]"
                  style={{ color: 'var(--color-text-tertiary)' }}
                  title={argsText}
                >
                  {argsText}
                </div>
              )}
              <div className="mt-2 flex gap-2">
                <button
                  type="button"
                  disabled={busyId === req.id}
                  onClick={() => resolve(req.id, 'grant')}
                  className="flex items-center gap-1 rounded-md px-2.5 py-1 text-[11px] font-medium disabled:opacity-50"
                  style={{ background: 'var(--color-success)', color: 'var(--color-on-accent)' }}
                >
                  <Check size={12} /> Grant
                </button>
                <button
                  type="button"
                  disabled={busyId === req.id}
                  onClick={() => resolve(req.id, 'deny')}
                  className="flex items-center gap-1 rounded-md px-2.5 py-1 text-[11px] font-medium disabled:opacity-50"
                  style={{
                    background: 'transparent',
                    border: '1px solid var(--color-error)',
                    color: 'var(--color-error)',
                  }}
                >
                  <X size={12} /> Deny
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
