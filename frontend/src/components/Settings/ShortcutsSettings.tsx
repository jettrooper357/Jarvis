import { useState, useEffect, useCallback } from 'react';
import { Plus, Trash2, FlaskConical, Check, X, ChevronDown, ChevronRight } from 'lucide-react';

type Pattern = { kind: 'phrase' | 'regex'; value: string };

type Rule = {
  id: string;
  name: string;
  enabled: boolean;
  priority: number;
  patterns: Pattern[];
  match_mode: 'contains' | 'whole_message';
  case_sensitive: boolean;
  target_kind: 'tool' | 'skill' | 'preset' | 'datasource';
  target_id: string;
  arg_template: Record<string, unknown>;
  post_prompt: string | null;
  post_model: string | null;
  on_failure: 'fallback_to_chief' | 'error' | 'custom_message';
  failure_message: string | null;
  created_at: string;
  updated_at: string;
  created_by: string;
};

type Targets = {
  tool: string[];
  skill: string[];
  datasource: string[];
  preset: string[];
};

type TestResult = {
  matched: boolean;
  handled: boolean;
  success: boolean;
  rule_id: string | null;
  rule_name: string | null;
  target_kind: string | null;
  target_id: string | null;
  content: string;
  fallback_to_chief: boolean;
  error: string | null;
  used_post_prompt: string | null;
};

const API = '/v1/shortcuts';

function emptyRule(): Omit<Rule, 'id' | 'created_at' | 'updated_at' | 'created_by'> {
  return {
    name: '',
    enabled: true,
    priority: 100,
    patterns: [{ kind: 'phrase', value: '' }],
    match_mode: 'contains',
    case_sensitive: false,
    target_kind: 'tool',
    target_id: '',
    arg_template: {},
    post_prompt: null,
    post_model: null,
    on_failure: 'fallback_to_chief',
    failure_message: null,
  };
}

