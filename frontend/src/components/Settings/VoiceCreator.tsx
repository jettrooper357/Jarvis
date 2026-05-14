import { useEffect, useRef, useState } from 'react';
import { X, Mic, Square, Upload, Sparkles, Copy } from 'lucide-react';
import {
  createVoiceClone,
  createVoiceMix,
  type BuiltinVoice,
} from '../../lib/api';

interface VoiceCreatorProps {
  open: boolean;
  onClose: () => void;
  builtin: BuiltinVoice[];
  cloneSupported: boolean;
  onCreated: () => void;
}

type Tab = 'mix' | 'clone';

const LANG_LABELS: Record<string, string> = {
  a: 'American English',
  b: 'British English',
  e: 'Spanish',
  f: 'French',
  h: 'Hindi',
  i: 'Italian',
  j: 'Japanese',
  p: 'Portuguese',
  z: 'Mandarin Chinese',
};

function groupVoices(voices: BuiltinVoice[]): Array<{ lang: string; voices: BuiltinVoice[] }> {
  const map = new Map<string, BuiltinVoice[]>();
  for (const v of voices) {
    const key = v.lang || '?';
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(v);
  }
  return Array.from(map.entries()).map(([lang, vs]) => ({ lang, voices: vs }));
}

function voiceDisplay(v: BuiltinVoice): string {
  if (!v.name) return v.id;
  const g = v.gender === 'f' ? '♀' : v.gender === 'm' ? '♂' : '';
  const name = v.name.charAt(0).toUpperCase() + v.name.slice(1);
  return `${name} ${g}`.trim();
}

