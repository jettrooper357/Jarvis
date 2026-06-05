import type { ModelInfo, SavingsData, ServerInfo } from '../types';

// ---------------------------------------------------------------------------
// Supabase config — safe to embed (RLS protects writes)
// ---------------------------------------------------------------------------

const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL || 'https://mtbtgpwzrbostweaanpr.supabase.co';
const SUPABASE_ANON_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY || 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im10YnRncHd6cmJvc3R3ZWFhbnByIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzMxODk0OTQsImV4cCI6MjA4ODc2NTQ5NH0._xMlqCfljtXpwPj54H-ghxfLFO-jiq4W2WhpU8vVL1c';

declare global {
  interface Window {
    __TAURI_INTERNALS__?: unknown;
  }
}

export const isTauri = () => typeof window !== 'undefined' && !!window.__TAURI_INTERNALS__;

// Cached API base URL fetched from the Tauri backend at startup.
// This avoids hardcoding the port — the Rust backend is the single
// source of truth for JARVIS_PORT.
let _tauriApiBase: string | null = null;

/** Pre-fetch the API base URL from the Tauri backend (call once at init). */
export async function initApiBase(): Promise<void> {
  if (!isTauri()) return;
  try {
    const { invoke } = await import('@tauri-apps/api/core');
    _tauriApiBase = await invoke<string>('get_api_base');
  } catch {
    // Command may not exist on older builds; fall through to default.
  }
}

const DESKTOP_API_FALLBACK = 'http://127.0.0.1:8000';

/**
 * A usable API base must be an absolute http(s) URL. Anything else (an
 * email address, a bare host without scheme, free text) would be treated by
 * `fetch` as a *relative* path and silently break every request with a 404
 * (e.g. `<origin>/jettrooper@hotmail.com/v1/...`). Reject those so we fall
 * back to a safe default instead.
 */
const isValidApiBase = (value: string): boolean => {
  try {
    const u = new URL(value);
    return u.protocol === 'http:' || u.protocol === 'https:';
  } catch {
    return false;
  }
};

const getSettingsApiUrl = (): string => {
  try {
    const raw = localStorage.getItem('openjarvis-settings');
    if (raw) {
      const parsed = JSON.parse(raw);
      if (parsed.apiUrl) {
        const cleaned = String(parsed.apiUrl).trim().replace(/\/+$/, '');
        if (isValidApiBase(cleaned)) return cleaned;
        // Malformed stored value (e.g. an email typed into the API URL
        // field): ignore it so getBase() uses the proper fallback rather
        // than producing broken relative requests.
        if (typeof console !== 'undefined') {
          console.warn('Ignoring invalid saved API URL:', cleaned);
        }
      }
    }
  } catch {}
  return '';
};

export const getBase = (): string => {
  const settingsUrl = getSettingsApiUrl();
  if (settingsUrl) return settingsUrl;
  if (import.meta.env.VITE_API_URL) return import.meta.env.VITE_API_URL;
  if (isTauri()) return _tauriApiBase || DESKTOP_API_FALLBACK;
  return '';
};

async function tauriInvoke<T>(command: string, args: Record<string, unknown> = {}): Promise<T> {
  const { invoke } = await import('@tauri-apps/api/core');
  const apiUrl = getBase();
  return invoke<T>(command, { apiUrl, ...args });
}

// ---------------------------------------------------------------------------
// Setup status (desktop only)
// ---------------------------------------------------------------------------

export interface SetupStatus {
  phase: string;
  detail: string;
  ollama_ready: boolean;
  server_ready: boolean;
  model_ready: boolean;
  error: string | null;
}

export async function getSetupStatus(): Promise<SetupStatus | null> {
  if (!isTauri()) return null;
  try {
    const { invoke } = await import('@tauri-apps/api/core');
    return await invoke<SetupStatus>('get_setup_status');
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

export async function fetchModels(): Promise<ModelInfo[]> {
  if (isTauri()) {
    try {
      const result = await tauriInvoke<{ data?: ModelInfo[] }>('fetch_models');
      return result?.data || [];
    } catch {
      // Fall through to fetch
    }
  }
  const res = await fetch(`${getBase()}/v1/models`);
  if (!res.ok) throw new Error(`Failed to fetch models: ${res.status}`);
  const data = await res.json();
  return data.data || [];
}

export async function fetchRecommendedModel(): Promise<{ model: string; reason: string }> {
  const res = await fetch(`${getBase()}/v1/recommended-model`);
  if (!res.ok) return { model: '', reason: 'Failed to fetch' };
  return res.json();
}

export async function saveCloudKey(keyName: string, keyValue: string): Promise<void> {
  if (isTauri()) {
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      await invoke('save_cloud_key', { keyName, keyValue });
      return;
    } catch {
      // Fall through to the HTTP API for dev/browser parity.
    }
  }
  const res = await fetch(`${getBase()}/v1/cloud/keys`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ keyName, keyValue }),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(`Failed to save cloud key: ${detail}`);
  }
}

export async function pullModel(modelName: string): Promise<void> {
  // In Tauri, go through the Rust backend directly (avoids CORS / timeout
  // issues with long model downloads via fetch).
  if (isTauri()) {
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      await invoke('pull_ollama_model', { modelName });
      return;
    } catch (e: any) {
      throw new Error(e?.message || e || 'Download failed');
    }
  }
  const res = await fetch(`${getBase()}/v1/models/pull`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: modelName }),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(`Failed to pull model: ${detail}`);
  }
}

export async function deleteModel(modelName: string): Promise<void> {
  if (isTauri()) {
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      await invoke('delete_ollama_model', { modelName });
      return;
    } catch (e: any) {
      throw new Error(e?.message || e || 'Delete failed');
    }
  }
  const res = await fetch(`${getBase()}/v1/models/${encodeURIComponent(modelName)}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(`Failed to delete model: ${detail}`);
  }
}

const _CLOUD_PREFIXES = ['gpt-', 'o1-', 'o3-', 'o4-', 'chatgpt-', 'claude-', 'gemini-', 'openrouter/', 'MiniMax-', 'codex/'];

export async function preloadModel(modelName: string): Promise<void> {
  // Cloud models don't need Ollama preloading
  if (_CLOUD_PREFIXES.some(p => modelName.startsWith(p))) {
    return;
  }
  // Trigger Ollama to load the model into memory (empty prompt, no generation).
  const ollamaUrl = 'http://127.0.0.1:11434';
  try {
    const res = await fetch(`${ollamaUrl}/api/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: modelName, prompt: '', keep_alive: '5m' }),
      signal: AbortSignal.timeout(120_000),
    });
    if (!res.ok) throw new Error(`Preload failed: ${res.status}`);
  } catch (e: any) {
    if (e.name === 'TimeoutError') throw new Error('Model load timed out (120s)');
    throw e;
  }
}

export async function fetchSavings(): Promise<SavingsData> {
  const res = await fetch(`${getBase()}/v1/savings`);
  if (!res.ok) throw new Error(`Failed to fetch savings: ${res.status}`);
  return res.json();
}

