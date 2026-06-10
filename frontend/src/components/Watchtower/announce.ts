import type { WatchtowerFinding, WatchtowerPriority } from '../../lib/api';

const SEEN_KEY = 'watchtower-announced';
const SEEN_CAP = 500; // max remembered finding ids; oldest-inserted are dropped first
const MAX_SPEECH_CHARS = 320; // TTS-friendly cap for a single spoken announcement

export const GREETING_TOAST_TITLE = 'Jarvis online';
export const GREETING_TOAST_DESCRIPTION = 'Monitoring active.';
export const GREETING_SPEECH = "Good to see you. I'm online and keeping watch.";

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
  // Novelty is keyed on finding_id ALONE, never on updated_at. The backend
  // re-upserts active findings every scan and bumps updated_at unconditionally
  // (store.py upsert UPDATE), so an updated_at comparison would re-announce the
  // same finding on every poll — spamming toasts and the local TTS backend
  // (which starves whisper STT). A finding re-announces only if it left the
  // active set (pruned from `seen`) and later returns.
  const fresh = active.filter((f) => seen[f.finding_id] === undefined);
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
  for (const id of ids.slice(ids.length - cap)) capped[id] = kept[id];
  return capped;
}

function humanizeType(findingType: string): string {
  return findingType.replace(/_/g, ' ').trim();
}

export interface HumanizedFinding {
  title: string;
  description: string;
  speech: string;
}

export function humanizeFinding(f: WatchtowerFinding): HumanizedFinding {
  const human = humanizeType(f.finding_type);
  const title = `Watchtower: ${human}`;
  const description = f.reason;
  // Warm, calm phrasing — a reassuring heads-up, not a robotic label. The
  // opener softens by priority so urgent items still feel human, not alarming.
  const opener =
    f.priority === 'emergency' || f.priority === 'urgent'
      ? 'Sorry to interrupt,'
      : f.priority === 'high'
        ? 'A quick heads up,'
        : 'When you have a moment,';
  const parts = [opener, f.reason.trim()];
  const action = (f.recommended_action || '').trim();
  if (action) parts.push(action);
  let speech = parts.join(' ');
  if (speech.length > MAX_SPEECH_CHARS) {
    speech = speech.slice(0, MAX_SPEECH_CHARS - 1).trimEnd() + '…';
  }
  return { title, description, speech };
}