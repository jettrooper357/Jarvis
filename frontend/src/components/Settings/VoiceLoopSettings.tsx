import { useAppStore } from '../../lib/store';
import { useAudioDevices } from '../Chat/voice/useAudioDevices';

/**
 * Settings rows for the hands-free voice conversation loop. Store-connected and
 * self-contained so it can be dropped into the Settings Voice section and
 * tested in isolation.
 */
export function VoiceLoopSettings() {
  const s = useAppStore((st) => st.settings);
  const update = useAppStore((st) => st.updateSettings);
  const { inputs, outputs } = useAudioDevices();
  return (
    <div className="space-y-3">
      <label className="flex items-center justify-between gap-3">
        <span>Allow interruption (barge-in)</span>
        <input
          aria-label="Allow interruption"
          type="checkbox"
          checked={s.voiceAllowInterruption}
          onChange={(e) => update({ voiceAllowInterruption: e.target.checked })}
        />
      </label>
      <label className="flex items-center justify-between gap-3">
        <span>Silence timeout (ms)</span>
        <input
          aria-label="Silence timeout"
          type="number"
          min={500}
          max={5000}
          step={100}
          value={s.voiceSilenceTimeoutMs}
          onChange={(e) => update({ voiceSilenceTimeoutMs: Number(e.target.value) })}
        />
      </label>
      <label className="flex items-center justify-between gap-3">
        <span>Minimum speech duration (ms)</span>
        <input
          aria-label="Minimum speech"
          type="number"
          min={50}
          max={2000}
          step={50}
          value={s.voiceMinSpeechMs}
          onChange={(e) => update({ voiceMinSpeechMs: Number(e.target.value) })}
        />
      </label>
      <label className="flex items-center justify-between gap-3">
        <span>Microphone</span>
        <select
          aria-label="Microphone device"
          value={s.voiceMicDeviceId}
          onChange={(e) => update({ voiceMicDeviceId: e.target.value })}
        >
          <option value="">System default</option>
          {inputs.map((d) => (
            <option key={d.deviceId} value={d.deviceId}>
              {d.label}
            </option>
          ))}
        </select>
      </label>
      <label className="flex items-center justify-between gap-3">
        <span>Speaker</span>
        <select
          aria-label="Speaker device"
          value={s.voiceSpeakerDeviceId}
          onChange={(e) => update({ voiceSpeakerDeviceId: e.target.value })}
        >
          <option value="">System default</option>
          {outputs.map((d) => (
            <option key={d.deviceId} value={d.deviceId}>
              {d.label}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