export async function fetchServerInfo(): Promise<ServerInfo> {
  const res = await fetch(`${getBase()}/v1/info`);
  if (!res.ok) throw new Error(`Failed to fetch server info: ${res.status}`);
  return res.json();
}

export async function checkHealth(): Promise<boolean> {
  if (isTauri()) {
    try {
      await tauriInvoke('check_health', { apiUrl: getBase() });
      return true;
    } catch {
      return false;
    }
  }
  try {
    const res = await fetch(`${getBase()}/health`);
    return res.ok;
  } catch {
    return false;
  }
}

export async function fetchEnergy(): Promise<unknown> {
  if (isTauri()) {
    try {
      return await tauriInvoke('fetch_energy', { apiUrl: getBase() });
    } catch {}
  }
  const res = await fetch(`${getBase()}/v1/telemetry/energy`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function fetchTelemetry(): Promise<unknown> {
  if (isTauri()) {
    try {
      return await tauriInvoke('fetch_telemetry', { apiUrl: getBase() });
    } catch {}
  }
  const res = await fetch(`${getBase()}/v1/telemetry/stats`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function fetchTraces(limit: number = 50): Promise<unknown> {
  if (isTauri()) {
    try {
      return await tauriInvoke('fetch_traces', { apiUrl: getBase(), limit });
    } catch {}
  }
  const res = await fetch(`${getBase()}/v1/traces?limit=${limit}`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// Watchtower
// ---------------------------------------------------------------------------

export type WatchtowerPriority = 'info' | 'low' | 'normal' | 'high' | 'urgent' | 'emergency';

export interface WatchtowerStatus {
  enabled: boolean;
  running: boolean;
  last_scan_at: number | null;
  local_ai_status: string;
  local_ai_only: boolean;
  local_ai_provider: string;
  rules_fallback_active: boolean;
  dnd_active: boolean;
  telegram_enabled: boolean;
  speech_enabled: boolean;
  active_findings: number;
  pending_internal_routes: number;
}

export interface WatchtowerFinding {
  finding_id: string;
  finding_type: string;
  entity_type: string;
  entity_id: string;
  project_id?: string | null;
  task_id?: string | null;
  agent_id?: string | null;
  priority: WatchtowerPriority;
  status: string;
  reason: string;
  recommended_action: string;
  created_at: number;
  updated_at: number;
  resolved_at?: number | null;
  last_notified_at?: number | null;
  notification_count: number;
  dedupe_key: string;
  metadata_json: Record<string, unknown>;
}

export interface WatchtowerInternalRoute {
  route_id: string;
  finding_id: string;
  source: string;
  from_agent_id: string;
  to_agent_id: string;
  route_type: string;
  priority: WatchtowerPriority;
  message_type: string;
  requires_response: boolean;
  response_due_at?: number | null;
  status: string;
  created_at: number;
  responded_at?: number | null;
  escalated_at?: number | null;
  metadata_json: Record<string, unknown>;
}

export interface WatchtowerNotification {
  notification_id: string;
  finding_id: string;
  priority: WatchtowerPriority;
  route: string;
  title: string;
  body: string;
  decision: string;
  dnd_applied: boolean;
  bypassed_dnd: boolean;
  sent_at?: number | null;
  error_message?: string | null;
  metadata: Record<string, unknown>;
}

export interface WatchtowerSpeechEvent {
  speech_event_id: string;
  finding_id: string;
  priority: WatchtowerPriority;
  text_spoken: string;
  dnd_applied: boolean;
  bypassed_dnd: boolean;
  spoken_at?: number | null;
  success: boolean;
  error_message?: string | null;
  metadata: Record<string, unknown>;
}

export interface WatchtowerBrief {
  status: WatchtowerStatus;
  active_count: number;
  actionable_count: number;
  items: WatchtowerFinding[];
  recent_notifications: WatchtowerNotification[];
  recent_speech: WatchtowerSpeechEvent[];
  pending_routes: WatchtowerInternalRoute[];
}

export interface WatchtowerSettings {
  enabled: boolean;
  loop_interval_seconds: number;
  local_ai_only: boolean;
  local_model_required: boolean;
  fallback_to_rules_if_local_ai_unavailable: boolean;
  dnd_enabled: boolean;
  quiet_hours_start: string;
  quiet_hours_end: string;
  dnd_timezone: string;
  allow_emergency_bypass: boolean;
  allow_urgent_bypass: boolean;
  defer_low_priority: boolean;
  defer_normal_priority: boolean;
  defer_high_priority: boolean;
  in_app_enabled: boolean;
  telegram_enabled: boolean;
  speech_enabled: boolean;
  in_app_min_priority: WatchtowerPriority;
  telegram_min_priority: WatchtowerPriority;
  speech_min_priority: WatchtowerPriority;
  both_min_priority: WatchtowerPriority;
  speak_normal_priority: boolean;
  speak_high_priority: boolean;
  default_cooldown_minutes: number;
  emergency_cooldown_minutes: number;
  digest_interval_minutes: number;
  internal_response_minutes: number;
  local_ai_provider: string;
}

async function watchtowerJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${getBase()}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(`Watchtower request failed: ${detail || res.status}`);
  }
  return res.json();
}

export async function fetchWatchtowerStatus(): Promise<WatchtowerStatus> {
  return watchtowerJson<WatchtowerStatus>('/v1/watchtower/status');
}

export async function fetchWatchtowerBrief(): Promise<WatchtowerBrief> {
  return watchtowerJson<WatchtowerBrief>('/v1/watchtower/brief');
}

export async function fetchWatchtowerNotifications(
  limit = 25,
): Promise<WatchtowerNotification[]> {
  const data = await watchtowerJson<{ notifications: WatchtowerNotification[] }>(
    `/v1/watchtower/notifications?limit=${limit}`,
  );
  return data.notifications || [];
}

export async function fetchWatchtowerSpeechEvents(
  limit = 25,
): Promise<WatchtowerSpeechEvent[]> {
  const data = await watchtowerJson<{ speech_events: WatchtowerSpeechEvent[] }>(
    `/v1/watchtower/speech-events?limit=${limit}`,
  );
  return data.speech_events || [];
}

export async function fetchWatchtowerFindings(
  status = 'active',
): Promise<WatchtowerFinding[]> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : '';
  const data = await watchtowerJson<{ findings: WatchtowerFinding[] }>(
    `/v1/watchtower/findings${qs}`,
  );
  return data.findings || [];
}

export async function fetchWatchtowerInternalRoutes(
  status = 'sent',
): Promise<WatchtowerInternalRoute[]> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : '';
  const data = await watchtowerJson<{ routes: WatchtowerInternalRoute[] }>(
    `/v1/watchtower/internal-routes${qs}`,
  );
  return data.routes || [];
}

export async function resolveWatchtowerFinding(findingId: string): Promise<void> {
  await watchtowerJson(`/v1/watchtower/findings/${encodeURIComponent(findingId)}/resolve`, {
    method: 'POST',
  });
}

export async function snoozeWatchtowerFinding(
  findingId: string,
  minutes = 60,
): Promise<void> {
  await watchtowerJson(`/v1/watchtower/findings/${encodeURIComponent(findingId)}/snooze`, {
    method: 'POST',
    body: JSON.stringify({ minutes }),
  });
}

export async function escalateWatchtowerFinding(findingId: string): Promise<void> {
  await watchtowerJson(`/v1/watchtower/findings/${encodeURIComponent(findingId)}/escalate`, {
    method: 'POST',
  });
}

export async function routeWatchtowerFindingToChief(findingId: string): Promise<void> {
  await watchtowerJson('/v1/watchtower/route-to-chief', {
    method: 'POST',
    body: JSON.stringify({ finding_id: findingId }),
  });
}

export async function speakWatchtowerFindingAgain(findingId: string): Promise<void> {
  await watchtowerJson('/v1/watchtower/speak-again', {
    method: 'POST',
    body: JSON.stringify({ finding_id: findingId }),
  });
}

export async function testWatchtowerTelegram(priority: WatchtowerPriority = 'high'): Promise<void> {
  await watchtowerJson('/v1/watchtower/test-telegram', {
    method: 'POST',
    body: JSON.stringify({ priority }),
  });
}

export async function testWatchtowerSpeech(priority: WatchtowerPriority = 'urgent'): Promise<void> {
  await watchtowerJson('/v1/watchtower/test-speech', {
    method: 'POST',
    body: JSON.stringify({ priority }),
  });
}

export async function scanWatchtowerNow(): Promise<{ findings: WatchtowerFinding[] }> {
  return watchtowerJson('/v1/watchtower/scan-now', { method: 'POST' });
}

export async function fetchWatchtowerSettings(): Promise<WatchtowerSettings> {
  return watchtowerJson<WatchtowerSettings>('/v1/watchtower/settings');
}

export async function patchWatchtowerSettings(
  settings: Partial<WatchtowerSettings>,
): Promise<WatchtowerSettings> {
  return watchtowerJson<WatchtowerSettings>('/v1/watchtower/settings', {
    method: 'PATCH',
    body: JSON.stringify(settings),
  });
}

// ---------------------------------------------------------------------------
// Speech
// ---------------------------------------------------------------------------

export interface TranscriptionResult {
  text: string;
  language: string | null;
  confidence: number | null;
  duration_seconds: number;
}

export interface SpeechHealth {
  available: boolean;
  backend?: string;
  reason?: string;
  tts_available?: boolean;
  tts_backend?: string | null;
}

export interface BuiltinVoice {
  id: string;
  lang?: string;
  gender?: string;
  name?: string;
}

export interface TTSProvider {
  id: string;
  label: string;
  configured: boolean;
  healthy: boolean;
}

export interface CustomVoice {
  id: string;
  name: string;
  kind: 'mix' | 'clone';
  created_at: number;
  kokoro_voice?: string;
  has_audio?: boolean;
  ref_text?: string;
}

export interface VoicesResponse {
  backend: string | null;
  provider?: string;
  providers?: TTSProvider[];
  clone_backend: string | null;
  builtin: BuiltinVoice[];
  custom: CustomVoice[];
}

export async function fetchSpeechVoices(provider = 'auto'): Promise<VoicesResponse> {
  const empty: VoicesResponse = { backend: null, clone_backend: null, builtin: [], custom: [] };
  try {
    const qs = provider ? `?provider=${encodeURIComponent(provider)}` : '';
    const res = await fetch(`${getBase()}/v1/speech/voices${qs}`);
    if (!res.ok) return empty;
    const data = await res.json();
    // Tolerate the old shape ({voices: string[], backend}) for any caller
    // that hasn't been rebuilt yet.
    if (Array.isArray(data.voices)) {
      return {
        backend: data.backend ?? null,
        clone_backend: null,
        builtin: (data.voices as string[]).map((id) => ({ id })),
        custom: [],
      };
    }
    return {
      backend: data.backend ?? null,
      provider: data.provider ?? provider,
      providers: data.providers ?? [],
      clone_backend: data.clone_backend ?? null,
      builtin: data.builtin ?? [],
      custom: data.custom ?? [],
    };
  } catch {
    return empty;
  }
}

export async function createVoiceMix(
  name: string,
  voiceIds: string[],
): Promise<CustomVoice> {
  const res = await fetch(`${getBase()}/v1/speech/voices/mix`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, voice_ids: voiceIds }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`mix failed: ${res.status} ${detail}`);
  }
  return res.json();
}

