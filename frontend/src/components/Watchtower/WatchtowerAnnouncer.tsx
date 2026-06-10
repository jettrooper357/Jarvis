import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router';
import { toast } from 'sonner';
import { fetchWatchtowerFindings, fetchWatchtowerStatus } from '../../lib/api';
import { speakViaChat } from '../../lib/voiceBus';
import { useAudioUnlock } from '../../hooks/useAudioUnlock';
import { useAppStore, generateId } from '../../lib/store';
import {
  GREETING_SPEECH,
  GREETING_TOAST_DESCRIPTION,
  GREETING_TOAST_TITLE,
  diffNewFindings,
  humanizeFinding,
  loadSeen,
  markSeen,
  pruneSeen,
  saveSeen,
} from './announce';

const POLL_MS = 20000;
const GREETED_KEY = 'watchtower-greeted';

export function WatchtowerAnnouncer() {
  const navigate = useNavigate();
  const { unlocked } = useAudioUnlock();
  const proactive = useAppStore((s) => s.settings.watchtowerProactive);

  const seenRef = useRef(loadSeen());
  const unlockedRef = useRef(unlocked);
  const greetingPendingRef = useRef(false);

  useEffect(() => {
    unlockedRef.current = unlocked;
  }, [unlocked]);

  // If audio was still locked when we greeted, speak the greeting as soon as
  // the user's first gesture unlocks audio.
  useEffect(() => {
    if (!unlocked || !greetingPendingRef.current) return;
    greetingPendingRef.current = false;
    speakViaChat(GREETING_SPEECH);
  }, [unlocked]);

  useEffect(() => {
    if (!proactive) return;
    let cancelled = false;
    let timer: number | undefined;

    const poll = async () => {
      try {
        const [findings, status] = await Promise.all([
          fetchWatchtowerFindings('active'),
          fetchWatchtowerStatus(),
        ]);
        if (cancelled || !Array.isArray(findings)) return;
        const fresh = diffNewFindings(findings, seenRef.current);
        const voiceOk = !!status && status.speech_enabled && !status.dnd_active;
        for (const f of fresh) {
          const { title, description, speech } = humanizeFinding(f);
          toast.warning(title, {
            description,
            duration: 15000,
            action: { label: 'Open', onClick: () => navigate('/command/mission-control') },
          });
          // Surface the finding inside the active chat conversation so the
          // chat assistant and the Watchtower share one thread ("connected").
          const convId = useAppStore.getState().activeId;
          if (convId) {
            useAppStore.getState().addMessage(convId, {
              id: generateId(),
              role: 'assistant',
              content: `**${title}**

${description}`,
              timestamp: Date.now(),
            });
          }
          // One voice: speak through the single chat TTS (queued, no overlap).
          if (voiceOk && unlockedRef.current) speakViaChat(speech);
        }
        seenRef.current = pruneSeen(markSeen(seenRef.current, fresh), findings);
        saveSeen(seenRef.current);
      } catch {
        // Non-blocking: the Watchtower panel surfaces API errors itself.
      }
    };

    const init = async () => {
      const alreadyGreeted = sessionStorage.getItem(GREETED_KEY) === 'yes';
      if (!alreadyGreeted) {
        // Baseline the current backlog as already-seen so login is greeting-only.
        try {
          const backlog = await fetchWatchtowerFindings('active');
          if (cancelled) return;
          if (Array.isArray(backlog)) {
            seenRef.current = pruneSeen(markSeen(seenRef.current, backlog), backlog);
            saveSeen(seenRef.current);
          }
        } catch {
          // ignore; the first poll will reconcile
        }
        sessionStorage.setItem(GREETED_KEY, 'yes');
        toast.info(GREETING_TOAST_TITLE, { description: GREETING_TOAST_DESCRIPTION });
        if (unlockedRef.current) {
          speakViaChat(GREETING_SPEECH);
        } else {
          greetingPendingRef.current = true;
          toast.info('Click anywhere to enable Jarvis voice', { duration: 8000 });
        }
      }
      if (cancelled) return;
      await poll();
      timer = window.setInterval(poll, POLL_MS);
    };

    void init();
    const onFocus = () => void poll();
    window.addEventListener('focus', onFocus);
    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
      window.removeEventListener('focus', onFocus);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [proactive]);

  return null;
}
