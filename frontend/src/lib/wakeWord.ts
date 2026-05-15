/**
 * Wake-word matcher for the streaming STT pipeline.
 *
 * When wake words are configured, every utterance the server emits as `final`
 * is checked: only utterances that *start* with one of the configured phrases
 * are forwarded to the chat — the wake phrase itself is stripped and the
 * remainder becomes the prompt. ("Hey Jarvis, what's the time" → "what's the
 * time".) Matching is case-insensitive and tolerant of punctuation and
 * whitespace differences, since Whisper inserts commas/periods that the user
 * obviously didn't speak.
 *
 * If `wakeWords` is empty, the input passes through unchanged so manual mic
 * use behaves exactly as before. No built-in wake phrases are applied.
 */

function normalize(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9 ]+/g, ' ').replace(/\s+/g, ' ').trim();
}

export function getEffectiveWakeWords(wakeWords: string[]): string[] {
  return (wakeWords || []).map((word) => word.trim()).filter(Boolean);
}

export function matchWakeWord(transcript: string, wakeWords: string[]): string | null {
  const effectiveWakeWords = getEffectiveWakeWords(wakeWords);
  if (effectiveWakeWords.length === 0) return transcript;
  const normT = normalize(transcript);
  if (!normT) return null;

  for (const w of effectiveWakeWords) {
    const normW = normalize(w);
    if (!normW) continue;
    if (normT === normW) return '';
    if (normT.startsWith(normW + ' ')) {
      const wakeWordCount = normW.split(' ').length;
      const transcriptWords = transcript.trim().split(/\s+/);
      return transcriptWords
        .slice(wakeWordCount)
        .join(' ')
        .replace(/^[,.\s!?:;]+/, '')
        .trim();
    }
  }
  return null;
}
