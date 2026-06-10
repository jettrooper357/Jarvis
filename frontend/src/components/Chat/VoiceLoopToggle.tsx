import { Headphones } from 'lucide-react';
import { useAppStore } from '../../lib/store';
import type { VoiceState } from './voice/voiceTypes';

const STATUS_LABEL: Partial<Record<VoiceState, string>> = {
  LISTENING: 'Listening…',
  USER_SPEAKING: 'Listening…',
  PROCESSING_STT: 'Thinking…',
  GENERATING_RESPONSE: 'Thinking…',
  PROCESSING_TTS: 'Thinking…',
  PLAYING_RESPONSE: 'Speaking…',
  INTERRUPTED: 'Interrupted',
};

/**
 * Hands-free voice conversation toggle for the chat input toolbar. The button
 * is store-connected (flips `voiceLoopEnabled`); the optional `state` prop is
 * the live conversation-machine state used to render a small status pill.
 */
export function VoiceLoopToggle({ state }: { state?: VoiceState }) {
  const enabled = useAppStore((s) => s.settings.voiceLoopEnabled);
  const update = useAppStore((s) => s.updateSettings);
  const label = state ? STATUS_LABEL[state] : undefined;
  return (
    <div className="flex items-center gap-1">
      <button
        type="button"
        aria-label="Hands-free voice conversation"
        aria-pressed={enabled}
        onClick={() => update({ voiceLoopEnabled: !enabled })}
        className="p-2 rounded-xl transition-colors shrink-0 cursor-pointer"
        style={{ color: enabled ? 'var(--color-accent)' : 'var(--color-text-tertiary)' }}
        title={enabled ? 'Hands-free voice conversation: on' : 'Hands-free voice conversation: off'}
      >
        <Headphones size={16} />
      </button>
      {enabled && label && (
        <span className="text-xs italic opacity-70" data-testid="voice-status">
          {label}
        </span>
      )}
    </div>
  );
}
