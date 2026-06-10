import { describe, it, expect } from 'vitest';
import { reduce, initialContext } from './voiceConversationMachine';
import type { VoiceContext, VoiceEvent } from './voiceTypes';

function run(ctx: VoiceContext, ...events: VoiceEvent[]) {
  let c = ctx;
  let effects: string[] = [];
  for (const e of events) {
    const r = reduce(c, e);
    c = r.context;
    effects = r.effects;
  }
  return { context: c, effects };
}

describe('voiceConversationMachine', () => {
  it('starts IDLE', () => {
    expect(initialContext.state).toBe('IDLE');
  });

  it('START -> LISTENING with START_LISTENING effect', () => {
    const r = reduce(initialContext, { type: 'START' });
    expect(r.context.state).toBe('LISTENING');
    expect(r.effects).toContain('START_LISTENING');
  });

  it('full happy path Listening->Speaking->STT->LLM->TTS->Playback->Listening', () => {
    const r = run(
      initialContext,
      { type: 'START' },
      { type: 'SPEECH_START' },
      { type: 'FINAL', text: 'hello' },
      { type: 'LLM_START' },
      { type: 'LLM_TOKEN', text: 'hi ' },
      { type: 'TTS_START' },
      { type: 'LLM_DONE' },
      { type: 'PLAYBACK_DONE' },
    );
    expect(r.context.state).toBe('LISTENING');
  });

  it('FINAL captures transcript and enters GENERATING_RESPONSE', () => {
    const r = run(initialContext, { type: 'START' }, { type: 'SPEECH_START' }, { type: 'FINAL', text: 'hey' });
    expect(r.context.state).toBe('GENERATING_RESPONSE');
    expect(r.context.transcript).toBe('hey');
  });

  it('INTERRUPT during GENERATING_RESPONSE tears down and enters INTERRUPTED', () => {
    const r = run(initialContext, { type: 'START' }, { type: 'SPEECH_START' }, { type: 'FINAL', text: 'x' }, { type: 'INTERRUPT' });
    expect(r.context.state).toBe('INTERRUPTED');
    expect(r.effects).toEqual(expect.arrayContaining(['STOP_TTS', 'ABORT_LLM', 'MARK_INTERRUPTED']));
  });

  it('INTERRUPT during PLAYING_RESPONSE tears down', () => {
    const r = run(
      initialContext,
      { type: 'START' }, { type: 'SPEECH_START' }, { type: 'FINAL', text: 'x' },
      { type: 'LLM_START' }, { type: 'TTS_START' }, { type: 'INTERRUPT' },
    );
    expect(r.context.state).toBe('INTERRUPTED');
    expect(r.effects).toEqual(expect.arrayContaining(['STOP_TTS', 'ABORT_LLM', 'MARK_INTERRUPTED']));
  });

  it('RESET from INTERRUPTED returns to LISTENING', () => {
    const interrupted = run(initialContext, { type: 'START' }, { type: 'SPEECH_START' }, { type: 'FINAL', text: 'x' }, { type: 'INTERRUPT' }).context;
    const r = reduce(interrupted, { type: 'RESET' });
    expect(r.context.state).toBe('LISTENING');
    expect(r.effects).toContain('START_LISTENING');
  });

  it('LLM_ERROR enters ERROR then RESET recovers to LISTENING', () => {
    const errored = run(initialContext, { type: 'START' }, { type: 'SPEECH_START' }, { type: 'FINAL', text: 'x' }, { type: 'LLM_ERROR', message: 'boom' }).context;
    expect(errored.state).toBe('ERROR');
    expect(errored.error).toBe('boom');
    expect(reduce(errored, { type: 'RESET' }).context.state).toBe('LISTENING');
  });

  it('STOP from any state returns to IDLE with STOP_LISTENING', () => {
    const listening = reduce(initialContext, { type: 'START' }).context;
    const r = reduce(listening, { type: 'STOP' });
    expect(r.context.state).toBe('IDLE');
    expect(r.effects).toContain('STOP_LISTENING');
  });

  it('ignores INTERRUPT while merely LISTENING (nothing to interrupt)', () => {
    const listening = reduce(initialContext, { type: 'START' }).context;
    const r = reduce(listening, { type: 'INTERRUPT' });
    expect(r.context.state).toBe('LISTENING');
    expect(r.effects).toEqual([]);
  });
});
