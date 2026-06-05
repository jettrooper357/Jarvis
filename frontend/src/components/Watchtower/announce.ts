import type { WatchtowerFinding, WatchtowerPriority } from '../../lib/api';

const SEEN_KEY = 'watchtower-announced';
const PROACTIVE_KEY = 'watchtower-proactive-enabled';
const SEEN_CAP = 500; // max remembered finding ids; oldest-inserted are dropped first
const MAX_SPEECH_CHARS = 320; // TTS-friendly cap for a single spoken announcement

export const GREETING_TOAST_TITLE = 'Jarvis online';
export const GREETING_TOAST_DESCRIPTION = 'Monitoring active.';
export const GREETING_SPEECH = 'Jarvis online. Monitoring active.';

/** finding_id -> last announced updated_at */
export type SeenMap = Record<string, number>;

const PRIORITY_RANK: Record<WatchtowerPriority, number> = {
  info: 0,
  low: 1,
  normal: 2,
  high: 3,
  urgent: 4,
  emergency: 5,
};

export function loadSeen(): SeenMap {
  try {
    const raw = localStorage.getItem(SEEN_KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return parsed as SeenMap;
    }
    return {};
  } catch {
    return {};
  }
}

export function saveSeen(seen: SeenMap): void {
  try {
    localStorage.setItem(SEEN_KEY, JSON.stringify(seen));
  } catch {
    // ignore unavailable storage
  }
}

export function diffNewFindings(
  active: WatchtowerFinding[],
  seen: SeenMap,
): WatchtowerFinding[] {
  const fresh = active.filter((f) => {
    const prev = seen[f.finding_id];
    return prev === undefined || f.updated_at > prev;
  });
  return fresh.sort((a, b) => {
    const pr = (PRIORITY_RANK[b.priority] ?? -1) - (PRIORITY_RANK[a.priority] ?? -1);
    return pr !== 0 ? pr : b.updated_at - a.updated_at;
  });
}

export function markSeen(seen: SeenMap, findings: WatchtowerFinding[]): SeenMap {
  const next: SeenMap = { ...seen };
  for (const f of findings) next[f.finding_id] = f.updated_at;
  return next;
}

export function pruneSeen(
  seen: SeenMap,
  active: WatchtowerFinding[],
  cap = SEEN_CAP,
): SeenMap {
  const activeIds = new Set(active.map((f) => f.finding_id));
  const kept: SeenMap = {};
  for (const [id, ts] of Object.entries(seen)) {
    if (activeIds.has(id)) kept[id] = ts;
  }
  const ids = Object.keys(kept);
  if (ids.length <= cap) return kept;
  const capped: SeenMap = {};
  for (const id of ids.slice(-cap)) capped[id] = kept[id];
  return capped;
}

export function humanizeFinding(f: WatchtowerFinding): {
  title: string;
  description: string;
  speech: string;
} {
  const issue = f.finding_type.replace(/_/g, ' ');
  return {
    title: `Watchtower: ${issue}`,
    description: f.reason,
    speech: `Jarvis Watchtower. ${issue}. ${f.reason}`.slice(0, MAX_SPEECH_CHARS),
  };
}

export function isProactiveEnabled(): boolean {
  try {
    return localStorage.getItem(PROACTIVE_KEY) !== 'false';
  } catch {
    return true;
  }
}

export function setProactiveEnabled(value: boolean): void {
  try {
    localStorage.setItem(PROACTIVE_KEY, value ? 'true' : 'false');
  } catch {
    // ignore
  }
}
