import type { VoiceContext, VoiceEffect, VoiceEvent, VoiceState } from './voiceTypes';

export const initialContext: VoiceContext = {
  state: 'IDLE',
  partial: '',
  transcript: '',
  error: null,
};

export interface ReduceResult {
  context: VoiceContext;
  effects: VoiceEffect[];
}

const INTERRUPTIBLE: VoiceState[] = [
  'PROCESSING_STT',
  'GENERATING_RESPONSE',
  'PROCESSING_TTS',
  'PLAYING_RESPONSE',
];

function next(
  ctx: VoiceContext,
  state: VoiceState,
  effects: VoiceEffect[] = [],
  patch: Partial<VoiceContext> = {},
): ReduceResult {
  return { context: { ...ctx, state, ...patch }, effects };
}

export function reduce(ctx: VoiceContext, ev: VoiceEvent): ReduceResult {
  // Global transitions available from any state.
  if (ev.type === 'STOP') return next(ctx, 'IDLE', ['STOP_LISTENING']);
  if (ev.type === 'ERROR') return next(ctx, 'ERROR', [], { error: ev.message });

  // Barge-in: only meaningful while we are producing or playing a response
  // (or transcribing). From LISTENING/USER_SPEAKING there is nothing to stop.
  if (ev.type === 'INTERRUPT') {
    if (INTERRUPTIBLE.includes(ctx.state)) {
      return next(ctx, 'INTERRUPTED', ['STOP_TTS', 'ABORT_LLM', 'MARK_INTERRUPTED']);
    }
    return next(ctx, ctx.state, []);
  }

  switch (ctx.state) {
    case 'IDLE':
      if (ev.type === 'START') return next(ctx, 'LISTENING', ['START_LISTENING']);
      return next(ctx, 'IDLE');

    case 'LISTENING':
      if (ev.type === 'SPEECH_START') return next(ctx, 'USER_SPEAKING', [], { partial: '' });
      if (ev.type === 'PARTIAL') return next(ctx, 'LISTENING', [], { partial: ev.text });
      return next(ctx, 'LISTENING');

    case 'USER_SPEAKING':
      if (ev.type === 'PARTIAL') return next(ctx, 'USER_SPEAKING', [], { partial: ev.text });
      if (ev.type === 'FINAL')
        // Abort any stale in-flight stream before the orchestrator starts the
        // new turn; STT already produced text server-side so we go to the LLM.
        return next(ctx, 'GENERATING_RESPONSE', ['ABORT_LLM'], { transcript: ev.text, partial: '' });
      if (ev.type === 'STT_ERROR') return next(ctx, 'ERROR', [], { error: ev.message });
      return next(ctx, 'USER_SPEAKING');

    case 'PROCESSING_STT':
      if (ev.type === 'FINAL') return next(ctx, 'GENERATING_RESPONSE', [], { transcript: ev.text });
      if (ev.type === 'STT_ERROR') return next(ctx, 'ERROR', [], { error: ev.message });
      return next(ctx, 'PROCESSING_STT');

    case 'GENERATING_RESPONSE':
      if (ev.type === 'TTS_START') return next(ctx, 'PLAYING_RESPONSE');
      if (ev.type === 'LLM_DONE') return next(ctx, 'PLAYING_RESPONSE');
      if (ev.type === 'LLM_ERROR') return next(ctx, 'ERROR', [], { error: ev.message });
      return next(ctx, 'GENERATING_RESPONSE');

    case 'PROCESSING_TTS':
      if (ev.type === 'TTS_START') return next(ctx, 'PLAYING_RESPONSE');
      if (ev.type === 'TTS_ERROR') return next(ctx, 'ERROR', [], { error: ev.message });
      return next(ctx, 'PROCESSING_TTS');

    case 'PLAYING_RESPONSE':
      if (ev.type === 'PLAYBACK_DONE') return next(ctx, 'LISTENING', ['START_LISTENING']);
      if (ev.type === 'TTS_ERROR') return next(ctx, 'ERROR', [], { error: ev.message });
      return next(ctx, 'PLAYING_RESPONSE');

    case 'INTERRUPTED':
      if (ev.type === 'RESET') return next(ctx, 'LISTENING', ['START_LISTENING'], { error: null });
      return next(ctx, 'INTERRUPTED');

    case 'ERROR':
      if (ev.type === 'RESET') return next(ctx, 'LISTENING', ['RECOVER_TO_LISTENING'], { error: null });
      return next(ctx, 'ERROR');

    default:
      return next(ctx, ctx.state);
  }
}
