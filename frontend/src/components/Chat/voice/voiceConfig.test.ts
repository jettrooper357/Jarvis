import { describe, it, expect } from 'vitest';
import { resolveVoiceConfig } from './voiceConfig';

const base = {
  voiceLoopEnabled: true,
  voiceSilenceTimeoutMs: 1800,
  voiceMinSpeechMs: 300,
  voiceAllowInterruption: true,
  voiceMicDeviceId: 'mic-1',
  voiceSpeakerDeviceId: 'spk-1',
  ttsProvider: 'auto',
  ttsVoice: 'af_sky',
  wakeWords: ['jarvis'],
};

describe('resolveVoiceConfig', () => {
  it('maps settings into a VoiceConfig', () => {
    const cfg = resolveVoiceConfig(base as never);
    expect(cfg.enabled).toBe(true);
    expect(cfg.silenceTimeoutMs).toBe(1800);
    expect(cfg.minSpeechMs).toBe(300);
    expect(cfg.allowInterruption).toBe(true);
    expect(cfg.micDeviceId).toBe('mic-1');
    expect(cfg.wakeWords).toEqual(['jarvis']);
  });

  it('applies safe defaults for missing/invalid numbers', () => {
    const cfg = resolveVoiceConfig({ ...base, voiceSilenceTimeoutMs: 0, voiceMinSpeechMs: -5 } as never);
    expect(cfg.silenceTimeoutMs).toBe(1800);
    expect(cfg.minSpeechMs).toBe(300);
  });
});
