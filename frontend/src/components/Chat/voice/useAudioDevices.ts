import { useEffect, useState } from 'react';

export interface AudioDevice {
  deviceId: string;
  label: string;
}

/**
 * Enumerates audio input (mic) and output (speaker) devices. Labels are only
 * populated once the user has granted mic permission at least once; before
 * that the browser returns blank labels, so we fall back to generic names.
 */
export function useAudioDevices() {
  const [inputs, setInputs] = useState<AudioDevice[]>([]);
  const [outputs, setOutputs] = useState<AudioDevice[]>([]);
  useEffect(() => {
    let cancelled = false;
    const md = navigator.mediaDevices;
    if (!md?.enumerateDevices) return;
    md.enumerateDevices()
      .then((list) => {
        if (cancelled) return;
        setInputs(
          list
            .filter((d) => d.kind === 'audioinput')
            .map((d) => ({ deviceId: d.deviceId, label: d.label || 'Microphone' })),
        );
        setOutputs(
          list
            .filter((d) => d.kind === 'audiooutput')
            .map((d) => ({ deviceId: d.deviceId, label: d.label || 'Speaker' })),
        );
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);
  return { inputs, outputs };
}
