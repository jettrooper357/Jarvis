import { useEffect, useState } from 'react';

// Browsers block AudioContext playback until the user has interacted with the
// page at least once. We latch that first gesture module-globally so any
// later AudioContext.resume() (inside useTTSPlayer) is permitted.
let globalUnlocked = false;
const GESTURES = ['pointerdown', 'keydown', 'touchstart'] as const;

export function useAudioUnlock(): { unlocked: boolean } {
  const [unlocked, setUnlocked] = useState(globalUnlocked);

  useEffect(() => {
    if (globalUnlocked) return;
    const onGesture = () => {
      globalUnlocked = true;
      setUnlocked(true);
      for (const g of GESTURES) window.removeEventListener(g, onGesture);
    };
    for (const g of GESTURES) window.addEventListener(g, onGesture, { passive: true });
    return () => {
      for (const g of GESTURES) window.removeEventListener(g, onGesture);
    };
  }, []);

  return { unlocked };
}
