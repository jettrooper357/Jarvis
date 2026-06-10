import { describe, it, expect, beforeEach } from 'vitest';
import { voiceLog, getVoiceLogBuffer, clearVoiceLog } from './voiceLog';

describe('voiceLog', () => {
  beforeEach(() => clearVoiceLog());

  it('records entries with level, message, and timestamp', () => {
    voiceLog.info('state', 'LISTENING');
    const buf = getVoiceLogBuffer();
    expect(buf).toHaveLength(1);
    expect(buf[0].level).toBe('info');
    expect(buf[0].category).toBe('state');
    expect(buf[0].message).toBe('LISTENING');
    expect(typeof buf[0].ts).toBe('number');
  });

  it('caps the ring buffer at 200 entries', () => {
    for (let i = 0; i < 250; i++) voiceLog.debug('tick', String(i));
    expect(getVoiceLogBuffer().length).toBe(200);
    expect(getVoiceLogBuffer()[199].message).toBe('249');
  });
});
