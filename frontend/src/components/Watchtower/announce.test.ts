import { beforeEach, describe, expect, it } from 'vitest';
import type { WatchtowerFinding } from '../../lib/api';
import {
  diffNewFindings,
  humanizeFinding,
  loadSeen,
  markSeen,
  pruneSeen,
  saveSeen,
  type SeenMap,
} from './announce';

function finding(over: Partial<WatchtowerFinding> = {}): WatchtowerFinding {
  return {
    finding_id: 'f1',
    finding_type: 'overdue_task',
    entity_type: 'project_task',
    entity_id: 'task-1',
    priority: 'normal',
    status: 'active',
    reason: 'Project task is overdue.',
    recommended_action: 'Check status.',
    created_at: 1,
    updated_at: 1,
    notification_count: 0,
    dedupe_key: 'k',
    metadata_json: {},
    ...over,
  };
}

describe('announce helpers', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('diffNewFindings returns unseen findings only', () => {
    const seen: SeenMap = { f1: 1 };
    const active = [finding({ finding_id: 'f1' }), finding({ finding_id: 'f2' })];
    const fresh = diffNewFindings(active, seen);
    expect(fresh.map((f) => f.finding_id)).toEqual(['f2']);
  });

  it('baseline (markSeen of current backlog) yields empty diff next fetch', () => {
    const active = [finding({ finding_id: 'f1' }), finding({ finding_id: 'f2' })];
    const seen = markSeen({}, active);
    expect(diffNewFindings(active, seen)).toEqual([]);
  });

  it('does NOT re-announce a finding whose only change is an updated_at bump', () => {
    // The backend bumps updated_at on every scan (store.py upsert UPDATE), so
    // novelty must be keyed on finding_id alone or the same finding repeats
    // on every poll.
    const seen = markSeen({}, [finding({ finding_id: 'f1', updated_at: 1 })]);
    const active = [finding({ finding_id: 'f1', updated_at: 5 })];
    expect(diffNewFindings(active, seen)).toEqual([]);
  });

  it('sorts fresh findings by priority desc then updated_at desc', () => {
    const active = [
      finding({ finding_id: 'low', priority: 'low', updated_at: 9 }),
      finding({ finding_id: 'em', priority: 'emergency', updated_at: 2 }),
      finding({ finding_id: 'normA', priority: 'normal', updated_at: 3 }),
      finding({ finding_id: 'normB', priority: 'normal', updated_at: 7 }),
    ];
    expect(diffNewFindings(active, {}).map((f) => f.finding_id)).toEqual([
      'em',
      'normB',
      'normA',
      'low',
    ]);
  });

  it('pruneSeen drops ids no longer active and caps size', () => {
    const seen: SeenMap = { f1: 1, gone: 1 };
    const pruned = pruneSeen(seen, [finding({ finding_id: 'f1' })]);
    expect(pruned).toEqual({ f1: 1 });
  });

  it('loadSeen returns {} when storage is empty', () => {
    expect(loadSeen()).toEqual({});
  });

  it('loadSeen returns {} when storage holds a non-object value', () => {
    localStorage.setItem('watchtower-announced', '"not-an-object"');
    expect(loadSeen()).toEqual({});
  });

  it('pruneSeen caps to the most recent entries when over cap', () => {
    const seen: SeenMap = { a: 1, b: 2, c: 3 };
    const active = [
      finding({ finding_id: 'a' }),
      finding({ finding_id: 'b' }),
      finding({ finding_id: 'c' }),
    ];
    const pruned = pruneSeen(seen, active, 2);
    expect(Object.keys(pruned)).toEqual(['b', 'c']);
  });

  it('loadSeen/saveSeen round-trips through localStorage', () => {
    saveSeen({ f1: 3 });
    expect(loadSeen()).toEqual({ f1: 3 });
  });

  it('humanizeFinding produces title, description, warm speech', () => {
    const h = humanizeFinding(finding({ finding_type: 'stale_approval', reason: 'Needs sign-off.' }));
    expect(h.title).toBe('Watchtower: stale approval');
    expect(h.description).toBe('Needs sign-off.');
    expect(h.speech.toLowerCase()).toContain('when you have a moment');
    expect(h.speech).toContain('Needs sign-off.');
  });

});