export async function createVoiceClone(
  name: string,
  audio: Blob,
  refText: string = '',
): Promise<CustomVoice> {
  const form = new FormData();
  form.append('name', name);
  form.append('ref_text', refText);
  form.append('file', audio, 'reference.wav');
  const res = await fetch(`${getBase()}/v1/speech/voices/clone`, {
    method: 'POST',
    body: form,
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`clone failed: ${res.status} ${detail}`);
  }
  return res.json();
}

export async function deleteVoice(voiceId: string): Promise<void> {
  const res = await fetch(`${getBase()}/v1/speech/voices/${encodeURIComponent(voiceId)}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`delete failed: ${res.status} ${detail}`);
  }
}

export async function synthesizeProbe(
  text = 'Hello.',
  voiceId = '',
  speed = 1.0,
  provider = 'auto',
): Promise<{ ok: boolean; bytes: number; reason?: string; blob?: Blob }> {
  try {
    const res = await fetch(`${getBase()}/v1/speech/synthesize`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, output_format: 'wav', voice_id: voiceId, speed, provider }),
    });
    if (!res.ok) {
      let detail = '';
      try {
        const j = await res.json();
        detail = j?.detail || '';
      } catch {}
      return { ok: false, bytes: 0, reason: detail || `HTTP ${res.status}` };
    }
    const blob = await res.blob();
    return { ok: blob.size > 1024, bytes: blob.size, blob };
  } catch (err) {
    return { ok: false, bytes: 0, reason: (err as Error).message };
  }
}

export async function transcribeAudio(audioBlob: Blob, filename = 'recording.webm'): Promise<TranscriptionResult> {
  if (isTauri()) {
    try {
      const buffer = await audioBlob.arrayBuffer();
      return await tauriInvoke<TranscriptionResult>('transcribe_audio', {
        audioData: Array.from(new Uint8Array(buffer)),
        filename,
      });
    } catch {
      // Fall through to fetch
    }
  }
  const formData = new FormData();
  formData.append('file', audioBlob, filename);
  const res = await fetch(`${getBase()}/v1/speech/transcribe`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) throw new Error(`Transcription failed: ${res.status}`);
  return res.json();
}

export async function fetchSpeechHealth(): Promise<SpeechHealth> {
  if (isTauri()) {
    try {
      return await tauriInvoke<SpeechHealth>('speech_health');
    } catch {
      return { available: false };
    }
  }
  const res = await fetch(`${getBase()}/v1/speech/health`);
  if (!res.ok) return { available: false };
  return res.json();
}

// ---------------------------------------------------------------------------
// Agent Manager
// ---------------------------------------------------------------------------

export interface ManagedAgent {
  id: string;
  name: string;
  agent_type: string;
  org_role?: string;
  manager_agent_id?: string | null;
  config: Record<string, unknown>;
  template_id?: string;
  configured_tools?: string[];
  configured_skills?: string[];
  effective_skills?: string[];
  auto_tools?: string[];
  effective_tools?: string[];
  knowledge_enabled?: boolean;
  // Phase 2A — capability axes for the Inspector. Lists are always
  // present (empty when no policy exists), never undefined at runtime
  // for a server-built record; typed optional for backwards compatibility
  // with cached responses.
  inherited_skills?: string[];
  inherited_tools?: string[];
  blocked_skills?: string[];
  blocked_tools?: string[];
  requires_approval_skills?: string[];
  requires_approval_tools?: string[];
  assigned_job_capabilities?: string[];
  inherited_job_capabilities?: string[];
  blocked_job_capabilities?: string[];
  requires_approval_job_capabilities?: string[];
  effective_job_capabilities?: string[];
  // Phase 2E — Chief-as-canonical-ingress designation.
  is_chief?: boolean;
  avatar_url?: string | null;
  avatar_mime_type?: string | null;
  avatar_file_name?: string | null;
  avatar_updated_at?: number | string | null;
  status: 'idle' | 'running' | 'paused' | 'error' | 'archived' | 'needs_attention' | 'budget_exceeded' | 'stalled' | 'input_required' | 'auth_required' | 'waiting_on_tool';
  summary_memory: string;
  created_at: number;
  updated_at: number;
  // Runtime stats
  total_runs?: number;
  total_cost?: number;
  total_tokens?: number;
  input_tokens?: number;
  output_tokens?: number;
  last_run_at?: number | null;
  // Schedule
  schedule_type?: string;
  schedule_value?: string;
  // Budget
  budget?: number;
  // Learning
  learning_enabled?: boolean;
  // Live progress
  current_activity?: string;
}

export interface AgentTask {
  id: string;
  agent_id: string;
  assigned_by_agent_id?: string | null;
  description: string;
  status: 'pending' | 'active' | 'completed' | 'failed';
  progress: Record<string, unknown>;
  findings: unknown[];
  // Mission Control: every agent task is tied to a project task/subtask.
  project_task_id?: string | null;
  project_id?: string | null;
  created_at: number;
}

export type AgentJobType = 'cron' | 'interval' | 'once' | 'manual' | 'if_this_then_that';
export type AgentJobStatus = 'active' | 'paused' | 'completed' | 'failed';

export interface AgentJob {
  id: string;
  agent_id: string;
  name: string;
  description: string;
  job_type: AgentJobType;
  trigger: Record<string, unknown>;
  prompt: string;
  status: AgentJobStatus;
  next_run_at?: number | null;
  last_run_at?: number | null;
  cooldown_seconds: number;
  required_capabilities: string[];
  approval_required_capabilities: string[];
  delegation_policy: Record<string, unknown>;
  task_overrides: Record<string, unknown>;
  created_at: number;
  updated_at: number;
}

export interface AgentJobRun {
  id: string;
  job_id: string;
  agent_id: string;
  task_id?: string | null;
  status: string;
  started_at: number;
  finished_at?: number | null;
  summary: string;
  error: string;
  event: Record<string, unknown>;
}

export interface AppEventType {
  name: string;
  description: string;
  source: string;
  payload_schema: Record<string, unknown>;
  created_at: number;
}

export interface ChannelBinding {
  id: string;
  agent_id: string;
  channel_type: string;
  config: Record<string, unknown>;
  session_id: string;
  routing_mode: string;
}

export interface AgentTemplate {
  id: string;
  name: string;
  description: string;
  source: 'built-in' | 'user';
  editable?: boolean;
  agent_type: string;
  [key: string]: unknown;
}

export interface InstalledSkill {
  name: string;
  description?: string;
  source?: 'built-in' | 'user' | 'workspace';
  editable?: boolean;
}

export interface TemplateDocument extends AgentTemplate {
  content: string;
}

export interface SkillDocument extends InstalledSkill {
  content: string;
}

export interface PersistedToolCall {
  tool: string;
  arguments: string;
  result?: string;
  success?: boolean;
  latency?: number;
}

export interface AgentMessage {
  id: string;
  agent_id: string;
  direction: 'user_to_agent' | 'agent_to_user';
  content: string;
  mode: 'immediate' | 'queued';
  status: 'pending' | 'delivered' | 'responded';
  created_at: number;
  tool_calls?: PersistedToolCall[] | null;
}

export async function fetchManagedAgents(): Promise<ManagedAgent[]> {
  const res = await fetch(`${getBase()}/v1/managed-agents`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.agents || [];
}

export async function fetchManagedAgent(agentId: string): Promise<ManagedAgent> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function createManagedAgent(body: {
  name: string;
  agent_type?: string;
  template_id?: string;
  config?: Record<string, unknown>;
  org_role?: string;
  manager_agent_id?: string | null;
}): Promise<ManagedAgent> {
  const res = await fetch(`${getBase()}/v1/managed-agents`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function updateManagedAgent(
  agentId: string,
  body: Partial<{
    name: string;
    agent_type: string;
    config: Record<string, unknown>;
    org_role: string;
    manager_agent_id: string | null;
  }>,
): Promise<ManagedAgent> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function deleteManagedAgent(agentId: string): Promise<void> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
}

// Phase 2A — Capability Inspector preview (no side effects).
export async function uploadAgentAvatar(agentId: string, file: File): Promise<ManagedAgent> {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`${getBase()}/v1/agents/${agentId}/avatar`, {
    method: 'POST',
    body: form,
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(`Failed to upload avatar: ${detail || res.status}`);
  }
  return res.json();
}

export async function deleteAgentAvatar(agentId: string): Promise<ManagedAgent> {
  const res = await fetch(`${getBase()}/v1/agents/${agentId}/avatar`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(`Failed to remove avatar: ${detail || res.status}`);
  }
  return res.json();
}

export async function previewAgentCapabilities(
  agentId: string,
  configOverrides?: Record<string, unknown>,
): Promise<ManagedAgent> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/preview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ config_overrides: configOverrides || null }),
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

// Phase 2B — append-only config version history.
export interface AgentConfigVersion {
  id: string;
  agent_id: string;
  version_number: number;
  snapshot: Record<string, unknown>;
  diff: {
    added?: Record<string, unknown>;
    removed?: Record<string, unknown>;
    changed?: Record<string, { from: unknown; to: unknown }>;
  };
  summary: string;
  created_at: number;
  created_by?: string | null;
}

export async function fetchAgentConfigVersions(
  agentId: string,
  limit?: number,
): Promise<AgentConfigVersion[]> {
  const qs = limit ? `?limit=${limit}` : '';
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/versions${qs}`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const body = await res.json();
  return body.versions ?? [];
}

export async function revertAgentConfig(
  agentId: string,
  versionId: string,
  updatedBy?: string,
): Promise<ManagedAgent> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/revert`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ version_id: versionId, updated_by: updatedBy || null }),
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

// Phase 2E — Chief as canonical ingress.

export interface ChiefStatus {
  enabled: boolean;
  chief_id: string | null;
  chief_name: string | null;
}

export async function getChiefStatus(): Promise<ChiefStatus> {
  const res = await fetch(`${getBase()}/v1/chief/status`);
  if (!res.ok) {
    // Server lacks the endpoint (older build) — treat as "feature off".
    return { enabled: false, chief_id: null, chief_name: null };
  }
  return res.json();
}

export async function designateChief(agentId: string): Promise<ManagedAgent> {
  const res = await fetch(`${getBase()}/v1/chief/designate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ agent_id: agentId }),
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

