/**
 * Single shared voice channel.
 *
 * Anything that wants Jarvis to speak (proactive Watchtower announcements,
 * future notifications) dispatches a `jarvis-speak` event instead of spinning
 * up its own TTS player. The chat composer (`InputArea`) owns the one TTS
 * instance and speaks these requests, so there is only ever ONE voice and
 * announcements queue behind the current reply rather than overlapping.
 */
export const JARVIS_SPEAK_EVENT = 'jarvis-speak';

export function speakViaChat(text: string): void {
  if (!text || !text.trim()) return;
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(JARVIS_SPEAK_EVENT, { detail: text }));
}
