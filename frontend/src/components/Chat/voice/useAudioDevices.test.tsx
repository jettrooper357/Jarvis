import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { useAudioDevices } from './useAudioDevices';

beforeEach(() => {
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: {
      enumerateDevices: vi.fn().mockResolvedValue([
        { kind: 'audioinput', deviceId: 'mic-1', label: 'Mic One' },
        { kind: 'audiooutput', deviceId: 'spk-1', label: 'Speaker One' },
      ]),
    },
  });
});

describe('useAudioDevices', () => {
  it('lists input and output devices', async () => {
    const { result } = renderHook(() => useAudioDevices());
    await waitFor(() => expect(result.current.inputs.length).toBe(1));
    expect(result.current.inputs[0].deviceId).toBe('mic-1');
    expect(result.current.outputs[0].deviceId).toBe('spk-1');
  });
});
