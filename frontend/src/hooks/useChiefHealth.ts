import { useCallback, useEffect, useState } from 'react';
import { getChiefStatus, type ChiefStatus } from '../lib/api';

const DEFAULT_POLL_MS = 30_000;
const FALLBACK: ChiefStatus = { enabled: false, chief_id: null, chief_name: null };

/**
 * Phase 2E — small hook that polls `GET /v1/chief/status`.
 *
 * The frontend gates its default-ingress switch on
 * `status.enabled && status.chief_id`. While the feature flag is off
 * server-side (Phase 2E commit 1 + commit 2 default), every consumer
 * sees `enabled: false` and falls back to the legacy ingress.
 */
export function useChiefHealth(pollIntervalMs: number = DEFAULT_POLL_MS) {
  const [status, setStatus] = useState<ChiefStatus>(FALLBACK);
  const [loaded, setLoaded] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const next = await getChiefStatus();
      setStatus(next);
    } catch {
      setStatus(FALLBACK);
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    void refresh();
    if (pollIntervalMs <= 0) return;
    const id = window.setInterval(() => {
      if (!cancelled) void refresh();
    }, pollIntervalMs);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [pollIntervalMs, refresh]);

  return {
    status,
    loaded,
    refresh,
    /** True when the default ingress should route through the Chief. */
    chiefIngressActive: status.enabled && !!status.chief_id,
  } as const;
}
