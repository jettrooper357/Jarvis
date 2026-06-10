import { describe, it, expect, vi, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useVoiceConversation } from './useVoiceConversation';
import type { VoiceConfig } from './voiceTypes';

afterEach(() => { vi.useRealTimers(); });

const cfg: VoiceConfig = {
  enabled: true, silenceTimeoutMs: 1800, minSpeechMs: 300, allowInterruption: true,
  micDeviceId: '', speakerDeviceId: '', ttsProvider: 'auto', ttsVoice: '', wakeWords: [],
};

function makeDeps() {
  return {
    startListening: vi.fn().mockResolvedValue(undefined),
    stopListening: vi.fn(),
    stopTts: vi.fn(),
    sendMessage: vi.fn().mockResolvedValue(undefined),
    abortLlm: vi.fn(),
    markLastAssistantInterrupted: vi.fn(),
  };
}

describe('useVoiceConversation', () => {
  it('start() begins listening', async () => {
    const deps = makeDeps();
    const { result } = renderHook(() => useVoiceConversation({ config: cfg, ...deps }));
    await act(async () => { await result.current.start(); });
    expect(deps.startListening).toHaveBeenCalled();
    expect(result.current.state).toBe('LISTENING');
  });

  it('a final transcript sends to the LLM', async () => {
    const deps = makeDeps();
    const { result } = renderHook(() => useVoiceConversation({ config: cfg, ...deps }));
    await act(async () => { await result.current.start(); });
    act(() => { result.current.handleSpeechStart(); });
    act(() => { result.current.handleFinal('hello there'); });
    expect(deps.sendMessage).toHaveBeenCalledWith('hello there');
    expect(result.current.state).toBe('GENERATING_RESPONSE');
  });

  it('barge-in during playback stops TTS, aborts LLM, marks interrupted, returns to LISTENING', async () => {
    vi.useFakeTimers(); // fake timers also mock Date.now() so we can pass the 300ms echo guard
    const deps = makeDeps();
    const { result } = renderHook(() => useVoiceConversation({ config: cfg, ...deps }));
    await act(async () => { await result.current.start(); });
    act(() => { result.current.handleSpeechStart(); });
    act(() => { result.current.handleFinal('x'); });
    act(() => { result.current.handleTtsStart(); }); // now PLAYING_RESPONSE, playback clock starts
    act(() => { vi.advanceTimersByTime(400); }); // move past the 300ms echo guard
    act(() => { result.current.handleSpeechStart(); }); // barge-in
    expect(deps.stopTts).toHaveBeenCalled();
    expect(deps.abortLlm).toHaveBeenCalled();
    expect(deps.markLastAssistantInterrupted).toHaveBeenCalled();
    expect(result.current.state).toBe('LISTENING');
  });

  it('barge-in is ignored while merely listening', async () => {
    const deps = makeDeps();
    const { result } = renderHook(() => useVoiceConversation({ config: cfg, ...deps }));
    await act(async () => { await result.current.start(); });
    act(() => { result.current.handleSpeechStart(); }); // USER_SPEAKING
    expect(deps.stopTts).not.toHaveBeenCalled();
    expect(deps.abortLlm).not.toHaveBeenCalled();
  });

  it('an LLM error recovers to LISTENING', async () => {
    const deps = makeDeps();
    const { result } = renderHook(() => useVoiceConversation({ config: cfg, ...deps }));
    await act(async () => { await result.current.start(); });
    act(() => { result.current.handleSpeechStart(); });
    act(() => { result.current.handleFinal('x'); });
    act(() => { result.current.handleLlmError('network'); });
    expect(result.current.state).toBe('LISTENING');
  });
});