/**
 * Send a chat message through the Chief ingress endpoint.
 *
 * The endpoint internally delegates to the same dispatcher as
 * ``sendAgentMessage`` so the SSE wire protocol is bit-identical; this
 * helper mirrors that function's callback shape so the InputArea can
 * swap call sites without changing its parsing logic.
 *
 * Throws an ``Error`` with ``.code = 'chief_ingress_disabled'`` or
 * ``'no_chief_designated'`` on a 412 so the caller can fall back to
 * the legacy ingress without inspecting the raw response.
 */
export async function sendChiefMessage(
  content: string,
  opts: {
    mode?: 'immediate' | 'queued';
    requestingUser?: string;
    signal?: AbortSignal;
    callbacks?: {
      onProgress?: (label: string) => void;
      onContentDelta?: (delta: string, fullContent: string) => void;
      onToolCallStart?: (info: AgentToolCallStart) => void;
      onToolCallEnd?: (info: AgentToolCallEnd) => void;
      onDone?: (
        fullContent: string,
        usage?: Record<string, number>,
        telemetry?: Record<string, unknown>,
      ) => void;
    };
  } = {},
): Promise<AgentMessage> {
  const { mode = 'queued', requestingUser, signal, callbacks } = opts;
  const res = await fetch(`${getBase()}/v1/chief/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      content,
      mode,
      stream: true,
      requesting_user: requestingUser || null,
    }),
    signal,
  });
  if (res.status === 412) {
    const detail = (await res.json().catch(() => ({}))) as {
      detail?: { error?: string; message?: string };
    };
    const err = new Error(detail?.detail?.message || 'Chief ingress unavailable');
    (err as Error & { code?: string }).code = detail?.detail?.error;
    throw err;
  }
  if (!res.ok) throw new Error(`Chief send failed: ${res.status}`);

  const contentType = res.headers.get('content-type') || '';
  if (contentType.includes('text/event-stream') && res.body) {
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let fullContent = '';
    let buffer = '';
    let lastUsage: Record<string, number> | undefined;
    let lastTelemetry: Record<string, unknown> | undefined;
    let currentEvent: string | undefined;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          if (line.startsWith('event: ')) {
            currentEvent = line.slice(7).trim();
            continue;
          }
          if (!line.startsWith('data: ')) {
            if (line.trim() === '') currentEvent = undefined;
            continue;
          }
          const data = line.slice(6);
          if (data === '[DONE]') {
            currentEvent = undefined;
            continue;
          }
          const evName = currentEvent;
          currentEvent = undefined;
          if (evName === 'tool_call_start') {
            try {
              const parsed = JSON.parse(data);
              callbacks?.onToolCallStart?.({
                tool: parsed.tool,
                arguments: parsed.arguments ?? '',
              });
            } catch {
              /* skip */
            }
            continue;
          }
          if (evName === 'tool_call_end') {
            try {
              const parsed = JSON.parse(data);
              callbacks?.onToolCallEnd?.({
                tool: parsed.tool,
                success: !!parsed.success,
                latency: typeof parsed.latency === 'number' ? parsed.latency : 0,
                result: parsed.result,
              });
            } catch {
              /* skip */
            }
            continue;
          }
          try {
            const chunk = JSON.parse(data);
            const toolProgress = chunk.choices?.[0]?.tool_progress;
            if (toolProgress) callbacks?.onProgress?.(toolProgress);
            const delta = chunk.choices?.[0]?.delta?.content || '';
            if (delta) {
              fullContent += delta;
              callbacks?.onContentDelta?.(delta, fullContent);
            }
            if (chunk.usage) lastUsage = chunk.usage;
            if (chunk.telemetry) lastTelemetry = chunk.telemetry;
          } catch {
            /* skip malformed chunks */
          }
        }
      }
    } catch {
      /* stream ended */
    }
    callbacks?.onDone?.(fullContent, lastUsage, lastTelemetry);
    return {
      id: '',
      agent_id: '',
      direction: 'agent_to_user',
      content: fullContent,
      mode,
      status: 'delivered',
      created_at: Date.now() / 1000,
    };
  }
  // Non-streaming path: JSON message record.
  return res.json();
}

export async function pauseManagedAgent(agentId: string): Promise<void> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/pause`, { method: 'POST' });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
}

