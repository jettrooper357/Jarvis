export type VoiceLogLevel = 'debug' | 'info' | 'warn' | 'error';
export interface VoiceLogEntry {
  ts: number;
  level: VoiceLogLevel;
  category: string;
  message: string;
}

const MAX = 200;
const buffer: VoiceLogEntry[] = [];
// Set window.__JARVIS_VOICE_DEBUG = true in the console to mirror to console.
function debugOn(): boolean {
  return (
    typeof window !== 'undefined' &&
    (window as unknown as { __JARVIS_VOICE_DEBUG?: boolean }).__JARVIS_VOICE_DEBUG === true
  );
}

function record(level: VoiceLogLevel, category: string, message: string): void {
  const entry: VoiceLogEntry = { ts: Date.now(), level, category, message };
  buffer.push(entry);
  if (buffer.length > MAX) buffer.splice(0, buffer.length - MAX);
  if (debugOn()) {
    const line = `[voice:${category}] ${message}`;
    if (level === 'error') console.error(line);
    else if (level === 'warn') console.warn(line);
    else console.log(line);
  }
}

export const voiceLog = {
  debug: (category: string, message: string) => record('debug', category, message),
  info: (category: string, message: string) => record('info', category, message),
  warn: (category: string, message: string) => record('warn', category, message),
  error: (category: string, message: string) => record('error', category, message),
};

export function getVoiceLogBuffer(): VoiceLogEntry[] {
  return buffer.slice();
}
export function clearVoiceLog(): void {
  buffer.length = 0;
}
