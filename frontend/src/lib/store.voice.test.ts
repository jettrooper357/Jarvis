import { describe, it, expect } from 'vitest';
import { useAppStore } from './store';

describe('voice settings defaults', () => {
  it('has voice loop defaults', () => {
    const s = useAppStore.getState().settings;
    expect(s.voiceLoopEnabled).toBe(false);
    expect(s.voiceSilenceTimeoutMs).toBe(1800);
    expect(s.voiceMinSpeechMs).toBe(300);
    expect(s.voiceAllowInterruption).toBe(true);
    expect(s.voiceMicDeviceId).toBe('');
    expect(s.voiceSpeakerDeviceId).toBe('');
  });

  it('updateSettings flips voiceLoopEnabled', () => {
    useAppStore.getState().updateSettings({ voiceLoopEnabled: true });
    expect(useAppStore.getState().settings.voiceLoopEnabled).toBe(true);
    useAppStore.getState().updateSettings({ voiceLoopEnabled: false });
  });
});