export async function resumeManagedAgent(agentId: string): Promise<void> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/resume`, { method: 'POST' });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
}

export interface ChiefPendingQuestion {
  question: string;
  reason: string;
  expected_response_type: string;
  options?: string[];
}

export interface ChiefPendingResponse {
  pending: boolean;
  pause_kind?: 'input_required' | 'auth_required';
  question?: ChiefPendingQuestion;
  checkpoint_id?: string;
  run_id?: string | null;
  turns_so_far?: number;
}

export async function fetchChiefPending(
  agentId: string,
): Promise<ChiefPendingResponse> {
  const res = await fetch(
    `${getBase()}/v1/managed-agents/${agentId}/chief-pending`,
  );
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export interface ChiefResumeResult {
  agent_id: string;
  response: string;
  status: string | null;
}

export interface TraceTreeNode {
  id: string;
  parent_trace_id: string | null;
  run_id: string | null;
  agent: string;
  outcome: string | null;
  duration: number;
  started_at: number;
  model: string;
  result_preview: string;
  metadata: Record<string, unknown>;
  children: TraceTreeNode[];
}

export async function fetchTraceTree(
  agentId: string,
  traceId: string,
): Promise<TraceTreeNode> {
  const res = await fetch(
    `${getBase()}/v1/managed-agents/${agentId}/traces/${traceId}/tree`,
  );
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `Failed: ${res.status}`);
  }
  const data = await res.json();
  return data.root as TraceTreeNode;
}

export async function resumeChief(
  agentId: string,
  answer: string,
): Promise<ChiefResumeResult> {
  const res = await fetch(
    `${getBase()}/v1/managed-agents/${agentId}/chief-resume`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answer }),
    },
  );
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `Failed: ${res.status}`);
  }
  return res.json();
}

// ── Phase 2D — Approvals ─────────────────────────────────────────
//
// The approval data plane (GET/POST /v1/approvals) returns 503 when the
// server has no approval store configured; listApprovals degrades to an
// empty list so the UI simply shows nothing rather than erroring.

export interface ApprovalRequest {
  id: string;
  agent_id: string;
  task_id: string | null;
  capability: string;
  args: Record<string, unknown>;
  args_hash: string | null;
  summary: string;
  state: 'pending' | 'granted' | 'denied';
  requested_by: string | null;
  requested_at: number;
  resolved_by: string | null;
  resolved_at: number | null;
  consumed_at: number | null;
  decision: string | null;
  reason: string | null;
}

export async function listApprovals(params?: {
  agentId?: string;
  state?: string;
  limit?: number;
}): Promise<ApprovalRequest[]> {
  const qs = new URLSearchParams();
  if (params?.agentId) qs.set('agent_id', params.agentId);
  if (params?.state) qs.set('state', params.state);
  if (params?.limit) qs.set('limit', String(params.limit));
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  const res = await fetch(`${getBase()}/v1/approvals${suffix}`);
  if (res.status === 503) return [];
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return (data.approvals || []) as ApprovalRequest[];
}

export async function grantApproval(
  approvalId: string,
  opts?: { resolvedBy?: string; reason?: string },
): Promise<ApprovalRequest> {
  const res = await fetch(
    `${getBase()}/v1/approvals/${approvalId}/grant`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        resolved_by: opts?.resolvedBy,
        reason: opts?.reason,
      }),
    },
  );
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `Failed: ${res.status}`);
  }
  return res.json();
}

export async function denyApproval(
  approvalId: string,
  opts?: { resolvedBy?: string; reason?: string },
): Promise<ApprovalRequest> {
  const res = await fetch(
    `${getBase()}/v1/approvals/${approvalId}/deny`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        resolved_by: opts?.resolvedBy,
        reason: opts?.reason,
      }),
    },
  );
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `Failed: ${res.status}`);
  }
  return res.json();
}

export async function fetchAgentTasks(
  agentId: string,
  includeDelegated = false,
): Promise<AgentTask[]> {
  const qs = includeDelegated ? '?include_delegated=true' : '';
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/tasks${qs}`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.tasks || [];
}

