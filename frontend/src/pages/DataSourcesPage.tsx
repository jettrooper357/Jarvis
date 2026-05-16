import { useEffect, useState, useCallback, useRef } from 'react';
import type { ReactNode, CSSProperties } from 'react';
import { motion } from 'motion/react';
import { useAppStore } from '../lib/store';
import {
  fetchManagedAgents,
  fetchAgentChannels,
  bindAgentChannel,
  unbindAgentChannel,
  createManagedAgent,
  sendblueRegisterWebhook,
  sendblueHealth,
  getMemoryStats,
  searchMemory,
  storeMemory,
  indexMemoryPath,
} from '../lib/api';
import type { ChannelBinding, ManagedAgent, MemoryStats, MemorySearchResult } from '../lib/api';
import { getBase, isTauri } from '../lib/api';
import {
  Database, MessageSquare, Loader2, Brain, Search, FolderOpen, FileText,
  Mail, Hash, MessageCircle, CalendarDays, Contact, StickyNote, BookText,
  Package, Upload, Link2, PhoneCall, AlertTriangle, RefreshCw, CheckCircle2,
  ChevronRight, Shield, MoreHorizontal,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { SOURCE_CATALOG } from '../types/connectors';
import type { ConnectRequest } from '../types/connectors';
import {
  listConnectors,
  connectSource,
  getSyncStatus,
  triggerSync,
  saveOAuthClient,
  fetchTelegramConfig,
  saveTelegramConfig,
  fetchTelegramHealth,
  getConnectorConfig,
  saveConnectorConfig,
} from '../lib/connectors-api';
import type { SyncStatus } from '../types/connectors';
import { HudFrame } from '../components/Jarvis/HudFrame';

// ---------------------------------------------------------------------------
// Inline connect form (reused from AgentsPage pattern)
// ---------------------------------------------------------------------------

function InlineConnectForm({
  fields,
  loading,
  onSubmit,
}: {
  fields: Array<{ name: string; placeholder: string; type?: string }>;
  loading: boolean;
  onSubmit: (req: ConnectRequest) => void;
}) {
  const [inputs, setInputs] = useState<Record<string, string>>({});

  const update = (name: string, value: string) =>
    setInputs((p) => ({ ...p, [name]: value }));

  const allFilled = fields.every((f) => inputs[f.name]?.trim());

  const submit = () => {
    const req: ConnectRequest = {};
    for (const f of fields) {
      if (f.name === 'email') req.email = inputs.email;
      else if (f.name === 'password') req.password = inputs.password;
      else if (f.name === 'token') req.token = inputs.token;
      else if (f.name === 'path') req.path = inputs.path;
    }
    if (req.email && req.password) {
      req.token = `${req.email}:${req.password}`;
      req.code = req.token;
    }
    if (req.token && !req.code) req.code = req.token;
    onSubmit(req);
  };

  return (
    <div>
      {fields.map((f) => (
        <input
          key={f.name}
          value={inputs[f.name] || ''}
          onChange={(e) => update(f.name, e.target.value)}
          placeholder={f.placeholder}
          type={f.type || 'text'}
          style={{
            width: '100%', padding: '7px 10px',
            background: 'var(--color-bg)',
            border: '1px solid var(--color-border)',
            borderRadius: 4, color: 'var(--color-text)',
            fontSize: 12, marginBottom: 6,
            boxSizing: 'border-box',
          }}
        />
      ))}
      <button
        onClick={submit}
        disabled={loading || !allFilled}
        style={{
          width: '100%', padding: 8,
          background: loading || !allFilled ? 'var(--color-disabled-bg)' : 'var(--color-accent-purple)',
          color: 'var(--color-on-accent)', border: 'none',
          borderRadius: 6, fontSize: 12, cursor: 'pointer',
        }}
      >
        Connect
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Connector JSON config editor (file-backed sources, e.g. News / RSS)
// ---------------------------------------------------------------------------

function ConnectorConfigEditor({
  connectorId,
  onSaved,
}: {
  connectorId: string;
  onSaved?: () => void;
}) {
  const [content, setContent] = useState('');
  const [path, setPath] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    getConnectorConfig(connectorId)
      .then((r) => {
        if (alive) {
          setContent(r.content);
          setPath(r.path);
        }
      })
      .catch((e: any) => {
        if (alive) setMsg({ kind: 'err', text: e.message || 'Failed to load config' });
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [connectorId]);

  const save = async () => {
    setSaving(true);
    setMsg(null);
    try {
      await saveConnectorConfig(connectorId, content);
      setMsg({ kind: 'ok', text: 'Saved. Click Sync to ingest the latest items.' });
      onSaved?.();
    } catch (e: any) {
      setMsg({ kind: 'err', text: e.message || 'Save failed' });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ borderTop: '1px solid var(--color-border)', padding: 12 }}>
      <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 4, color: 'var(--color-text)' }}>
        Edit config (JSON)
      </div>
      {path && (
        <div
          style={{
            fontSize: 10,
            color: 'var(--color-text-tertiary)',
            marginBottom: 6,
            fontFamily: 'monospace',
            wordBreak: 'break-all',
          }}
        >
          {path}
        </div>
      )}
      {loading ? (
        <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
          <Loader2
            size={12}
            className="animate-spin"
            style={{ display: 'inline', marginRight: 6, verticalAlign: 'middle' }}
          />
          Loading…
        </div>
      ) : (
        <>
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            spellCheck={false}
            rows={10}
            style={{
              width: '100%',
              padding: 10,
              fontFamily: 'monospace',
              fontSize: 12,
              background: 'var(--color-bg)',
              border: '1px solid var(--color-border)',
              borderRadius: 4,
              color: 'var(--color-text)',
              boxSizing: 'border-box',
              resize: 'vertical',
            }}
          />
          {msg && (
            <div
              style={{
                fontSize: 11,
                marginTop: 6,
                color: msg.kind === 'ok' ? 'var(--color-success)' : 'var(--color-error)',
              }}
            >
              {msg.text}
            </div>
          )}
          <button
            onClick={save}
            disabled={saving}
            style={{
              marginTop: 8,
              width: '100%',
              padding: 8,
              background: saving ? 'var(--color-disabled-bg)' : 'var(--color-accent-purple)',
              color: 'var(--color-on-accent)',
              border: 'none',
              borderRadius: 6,
              fontSize: 12,
              cursor: saving ? 'not-allowed' : 'pointer',
            }}
          >
            {saving ? 'Saving…' : 'Save config'}
          </button>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Upload / Paste form
// ---------------------------------------------------------------------------

const ACCEPTED_EXTENSIONS = '.txt,.md,.pdf,.docx,.csv';

function UploadForm({ onDone }: { onDone?: () => void }) {
  const [tab, setTab] = useState<'paste' | 'upload'>('paste');
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState('');
  const [error, setError] = useState('');

  const handlePaste = async () => {
    if (!content.trim()) return;
    setBusy(true);
    setError('');
    setResult('');
    try {
      const res = await fetch(`${getBase()}/v1/connectors/upload/ingest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: title.trim(), content }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `Upload failed: ${res.status}`);
      }
      const data = await res.json();
      setResult(`Added ${data.chunks_added} chunk${data.chunks_added !== 1 ? 's' : ''} to knowledge base`);
      setTitle('');
      setContent('');
      onDone?.();
    } catch (err: any) {
      setError(err.message || 'Upload failed');
    } finally {
      setBusy(false);
    }
  };

  const handleUpload = async () => {
    if (files.length === 0) return;
    setBusy(true);
    setError('');
    setResult('');
    try {
      const formData = new FormData();
      for (const f of files) formData.append('files', f);
      if (title.trim()) formData.append('title', title.trim());

      const res = await fetch(`${getBase()}/v1/connectors/upload/ingest/files`, {
        method: 'POST',
        body: formData,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `Upload failed: ${res.status}`);
      }
      const data = await res.json();
      setResult(`Added ${data.chunks_added} chunk${data.chunks_added !== 1 ? 's' : ''} from ${files.length} file${files.length !== 1 ? 's' : ''}`);
      setFiles([]);
      setTitle('');
      onDone?.();
    } catch (err: any) {
      setError(err.message || 'Upload failed');
    } finally {
      setBusy(false);
    }
  };

  const tabStyle = (active: boolean): React.CSSProperties => ({
    flex: 1, padding: '6px 0', textAlign: 'center',
    fontSize: 12, fontWeight: 600, cursor: 'pointer',
    background: active ? 'var(--color-accent-purple)' : 'transparent',
    color: active ? 'white' : 'var(--color-text-secondary)',
    border: 'none', borderRadius: 4,
  });

  const inputStyle: React.CSSProperties = {
    width: '100%', padding: '7px 10px',
    background: 'var(--color-bg)',
    border: '1px solid var(--color-border)',
    borderRadius: 4, color: 'var(--color-text)',
    fontSize: 12, marginBottom: 6,
    boxSizing: 'border-box' as const,
  };

  return (
    <div>
      {/* Tab bar */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 10,
        background: 'var(--color-bg)', borderRadius: 6, padding: 2 }}>
        <button style={tabStyle(tab === 'paste')} onClick={() => setTab('paste')}>
          Paste Text
        </button>
        <button style={tabStyle(tab === 'upload')} onClick={() => setTab('upload')}>
          Upload Files
        </button>
      </div>

      {/* Title input (shared) */}
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Title (optional)"
        style={inputStyle}
      />

      {tab === 'paste' && (
        <>
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="Paste your text here..."
            rows={6}
            style={{
              ...inputStyle,
              resize: 'vertical',
              fontFamily: 'inherit',
              minHeight: 100,
            }}
          />
          <button
            onClick={handlePaste}
            disabled={busy || !content.trim()}
            style={{
              width: '100%', padding: 8,
              background: busy || !content.trim() ? 'var(--color-disabled-bg)' : 'var(--color-accent-purple)',
              color: 'var(--color-on-accent)', border: 'none',
              borderRadius: 6, fontSize: 12, cursor: 'pointer',
            }}
          >
            {busy ? 'Adding...' : 'Add to Knowledge Base'}
          </button>
        </>
      )}

      {tab === 'upload' && (
        <>
          <input
            type="file"
            multiple
            accept={ACCEPTED_EXTENSIONS}
            onChange={(e) => {
              const selected = Array.from(e.target.files || []);
              setFiles(selected);
            }}
            style={{ ...inputStyle, padding: 6 }}
          />
          {files.length > 0 && (
            <div style={{ fontSize: 11, color: 'var(--color-text-secondary)', marginBottom: 6 }}>
              {files.map((f) => f.name).join(', ')}
            </div>
          )}
          <button
            onClick={handleUpload}
            disabled={busy || files.length === 0}
            style={{
              width: '100%', padding: 8,
              background: busy || files.length === 0 ? 'var(--color-disabled-bg)' : 'var(--color-accent-purple)',
              color: 'var(--color-on-accent)', border: 'none',
              borderRadius: 6, fontSize: 12, cursor: 'pointer',
            }}
          >
            {busy ? 'Uploading...' : 'Upload & Index'}
          </button>
        </>
      )}

      {result && (
        <div style={{ fontSize: 12, color: 'var(--color-success)', marginTop: 8 }}>
          {result}
        </div>
      )}
      {error && (
        <div style={{ fontSize: 12, color: 'var(--color-error)', marginTop: 8 }}>
          {error}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Icon map
// ---------------------------------------------------------------------------

const iconMap: Record<string, LucideIcon> = {
  gmail: Mail,
  gmail_imap: Mail,
  gmail_api: Mail,
  outlook: Mail,
  slack: Hash,
  imessage: MessageCircle,
  whatsapp: PhoneCall,
  gdrive: FolderOpen,
  dropbox: Package,
  notion: BookText,
  obsidian: FileText,
  apple_notes: StickyNote,
  granola: FileText,
  gcalendar: CalendarDays,
  gcontacts: Contact,
  apple_contacts: Contact,
  upload: Upload,
};

const IconFor = ({ id, size = 18 }: { id: string; size?: number }) => {
  const Ico = iconMap[id] ?? Link2;
  return <Ico size={size} />;
};

// Connector glyph in a J.A.R.V.I.S. accent tile (replaces the bare icon).
const SourceIconTile = ({ id, size = 44 }: { id: string; size?: number }) => (
  <div
    className="shrink-0 grid place-items-center rounded-xl"
    style={{
      width: size,
      height: size,
      background: 'var(--color-accent-subtle)',
      border: '1px solid color-mix(in srgb, var(--color-accent) 30%, transparent)',
    }}
  >
    <IconFor id={id} size={Math.round(size * 0.42)} />
  </div>
);

// A connector card with the four animated HUD corner brackets. Unlike a raw
// hud-panel it keeps overflow visible so the brackets aren't clipped.
function HudRow({
  children,
  accent = 'var(--color-accent)',
  style,
}: {
  children: ReactNode;
  accent?: string;
  style?: CSSProperties;
}) {
  return (
    <div
      className="hud-frame relative"
      style={{
        background:
          'linear-gradient(180deg, color-mix(in srgb, var(--color-surface) 88%, transparent), var(--color-surface))',
        border: `1px solid color-mix(in srgb, ${accent} 26%, transparent)`,
        borderRadius: 'var(--radius-lg)',
        ...style,
      }}
    >
      <span className="hud-corner hud-corner--tl" aria-hidden="true" />
      <span className="hud-corner hud-corner--tr" aria-hidden="true" />
      <span className="hud-corner hud-corner--bl" aria-hidden="true" />
      <span className="hud-corner hud-corner--br" aria-hidden="true" />
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Data Sources section
// ---------------------------------------------------------------------------

// Sync status display component with progress bar
function SyncStatusDisplay({
  chunks,
  sync,
  unitLabel,
  connectorId,
  onSyncTriggered,
}: {
  chunks: number;
  sync: SyncStatus | undefined;
  unitLabel: string;
  connectorId: string;
  onSyncTriggered: () => void;
}) {
  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState('');

  const handleSync = async () => {
    setSyncing(true);
    setSyncError('');
    try {
      await triggerSync(connectorId);
      onSyncTriggered();
    } catch (err: any) {
      setSyncError(err.message || 'Sync failed');
    } finally {
      setSyncing(false);
    }
  };

  // Error state
  if (sync?.error) {
    return (
      <div>
        <div style={{ fontSize: 12, color: 'var(--color-error)', marginBottom: 4 }}>
          Error: {sync.error}
        </div>
        <button
          onClick={handleSync}
          disabled={syncing}
          style={{
            fontSize: 10, padding: '2px 10px',
            background: 'var(--color-accent-purple)', color: 'var(--color-on-accent)',
            border: 'none', borderRadius: 3,
            cursor: 'pointer', fontWeight: 600,
            opacity: syncing ? 0.5 : 1,
          }}
        >{syncing ? 'Retrying...' : 'Retry Sync'}</button>
      </div>
    );
  }

  // Done — has chunks
  if (chunks > 0) {
    return (
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 12, color: 'var(--color-success)' }}>
            {chunks.toLocaleString()} {unitLabel}
          </span>
          <button
            onClick={handleSync}
            disabled={syncing}
            style={{
              fontSize: 9, padding: '1px 6px',
              background: 'transparent',
              color: 'var(--color-text-tertiary)',
              border: '1px solid var(--color-border)',
              borderRadius: 3, cursor: 'pointer',
            }}
          >{syncing ? '...' : 'Re-sync'}</button>
        </div>
        {syncError && (
          <div style={{ fontSize: 11, color: 'var(--color-error)', marginTop: 4 }}>
            {syncError}
          </div>
        )}
      </div>
    );
  }

  // Actively syncing
  if (sync?.state === 'syncing' || syncing) {
    const pct = sync?.items_total && sync.items_total > 0
      ? Math.round((sync.items_synced / sync.items_total) * 100)
      : null;
    const label = sync?.items_total && sync.items_total > 0
      ? `${sync.items_synced.toLocaleString()} / ${sync.items_total.toLocaleString()}`
      : sync?.items_synced && sync.items_synced > 0
        ? `${sync.items_synced.toLocaleString()} items so far`
        : 'Starting...';
    return (
      <div>
        <div style={{ fontSize: 11, color: 'var(--color-warning)', marginBottom: 4 }}>
          Syncing — {label}
        </div>
        <div style={{
          height: 4, borderRadius: 2,
          background: 'var(--color-bg-tertiary)',
          overflow: 'hidden',
        }}>
          <div style={{
            height: '100%', borderRadius: 2,
            background: 'var(--color-warning)',
            width: pct != null ? `${pct}%` : '30%',
            transition: 'width 0.5s ease',
            animationName: pct == null ? 'pulse' : undefined,
            animationDuration: pct == null ? '1.5s' : undefined,
            animationIterationCount: pct == null ? 'infinite' : undefined,
          }} />
        </div>
      </div>
    );
  }

  // Idle with items synced but no chunks yet (indexing)
  if (sync?.state === 'idle' && sync.items_synced > 0) {
    return (
      <div>
        <div style={{ fontSize: 11, color: 'var(--color-warning)', marginBottom: 4 }}>
          Indexing {sync.items_synced.toLocaleString()} items...
        </div>
        <div style={{
          height: 4, borderRadius: 2,
          background: 'var(--color-bg-tertiary)',
          overflow: 'hidden',
        }}>
          <div style={{
            height: '100%', borderRadius: 2, background: 'var(--color-warning)',
            width: '60%',
            animationName: 'pulse', animationDuration: '1.5s', animationIterationCount: 'infinite',
          }} />
        </div>
      </div>
    );
  }

  // Connected but no chunks yet
  const hasSynced = sync?.last_sync != null;
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
          {hasSynced
            ? 'Synced — 0 items found'
            : 'Connected — not synced yet'}
        </span>
        <button
          onClick={handleSync}
          disabled={syncing}
          style={{
            fontSize: 10, padding: '2px 10px',
            background: 'var(--color-accent-purple)', color: 'var(--color-on-accent)',
            border: 'none', borderRadius: 3,
            cursor: 'pointer', fontWeight: 600,
            opacity: syncing ? 0.5 : 1,
          }}
        >{syncing ? 'Syncing...' : hasSynced ? 'Re-sync' : 'Sync Now'}</button>
      </div>
      {hasSynced && connectorId === 'slack' && (
        <div style={{ fontSize: 10, color: 'var(--color-text-tertiary)', marginTop: 4 }}>
          Tip: invite the bot to channels with /invite @OpenJarvis, then re-sync
        </div>
      )}
      {syncError && (
        <div style={{ fontSize: 11, color: 'var(--color-error)', marginTop: 4 }}>
          {syncError}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Re-authorize an already-connected OAuth source (kicks off the consent flow)
// ---------------------------------------------------------------------------

function OAuthReauthorize({
  connectorId,
  displayName,
  onDone,
}: {
  connectorId: string;
  displayName: string;
  onDone: () => void;
}) {
  const [waiting, setWaiting] = useState(false);

  const start = () => {
    const url = `${getBase()}/v1/connectors/${encodeURIComponent(connectorId)}/oauth/start`;
    window.open(url, '_blank', 'width=600,height=700');
    setWaiting(true);
    const startedAt = Date.now();
    const interval = setInterval(async () => {
      try {
        const info = await fetch(`${getBase()}/v1/connectors/${encodeURIComponent(connectorId)}`).then((r) => r.json());
        if (info.connected) {
          // OAuth flow signals completion by the connector flipping to connected
          // *with* fresh tokens. We can't directly observe scopes, but the next
          // sync attempt will surface a 403 again if scopes were unchecked.
          clearInterval(interval);
          setWaiting(false);
          onDone();
        }
      } catch { /* ignore polling errors */ }
      if (Date.now() - startedAt > 180_000) {
        clearInterval(interval);
        setWaiting(false);
      }
    }, 2000);
  };

  return (
    <div style={{ borderTop: '1px solid var(--color-border)', padding: 12 }}>
      <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginBottom: 10 }}>
        Re-authorize {displayName}. Google will open in a new window — be sure to
        leave every box checked (especially anything mentioning Gmail) so the new
        access token carries the right scopes.
      </div>
      {waiting ? (
        <div style={{ fontSize: 12, color: 'var(--color-accent)' }}>
          Waiting for authorization… complete it in the popup, then this card refreshes.
        </div>
      ) : (
        <button
          onClick={start}
          style={{
            fontSize: 12, padding: '6px 14px',
            background: 'var(--color-accent-purple)',
            color: 'var(--color-on-accent)',
            border: 'none', borderRadius: 4,
            cursor: 'pointer', fontWeight: 600,
          }}
        >
          Re-authorize with Google
        </button>
      )}
    </div>
  );
}


// ---------------------------------------------------------------------------
// Paste-the-Google-OAuth-client-JSON form
// ---------------------------------------------------------------------------

function GoogleOAuthClientForm() {
  const [open, setOpen] = useState(false);
  const [raw, setRaw] = useState('');
  const [status, setStatus] = useState<
    { kind: 'idle' }
    | { kind: 'saving' }
    | { kind: 'ok'; preview: string }
    | { kind: 'err'; msg: string }
  >({ kind: 'idle' });

  const submit = async () => {
    setStatus({ kind: 'saving' });
    let payload: unknown;
    try {
      payload = JSON.parse(raw);
    } catch {
      setStatus({ kind: 'err', msg: 'Not valid JSON. Paste the full contents of client_secret_*.json.' });
      return;
    }
    try {
      const res = await saveOAuthClient('google', payload);
      setStatus({ kind: 'ok', preview: res.client_id_preview });
      setRaw('');
    } catch (err: any) {
      setStatus({ kind: 'err', msg: err.message || 'Save failed' });
    }
  };

  return (
    <HudRow style={{ padding: '16px 18px' }}>
      <button
        onClick={() => setOpen((v) => !v)}
        style={{
          width: '100%',
          display: 'flex', alignItems: 'center', gap: 14,
          background: 'transparent', border: 'none', cursor: 'pointer',
          padding: 0,
        }}
      >
        <div
          className="shrink-0 grid place-items-center rounded-xl"
          style={{
            width: 44, height: 44,
            background: 'var(--color-accent-subtle)',
            border: '1px solid color-mix(in srgb, var(--color-accent) 30%, transparent)',
          }}
        >
          <Shield size={20} style={{ color: 'var(--color-accent)' }} />
        </div>
        <div style={{ textAlign: 'left', flex: 1, minWidth: 0 }}>
          <div className="font-semibold" style={{ fontSize: 14, color: 'var(--color-text)' }}>
            Google OAuth client credentials
          </div>
          <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginTop: 2 }}>
            Paste your <code>client_secret_*.json</code> here so every Google connector
            (Gmail / Drive / Calendar / Tasks / Contacts) can use it.
          </div>
        </div>
        <span
          className="shrink-0 grid place-items-center rounded-md"
          style={{
            width: 30, height: 26,
            border: '1px solid var(--color-border)',
            color: 'var(--color-text-tertiary)',
          }}
        >
          <MoreHorizontal size={14} />
        </span>
      </button>

      {open && (
        <div style={{ marginTop: 10 }}>
          <textarea
            value={raw}
            onChange={(e) => setRaw(e.target.value)}
            placeholder={'{\n  "installed": {\n    "client_id": "...apps.googleusercontent.com",\n    "client_secret": "..."\n  }\n}'}
            rows={6}
            style={{
              width: '100%',
              background: 'var(--color-bg-secondary)',
              border: '1px solid var(--color-border)',
              borderRadius: 4, color: 'var(--color-text)',
              fontSize: 11, padding: '8px 10px',
              fontFamily: 'monospace',
              boxSizing: 'border-box',
              resize: 'vertical',
            }}
          />
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
            <button
              onClick={submit}
              disabled={status.kind === 'saving' || !raw.trim()}
              style={{
                fontSize: 12, padding: '6px 16px',
                background: status.kind === 'saving' || !raw.trim()
                  ? 'var(--color-disabled-bg)'
                  : 'var(--color-accent-purple)',
                color: 'var(--color-on-accent)',
                border: 'none', borderRadius: 4, cursor: 'pointer',
                fontWeight: 600,
              }}
            >
              {status.kind === 'saving' ? 'Saving…' : 'Save'}
            </button>
            {status.kind === 'ok' && (
              <span style={{ fontSize: 11, color: 'var(--color-success)' }}>
                Saved. client_id = {status.preview}. Click Reconnect on a Google connector to use it.
              </span>
            )}
            {status.kind === 'err' && (
              <span style={{ fontSize: 11, color: 'var(--color-error)' }}>
                {status.msg}
              </span>
            )}
          </div>
        </div>
      )}
    </HudRow>
  );
}


function DataSourcesSection() {
  const cachedConnectors = useAppStore((s) => s.cachedConnectors);
  const setCachedConnectors = useAppStore((s) => s.setCachedConnectors);
  const connectors = cachedConnectors ?? [];
  const isFirstLoad = cachedConnectors === null;
  const [syncStatuses, setSyncStatuses] = useState<Record<string, SyncStatus>>({});
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const loadConnectors = useCallback(() => {
    listConnectors()
      .then((list) =>
        setCachedConnectors(
          list.map((c) => ({
            connector_id: c.connector_id,
            display_name: c.display_name,
            connected: c.connected,
            chunks: (c as any).chunks || 0,
            auth_type: c.auth_type,
            config_editable: (c as any).config_editable === true,
          })),
        ),
      )
      .catch(() => {});
  }, [setCachedConnectors]);

  const setConnectors = setCachedConnectors;

  // Poll sync status for connected sources
  const loadSyncStatuses = useCallback(async () => {
    const connected = connectors.filter((c) => c.connected);
    const statuses: Record<string, SyncStatus> = {};
    await Promise.all(
      connected.map(async (c) => {
        try {
          statuses[c.connector_id] = await getSyncStatus(c.connector_id);
        } catch { /* */ }
      }),
    );
    setSyncStatuses((prev) => ({ ...prev, ...statuses }));
  }, [connectors]);

  useEffect(() => {
    loadConnectors();
    const interval = setInterval(loadConnectors, 10000);
    return () => clearInterval(interval);
  }, [loadConnectors]);

  useEffect(() => {
    if (connectors.some((c) => c.connected)) {
      loadSyncStatuses();
      const interval = setInterval(loadSyncStatuses, 5000);
      return () => clearInterval(interval);
    }
  }, [connectors, loadSyncStatuses]);

  const [connectingId, setConnectingId] = useState<string | null>(null);
  const [connectStage, setConnectStage] = useState<string>('');
  const [connectError, setConnectError] = useState<string>('');

  const handleConnect = async (id: string, req: ConnectRequest) => {
    setLoading(true);
    setConnectingId(id);
    setConnectStage('Connecting...');
    setConnectError('');
    try {
      await connectSource(id, req);
      setConnectStage('Connected! Starting sync...');

      // Wait for connector to show as connected
      for (let i = 0; i < 20; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        const updated = await listConnectors();
        const target = updated.find((c) => c.connector_id === id);
        if (target?.connected) {
          setConnectors(updated.map((c) => ({
            connector_id: c.connector_id,
            display_name: c.display_name,
            connected: c.connected,
            chunks: (c as any).chunks || 0,
          })));
          break;
        }
        setConnectStage(i < 5 ? 'Authenticating...' : 'Waiting for connection...');
      }

      // Trigger sync
      setConnectStage('Syncing data...');
      try {
        await triggerSync(id);
      } catch { /* sync may already be running */ }

      // Close form after a brief moment
      await new Promise((r) => setTimeout(r, 1500));
      setExpandedId(null);
      loadConnectors();
      loadSyncStatuses();
    } catch (err: any) {
      let errorMsg = err.message || 'Connection failed';
      if (id === 'gmail_imap' && (errorMsg.includes('auth') || errorMsg.includes('credentials') || errorMsg.includes('LOGIN'))) {
        errorMsg = 'Invalid credentials — make sure you\'re using an App Password (16 characters), not your regular Gmail password.';
      }
      setConnectError(errorMsg);
      setConnectStage('');
    } finally {
      setLoading(false);
      setConnectingId(null);
      setConnectStage('');
    }
  };

  const connected = connectors.filter((c) => c.connected);
  const notConnectedBase = connectors.filter((c) => !c.connected);
  // Always show the upload card in the not-connected list (it has no backend connector)
  const uploadEntry = { connector_id: 'upload', display_name: 'Upload / Paste', connected: false, chunks: 0, config_editable: false };
  const notConnected = notConnectedBase.some((c) => c.connector_id === 'upload')
    ? notConnectedBase
    : [...notConnectedBase, uploadEntry];

  if (isFirstLoad) {
    return (
      <div className="flex flex-col gap-5">
        <section>
          <div className="hud-label mb-2" style={{ color: 'var(--color-text-tertiary)' }}>
            Loading sources…
          </div>
          <div className="flex flex-col gap-2">
            {[0, 1, 2, 3].map((i) => (
              <div
                key={i}
                className="hud-panel data-skeleton"
                style={{
                  padding: '14px 18px',
                  height: 60,
                  opacity: 0.6 - i * 0.08,
                }}
              />
            ))}
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <GoogleOAuthClientForm />

      {/* Connected sources */}
      {connected.length > 0 && (
        <section>
          <div className="hud-label mb-2 flex items-center gap-2">
            <span style={{ display: 'inline-block', width: 6, height: 6, borderRadius: 999, background: 'var(--color-success)' }} />
            Connected · {connected.length}
          </div>
          <div className="flex flex-col gap-2">
          {connected.map((c) => {
            const meta = SOURCE_CATALOG.find(s => s.connector_id === c.connector_id);
            const unit = meta?.unitLabel || 'items';
            const sync = syncStatuses[c.connector_id];
            const isReconnecting = expandedId === c.connector_id;
            const hasError = !!sync?.error;
            return (
              <HudRow
                key={c.connector_id}
                accent={hasError ? 'var(--color-error)' : 'var(--color-accent)'}
              >
                <div style={{
                  padding: '14px 18px',
                  display: 'flex', alignItems: 'center', gap: 14,
                }}>
                  <SourceIconTile id={c.connector_id} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="font-semibold" style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-text)' }}>
                      {c.display_name}
                    </div>
                    <SyncStatusDisplay
                      chunks={c.chunks}
                      sync={sync}
                      unitLabel={unit}
                      connectorId={c.connector_id}
                      onSyncTriggered={loadConnectors}
                    />
                  </div>
                  <button
                    onClick={() => setExpandedId(isReconnecting ? null : c.connector_id)}
                    style={{
                      padding: '7px 16px',
                      background: 'transparent',
                      color: 'var(--color-accent)',
                      border: '1px solid color-mix(in srgb, var(--color-accent) 45%, transparent)',
                      borderRadius: 6, cursor: 'pointer',
                      fontSize: 13, fontWeight: 500,
                    }}
                  >
                    {isReconnecting ? 'Cancel' : 'Reconnect'}
                  </button>
                  <ChevronRight size={18} style={{ color: 'var(--color-text-tertiary)', flexShrink: 0 }} />
                </div>
                {isReconnecting && c.auth_type === 'oauth' && !meta?.steps && (
                  <OAuthReauthorize connectorId={c.connector_id} displayName={c.display_name} onDone={() => { setExpandedId(null); loadConnectors(); loadSyncStatuses(); }} />
                )}
                {isReconnecting && meta?.steps && (
                  <div style={{ borderTop: '1px solid var(--color-border)', padding: 12 }}>
                    <div style={{ fontSize: 12, color: 'var(--color-warning)', marginBottom: 8 }}>
                      Re-enter credentials to reconnect this source.
                    </div>
                    {meta.steps.map((step, i) => (
                      <div
                        key={i}
                        style={{
                          background: 'var(--color-bg)',
                          border: '1px solid var(--color-border)',
                          borderRadius: 6, padding: 10,
                          marginBottom: 8,
                        }}
                      >
                        <div style={{ color: 'var(--color-accent-purple)', fontSize: 10, fontWeight: 600, marginBottom: 3 }}>
                          STEP {i + 1}
                        </div>
                        <div style={{ fontSize: 12, marginBottom: step.url ? 4 : 0 }}>{step.label}</div>
                        {step.url && (
                          <a
                            href={step.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{ color: 'var(--color-accent)', fontSize: 11, textDecoration: 'underline' }}
                          >
                            {step.urlLabel || 'Open'} &rarr;
                          </a>
                        )}
                      </div>
                    ))}
                    {meta.inputFields && (
                      <InlineConnectForm
                        fields={meta.inputFields}
                        loading={loading}
                        onSubmit={(req) => handleConnect(c.connector_id, req)}
                      />
                    )}
                  </div>
                )}
                {isReconnecting && c.config_editable && (
                  <ConnectorConfigEditor
                    connectorId={c.connector_id}
                    onSaved={() => {
                      loadConnectors();
                      loadSyncStatuses();
                    }}
                  />
                )}
              </HudRow>
            );
          })}
          </div>
        </section>
      )}

      {/* Not connected list */}
      {notConnected.length > 0 && (
        <section>
          <div className="hud-label mb-2 flex items-center gap-2">
            <span style={{ display: 'inline-block', width: 6, height: 6, borderRadius: 999, background: 'var(--color-text-tertiary)' }} />
            Available · {notConnected.length}
          </div>
          <div className="grid grid-cols-2 gap-2">
          {notConnected.map((c) => {
            const meta = SOURCE_CATALOG.find(s => s.connector_id === c.connector_id);
            const isExpanded = expandedId === c.connector_id;

            return (
              <HudRow
                key={c.connector_id}
                style={{
                  gridColumn: isExpanded ? '1 / -1' : undefined,
                  opacity: isExpanded ? 1 : 0.8,
                  borderStyle: isExpanded ? 'solid' : 'dashed',
                }}
              >
                <div
                  style={{
                    padding: '12px 14px', display: 'flex',
                    alignItems: 'center', gap: 12,
                    cursor: 'pointer',
                  }}
                  onClick={() => setExpandedId(isExpanded ? null : c.connector_id)}
                >
                  <SourceIconTile id={c.connector_id} size={38} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="font-semibold" style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-text)' }}>
                      {c.display_name}
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)', marginTop: 2 }}>
                      Not connected
                    </div>
                  </div>
                  <span style={{ color: 'var(--color-accent)', fontSize: 12, fontWeight: 500 }}>
                    {isExpanded ? '× Close' : '+ Add'}
                  </span>
                </div>

                {isExpanded && c.connector_id === 'upload' && (
                  <div style={{ borderTop: '1px solid var(--color-border)', padding: 12 }}>
                    <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginBottom: 10 }}>
                      Paste text or upload files (.txt, .md, .pdf, .docx, .csv) to add them to your knowledge base.
                    </div>
                    <UploadForm onDone={loadConnectors} />
                  </div>
                )}

                {isExpanded && c.connector_id !== 'upload' && meta?.steps && (
                  <div style={{ borderTop: '1px solid var(--color-border)', padding: 12 }}>
                    {meta.steps.map((step, i) => (
                      <div
                        key={i}
                        style={{
                          background: 'var(--color-bg)',
                          border: '1px solid var(--color-border)',
                          borderRadius: 6, padding: 10,
                          marginBottom: 8,
                        }}
                      >
                        <div style={{ color: 'var(--color-accent-purple)', fontSize: 10, fontWeight: 600, marginBottom: 3 }}>
                          STEP {i + 1}
                        </div>
                        <div style={{ fontSize: 12, marginBottom: step.url ? 4 : 0 }}>{step.label}</div>
                        {step.url && (
                          <a
                            href={step.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{ color: 'var(--color-accent)', fontSize: 11, textDecoration: 'underline' }}
                          >
                            {step.urlLabel || 'Open'} &rarr;
                          </a>
                        )}
                      </div>
                    ))}
                    {meta?.inputFields && (
                      <InlineConnectForm
                        fields={meta.inputFields}
                        loading={loading && connectingId === c.connector_id}
                        onSubmit={(req) => handleConnect(c.connector_id, req)}
                      />
                    )}
                    {meta?.troubleshooting && (
                      <details className="mt-2">
                        <summary className="text-[11px] cursor-pointer" style={{ color: 'var(--color-text-tertiary)' }}>
                          Having trouble?
                        </summary>
                        <ul className="mt-1 space-y-1">
                          {meta.troubleshooting.map((tip: string, i: number) => (
                            <li key={i} className="text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>
                              {tip}
                            </li>
                          ))}
                        </ul>
                      </details>
                    )}
                    {/* Connection progress */}
                    {connectingId === c.connector_id && connectStage && (
                      <div style={{ marginTop: 8 }}>
                        <div style={{
                          display: 'flex', alignItems: 'center', gap: 6,
                          fontSize: 12, color: 'var(--color-warning)',
                        }}>
                          <div className="animate-spin" style={{
                            width: 12, height: 12, borderRadius: '50%',
                            border: '2px solid var(--color-warning)',
                            borderTopColor: 'transparent',
                          }} />
                          {connectStage}
                        </div>
                        <div style={{
                          height: 3, borderRadius: 2, marginTop: 6,
                          background: 'var(--color-bg-tertiary)',
                          overflow: 'hidden',
                        }}>
                          <div style={{
                            height: '100%', borderRadius: 2, background: 'var(--color-warning)',
                            width: connectStage.includes('Sync') ? '75%' : connectStage.includes('Connected') ? '50%' : '25%',
                            transition: 'width 0.5s ease',
                          }} />
                        </div>
                      </div>
                    )}
                    {/* Connection error */}
                    {connectError && connectingId === null && expandedId === c.connector_id && (
                      <div style={{ fontSize: 11, color: 'var(--color-error)', marginTop: 6 }}>
                        {connectError}
                      </div>
                    )}
                  </div>
                )}
                {isExpanded && c.connector_id !== 'upload' && c.config_editable && (
                  <ConnectorConfigEditor
                    connectorId={c.connector_id}
                    onSaved={() => {
                      loadConnectors();
                      loadSyncStatuses();
                    }}
                  />
                )}
              </HudRow>
            );
          })}
          </div>
        </section>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Messaging channels section
// ---------------------------------------------------------------------------

interface ChannelField {
  key: string;
  label: string;
  placeholder: string;
  type?: 'text' | 'password';
  required?: boolean;
}

interface MessagingChannelConfig {
  type: string;
  name: string;
  icon: string;
  description: string;
  setupSteps: string[];
  fields: ChannelField[];
  activeLabel: (cfg: Record<string, unknown>) => string;
  howToUse: (cfg: Record<string, unknown>) => string;
}

const MESSAGING_CHANNELS: MessagingChannelConfig[] = [
  {
    type: 'slack',
    name: 'Slack',
    icon: '#',
    description: 'DM your agent in any Slack workspace',
    setupSteps: [
      '1. Go to api.slack.com/apps \u2192 click "Create New App" \u2192 choose "From an app manifest"',
      '2. Select your workspace. When asked for the manifest format, choose JSON. Then paste the manifest below (click "Copy" to copy it):',
      'COPYABLE:{"display_information":{"name":"OpenJarvis"},"features":{"app_home":{"home_tab_enabled":true,"messages_tab_enabled":true,"messages_tab_read_only_enabled":false},"bot_user":{"display_name":"OpenJarvis","always_online":true}},"oauth_config":{"scopes":{"bot":["chat:write","im:write","im:read","im:history","mpim:read","mpim:history","users:read","channels:read","channels:history","channels:join","groups:read","groups:history","app_mentions:read"]}},"settings":{"event_subscriptions":{"bot_events":["message.im"]},"socket_mode_enabled":true}}',
      '3. Click "Next" \u2192 review the summary \u2192 click "Create". Then go to "Install App" in the left sidebar \u2192 click "Install to Workspace" \u2192 click "Allow"',
      '4. In the left sidebar, click "OAuth & Permissions". Copy the "Bot User OAuth Token" (starts with xoxb-...)',
      '5. In the left sidebar, click "Basic Information" \u2192 scroll to "App-Level Tokens" \u2192 click "Generate Token and Scopes" \u2192 name it "socket" \u2192 click "Add Scope" \u2192 select "connections:write" \u2192 click "Generate" \u2192 copy the token (starts with xapp-...)',
      '6. (Optional) Still in "Basic Information", scroll to "Display Information" \u2192 upload the OpenJarvis icon as the app icon',
      '7. Paste both tokens below and click Connect',
    ],
    fields: [
      { key: 'bot_token', label: 'Bot Token', placeholder: 'xoxb-...', type: 'password', required: true },
      { key: 'app_token', label: 'App Token', placeholder: 'xapp-...', type: 'password', required: true },
    ],
    activeLabel: () => 'Connected to Slack',
    howToUse: () => 'Open Slack and DM @OpenJarvis to talk to your agent.',
  },
  {
    type: 'telegram',
    name: 'Telegram',
    icon: '✈',
    description: 'DM this agent on Telegram via a shared bot',
    setupSteps: [
      '1. Create one Telegram bot via @BotFather (use the same bot for every agent).',
      '2. Put its token in ~/.openjarvis/config.toml under [channels.telegram] bot_token = "..." and restart the server.',
      '3. Open Telegram, talk to your bot once (any message), then visit @userinfobot or @getmyid_bot to read your numeric chat ID.',
      '4. Paste that chat ID below. You can dedicate that chat to this agent, or reuse the same chat for multiple agents and target one explicitly with /agent <id> <message>.',
    ],
    fields: [
      { key: 'channel', label: 'Telegram Chat ID', placeholder: '123456789', type: 'text', required: true },
    ],
    activeLabel: (cfg) =>
      cfg.channel ? `Chat ID ${String(cfg.channel)}` : 'Telegram connected',
    howToUse: (cfg) =>
      cfg.channel
        ? `Message your bot from chat ${String(cfg.channel)}. If this chat is shared across agents, use /agent <id> <message> to route to a specific one.`
        : 'Message your bot from the bound chat. If that chat is shared across agents, use /agent <id> <message> to target one.',
  },
];

// SendBlue wizard — simplified for standalone page
function SendBlueSection({
  agentId,
  binding,
  onDone,
  onRemove,
}: {
  agentId: string;
  binding?: ChannelBinding;
  onDone: () => void;
  onRemove: (id: string) => void;
}) {
  const [step, setStep] = useState(0);
  const [apiKey, setApiKey] = useState('');
  const [apiSecret, setApiSecret] = useState('');
  const [phone, setPhone] = useState('');
  const [webhookUrl, setWebhookUrl] = useState('');
  const [webhookStatus, setWebhookStatus] = useState<'idle' | 'registering' | 'done' | 'error'>('idle');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [health, setHealth] = useState<any>(null);

  useEffect(() => {
    if (binding) {
      sendblueHealth().then(setHealth).catch(() => {});
    }
  }, [agentId, binding]);

  const registerWebhook = async () => {
    if (!webhookUrl.trim()) return;
    setWebhookStatus('registering');
    try {
      const url = webhookUrl.trim().replace(/\/+$/, '') + '/v1/channels/sendblue/webhook';
      await sendblueRegisterWebhook(apiKey.trim(), apiSecret.trim(), url);
      setWebhookStatus('done');
    } catch {
      setWebhookStatus('error');
    }
  };

  if (binding) {
    const cfg = (binding.config || {}) as Record<string, unknown>;
    return (
      <div style={{
        background: 'var(--color-bg-secondary)',
        border: '1px solid color-mix(in srgb, var(--color-success) 22%, transparent)',
        borderRadius: 8, marginBottom: 10,
        overflow: 'hidden',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', padding: '12px 14px' }}>
          <span style={{ fontSize: 18, marginRight: 10 }}>{'\uD83D\uDCF1'}</span>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 600, fontSize: 13 }}>iMessage + SMS</div>
            <div style={{ fontSize: 11, color: 'var(--color-success)' }}>
              Active &mdash; text {(cfg.phone_number as string) || 'your number'} to chat
            </div>
          </div>
          <button
            onClick={() => onRemove(binding.id)}
            style={{
              fontSize: 10, padding: '2px 8px',
              background: 'transparent',
              color: 'var(--color-text-secondary)',
              border: '1px solid var(--color-border)',
              borderRadius: 4, cursor: 'pointer',
            }}
          >Remove</button>
        </div>
        {health && (
          <div style={{
            borderTop: '1px solid var(--color-border)',
            padding: '8px 14px', fontSize: 11,
            color: 'var(--color-text-secondary)',
          }}>
            Webhook: {health.webhook_registered ? 'registered' : 'not registered'}
            {health.phone_number && ` \u2022 ${health.phone_number}`}
          </div>
        )}
      </div>
    );
  }

  const inputStyle: React.CSSProperties = {
    width: '100%', padding: '6px 10px',
    background: 'var(--color-bg)', border: '1px solid var(--color-border)',
    borderRadius: 4, color: 'var(--color-text)', fontSize: 12,
    boxSizing: 'border-box',
  };

  // Not active — setup wizard
  const steps = [
    {
      title: 'Get SendBlue API keys',
      content: (
        <div>
          <div style={{ fontSize: 12, marginBottom: 8 }}>
            SendBlue lets your agent send and receive iMessages and SMS. You need an account and API credentials.
          </div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
            <a
              href="https://sendblue.co"
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: 'var(--color-accent)', fontSize: 12, textDecoration: 'underline' }}
            >
              1. Sign up at sendblue.co &rarr;
            </a>
          </div>
          <div style={{ marginBottom: 8 }}>
            <a
              href="https://dashboard.sendblue.co/api-credentials"
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: 'var(--color-accent)', fontSize: 12, textDecoration: 'underline' }}
            >
              2. Go to your API Credentials page &rarr;
            </a>
          </div>
          <div style={{ fontSize: 11, color: 'var(--color-text-secondary)', marginBottom: 6 }}>
            Copy the "API Key" and "API Secret" from the credentials page and paste them below.
          </div>
          <input value={apiKey} onChange={(e) => setApiKey(e.target.value)}
            placeholder="API Key" style={{ ...inputStyle, marginTop: 4 }} />
          <input value={apiSecret} onChange={(e) => setApiSecret(e.target.value)}
            placeholder="API Secret" type="password" style={{ ...inputStyle, marginTop: 4 }} />
        </div>
      ),
      canAdvance: apiKey.trim() && apiSecret.trim(),
    },
    {
      title: 'Enter your phone number',
      content: (
        <div>
          <div style={{ fontSize: 12, marginBottom: 8 }}>
            Which phone number should SendBlue use? This is the number people will text to reach your agent.
          </div>
          <input value={phone} onChange={(e) => setPhone(e.target.value)}
            placeholder="+1XXXXXXXXXX" style={inputStyle} />
        </div>
      ),
      canAdvance: phone.trim().length >= 10,
    },
    {
      title: 'Set up webhook (ngrok tunnel)',
      content: (
        <div>
          <div style={{ fontSize: 12, marginBottom: 8 }}>
            SendBlue needs a public URL to send incoming messages to your local server. Use ngrok to create a tunnel.
          </div>
          <div style={{
            fontSize: 11, lineHeight: 1.6,
            color: 'var(--color-text-secondary)',
            padding: '8px 10px', marginBottom: 10,
            background: 'var(--color-bg-secondary)',
            borderRadius: 6,
            borderLeft: '3px solid var(--color-accent, var(--color-accent-purple))',
          }}>
            <div><strong>1.</strong> Open a terminal and run: <code style={{ color: 'var(--color-accent)', background: 'var(--color-bg)', padding: '1px 4px', borderRadius: 3 }}>ngrok http 8000</code></div>
            <div style={{ marginTop: 4 }}><strong>2.</strong> Copy the <code style={{ color: 'var(--color-accent)', background: 'var(--color-bg)', padding: '1px 4px', borderRadius: 3 }}>https://</code> forwarding URL (e.g. https://abc123.ngrok.io)</div>
            <div style={{ marginTop: 4 }}><strong>3.</strong> Paste it below and click "Register Webhook"</div>
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <input
              value={webhookUrl}
              onChange={(e) => { setWebhookUrl(e.target.value); setWebhookStatus('idle'); }}
              placeholder="https://abc123.ngrok-free.app"
              style={{ ...inputStyle, flex: 1 }}
            />
            <button
              onClick={registerWebhook}
              disabled={!webhookUrl.trim() || webhookStatus === 'registering'}
              style={{
                fontSize: 11, padding: '6px 12px', whiteSpace: 'nowrap',
                background: webhookStatus === 'done' ? 'var(--color-success)' : 'var(--color-accent-purple)',
                color: 'var(--color-on-accent)', border: 'none', borderRadius: 4,
                cursor: 'pointer', fontWeight: 600,
                opacity: !webhookUrl.trim() || webhookStatus === 'registering' ? 0.5 : 1,
              }}
            >
              {webhookStatus === 'registering' ? 'Registering...'
                : webhookStatus === 'done' ? 'Registered!'
                : webhookStatus === 'error' ? 'Retry'
                : 'Register Webhook'}
            </button>
          </div>
          {webhookStatus === 'done' && (
            <div style={{ fontSize: 11, color: 'var(--color-success)', marginTop: 6 }}>
              Webhook registered! Incoming texts will be forwarded to your agent.
            </div>
          )}
          {webhookStatus === 'error' && (
            <div style={{ fontSize: 11, color: 'var(--color-error)', marginTop: 6 }}>
              Failed to register webhook. Check your ngrok URL and SendBlue credentials.
            </div>
          )}
          <div style={{ fontSize: 10, color: 'var(--color-text-tertiary)', marginTop: 8 }}>
            Don't have ngrok? <a href="https://ngrok.com/download" target="_blank" rel="noopener noreferrer" style={{ color: 'var(--color-accent)', textDecoration: 'underline' }}>Download it free</a>. You can also skip this step and register the webhook later.
          </div>
        </div>
      ),
      canAdvance: true, // webhook is optional — user can skip
    },
  ];

  const handleFinish = async () => {
    setLoading(true);
    setError('');
    try {
      await bindAgentChannel(agentId, 'sendblue', {
        api_key: apiKey.trim(),
        api_secret: apiSecret.trim(),
        phone_number: phone.trim(),
      });
      // If webhook was registered in the wizard, that's already done.
      // If not, try a best-effort registration with the provided URL.
      if (webhookUrl.trim() && webhookStatus !== 'done') {
        try {
          const url = webhookUrl.trim().replace(/\/+$/, '') + '/v1/channels/sendblue/webhook';
          await sendblueRegisterWebhook(apiKey.trim(), apiSecret.trim(), url);
        } catch { /* */ }
      }
      onDone();
      setStep(0);
      setApiKey('');
      setApiSecret('');
      setPhone('');
      setWebhookUrl('');
      setWebhookStatus('idle');
    } catch (err: any) {
      setError(err.message || 'Failed to connect');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      background: 'var(--color-bg-secondary)',
      border: '1px dashed var(--color-border)',
      borderRadius: 8, marginBottom: 10,
      overflow: 'hidden',
    }}>
      <div
        style={{
          display: 'flex', alignItems: 'center',
          padding: '12px 14px', cursor: 'pointer',
        }}
        onClick={() => setStep(step === 0 && !apiKey ? -1 : 0)}
      >
        <span style={{ fontSize: 18, marginRight: 10 }}>{'\uD83D\uDCF1'}</span>
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 600, fontSize: 13 }}>iMessage + SMS (SendBlue)</div>
          <div style={{ fontSize: 11, color: 'var(--color-text-secondary)' }}>
            Let people text your agent from any phone
          </div>
        </div>
        <span style={{ color: 'var(--color-accent-purple)', fontSize: 11, fontWeight: 500 }}>
          {step >= 0 ? 'Set Up' : '+ Add'}
        </span>
      </div>

      {step >= 0 && (
        <div style={{ borderTop: '1px solid var(--color-border)', padding: 14 }}>
          {/* Step indicator */}
          <div style={{ display: 'flex', gap: 4, marginBottom: 12 }}>
            {steps.map((_, i) => (
              <div
                key={i}
                style={{
                  flex: 1, height: 3, borderRadius: 2,
                  background: i <= step ? 'var(--color-accent-purple)' : 'var(--color-border)',
                }}
              />
            ))}
          </div>

          <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 8 }}>
            {steps[step]?.title}
          </div>
          {steps[step]?.content}

          {error && (
            <div style={{ fontSize: 11, color: 'var(--color-error)', marginTop: 6 }}>{error}</div>
          )}

          <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
            {step > 0 && (
              <button
                onClick={() => setStep(step - 1)}
                style={{
                  fontSize: 12, padding: '6px 16px',
                  background: 'var(--color-bg)',
                  color: 'var(--color-text-secondary)',
                  border: '1px solid var(--color-border)',
                  borderRadius: 5, cursor: 'pointer',
                }}
              >Back</button>
            )}
            {step < steps.length - 1 ? (
              <button
                onClick={() => setStep(step + 1)}
                disabled={!steps[step]?.canAdvance}
                style={{
                  fontSize: 12, padding: '6px 16px',
                  background: 'var(--color-accent-purple)', color: 'var(--color-on-accent)',
                  border: 'none', borderRadius: 5,
                  cursor: 'pointer', fontWeight: 600,
                  opacity: steps[step]?.canAdvance ? 1 : 0.5,
                }}
              >Next</button>
            ) : (
              <button
                onClick={handleFinish}
                disabled={loading || !steps[step]?.canAdvance}
                style={{
                  fontSize: 12, padding: '6px 16px',
                  background: 'var(--color-accent-purple)', color: 'var(--color-on-accent)',
                  border: 'none', borderRadius: 5,
                  cursor: 'pointer', fontWeight: 600,
                  opacity: loading || !steps[step]?.canAdvance ? 0.5 : 1,
                }}
              >{loading ? 'Connecting...' : 'Connect'}</button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Global Telegram bot config (shared by every agent's chat-ID binding)
// ---------------------------------------------------------------------------

function TelegramBotConfigForm() {
  const [hasToken, setHasToken] = useState(false);
  const [tokenPreview, setTokenPreview] = useState('');
  const [botToken, setBotToken] = useState('');
  const [showBotToken, setShowBotToken] = useState(false);
  const [allowedChatIds, setAllowedChatIds] = useState('');
  const [health, setHealth] = useState<
    { kind: 'idle' }
    | { kind: 'checking' }
    | { kind: 'ok'; msg: string; botUsername?: string }
    | { kind: 'err'; msg: string; detail?: string }
  >({ kind: 'idle' });
  const [status, setStatus] = useState<
    { kind: 'idle' }
    | { kind: 'saving' }
    | { kind: 'ok'; restart: boolean }
    | { kind: 'err'; msg: string }
  >({ kind: 'idle' });

  const checkHealth = useCallback(async () => {
    setHealth({ kind: 'checking' });
    try {
      const result = await fetchTelegramHealth();
      if (result.status === 'ok') {
        setHealth({
          kind: 'ok',
          msg: result.message,
          botUsername: result.bot_username || undefined,
        });
        return;
      }
      if (result.status === 'not_configured') {
        setHealth({ kind: 'idle' });
        return;
      }
      setHealth({
        kind: 'err',
        msg: result.message,
        detail: result.detail,
      });
    } catch (err: any) {
      setHealth({
        kind: 'err',
        msg: err?.message || 'Failed to check Telegram connectivity.',
      });
    }
  }, []);

  useEffect(() => {
    fetchTelegramConfig()
      .then((cfg) => {
        setHasToken(cfg.has_token);
        setTokenPreview(cfg.token_preview);
        setBotToken(cfg.bot_token || '');
        setAllowedChatIds(cfg.allowed_chat_ids || '');
        if (cfg.has_token) {
          checkHealth().catch(() => {});
        } else {
          setHealth({ kind: 'idle' });
        }
      })
      .catch(() => {});
  }, [checkHealth]);

  const submit = async () => {
    const token = botToken.trim();
    if (!token) {
      setStatus({ kind: 'err', msg: 'Bot token is required.' });
      return;
    }
    setStatus({ kind: 'saving' });
    try {
      const res = await saveTelegramConfig(token, allowedChatIds.trim());
      setHasToken(true);
      setTokenPreview(res.token_preview);
      setBotToken(res.bot_token || token);
      setStatus({ kind: 'ok', restart: res.restart_required });
      await checkHealth();
    } catch (err: any) {
      setStatus({ kind: 'err', msg: err.message || 'Save failed' });
    }
  };

  return (
    <section
      style={{
        background: 'var(--color-bg-secondary)',
        border: hasToken
          ? '1px solid color-mix(in srgb, var(--color-success) 22%, transparent)'
          : '1px dashed var(--color-border)',
        borderRadius: 8,
        padding: '14px 16px',
        marginBottom: 12,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
        <span style={{ fontSize: 18 }}>✈</span>
        <div style={{ flex: 1, fontWeight: 600, fontSize: 13, color: 'var(--color-text)' }}>
          Telegram bot
        </div>
        {hasToken && (
          <span
            style={{
              fontSize: 10, padding: '2px 8px',
              borderRadius: 999,
              background: 'color-mix(in srgb, var(--color-success) 18%, transparent)',
              color: 'var(--color-success)',
            }}
          >
            Saved · {tokenPreview}
          </span>
        )}
      </div>
      <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)', marginBottom: 10 }}>
        One bot, many agents. Set the token once here; per-agent chat IDs go in the cards below.
        Get a token from <code>@BotFather</code> on Telegram.
      </div>

      {health.kind === 'err' && (
        <div
          style={{
            display: 'flex',
            gap: 10,
            alignItems: 'flex-start',
            padding: '10px 12px',
            borderRadius: 6,
            marginBottom: 10,
            background: 'color-mix(in srgb, var(--color-warning) 12%, var(--color-bg))',
            border: '1px solid color-mix(in srgb, var(--color-warning) 26%, transparent)',
            color: 'var(--color-text)',
          }}
        >
          <AlertTriangle size={15} style={{ color: 'var(--color-warning)', flexShrink: 0, marginTop: 1 }} />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 2, color: 'var(--color-warning)' }}>
              Telegram connection issue
            </div>
            <div style={{ fontSize: 11, lineHeight: 1.5 }}>
              {health.msg}
            </div>
            {health.detail && (
              <div style={{ fontSize: 10, marginTop: 4, color: 'var(--color-text-tertiary)', wordBreak: 'break-word' }}>
                {health.detail}
              </div>
            )}
          </div>
        </div>
      )}

      {health.kind === 'ok' && (
        <div
          style={{
            display: 'flex',
            gap: 10,
            alignItems: 'flex-start',
            padding: '10px 12px',
            borderRadius: 6,
            marginBottom: 10,
            background: 'color-mix(in srgb, var(--color-success) 10%, var(--color-bg))',
            border: '1px solid color-mix(in srgb, var(--color-success) 22%, transparent)',
            color: 'var(--color-text)',
          }}
        >
          <CheckCircle2 size={15} style={{ color: 'var(--color-success)', flexShrink: 0, marginTop: 1 }} />
          <div style={{ fontSize: 11, lineHeight: 1.5 }}>
            {health.msg}
            {health.botUsername ? ` Connected as @${health.botUsername}.` : ''}
          </div>
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 3 }}>
        <label style={{ display: 'block', fontSize: 11, color: 'var(--color-text-secondary)', fontWeight: 500 }}>
          Bot Token {hasToken ? '' : '*'}
        </label>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {hasToken && (
            <button
              type="button"
              onClick={() => checkHealth().catch(() => {})}
              disabled={health.kind === 'checking'}
              style={{
                border: 'none',
                background: 'transparent',
                color: 'var(--color-accent)',
                fontSize: 11,
                fontWeight: 600,
                cursor: health.kind === 'checking' ? 'default' : 'pointer',
                padding: 0,
                display: 'flex',
                alignItems: 'center',
                gap: 4,
                opacity: health.kind === 'checking' ? 0.7 : 1,
              }}
            >
              <RefreshCw size={11} className={health.kind === 'checking' ? 'animate-spin' : ''} />
              {health.kind === 'checking' ? 'Checking…' : 'Check connection'}
            </button>
          )}
          <button
            type="button"
            onClick={() => setShowBotToken((value) => !value)}
            style={{
              border: 'none',
              background: 'transparent',
              color: 'var(--color-accent)',
              fontSize: 11,
              fontWeight: 600,
              cursor: 'pointer',
              padding: 0,
            }}
          >
            {showBotToken ? 'Hide' : 'Show'}
          </button>
        </div>
      </div>
      <input
        type={showBotToken ? 'text' : 'password'}
        value={botToken}
        onChange={(e) => setBotToken(e.target.value)}
        placeholder={hasToken ? 'Paste a new token to replace the current one' : '1234567890:AA…'}
        style={{
          width: '100%', padding: '7px 10px',
          background: 'var(--color-bg)',
          border: '1px solid var(--color-border)',
          borderRadius: 4, color: 'var(--color-text)',
          fontSize: 12, marginBottom: 10, boxSizing: 'border-box',
        }}
      />

      <label style={{ display: 'block', fontSize: 11, color: 'var(--color-text-secondary)', marginBottom: 3, fontWeight: 500 }}>
        Allowed Chat IDs (optional)
      </label>
      <input
        type="text"
        value={allowedChatIds}
        onChange={(e) => setAllowedChatIds(e.target.value)}
        placeholder="Comma-separated chat IDs. Leave empty to allow all."
        style={{
          width: '100%', padding: '7px 10px',
          background: 'var(--color-bg)',
          border: '1px solid var(--color-border)',
          borderRadius: 4, color: 'var(--color-text)',
          fontSize: 12, marginBottom: 10, boxSizing: 'border-box',
        }}
      />

      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <button
          onClick={submit}
          disabled={status.kind === 'saving'}
          style={{
            fontSize: 12, padding: '7px 18px',
            background: status.kind === 'saving' ? 'var(--color-disabled-bg)' : 'var(--color-accent-purple)',
            color: 'var(--color-on-accent)', border: 'none',
            borderRadius: 4, cursor: 'pointer', fontWeight: 600,
          }}
        >
          {status.kind === 'saving' ? 'Saving…' : hasToken ? 'Update' : 'Save'}
        </button>
        {status.kind === 'ok' && (
          <span style={{ fontSize: 11, color: 'var(--color-success)' }}>
            Saved.{status.restart ? ' Restart the backend to activate the bot.' : ''}
          </span>
        )}
        {status.kind === 'err' && (
          <span style={{ fontSize: 11, color: 'var(--color-error)' }}>
            {status.msg}
          </span>
        )}
      </div>
    </section>
  );
}


function MessagingSection({ agentId }: { agentId: string }) {
  const [bindings, setBindings] = useState<ChannelBinding[]>([]);
  const [setupType, setSetupType] = useState<string | null>(null);
  const [formValues, setFormValues] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);

  const loadBindings = useCallback(() => {
    fetchAgentChannels(agentId).then(setBindings).catch(() => setBindings([]));
  }, [agentId]);

  useEffect(() => { loadBindings(); }, [loadBindings]);

  const setField = (key: string, value: string) =>
    setFormValues((prev) => ({ ...prev, [key]: value }));

  const handleSetup = async (ch: MessagingChannelConfig) => {
    const missing = ch.fields.filter((f) => f.required && !formValues[f.key]?.trim());
    if (missing.length > 0) return;
    setLoading(true);
    try {
      const config: Record<string, string> = {};
      for (const f of ch.fields) {
        const v = formValues[f.key]?.trim();
        if (v) config[f.key] = v;
      }
      await bindAgentChannel(agentId, ch.type, config);
      setSetupType(null);
      setFormValues({});
      loadBindings();
    } catch { /* */ } finally { setLoading(false); }
  };

  const handleRemove = async (bindingId: string) => {
    try {
      await unbindAgentChannel(agentId, bindingId);
      loadBindings();
    } catch { /* */ }
  };

  const inputStyle: React.CSSProperties = {
    width: '100%', padding: '6px 10px',
    background: 'var(--color-bg-secondary)',
    border: '1px solid var(--color-border)',
    borderRadius: 4, color: 'var(--color-text)',
    fontSize: 12, boxSizing: 'border-box',
  };

  return (
    <div>
      {/* Global Telegram bot config (shared by all agents) */}
      <TelegramBotConfigForm />

      {/* SendBlue */}
      <SendBlueSection
        agentId={agentId}
        binding={bindings.find((b) => b.channel_type === 'sendblue')}
        onDone={loadBindings}
        onRemove={(id) => { unbindAgentChannel(agentId, id).then(loadBindings).catch(() => {}); }}
      />

      {/* Other messaging channels */}
      {MESSAGING_CHANNELS.map((ch) => {
        const binding = bindings.find((b) => b.channel_type === ch.type);
        const cfg = (binding?.config || {}) as Record<string, unknown>;
        const isSetup = setupType === ch.type;
        const canConnect = ch.fields.every((f) => !f.required || formValues[f.key]?.trim());

        return (
          <div
            key={ch.type}
            style={{
              background: 'var(--color-bg-secondary)',
              border: binding ? '1px solid color-mix(in srgb, var(--color-success) 22%, transparent)' : '1px dashed var(--color-border)',
              borderRadius: 8, marginBottom: 10, overflow: 'hidden',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', padding: '12px 14px' }}>
              <span style={{ fontSize: 18, marginRight: 10 }}>{ch.icon}</span>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600, fontSize: 13 }}>{ch.name}</div>
                <div style={{
                  fontSize: 11,
                  color: binding ? 'var(--color-success)' : 'var(--color-text-secondary)',
                }}>
                  {binding ? ch.activeLabel(cfg) : ch.description}
                </div>
              </div>
              {binding ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{
                    background: 'color-mix(in srgb, var(--color-success) 22%, transparent)', color: 'var(--color-success)',
                    padding: '2px 8px', borderRadius: 10,
                    fontSize: 10, fontWeight: 600,
                  }}>Active</span>
                  <button
                    onClick={() => handleRemove(binding.id)}
                    style={{
                      fontSize: 10, padding: '2px 8px', background: 'transparent',
                      color: 'var(--color-text-secondary)',
                      border: '1px solid var(--color-border)',
                      borderRadius: 4, cursor: 'pointer',
                    }}
                  >Remove</button>
                </div>
              ) : (
                <button
                  onClick={() => { setSetupType(isSetup ? null : ch.type); setFormValues({}); }}
                  style={{
                    fontSize: 10, padding: '3px 12px', background: 'var(--color-accent-purple)',
                    color: 'var(--color-on-accent)', border: 'none', borderRadius: 5,
                    cursor: 'pointer', fontWeight: 600,
                  }}
                >{isSetup ? 'Cancel' : 'Set Up'}</button>
              )}
            </div>

            {binding && (
              <div style={{
                borderTop: '1px solid var(--color-border)',
                padding: '10px 14px', background: 'var(--color-bg)',
              }}>
                <div style={{ fontSize: 11, color: 'var(--color-text-secondary)', display: 'flex', alignItems: 'flex-start', gap: 6 }}>
                  <span style={{ flexShrink: 0 }}>{'\u2192'}</span>
                  <span>{ch.howToUse(cfg)}</span>
                </div>
              </div>
            )}

            {isSetup && (
              <div style={{
                borderTop: '1px solid var(--color-border)',
                padding: 14, background: 'var(--color-bg)',
              }}>
                <div style={{
                  fontSize: 11, lineHeight: 1.5,
                  color: 'var(--color-text-secondary)',
                  marginBottom: 12, padding: '8px 10px',
                  background: 'var(--color-bg-secondary)',
                  borderRadius: 6,
                  borderLeft: '3px solid var(--color-accent, var(--color-accent-purple))',
                }}>
                  {ch.setupSteps.map((s, i) => {
                    if (s.startsWith('COPYABLE:')) {
                      const text = s.slice(9);
                      return (
                        <div key={i} style={{ marginBottom: 6, marginTop: 4 }}>
                          <div style={{
                            position: 'relative',
                            background: 'var(--color-bg)',
                            border: '1px solid var(--color-border)',
                            borderRadius: 4, padding: '8px 10px',
                            fontSize: 10, fontFamily: 'monospace',
                            wordBreak: 'break-all', lineHeight: 1.4,
                            maxHeight: 80, overflowY: 'auto',
                          }}>
                            {text}
                            <button
                              onClick={() => { navigator.clipboard.writeText(text); }}
                              style={{
                                position: 'sticky', float: 'right', top: 0,
                                fontSize: 10, padding: '2px 8px',
                                background: 'var(--color-accent-purple)', color: 'var(--color-on-accent)',
                                border: 'none', borderRadius: 3,
                                cursor: 'pointer', fontWeight: 600,
                              }}
                            >Copy</button>
                          </div>
                        </div>
                      );
                    }
                    return (
                      <div key={i} style={{ marginBottom: i < ch.setupSteps.length - 1 ? 4 : 0 }}>{s}</div>
                    );
                  })}
                </div>
                {ch.fields.map((field) => (
                  <div key={field.key} style={{ marginBottom: 8 }}>
                    <label style={{
                      display: 'block', fontSize: 11,
                      color: 'var(--color-text-secondary)',
                      marginBottom: 3, fontWeight: 500,
                    }}>
                      {field.label}{field.required ? ' *' : ''}
                    </label>
                    <input
                      type={field.type || 'text'}
                      value={formValues[field.key] || ''}
                      onChange={(e) => setField(field.key, e.target.value)}
                      placeholder={field.placeholder}
                      style={inputStyle}
                    />
                  </div>
                ))}
                <button
                  onClick={() => handleSetup(ch)}
                  disabled={loading || !canConnect}
                  style={{
                    fontSize: 12, padding: '7px 20px', background: 'var(--color-accent-purple)',
                    color: 'var(--color-on-accent)', border: 'none', borderRadius: 5,
                    cursor: 'pointer', fontWeight: 600,
                    opacity: loading || !canConnect ? 0.5 : 1, marginTop: 4,
                  }}
                >{loading ? 'Connecting...' : 'Connect'}</button>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Memory section
// ---------------------------------------------------------------------------

function MemorySection() {
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [statsError, setStatsError] = useState('');

  // Search
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<MemorySearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchDone, setSearchDone] = useState(false);

  // Index
  const [indexPath, setIndexPath] = useState('');
  const [indexing, setIndexing] = useState(false);
  const [indexResult, setIndexResult] = useState('');
  const [indexError, setIndexError] = useState('');

  // Store
  const [storeContent, setStoreContent] = useState('');
  const [storing, setStoring] = useState(false);
  const [storeResult, setStoreResult] = useState('');
  const [storeError, setStoreError] = useState('');

  const statsInterval = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadStats = useCallback(() => {
    getMemoryStats()
      .then((s) => { setStats(s); setStatsError(''); })
      .catch(() => setStatsError('Could not reach memory backend'));
  }, []);

  useEffect(() => {
    loadStats();
    statsInterval.current = setInterval(loadStats, 10000);
    return () => { if (statsInterval.current) clearInterval(statsInterval.current); };
  }, [loadStats]);

  const handleSearch = async () => {
    if (!searchQuery.trim()) return;
    setSearching(true);
    setSearchDone(false);
    try {
      const results = await searchMemory(searchQuery.trim());
      setSearchResults(results || []);
      setSearchDone(true);
    } catch {
      setSearchResults([]);
      setSearchDone(true);
    } finally {
      setSearching(false);
    }
  };

  const handleBrowse = async () => {
    if (isTauri()) {
      try {
        const { open } = await import('@tauri-apps/plugin-dialog');
        const selected = await open({ directory: true, multiple: false, title: 'Select folder to index' });
        if (selected) setIndexPath(selected as string);
        return;
      } catch {
        // fall through to browser picker
      }
    }
    const input = document.createElement('input');
    input.type = 'file';
    input.setAttribute('webkitdirectory', '');
    input.onchange = () => {
      const files = input.files;
      if (files && files.length > 0) {
        const rel = (files[0] as any).webkitRelativePath || '';
        const folder = rel.split('/')[0];
        if (folder) setIndexPath(folder);
      }
    };
    input.click();
  };

  const handleIndex = async () => {
    if (!indexPath.trim()) return;
    setIndexing(true);
    setIndexResult('');
    setIndexError('');
    try {
      const res = await indexMemoryPath(indexPath.trim());
      setIndexResult(`Indexed ${res.chunks_indexed} chunk${res.chunks_indexed !== 1 ? 's' : ''}`);
      setIndexPath('');
      loadStats();
    } catch (err: any) {
      setIndexError(err.message || 'Indexing failed');
    } finally {
      setIndexing(false);
    }
  };

  const handleStore = async () => {
    if (!storeContent.trim()) return;
    setStoring(true);
    setStoreResult('');
    setStoreError('');
    try {
      await storeMemory(storeContent.trim());
      setStoreResult('Stored successfully');
      setStoreContent('');
      loadStats();
    } catch (err: any) {
      setStoreError(err.message || 'Failed to store');
    } finally {
      setStoring(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Stats overview */}
      <div
        className="rounded-xl p-5 relative overflow-hidden"
        style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
      >
        {/* Subtle gradient accent along top edge */}
        <div className="absolute top-0 left-0 right-0 h-[2px]" style={{
          background: 'linear-gradient(90deg, var(--color-accent-purple), var(--color-accent), transparent)',
        }} />
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg flex items-center justify-center" style={{
              background: 'var(--color-accent-purple-subtle)',
            }}>
              <Brain size={18} style={{ color: 'var(--color-accent-purple)' }} />
            </div>
            <div>
              <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>Memory Backend</h3>
              {statsError ? (
                <p className="text-xs mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>{statsError}</p>
              ) : stats ? (
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="w-1.5 h-1.5 rounded-full" style={{
                    background: stats.entries > 0 ? 'var(--color-success)' : 'var(--color-text-tertiary)',
                  }} />
                  <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                    {stats.backend} &middot; {stats.entries.toLocaleString()} {stats.entries === 1 ? 'chunk' : 'chunks'}
                  </span>
                </div>
              ) : (
                <p className="text-xs mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>Connecting...</p>
              )}
            </div>
          </div>
          {stats && stats.entries > 0 && (
            <div className="text-right">
              <div className="text-lg font-bold tabular-nums" style={{ color: 'var(--color-text)' }}>
                {stats.entries.toLocaleString()}
              </div>
              <div className="text-[10px] uppercase tracking-wider" style={{ color: 'var(--color-text-tertiary)' }}>
                indexed
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Search */}
      <div
        className="rounded-xl p-5"
        style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
      >
        <div className="flex items-center gap-2 mb-3">
          <Search size={14} style={{ color: 'var(--color-accent-purple)' }} />
          <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>Search Memory</h3>
        </div>
        <div className="flex gap-2">
          <div className="flex-1 relative">
            <input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleSearch(); }}
              placeholder="What are you looking for?"
              className="w-full text-sm px-3 py-2 rounded-lg outline-none transition-colors"
              style={{
                background: 'var(--color-bg)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text)',
              }}
            />
          </div>
          <button
            onClick={handleSearch}
            disabled={searching || !searchQuery.trim()}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium transition-all cursor-pointer whitespace-nowrap"
            style={{
              background: searching || !searchQuery.trim() ? 'var(--color-bg-tertiary)' : 'var(--color-accent-purple)',
              color: searching || !searchQuery.trim() ? 'var(--color-text-tertiary)' : 'var(--color-on-accent)',
              opacity: searching || !searchQuery.trim() ? 0.6 : 1,
            }}
          >
            {searching ? <Loader2 size={13} className="animate-spin" /> : <Search size={13} />}
            {searching ? 'Searching' : 'Search'}
          </button>
        </div>

        {/* Results */}
        {searchDone && searchResults.length === 0 && (
          <div className="flex flex-col items-center py-6 gap-2">
            <Search size={20} style={{ color: 'var(--color-text-tertiary)', opacity: 0.4 }} />
            <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>No matching memories found</p>
          </div>
        )}
        {searchResults.length > 0 && (
          <div className="mt-3 space-y-2">
            {searchResults.map((r, i) => (
              <div
                key={i}
                className="rounded-lg p-3 transition-colors"
                style={{
                  background: 'var(--color-bg)',
                  border: '1px solid var(--color-border)',
                }}
              >
                <p className="text-xs leading-relaxed" style={{ color: 'var(--color-text)' }}>
                  {r.content.length > 250 ? r.content.slice(0, 250) + '...' : r.content}
                </p>
                <div className="flex items-center gap-3 mt-2">
                  <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium" style={{
                    background: r.score > 0.5
                      ? 'rgba(74, 222, 128, 0.1)'
                      : r.score > 0.2
                        ? 'var(--color-accent-amber-subtle)'
                        : 'var(--color-bg-tertiary)',
                    color: r.score > 0.5
                      ? 'var(--color-success)'
                      : r.score > 0.2
                        ? 'var(--color-warning)'
                        : 'var(--color-text-tertiary)',
                  }}>
                    {(r.score * 100).toFixed(0)}% match
                  </span>
                  {r.metadata?.source != null && (
                    <span className="text-[10px]" style={{ color: 'var(--color-text-tertiary)' }}>
                      {String(r.metadata.source)}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Add to Memory — two-column grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Index folder */}
        <div
          className="rounded-xl p-5"
          style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
        >
          <div className="flex items-center gap-2 mb-3">
            <FolderOpen size={14} style={{ color: 'var(--color-accent-purple)' }} />
            <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>Index Folder</h3>
          </div>
          <p className="text-xs mb-3" style={{ color: 'var(--color-text-tertiary)' }}>
            Scan a folder and index all supported files into memory.
          </p>
          <div className="flex gap-2 mb-2">
            <input
              value={indexPath}
              onChange={(e) => setIndexPath(e.target.value)}
              placeholder="~/Documents/notes"
              className="flex-1 text-sm px-3 py-2 rounded-lg outline-none"
              style={{
                background: 'var(--color-bg)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text)',
              }}
            />
            {isTauri() && (
              <button
                onClick={handleBrowse}
                className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium cursor-pointer transition-colors whitespace-nowrap"
                style={{
                  background: 'var(--color-bg)',
                  border: '1px solid var(--color-border)',
                  color: 'var(--color-text-secondary)',
                }}
              >
                <FolderOpen size={12} />
                Browse
              </button>
            )}
          </div>
          <button
            onClick={handleIndex}
            disabled={indexing || !indexPath.trim()}
            className="w-full flex items-center justify-center gap-1.5 py-2 rounded-lg text-sm font-medium cursor-pointer transition-all"
            style={{
              background: indexing || !indexPath.trim() ? 'var(--color-bg-tertiary)' : 'var(--color-accent-purple)',
              color: indexing || !indexPath.trim() ? 'var(--color-text-tertiary)' : 'var(--color-on-accent)',
              opacity: indexing || !indexPath.trim() ? 0.6 : 1,
            }}
          >
            {indexing && <Loader2 size={13} className="animate-spin" />}
            {indexing ? 'Indexing files...' : 'Index'}
          </button>
          {indexResult && (
            <p className="text-xs mt-2 font-medium" style={{ color: 'var(--color-success)' }}>{indexResult}</p>
          )}
          {indexError && (
            <p className="text-xs mt-2 font-medium" style={{ color: 'var(--color-error)' }}>{indexError}</p>
          )}
        </div>

        {/* Paste content */}
        <div
          className="rounded-xl p-5"
          style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
        >
          <div className="flex items-center gap-2 mb-3">
            <FileText size={14} style={{ color: 'var(--color-accent-purple)' }} />
            <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>Store Text</h3>
          </div>
          <p className="text-xs mb-3" style={{ color: 'var(--color-text-tertiary)' }}>
            Paste any text to add directly to your memory store.
          </p>
          <textarea
            value={storeContent}
            onChange={(e) => setStoreContent(e.target.value)}
            placeholder="Paste or type content here..."
            rows={4}
            className="w-full text-sm px-3 py-2 rounded-lg outline-none resize-y"
            style={{
              background: 'var(--color-bg)',
              border: '1px solid var(--color-border)',
              color: 'var(--color-text)',
              fontFamily: 'inherit',
              minHeight: 80,
              marginBottom: 8,
            }}
          />
          <button
            onClick={handleStore}
            disabled={storing || !storeContent.trim()}
            className="w-full flex items-center justify-center gap-1.5 py-2 rounded-lg text-sm font-medium cursor-pointer transition-all"
            style={{
              background: storing || !storeContent.trim() ? 'var(--color-bg-tertiary)' : 'var(--color-accent-purple)',
              color: storing || !storeContent.trim() ? 'var(--color-text-tertiary)' : 'var(--color-on-accent)',
              opacity: storing || !storeContent.trim() ? 0.6 : 1,
            }}
          >
            {storing && <Loader2 size={13} className="animate-spin" />}
            {storing ? 'Storing...' : 'Store'}
          </button>
          {storeResult && (
            <p className="text-xs mt-2 font-medium" style={{ color: 'var(--color-success)' }}>{storeResult}</p>
          )}
          {storeError && (
            <p className="text-xs mt-2 font-medium" style={{ color: 'var(--color-error)' }}>{storeError}</p>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function DataSourcesPage() {
  const [agents, setAgents] = useState<ManagedAgent[]>([]);
  const [activeTab, setActiveTab] = useState<'sources' | 'messaging' | 'memory'>('sources');
  const [creatingAgent, setCreatingAgent] = useState(false);

  const loadAgents = useCallback(() => {
    fetchManagedAgents().then(setAgents).catch(() => {});
  }, []);

  useEffect(() => { loadAgents(); }, [loadAgents]);

  // Pick the first agent for messaging channel bindings.
  // If none exists and user opens Messaging tab, auto-create a default one.
  const firstAgent = agents[0];

  const ensureAgent = useCallback(async (): Promise<string | null> => {
    if (firstAgent) return firstAgent.id;
    setCreatingAgent(true);
    try {
      const agent = await createManagedAgent({
        name: "My Assistant",
        template_id: "personal_deep_research",
      });
      setAgents((prev) => [...prev, agent]);
      return agent.id;
    } catch {
      return null;
    } finally {
      setCreatingAgent(false);
    }
  }, [firstAgent]);

  // Auto-create agent when switching to messaging tab
  useEffect(() => {
    if (activeTab === 'messaging' && !firstAgent && !creatingAgent) {
      ensureAgent();
    }
  }, [activeTab, firstAgent, creatingAgent, ensureAgent]);

  const tabs = [
    { id: 'sources' as const, label: 'Data Sources', icon: Database },
    { id: 'messaging' as const, label: 'Messaging Channels', icon: MessageSquare },
    { id: 'memory' as const, label: 'Memory', icon: Brain },
  ];

  return (
    <div className="flex-1 overflow-y-auto px-6 py-8">
      <div className="max-w-6xl mx-auto">
      <HudFrame className="rounded-xl p-6">
      <header className="mb-7 flex items-start gap-5">
        <div
          className="shrink-0 grid place-items-center rounded-2xl"
          style={{
            width: 64,
            height: 64,
            background: 'var(--color-accent-subtle)',
            border: '1px solid color-mix(in srgb, var(--color-accent) 35%, transparent)',
            boxShadow: '0 0 24px -8px var(--color-accent-glow)',
          }}
        >
          <Database size={28} style={{ color: 'var(--color-accent)' }} />
        </div>
        <div>
          <h1
            className="hud-title text-2xl tracking-[0.04em]"
            style={{ color: 'var(--color-text)' }}
          >
            Data Sources, Channels &amp; Memory
          </h1>
          <p className="text-sm mt-2 max-w-2xl" style={{ color: 'var(--color-text-secondary)' }}>
            Connect your personal data and messaging channels to give your AI
            assistant context, memory, and real-time awareness.
          </p>
        </div>
      </header>

      <div
        className="flex gap-1 mb-6"
        style={{ borderBottom: '1px solid var(--color-border)' }}
      >
        {tabs.map((tab) => {
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className="relative px-4 py-2.5 text-sm transition-colors cursor-pointer"
              style={{
                color: isActive ? 'var(--color-accent)' : 'var(--color-text-secondary)',
                fontWeight: isActive ? 600 : 400,
              }}
            >
              {tab.label}
              {isActive && (
                <motion.span
                  layoutId="data-sources-tab-indicator"
                  className="absolute left-0 right-0 -bottom-px h-[2px]"
                  style={{
                    background: 'var(--color-accent)',
                    boxShadow: '0 0 8px var(--color-accent-glow)',
                  }}
                  transition={{ type: 'spring', stiffness: 380, damping: 30 }}
                />
              )}
            </button>
          );
        })}
      </div>

      <div>
        {activeTab === 'sources' && <DataSourcesSection />}
        {activeTab === 'messaging' && (
          firstAgent ? (
            <MessagingSection agentId={firstAgent.id} />
          ) : creatingAgent ? (
            <div className="flex items-center gap-3 p-4 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
              <Loader2 size={16} className="animate-spin" style={{ color: 'var(--color-accent)' }} />
              Setting up your assistant...
            </div>
          ) : null
        )}
        {activeTab === 'memory' && <MemorySection />}
      </div>
      </HudFrame>
      </div>
    </div>
  );
}
