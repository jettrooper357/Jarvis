// NOTE: useAudioUnlock latches a MODULE-GLOBAL flag that cannot be reset
// between tests. This file must contain exactly ONE test — a second test would
// start with the latch already true and fail its initial `false` assertion.
import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useAudioUnlock } from './useAudioUnlock';

describe('useAudioUnlock', () => {
  it('flips unlocked to true after a user gesture', () => {
    const { result } = renderHook(() => useAudioUnlock());
    expect(result.current.unlocked).toBe(false);
    act(() => {
      window.dispatchEvent(new Event('pointerdown'));
    });
    expect(result.current.unlocked).toBe(true);
  });
});