export async function createAgentTask(
  agentId: string,
  description: string,
  projectTaskId: string,
  projectId?: string,
): Promise<AgentTask> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/tasks`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      description,
      project_task_id: projectTaskId,
      project_id: projectId,
    }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `Failed: ${res.status}`);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Mission Control aggregation
// ---------------------------------------------------------------------------

export interface MissionControlKpis {
  projects_total: number;
  projects_active: number;
  projects_at_risk: number;
  tasks_total: number;
  tasks_in_progress: number;
  tasks_overdue: number;
  tasks_blocked: number;
  tasks_done: number;
  avg_completion: number;
  workload_by_assignee: Record<string, number>;
  at_risk_projects: { id: string; name: string; status: string }[];
}

export interface MissionControlLinkedAgent {
  agent_id: string;
  agent_name: string;
  agent_status: string;
  working?: boolean;
  current_activity: string;
  agent_task_id: string;
  agent_task_status: string;
}

export interface MissionControlTask {
  id: string;
  title: string;
  description?: string;
  status: string;
  priority?: string;
  type?: string;
  percent_complete: number;
  assigned_to?: string;
  due_date?: string | null;
  parent_task_id?: string | null;
  updated_at?: number;
  linked_agents: MissionControlLinkedAgent[];
  subtasks: MissionControlTask[];
}

export interface MissionControlProject {
  id: string;
  name: string;
  description?: string;
  status: string;
  progress: number;
  tasks: MissionControlTask[];
}

export interface MissionControlAgent {
  id: string;
  name: string;
  org_role: string;
  role_tier: 'manager' | 'worker' | 'qa';
  status: string;
  working: boolean;
  stale?: boolean;
  last_activity_at?: number | null;
  current_activity: string;
  manager_agent_id?: string | null;
  linked_project_task_id?: string | null;
}

export interface MissionControlData {
  kpis: MissionControlKpis;
  projects: MissionControlProject[];
  agents: MissionControlAgent[];
}

export async function fetchMissionControl(): Promise<MissionControlData> {
  const res = await fetch(`${getBase()}/v1/projects/mission-control`);
  if (!res.ok) throw new Error(`Failed to fetch Mission Control: ${res.status}`);
  return res.json();
}

export interface ProjectTaskNote {
  id: string;
  task_id: string;
  author: string;
  content: string;
  type: string;
  ai_summary?: string | null;
  created_at: number;
}

export async function fetchTaskNotes(
  taskId: string,
): Promise<ProjectTaskNote[]> {
  const res = await fetch(
    `${getBase()}/v1/projects/tasks/${taskId}/notes`,
  );
  if (!res.ok) return [];
  const data = await res.json();
  return data.notes || [];
}

export async function updateAgentTask(
  agentId: string,
  taskId: string,
  updates: { description?: string; status?: AgentTask['status'] },
): Promise<AgentTask> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/tasks/${taskId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function deleteAgentTask(agentId: string, taskId: string): Promise<void> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/tasks/${taskId}`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
}

export async function fetchAgentJobs(agentId: string): Promise<AgentJob[]> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/jobs`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.jobs || [];
}

export async function createAgentJob(
  agentId: string,
  body: {
    name: string;
    job_type: AgentJobType;
    prompt: string;
    description?: string;
    trigger?: Record<string, unknown>;
    status?: AgentJobStatus;
    cooldown_seconds?: number;
    required_capabilities?: string[];
    approval_required_capabilities?: string[];
    delegation_policy?: Record<string, unknown>;
    task_overrides?: Record<string, unknown>;
  },
): Promise<AgentJob> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/jobs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function updateAgentJob(
  agentId: string,
  jobId: string,
  body: Partial<AgentJob>,
): Promise<AgentJob> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/jobs/${jobId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function deleteAgentJob(agentId: string, jobId: string): Promise<void> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/jobs/${jobId}`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
}

