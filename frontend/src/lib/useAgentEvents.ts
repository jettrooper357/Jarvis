import { useEffect, useRef } from 'react';
import { getBase } from './api';

export interface AgentEvent {
  type: string;
  timestamp: number;
  data: Record<string, unknown>;
}

function buildWsUrl(agentId?: string): string {
  const base = getBase();
  let origin: string;
  if (base) {
    origin = base.replace(/^http/, 'ws');
  } else {
    const loc = window.location;
    origin = `${loc.protocol === 'https:' ? 'wss:' : 'ws:'}//${loc.host}`;
  }
  const path = '/v1/agents/events';
  return agentId
    ? `${origin}${path}?agent_id=${encodeURIComponent(agentId)}`
    : `${origin}${path}`;
}

/**
 * Subscribe to agent events over WebSocket.
 * Auto-reconnects with backoff when the socket drops.
 *
 * Pass `'*'` as ``agentId`` to receive events for every agent (no
 * server-side filter) — used by the org chart to track activity globally.
 */
export function useAgentEvents(
  agentId: string | undefined,
  onEvent: (event: AgentEvent) => void,
  eventTypes?: readonly string[],
): void {
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  const typesRef = useRef(eventTypes);
  typesRef.current = eventTypes;

  useEffect(() => {
    if (!agentId) return;
    let ws: WebSocket | null = null;
    let closed = false;
    let retry = 0;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    // A connection must stay open at least this long to count as
    // "healthy" and reset the backoff. Sockets that open then close
    // almost immediately are flapping (backend overloaded/restarting);
    // resetting the backoff on every onopen turns that into a ~1s
    // reconnect hammer that, across every mounted subscription (incl.
    // the global '*' one), exhausts browser sockets
    // (net::ERR_INSUFFICIENT_RESOURCES).
    const STABLE_MS = 5000;

    const connect = () => {
      if (closed) return;
      let openedAt = 0;
      try {
        ws = new WebSocket(buildWsUrl(agentId === '*' ? undefined : agentId));
      } catch {
        schedule();
        return;
      }
      ws.onopen = () => {
        openedAt = Date.now();
      };
      ws.onmessage = (msg) => {
        try {
          const payload = JSON.parse(msg.data) as AgentEvent;
          if (payload.type === 'ping') return; // server idle keepalive
          const allowed = typesRef.current;
          if (allowed && !allowed.includes(payload.type)) return;
          onEventRef.current(payload);
        } catch {
          // ignore malformed payload
        }
      };
      ws.onclose = () => {
        if (closed) return;
        if (openedAt && Date.now() - openedAt >= STABLE_MS) {
          retry = 0; // genuine long-lived connection dropped — reconnect fast
        }
        schedule();
      };
      ws.onerror = () => {
        ws?.close();
      };
    };

    const schedule = () => {
      if (closed) return;
      // Exponential backoff (1s→30s) plus jitter so the many concurrent
      // subscriptions don't reconnect in lockstep (thundering herd).
      const base = Math.min(30000, 1000 * 2 ** Math.min(retry, 5));
      const delay = base + Math.floor(Math.random() * 1000);
      retry += 1;
      reconnectTimer = setTimeout(connect, delay);
    };

    connect();

    return () => {
      closed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, [agentId]);
}