export function ShortcutsSettings() {
  const [rules, setRules] = useState<Rule[]>([]);
  const [targets, setTargets] = useState<Targets>({ tool: [], skill: [], datasource: [], preset: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<ReturnType<typeof emptyRule> | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [testMessage, setTestMessage] = useState('');
  const [testResult, setTestResult] = useState<TestResult | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [r1, r2] = await Promise.all([
        fetch(API).then(r => r.json()),
        fetch(`${API}/targets`).then(r => r.json()),
      ]);
      setRules(r1.rules || []);
      setTargets(r2);
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const startCreate = () => {
    setEditingId(null);
    setDraft(emptyRule());
  };

  const startEdit = (rule: Rule) => {
    setEditingId(rule.id);
    setDraft({
      name: rule.name,
      enabled: rule.enabled,
      priority: rule.priority,
      patterns: rule.patterns.length ? rule.patterns : [{ kind: 'phrase', value: '' }],
      match_mode: rule.match_mode,
      case_sensitive: rule.case_sensitive,
      target_kind: rule.target_kind,
      target_id: rule.target_id,
      arg_template: rule.arg_template,
      post_prompt: rule.post_prompt,
      post_model: rule.post_model,
      on_failure: rule.on_failure,
      failure_message: rule.failure_message,
    });
  };

  const cancelDraft = () => {
    setDraft(null);
    setEditingId(null);
  };

  const saveDraft = async () => {
    if (!draft) return;
    const url = editingId ? `${API}/${editingId}` : API;
    const method = editingId ? 'PUT' : 'POST';
    try {
      const resp = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(draft),
      });
      if (!resp.ok) {
        const body = await resp.text();
        throw new Error(body || resp.statusText);
      }
      await refresh();
      cancelDraft();
    } catch (e) {
      setError(String(e));
    }
  };

  const toggleEnabled = async (rule: Rule) => {
    try {
      const payload = { ...rule, enabled: !rule.enabled };
      await fetch(`${API}/${rule.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      refresh();
    } catch (e) {
      setError(String(e));
    }
  };

  const deleteRule = async (rule: Rule) => {
    if (!confirm(`Delete shortcut "${rule.name}"?`)) return;
    try {
      await fetch(`${API}/${rule.id}`, { method: 'DELETE' });
      refresh();
    } catch (e) {
      setError(String(e));
    }
  };

  const runTest = async () => {
    if (!testMessage.trim()) return;
    try {
      const resp = await fetch(`${API}/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: testMessage }),
      });
      const body = await resp.json();
      setTestResult(body);
    } catch (e) {
      setError(String(e));
    }
  };

  if (loading) return <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>Loading…</div>;

  return (
    <div className="flex flex-col gap-3">
      {error && (
        <div className="text-xs px-3 py-2 rounded" style={{ background: 'var(--color-error-soft, #4a1d1d)', color: 'var(--color-error, #f87171)' }}>
          {error}
        </div>
      )}

      <div className="flex items-center justify-between">
        <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
          {rules.length} {rules.length === 1 ? 'rule' : 'rules'}
        </div>
        <button onClick={startCreate} className="flex items-center gap-1 text-xs px-2 py-1 rounded"
          style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text)' }}>
          <Plus size={12} /> New shortcut
        </button>
      </div>

      <div className="flex flex-col gap-2">
        {rules.map(rule => (
          <div key={rule.id} className="rounded" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)' }}>
            <div className="flex items-center justify-between p-3">
              <div className="flex items-center gap-2 min-w-0 flex-1">
                <button onClick={() => setOpenId(openId === rule.id ? null : rule.id)} style={{ color: 'var(--color-text-tertiary)' }}>
                  {openId === rule.id ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                </button>
                <div className="flex items-center gap-2 min-w-0">
                  <input type="checkbox" checked={rule.enabled} onChange={() => toggleEnabled(rule)} />
                  <span className="text-sm font-medium truncate" style={{ color: 'var(--color-text)' }}>{rule.name}</span>
                  {rule.created_by === 'system' && (
                    <span className="text-[9px] px-1.5 py-0.5 rounded" style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text-tertiary)' }}>
                      built-in
                    </span>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-3 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                <span className="px-1.5 py-0.5 rounded" style={{ background: 'var(--color-bg-tertiary)' }}>{rule.target_kind}:{rule.target_id || '—'}</span>
                <button onClick={() => startEdit(rule)} className="px-2 py-0.5 rounded" style={{ background: 'var(--color-bg-tertiary)' }}>Edit</button>
                <button onClick={() => deleteRule(rule)} style={{ color: 'var(--color-error, #f87171)' }}>
                  <Trash2 size={13} />
                </button>
              </div>
            </div>
            {openId === rule.id && (
              <div className="px-3 pb-3 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                <div className="grid grid-cols-2 gap-2">
                  <div><span style={{ color: 'var(--color-text-tertiary)' }}>Priority:</span> {rule.priority}</div>
                  <div><span style={{ color: 'var(--color-text-tertiary)' }}>Match:</span> {rule.match_mode}{rule.case_sensitive ? ' (case-sensitive)' : ''}</div>
                  <div><span style={{ color: 'var(--color-text-tertiary)' }}>On failure:</span> {rule.on_failure}</div>
                  <div><span style={{ color: 'var(--color-text-tertiary)' }}>Post model:</span> {rule.post_model || 'global default'}</div>
                </div>
                <div className="mt-2"><span style={{ color: 'var(--color-text-tertiary)' }}>Patterns:</span>
                  <ul className="ml-3 mt-1">
                    {rule.patterns.map((p, i) => <li key={i}><code>{p.kind}</code>: <code>{p.value}</code></li>)}
                  </ul>
                </div>
                {rule.post_prompt !== null && (
                  <div className="mt-2"><span style={{ color: 'var(--color-text-tertiary)' }}>Post prompt:</span>
                    <div className="mt-1 p-2 rounded" style={{ background: 'var(--color-bg-tertiary)', whiteSpace: 'pre-wrap' }}>
                      {rule.post_prompt || <em style={{ color: 'var(--color-text-tertiary)' }}>(empty — passthrough)</em>}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
        {rules.length === 0 && !draft && (
          <div className="text-xs italic text-center py-4" style={{ color: 'var(--color-text-tertiary)' }}>
            No shortcuts yet. Click "New shortcut" to author one.
          </div>
        )}
      </div>

      {draft && (
        <div className="rounded p-3 flex flex-col gap-2" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-accent)' }}>
          <div className="text-xs font-semibold" style={{ color: 'var(--color-text)' }}>
            {editingId ? 'Edit shortcut' : 'New shortcut'}
          </div>
          <DraftEditor draft={draft} setDraft={setDraft} targets={targets} />
          <div className="flex items-center justify-end gap-2 mt-2">
            <button onClick={cancelDraft} className="flex items-center gap-1 text-xs px-2 py-1 rounded" style={{ background: 'var(--color-bg-tertiary)' }}>
              <X size={12} /> Cancel
            </button>
            <button onClick={saveDraft} className="flex items-center gap-1 text-xs px-2 py-1 rounded" style={{ background: 'var(--color-accent)', color: 'white' }}>
              <Check size={12} /> Save
            </button>
          </div>
        </div>
      )}

      <div className="rounded p-3 flex flex-col gap-2" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border-subtle)' }}>
        <div className="flex items-center gap-2 text-xs font-semibold" style={{ color: 'var(--color-text)' }}>
          <FlaskConical size={13} /> Test a message
        </div>
        <div className="flex gap-2">
          <input value={testMessage} onChange={e => setTestMessage(e.target.value)} placeholder="e.g. what's the news"
            className="flex-1 px-2 py-1 rounded text-xs"
            style={{ background: 'var(--color-bg-tertiary)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }} />
          <button onClick={runTest} className="text-xs px-3 py-1 rounded" style={{ background: 'var(--color-accent)', color: 'white' }}>Run</button>
        </div>
        {testResult && (
          <div className="text-xs mt-1" style={{ color: 'var(--color-text-secondary)' }}>
            {testResult.matched ? (
              <>
                <div>Matched: <strong>{testResult.rule_name}</strong> ({testResult.target_kind}:{testResult.target_id})</div>
                <div>Handled: {String(testResult.handled)} · Success: {String(testResult.success)}{testResult.fallback_to_chief && ' · would fall back to Chief'}</div>
                {testResult.error && <div style={{ color: 'var(--color-error, #f87171)' }}>Error: {testResult.error}</div>}
                {testResult.content && (
                  <div className="mt-1 p-2 rounded" style={{ background: 'var(--color-bg-tertiary)', whiteSpace: 'pre-wrap', maxHeight: 240, overflow: 'auto' }}>
                    {testResult.content}
                  </div>
                )}
              </>
            ) : (
              <em style={{ color: 'var(--color-text-tertiary)' }}>No match — Chief would handle this normally.</em>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function DraftEditor({
  draft,
  setDraft,
  targets,
}: {
  draft: ReturnType<typeof emptyRule>;
  setDraft: (d: ReturnType<typeof emptyRule>) => void;
  targets: Targets;
}) {
  const update = <K extends keyof ReturnType<typeof emptyRule>>(key: K, value: ReturnType<typeof emptyRule>[K]) =>
    setDraft({ ...draft, [key]: value });

  const updatePattern = (index: number, patch: Partial<Pattern>) => {
    const next = draft.patterns.slice();
    next[index] = { ...next[index], ...patch };
    update('patterns', next);
  };

  const addPattern = () => update('patterns', [...draft.patterns, { kind: 'phrase', value: '' }]);
  const removePattern = (index: number) => update('patterns', draft.patterns.filter((_, i) => i !== index));

  const inputStyle = {
    background: 'var(--color-bg-tertiary)',
    border: '1px solid var(--color-border)',
    color: 'var(--color-text)',
  };

  const targetOptions = targets[draft.target_kind] || [];

  return (
    <div className="grid grid-cols-2 gap-2 text-xs">
      <label className="col-span-2 flex flex-col gap-1">
        <span style={{ color: 'var(--color-text-tertiary)' }}>Name</span>
        <input value={draft.name} onChange={e => update('name', e.target.value)}
          className="px-2 py-1 rounded" style={inputStyle} />
      </label>

      <label className="flex flex-col gap-1">
        <span style={{ color: 'var(--color-text-tertiary)' }}>Target kind</span>
        <select value={draft.target_kind} onChange={e => update('target_kind', e.target.value as Rule['target_kind'])}
          className="px-2 py-1 rounded" style={inputStyle}>
          <option value="tool">tool</option>
          <option value="skill">skill</option>
          <option value="preset">preset</option>
          <option value="datasource">datasource</option>
        </select>
      </label>

      <label className="flex flex-col gap-1">
        <span style={{ color: 'var(--color-text-tertiary)' }}>Target id</span>
        <input value={draft.target_id} onChange={e => update('target_id', e.target.value)}
          list="shortcut-targets" className="px-2 py-1 rounded" style={inputStyle} />
        <datalist id="shortcut-targets">
          {targetOptions.map(t => <option key={t} value={t} />)}
        </datalist>
      </label>

      <label className="flex flex-col gap-1">
        <span style={{ color: 'var(--color-text-tertiary)' }}>Priority</span>
        <input type="number" value={draft.priority} onChange={e => update('priority', Number(e.target.value))}
          className="px-2 py-1 rounded" style={inputStyle} />
      </label>

      <label className="flex flex-col gap-1">
        <span style={{ color: 'var(--color-text-tertiary)' }}>Match mode</span>
        <select value={draft.match_mode} onChange={e => update('match_mode', e.target.value as Rule['match_mode'])}
          className="px-2 py-1 rounded" style={inputStyle}>
          <option value="contains">contains</option>
          <option value="whole_message">whole_message</option>
        </select>
      </label>

      <label className="flex items-center gap-2 col-span-2">
        <input type="checkbox" checked={draft.case_sensitive} onChange={e => update('case_sensitive', e.target.checked)} />
        <span style={{ color: 'var(--color-text-secondary)' }}>Case-sensitive matching</span>
      </label>

      <div className="col-span-2 flex flex-col gap-1">
        <span style={{ color: 'var(--color-text-tertiary)' }}>Patterns</span>
        {draft.patterns.map((p, i) => (
          <div key={i} className="flex gap-2">
            <select value={p.kind} onChange={e => updatePattern(i, { kind: e.target.value as Pattern['kind'] })}
              className="px-2 py-1 rounded" style={inputStyle}>
              <option value="phrase">phrase</option>
              <option value="regex">regex</option>
            </select>
            <input value={p.value} onChange={e => updatePattern(i, { value: e.target.value })}
              placeholder={p.kind === 'phrase' ? "e.g. what's the news" : '^news about (?P<topic>.+)$'}
              className="flex-1 px-2 py-1 rounded" style={inputStyle} />
            <button onClick={() => removePattern(i)} style={{ color: 'var(--color-error, #f87171)' }}>
              <X size={13} />
            </button>
          </div>
        ))}
        <button onClick={addPattern} className="self-start text-xs px-2 py-0.5 rounded mt-1"
          style={{ background: 'var(--color-bg-tertiary)' }}>
          + Pattern
        </button>
      </div>

      <label className="col-span-2 flex flex-col gap-1">
        <span style={{ color: 'var(--color-text-tertiary)' }}>Arg template (JSON, slots interpolated as <code>{'{slot}'}</code>)</span>
        <textarea value={JSON.stringify(draft.arg_template, null, 2)}
          onChange={e => {
            try {
              update('arg_template', JSON.parse(e.target.value || '{}'));
            } catch {
              // ignore invalid JSON while typing
            }
          }}
          rows={3} className="px-2 py-1 rounded font-mono" style={inputStyle} />
      </label>

      <label className="col-span-2 flex flex-col gap-1">
        <span style={{ color: 'var(--color-text-tertiary)' }}>Post-processor prompt (blank ⇒ tool default; empty string ⇒ passthrough)</span>
        <textarea value={draft.post_prompt ?? ''} onChange={e => update('post_prompt', e.target.value || null)}
          rows={3} className="px-2 py-1 rounded" style={inputStyle} />
      </label>

      <label className="flex flex-col gap-1">
        <span style={{ color: 'var(--color-text-tertiary)' }}>Post model (blank ⇒ global default)</span>
        <input value={draft.post_model ?? ''} onChange={e => update('post_model', e.target.value || null)}
          placeholder="engine/model" className="px-2 py-1 rounded" style={inputStyle} />
      </label>

      <label className="flex flex-col gap-1">
        <span style={{ color: 'var(--color-text-tertiary)' }}>On failure</span>
        <select value={draft.on_failure} onChange={e => update('on_failure', e.target.value as Rule['on_failure'])}
          className="px-2 py-1 rounded" style={inputStyle}>
          <option value="fallback_to_chief">fallback_to_chief</option>
          <option value="error">error</option>
          <option value="custom_message">custom_message</option>
        </select>
      </label>

      {draft.on_failure === 'custom_message' && (
        <label className="col-span-2 flex flex-col gap-1">
          <span style={{ color: 'var(--color-text-tertiary)' }}>Failure message</span>
          <input value={draft.failure_message ?? ''} onChange={e => update('failure_message', e.target.value || null)}
            className="px-2 py-1 rounded" style={inputStyle} />
        </label>
      )}
    </div>
  );
}