export async function runAgentJob(agentId: string, jobId: string): Promise<AgentJobRun> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/jobs/${jobId}/run`, {
    method: 'POST',
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function fetchAppEvents(): Promise<AppEventType[]> {
  const res = await fetch(`${getBase()}/v1/app-events`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.events || [];
}

export async function registerAppEvent(body: {
  name: string;
  description?: string;
  source?: string;
  payload_schema?: Record<string, unknown>;
}): Promise<AppEventType> {
  const res = await fetch(`${getBase()}/v1/app-events`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function emitAppEvent(
  name: string,
  payload: Record<string, unknown> = {},
): Promise<{ event: string; fired_jobs: string[] }> {
  const res = await fetch(`${getBase()}/v1/app-events/emit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, payload }),
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function fetchAgentChannels(agentId: string): Promise<ChannelBinding[]> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/channels`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.bindings || [];
}

export async function bindAgentChannel(
  agentId: string,
  channelType: string,
  config?: Record<string, unknown>,
): Promise<ChannelBinding> {
  const res = await fetch(
    `${getBase()}/v1/managed-agents/${agentId}/channels`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        channel_type: channelType,
        config: config || {},
        routing_mode: 'dedicated',
      }),
    },
  );
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function unbindAgentChannel(
  agentId: string,
  bindingId: string,
): Promise<void> {
  const res = await fetch(
    `${getBase()}/v1/managed-agents/${agentId}/channels/${bindingId}`,
    { method: 'DELETE' },
  );
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
}

// -- SendBlue auto-setup helpers ------------------------------------------

export async function sendblueVerify(
  apiKeyId: string,
  apiSecretKey: string,
): Promise<{ valid: boolean; numbers: string[]; raw: unknown }> {
  const res = await fetch(`${getBase()}/v1/channels/sendblue/verify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ api_key_id: apiKeyId, api_secret_key: apiSecretKey }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Verification failed: ${res.status}`);
  }
  return res.json();
}

export async function sendblueRegisterWebhook(
  apiKeyId: string,
  apiSecretKey: string,
  webhookUrl: string,
): Promise<{ registered: boolean; status: number }> {
  const res = await fetch(`${getBase()}/v1/channels/sendblue/register-webhook`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      api_key_id: apiKeyId,
      api_secret_key: apiSecretKey,
      webhook_url: webhookUrl,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Webhook registration failed: ${res.status}`);
  }
  return res.json();
}

export async function sendblueTest(
  apiKeyId: string,
  apiSecretKey: string,
  fromNumber: string,
  toNumber: string,
): Promise<{ sent: boolean; status: number }> {
  const res = await fetch(`${getBase()}/v1/channels/sendblue/test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      api_key_id: apiKeyId,
      api_secret_key: apiSecretKey,
      from_number: fromNumber,
      to_number: toNumber,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Test message failed: ${res.status}`);
  }
  return res.json();
}

export async function sendblueHealth(): Promise<{ channel_connected: boolean; bridge_wired: boolean; ready: boolean }> {
  const res = await fetch(`${getBase()}/v1/channels/sendblue/health`);
  if (!res.ok) return { channel_connected: false, bridge_wired: false, ready: false };
  return res.json();
}