export function VoiceCreator({ open, onClose, builtin, cloneSupported, onCreated }: VoiceCreatorProps) {
  const [tab, setTab] = useState<Tab>('mix');
  const [name, setName] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [refText, setRefText] = useState('');
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null);
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);

  useEffect(() => {
    if (!open) {
      setName('');
      setSelected([]);
      setRefText('');
      setAudioBlob(null);
      setError('');
      setRecording(false);
    }
  }, [open]);

  if (!open) return null;

  const grouped = groupVoices(builtin);

  const toggle = (id: string) => {
    setSelected((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id);
      if (prev.length >= 4) return prev;
      return [...prev, id];
    });
  };

  const handleSaveMix = async () => {
    setError('');
    if (!name.trim()) { setError('Give the voice a name'); return; }
    if (selected.length < 2) { setError('Pick at least 2 voices to mix'); return; }
    setSubmitting(true);
    try {
      await createVoiceMix(name.trim(), selected);
      onCreated();
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  const startRecording = async () => {
    setError('');
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      chunksRef.current = [];
      mr.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
      mr.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: mr.mimeType || 'audio/webm' });
        setAudioBlob(blob);
        stream.getTracks().forEach((t) => t.stop());
      };
      mr.start();
      mediaRecorderRef.current = mr;
      setRecording(true);
    } catch (e) {
      setError(`Mic error: ${(e as Error).message}`);
    }
  };

  const stopRecording = () => {
    mediaRecorderRef.current?.stop();
    mediaRecorderRef.current = null;
    setRecording(false);
  };

  const handleFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) setAudioBlob(f);
  };

  const handleSaveClone = async () => {
    setError('');
    if (!name.trim()) { setError('Give the voice a name'); return; }
    if (!audioBlob) { setError('Record or upload a reference clip first'); return; }
    if (audioBlob.size < 10000) { setError('Audio is too short — aim for 6-10 seconds'); return; }
    setSubmitting(true);
    try {
      await createVoiceClone(name.trim(), audioBlob, refText.trim());
      onCreated();
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.55)' }}
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl rounded-2xl p-6 max-h-[90vh] overflow-y-auto"
        style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold flex items-center gap-2" style={{ color: 'var(--color-text)' }}>
            <Sparkles size={16} /> Create a voice
          </h2>
          <button onClick={onClose} className="p-1 rounded hover:opacity-70 cursor-pointer" aria-label="Close">
            <X size={16} />
          </button>
        </div>

        <div className="flex gap-1 p-0.5 rounded-lg mb-4" style={{ background: 'var(--color-bg-secondary)' }}>
          {(['mix', 'clone'] as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className="flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-colors cursor-pointer"
              style={{
                background: tab === t ? 'var(--color-surface)' : 'transparent',
                color: tab === t ? 'var(--color-text)' : 'var(--color-text-tertiary)',
                boxShadow: tab === t ? 'var(--shadow-sm)' : 'none',
              }}
            >
              {t === 'mix' ? 'Mix existing voices' : 'Clone from sample'}
            </button>
          ))}
        </div>

        <div className="mb-3">
          <label className="text-xs font-medium block mb-1" style={{ color: 'var(--color-text-secondary)' }}>
            Voice name
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={tab === 'mix' ? 'e.g. Warm narrator' : 'e.g. My voice'}
            className="w-full px-3 py-2 rounded-lg text-sm outline-none"
            style={{
              background: 'var(--color-bg-secondary)',
              color: 'var(--color-text)',
              border: '1px solid var(--color-border)',
            }}
          />
        </div>

        {tab === 'mix' && (
          <div>
            <p className="text-xs mb-3" style={{ color: 'var(--color-text-tertiary)' }}>
              Pick 2–4 voices. Kokoro averages their embeddings to make a new one.
              Currently selected: <strong>{selected.length}</strong>
            </p>
            <div className="space-y-3 max-h-72 overflow-y-auto pr-1">
              {grouped.map(({ lang, voices }) => (
                <div key={lang}>
                  <div className="text-[10px] uppercase tracking-wider mb-1" style={{ color: 'var(--color-text-tertiary)' }}>
                    {LANG_LABELS[lang] || lang}
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {voices.map((v) => {
                      const isSel = selected.includes(v.id);
                      return (
                        <button
                          key={v.id}
                          onClick={() => toggle(v.id)}
                          className="px-2 py-1 rounded-md text-xs cursor-pointer transition-colors"
                          style={{
                            background: isSel ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
                            color: isSel ? 'white' : 'var(--color-text)',
                            border: '1px solid ' + (isSel ? 'var(--color-accent)' : 'var(--color-border)'),
                          }}
                        >
                          {voiceDisplay(v)}
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {tab === 'clone' && (
          <div>
            {!cloneSupported && (
              <div className="mb-3 p-2 rounded text-xs" style={{ background: 'rgba(217,119,6,0.1)', color: 'var(--color-warning, #d97706)', border: '1px solid var(--color-warning, #d97706)' }}>
                Voice cloning isn't installed on the server. Run <code>uv sync --extra speech-clone</code> and restart to enable. CPU-only inference is slow — a GPU is recommended.
              </div>
            )}
            <p className="text-xs mb-2" style={{ color: 'var(--color-text-tertiary)' }}>
              Record or upload <strong>6–10 seconds</strong> of clear speech. F5-TTS clones the voice from this sample. Only clone voices you have consent to use.
            </p>
            <div className="flex items-center gap-2 mb-3">
              {!recording ? (
                <button
                  onClick={startRecording}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium cursor-pointer"
                  style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' }}
                >
                  <Mic size={12} /> Record
                </button>
              ) : (
                <button
                  onClick={stopRecording}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium cursor-pointer"
                  style={{ background: 'var(--color-error)', color: 'white' }}
                >
                  <Square size={12} /> Stop
                </button>
              )}
              <label className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium cursor-pointer"
                style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' }}>
                <Upload size={12} /> Upload
                <input type="file" accept="audio/*" onChange={handleFile} className="hidden" />
              </label>
              {audioBlob && (
                <span className="text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>
                  {(audioBlob.size / 1024).toFixed(1)} KB ready
                </span>
              )}
            </div>
            <label className="text-xs font-medium block mb-1" style={{ color: 'var(--color-text-secondary)' }}>
              Transcript of the sample (optional)
            </label>
            <textarea
              value={refText}
              onChange={(e) => setRefText(e.target.value)}
              placeholder="Leave blank to auto-transcribe with Whisper"
              rows={2}
              className="w-full px-3 py-2 rounded-lg text-sm outline-none resize-none"
              style={{
                background: 'var(--color-bg-secondary)',
                color: 'var(--color-text)',
                border: '1px solid var(--color-border)',
              }}
            />
          </div>
        )}

        {error && (
          <div className="mt-3 p-2 rounded text-xs" style={{ background: 'var(--color-error)', color: 'white' }}>
            {error}
          </div>
        )}

        <div className="flex justify-end gap-2 mt-4">
          <button
            onClick={onClose}
            className="px-3 py-1.5 rounded-lg text-xs font-medium cursor-pointer"
            style={{ background: 'transparent', color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
          >
            Cancel
          </button>
          <button
            disabled={submitting || (tab === 'clone' && !cloneSupported)}
            onClick={tab === 'mix' ? handleSaveMix : handleSaveClone}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
            style={{ background: 'var(--color-accent)', color: 'white' }}
          >
            <Copy size={12} /> {submitting ? 'Saving…' : 'Save voice'}
          </button>
        </div>
      </div>
    </div>
  );
}
