import { useCallback, useEffect, useState } from 'react';
import { Trash2 } from 'lucide-react';
import { listNotes, addNote, deleteNote } from '../../lib/projects-api';
import type { Note } from '../../lib/projects-api';

const NOTE_TYPES = ['Comment', 'Decision', 'Action Item', 'Update'];

export function TaskNotesPanel({ taskId }: { taskId: string }) {
  const [notes, setNotes] = useState<Note[]>([]);
  const [content, setContent] = useState('');
  const [type, setType] = useState('Comment');
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    listNotes(taskId)
      .then(setNotes)
      .catch(() => setNotes([]));
  }, [taskId]);

  useEffect(() => {
    load();
  }, [load]);

  const submit = async () => {
    if (!content.trim()) return;
    setBusy(true);
    try {
      await addNote(taskId, { content: content.trim(), type });
      setContent('');
      load();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <div
        className="text-xs font-semibold mb-2"
        style={{ color: 'var(--color-text)' }}
      >
        Notes &amp; updates
      </div>
      <div className="space-y-2 mb-2 max-h-48 overflow-y-auto">
        {notes.length === 0 && (
          <div
            className="text-xs"
            style={{ color: 'var(--color-text-tertiary)' }}
          >
            No notes yet.
          </div>
        )}
        {notes.map((n) => (
          <div
            key={n.id}
            className="p-2 rounded text-xs"
            style={{
              background: 'var(--color-bg-secondary)',
              border: '1px solid var(--color-border)',
            }}
          >
            <div className="flex items-center justify-between mb-1">
              <span style={{ color: 'var(--color-accent)' }}>{n.type}</span>
              <button
                onClick={() => deleteNote(n.id).then(load)}
                style={{ color: 'var(--color-text-tertiary)' }}
              >
                <Trash2 size={12} />
              </button>
            </div>
            <div style={{ color: 'var(--color-text-secondary)' }}>
              {n.content}
            </div>
            {n.ai_summary && (
              <div
                className="mt-1 italic"
                style={{ color: 'var(--color-text-tertiary)' }}
              >
                AI: {n.ai_summary}
              </div>
            )}
          </div>
        ))}
      </div>
      <div className="flex gap-2 items-start">
        <select
          value={type}
          onChange={(e) => setType(e.target.value)}
          className="text-xs rounded"
          style={{
            padding: '6px',
            background: 'var(--color-bg-secondary)',
            border: '1px solid var(--color-border)',
            color: 'var(--color-text)',
          }}
        >
          {NOTE_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder="Add a note…"
          rows={2}
          className="flex-1 text-xs rounded"
          style={{
            padding: '6px 8px',
            background: 'var(--color-bg-secondary)',
            border: '1px solid var(--color-border)',
            color: 'var(--color-text)',
            resize: 'vertical',
          }}
        />
        <button
          onClick={submit}
          disabled={busy || !content.trim()}
          className="text-xs px-3 py-2 rounded-lg cursor-pointer disabled:opacity-50"
          style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}
        >
          Add
        </button>
      </div>
    </div>
  );
}
