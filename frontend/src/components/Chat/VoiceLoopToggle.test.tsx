import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { VoiceLoopToggle } from './VoiceLoopToggle';
import { useAppStore } from '../../lib/store';

describe('VoiceLoopToggle', () => {
  beforeEach(() => {
    useAppStore.getState().updateSettings({ voiceLoopEnabled: false });
  });

  it('renders the hands-free toggle button', () => {
    render(<VoiceLoopToggle />);
    expect(
      screen.getByRole('button', { name: /hands-free voice conversation/i }),
    ).toBeInTheDocument();
  });

  it('flips voiceLoopEnabled in the store on click', () => {
    render(<VoiceLoopToggle />);
    fireEvent.click(screen.getByRole('button', { name: /hands-free voice conversation/i }));
    expect(useAppStore.getState().settings.voiceLoopEnabled).toBe(true);
  });

  it('shows the status pill when enabled and a state is provided', () => {
    useAppStore.getState().updateSettings({ voiceLoopEnabled: true });
    render(<VoiceLoopToggle state="LISTENING" />);
    expect(screen.getByTestId('voice-status')).toHaveTextContent('Listening');
  });

  it('hides the status pill when disabled', () => {
    render(<VoiceLoopToggle state="LISTENING" />);
    expect(screen.queryByTestId('voice-status')).toBeNull();
  });
});
