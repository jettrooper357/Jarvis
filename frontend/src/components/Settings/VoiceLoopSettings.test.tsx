import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { VoiceLoopSettings } from './VoiceLoopSettings';
import { useAppStore } from '../../lib/store';

describe('VoiceLoopSettings', () => {
  beforeEach(() => {
    useAppStore.getState().updateSettings({
      voiceAllowInterruption: true,
      voiceSilenceTimeoutMs: 1800,
      voiceMinSpeechMs: 300,
    });
  });

  it('renders silence timeout, min speech, and allow-interruption controls', () => {
    render(<VoiceLoopSettings />);
    expect(screen.getByLabelText(/silence timeout/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/minimum speech/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/allow interruption/i)).toBeInTheDocument();
  });

  it('writes silence timeout changes to the store', () => {
    render(<VoiceLoopSettings />);
    fireEvent.change(screen.getByLabelText(/silence timeout/i), { target: { value: '2200' } });
    expect(useAppStore.getState().settings.voiceSilenceTimeoutMs).toBe(2200);
  });

  it('toggles allow-interruption in the store', () => {
    render(<VoiceLoopSettings />);
    fireEvent.click(screen.getByLabelText(/allow interruption/i));
    expect(useAppStore.getState().settings.voiceAllowInterruption).toBe(false);
  });
});
