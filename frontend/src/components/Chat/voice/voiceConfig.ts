import type { VoiceConfig } from './voiceTypes';

interface VoiceSettingsSlice {
  voiceLoopEnabled: boolean;
  voiceSilenceTimeoutMs: number;
  voiceMinSpeechMs: number;
  voiceAllowInterruption: boolean;
  voiceMicDeviceId: string;
  voiceSpeakerDeviceId: string;
  ttsProvider: string;
  ttsVoice: string;
  wakeWords: string[];
}

const DEFAULT_SILENCE_MS = 1800;
const DEFAULT_MIN_SPEECH_MS = 300;

function posInt(value: number, fallback: number): number {
  return Number.isFinite(value) && value > 0 ? Math.round(value) : fallback;
}

export function resolveVoiceConfig(s: VoiceSettingsSlice): VoiceConfig {
  return {
    enabled: !!s.voiceLoopEnabled,
    silenceTimeoutMs: posInt(s.voiceSilenceTimeoutMs, DEFAULT_SILENCE_MS),
    minSpeechMs: posInt(s.voiceMinSpeechMs, DEFAULT_MIN_SPEECH_MS),
    allowInterruption: s.voiceAllowInterruption !== false,
    micDeviceId: s.voiceMicDeviceId || '',
    speakerDeviceId: s.voiceSpeakerDeviceId || '',
    ttsProvider: s.ttsProvider || 'auto',
    ttsVoice: s.ttsVoice || '',
    wakeWords: Array.isArray(s.wakeWords) ? s.wakeWords : [],
  };
}
