import { getBase } from './api';
import type { ConnectorInfo, SyncStatus, ConnectRequest } from '../types/connectors';

// ---------------------------------------------------------------------------
// Connectors API
// ---------------------------------------------------------------------------

export async function listConnectors(): Promise<ConnectorInfo[]> {
  const res = await fetch(`${getBase()}/v1/connectors`);
  if (!res.ok) throw new Error(`Failed to list connectors: ${res.status}`);
  const data = await res.json();
  return data.connectors || [];
}

export async function getConnector(id: string): Promise<ConnectorInfo> {
  const res = await fetch(`${getBase()}/v1/connectors/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error(`Failed to get connector ${id}: ${res.status}`);
  return res.json();
}

export async function connectSource(id: string, req: ConnectRequest): Promise<ConnectorInfo> {
  const res = await fetch(`${getBase()}/v1/connectors/${encodeURIComponent(id)}/connect`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  if (!res.ok) throw new Error(`Failed to connect ${id}: ${res.status}`);
  return res.json();
}

export async function disconnectSource(id: string): Promise<void> {
  const res = await fetch(`${getBase()}/v1/connectors/${encodeURIComponent(id)}/disconnect`, {
    method: 'POST',
  });
  if (!res.ok) throw new Error(`Failed to disconnect ${id}: ${res.status}`);
}

export async function getSyncStatus(id: string): Promise<SyncStatus> {
  const res = await fetch(`${getBase()}/v1/connectors/${encodeURIComponent(id)}/sync`);
  if (!res.ok) throw new Error(`Failed to get sync status for ${id}: ${res.status}`);
  return res.json();
}

export async function triggerSync(id: string): Promise<{ connector_id: string; chunks_indexed: number; status: string }> {
  const res = await fetch(`${getBase()}/v1/connectors/${encodeURIComponent(id)}/sync`, {
    method: 'POST',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Sync failed: ${res.status}`);
  }
  return res.json();
}

export async function getConnectorConfig(
  id: string,
): Promise<{ connector_id: string; path: string; exists: boolean; content: string }> {
  const res = await fetch(
    `${getBase()}/v1/connectors/${encodeURIComponent(id)}/config`,
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Failed to load config: ${res.status}`);
  }
  return res.json();
}

export async function saveConnectorConfig(
  id: string,
  content: string,
): Promise<{ connector_id: string; path: string; saved: boolean }> {
  const res = await fetch(
    `${getBase()}/v1/connectors/${encodeURIComponent(id)}/config`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    },
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Failed to save config: ${res.status}`);
  }
  return res.json();
}

export async function fetchTelegramConfig(): Promise<{
  has_token: boolean;
  token_preview: string;
  bot_token: string;
  allowed_chat_ids: string;
}> {
  const res = await fetch(`${getBase()}/v1/channels/telegram/config`);
  if (!res.ok) throw new Error(`Failed to fetch telegram config: ${res.status}`);
  return res.json();
}

export async function saveTelegramConfig(
  botToken: string,
  allowedChatIds: string = '',
): Promise<{
  saved: boolean;
  token_preview: string;
  bot_token: string;
  allowed_chat_ids: string;
  restart_required: boolean;
}> {
  const res = await fetch(`${getBase()}/v1/channels/telegram/config`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ bot_token: botToken, allowed_chat_ids: allowedChatIds }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Save failed: ${res.status}`);
  }
  return res.json();
}

export async function fetchTelegramHealth(): Promise<{
  configured: boolean;
  status: 'ok' | 'not_configured' | 'network_error' | 'invalid_token' | 'telegram_error';
  message: string;
  detail?: string;
  bot_username?: string;
  bot_id?: number;
}> {
  const res = await fetch(`${getBase()}/v1/channels/telegram/health`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Failed to check Telegram health: ${res.status}`);
  }
  return res.json();
}

export async function saveOAuthClient(
  provider: string,
  payload: unknown,
): Promise<{ provider: string; client_id_preview: string; saved_files: string[] }> {
  const res = await fetch(
    `${getBase()}/v1/connectors/oauth-clients/${encodeURIComponent(provider)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Save failed: ${res.status}`);
  }
  return res.json();
}
