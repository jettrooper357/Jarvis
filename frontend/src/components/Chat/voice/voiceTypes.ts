export type VoiceState =
  | 'IDLE'
  | 'LISTENING'
  | 'USER_SPEAKING'
  | 'PROCESSING_STT'
  | 'GENERATING_RESPONSE'
  | 'PROCESSING_TTS'
  | 'PLAYING_RESPONSE'
  | 'INTERRUPTED'
  | 'ERROR';

export type VoiceEvent =
  | { type: 'START' }
  | { type: 'MIC_READY' }
  | { type: 'SPEECH_START' }
  | { type: 'PARTIAL'; text: string }
  | { type: 'FINAL'; text: string }
  | { type: 'LLM_START' }
  | { type: 'LLM_TOKEN'; text: string }
  | { type: 'LLM_DONE' }
  | { type: 'TTS_START' }
  | { type: 'PLAYBACK_DONE' }
  | { type: 'INTERRUPT' }
  | { type: 'STT_ERROR'; message: string }
  | { type: 'LLM_ERROR'; message: string }
  | { type: 'TTS_ERROR'; message: string }
  | { type: 'ERROR'; message: string }
  | { type: 'STOP' }
  | { type: 'RESET' };

/** Side effects the orchestrator must perform after a transition. */
export type VoiceEffect =
  | 'START_LISTENING'
  | 'STOP_LISTENING'
  | 'ABORT_LLM'
  | 'STOP_TTS'
  | 'MARK_INTERRUPTED'
  | 'RECOVER_TO_LISTENING'
  | 'RECOVER_TO_IDLE';

export interface VoiceContext {
  state: VoiceState;
  partial: string;
  transcript: string;
  error: string | null;
}

export interface VoiceConfig {
  enabled: boolean;
  silenceTimeoutMs: number;
  minSpeechMs: number;
  allowInterruption: boolean;
  micDeviceId: string;
  speakerDeviceId: string;
  ttsProvider: string;
  ttsVoice: string;
  wakeWords: string[];
}