export async function fetchTemplates(): Promise<AgentTemplate[]> {
  const res = await fetch(`${getBase()}/v1/templates`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.templates || [];
}

export async function fetchTemplateDocument(templateId: string): Promise<TemplateDocument> {
  const res = await fetch(`${getBase()}/v1/templates/${encodeURIComponent(templateId)}`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function createTemplateDocument(content: string): Promise<TemplateDocument> {
  const res = await fetch(`${getBase()}/v1/templates`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function updateTemplateDocument(templateId: string, content: string): Promise<TemplateDocument> {
  const res = await fetch(`${getBase()}/v1/templates/${encodeURIComponent(templateId)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function deleteTemplateDocument(templateId: string): Promise<void> {
  const res = await fetch(`${getBase()}/v1/templates/${encodeURIComponent(templateId)}`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
}

export async function fetchSkills(): Promise<InstalledSkill[]> {
  const res = await fetch(`${getBase()}/v1/skills`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.skills || [];
}

export async function fetchSkillDocument(skillName: string): Promise<SkillDocument> {
  const res = await fetch(`${getBase()}/v1/skills/${encodeURIComponent(skillName)}`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function createSkillDocument(content: string): Promise<SkillDocument> {
  const res = await fetch(`${getBase()}/v1/skills`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function updateSkillDocument(skillName: string, content: string): Promise<SkillDocument> {
  const res = await fetch(`${getBase()}/v1/skills/${encodeURIComponent(skillName)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function deleteSkillDocument(skillName: string): Promise<void> {
  const res = await fetch(`${getBase()}/v1/skills/${encodeURIComponent(skillName)}`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
}

export interface RemoteSkill {
  name: string;
  category: string;
  description: string;
  source: string;
}

export interface SkillInstallResult {
  success: boolean;
  skipped: boolean;
  name: string;
  source: string;
  target_path: string;
  translated_tools: string[];
  untranslated_tools: string[];
  scripts_imported: boolean;
  warnings: string[];
}

export async function browseRemoteSkills(params: {
  source: string;
  query?: string;
  category?: string;
  url?: string;
}): Promise<{ skills: RemoteSkill[]; total: number }> {
  const qs = new URLSearchParams({ source: params.source });
  if (params.query) qs.set('query', params.query);
  if (params.category) qs.set('category', params.category);
  if (params.url) qs.set('url', params.url);
  const res = await fetch(`${getBase()}/v1/skills/browse?${qs.toString()}`);
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `Failed: ${res.status}`);
  }
  return res.json();
}

export async function installRemoteSkill(body: {
  source: string;
  name: string;
  url?: string;
  with_scripts?: boolean;
  force?: boolean;
}): Promise<SkillInstallResult> {
  const res = await fetch(`${getBase()}/v1/skills/install`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const errBody = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(errBody.detail || `Failed: ${res.status}`);
  }
  return res.json();
}

export async function runManagedAgent(agentId: string): Promise<void> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/run`, { method: 'POST' });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `Failed: ${res.status}`);
  }
}

export async function recoverManagedAgent(agentId: string): Promise<{ recovered: boolean; checkpoint: unknown }> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/recover`, { method: 'POST' });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `Failed: ${res.status}`);
  }
  return res.json();
}

export async function fetchAgentState(agentId: string): Promise<{
  agent: ManagedAgent;
  tasks: AgentTask[];
  channels: ChannelBinding[];
  messages: AgentMessage[];
  checkpoint: unknown;
}> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/state`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export interface AgentToolCallStart {
  tool: string;
  arguments: string;
}

export interface AgentToolCallEnd {
  tool: string;
  success: boolean;
  latency: number;
  result?: string;
}

export async function sendAgentMessage(
  agentId: string,
  content: string,
  mode: 'immediate' | 'queued' = 'queued',
  callbacks?: {
    onProgress?: (label: string) => void;
    onContentDelta?: (delta: string, fullContent: string) => void;
    onToolCallStart?: (info: AgentToolCallStart) => void;
    onToolCallEnd?: (info: AgentToolCallEnd) => void;
    onDone?: (fullContent: string, usage?: Record<string, number>, telemetry?: Record<string, unknown>) => void;
  },
): Promise<AgentMessage> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content, mode, stream: true }),
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);

  // If streaming, consume the SSE response so the agent runs
  const contentType = res.headers.get('content-type') || '';
  if (contentType.includes('text/event-stream') && res.body) {
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let fullContent = '';
    let buffer = '';
    let lastUsage: Record<string, number> | undefined;
    let lastTelemetry: Record<string, unknown> | undefined;
    let currentEvent: string | undefined;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          if (line.startsWith('event: ')) {
            currentEvent = line.slice(7).trim();
            continue;
          }
          if (!line.startsWith('data: ')) {
            if (line.trim() === '') currentEvent = undefined;
            continue;
          }
          const data = line.slice(6);
          if (data === '[DONE]') {
            currentEvent = undefined;
            continue;
          }
          const evName = currentEvent;
          currentEvent = undefined;

          if (evName === 'tool_call_start') {
            try {
              const parsed = JSON.parse(data);
              callbacks?.onToolCallStart?.({
                tool: parsed.tool,
                arguments: parsed.arguments ?? '',
              });
            } catch {
              /* skip */
            }
            continue;
          }
          if (evName === 'tool_call_end') {
            try {
              const parsed = JSON.parse(data);
              callbacks?.onToolCallEnd?.({
                tool: parsed.tool,
                success: !!parsed.success,
                latency: typeof parsed.latency === 'number' ? parsed.latency : 0,
                result: parsed.result,
              });
            } catch {
              /* skip */
            }
            continue;
          }

          try {
            const chunk = JSON.parse(data);
            // Deep-research branch still uses tool_progress in a data chunk
            const toolProgress = chunk.choices?.[0]?.tool_progress;
            if (toolProgress) {
              callbacks?.onProgress?.(toolProgress);
            }
            const delta = chunk.choices?.[0]?.delta?.content || '';
            if (delta) {
              fullContent += delta;
              callbacks?.onContentDelta?.(delta, fullContent);
            }
            if (chunk.usage) lastUsage = chunk.usage;
            if (chunk.telemetry) lastTelemetry = chunk.telemetry;
          } catch {
            /* skip malformed chunks */
          }
        }
      }
    } catch { /* stream ended */ }

    callbacks?.onDone?.(fullContent, lastUsage, lastTelemetry);

    return {
      id: '',
      agent_id: agentId,
      direction: 'agent_to_user',
      content: fullContent,
      mode,
      status: 'delivered',
      created_at: Date.now() / 1000,
    };
  }

  return res.json();
}

export async function fetchAgentMessages(agentId: string): Promise<AgentMessage[]> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/messages`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.messages || [];
}

export async function fetchErrorAgents(): Promise<ManagedAgent[]> {
  const res = await fetch(`${getBase()}/v1/agents/errors`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.agents || [];
}

// ---------------------------------------------------------------------------
// Agent Learning + Traces
// ---------------------------------------------------------------------------

export interface LearningLogEntry {
  id: string;
  agent_id: string;
  event_type: string;
  description: string;
  data: Record<string, unknown>;
  created_at: number;
}

export interface AgentTrace {
  id: string;
  outcome: string;
  duration: number;
  started_at: number;
  steps: number;
  error_message?: string;
  metadata?: Record<string, unknown>;
}

export interface ToolInfo {
  name: string;
  description: string;
  category: string;
  source: 'tool' | 'channel';
  requires_credentials: boolean;
  credential_keys: string[];
  configured: boolean;
}

export async function fetchAvailableTools(): Promise<ToolInfo[]> {
  const res = await fetch(`${getBase()}/v1/tools`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.tools || [];
}

export async function saveToolCredentials(
  toolName: string,
  credentials: Record<string, string>,
): Promise<void> {
  const res = await fetch(`${getBase()}/v1/tools/${toolName}/credentials`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(credentials),
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
}

export interface AgentTraceDetail {
  id: string;
  agent: string;
  outcome: string;
  duration: number;
  started_at: number;
  steps: Array<{
    step_type: string;
    input: unknown;
    output: string;
    duration: number;
    metadata: Record<string, unknown>;
  }>;
}

export async function fetchLearningLog(agentId: string): Promise<LearningLogEntry[]> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/learning`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.learning_log || [];
}

export async function triggerLearning(agentId: string): Promise<void> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/learning/run`, { method: 'POST' });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
}

export async function fetchAgentTraces(agentId: string, limit = 20): Promise<AgentTrace[]> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/traces?limit=${limit}`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.traces || [];
}

export async function fetchAgentTrace(agentId: string, traceId: string): Promise<AgentTraceDetail> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/traces/${traceId}`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// Leaderboard savings submission (Supabase)
// ---------------------------------------------------------------------------

export interface SavingsSubmission {
  anon_id: string;
  display_name: string;
  email: string;
  total_calls: number;
  total_tokens: number;
  dollar_savings: number;
  energy_wh_saved: number;
  flops_saved: number;
  token_counting_version?: number;
}

export async function submitSavings(data: SavingsSubmission): Promise<boolean> {
  if (!SUPABASE_URL || !SUPABASE_ANON_KEY) return false;
  try {
    const res = await fetch(
      `${SUPABASE_URL}/rest/v1/savings_entries?on_conflict=anon_id`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          apikey: SUPABASE_ANON_KEY,
          Authorization: `Bearer ${SUPABASE_ANON_KEY}`,
          Prefer: 'resolution=merge-duplicates',
        },
        body: JSON.stringify(data),
      },
    );
    return res.ok || res.status === 201 || res.status === 200;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Memory
// ---------------------------------------------------------------------------

export interface MemorySearchResult {
  content: string;
  score: number;
  metadata: Record<string, unknown>;
}

export interface MemoryStats {
  entries: number;
  backend: string;
  [key: string]: unknown;
}

export interface MemoryConfig {
  backend: string;
  context_from_memory: boolean;
  context_top_k: number;
  context_min_score: number;
  context_max_tokens: number;
}

export async function getMemoryStats(): Promise<MemoryStats> {
  const res = await fetch(`${getBase()}/v1/memory/stats`);
  if (!res.ok) throw new Error('Failed to fetch memory stats');
  return res.json();
}

export async function searchMemory(query: string, topK: number = 5): Promise<MemorySearchResult[]> {
  const res = await fetch(`${getBase()}/v1/memory/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, top_k: topK }),
  });
  if (!res.ok) throw new Error('Failed to search memory');
  const data = await res.json();
  return data.results;
}

export async function storeMemory(content: string, metadata?: Record<string, unknown>): Promise<void> {
  const res = await fetch(`${getBase()}/v1/memory/store`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content, metadata }),
  });
  if (!res.ok) throw new Error('Failed to store memory');
}

export async function indexMemoryPath(path: string): Promise<{ chunks_indexed: number }> {
  const res = await fetch(`${getBase()}/v1/memory/index`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  });
  if (!res.ok) throw new Error('Failed to index path');
  return res.json();
}

export async function getMemoryConfig(): Promise<MemoryConfig> {
  const res = await fetch(`${getBase()}/v1/memory/config`);
  if (!res.ok) throw new Error('Failed to fetch memory config');
  return res.json();
}
