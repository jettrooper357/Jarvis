import { useCallback, useEffect, useState } from 'react';
import { Plus, Pencil, Trash2, RefreshCw, Download, Search } from 'lucide-react';
import { toast } from 'sonner';
import {
  fetchSkills,
  fetchSkillDocument,
  createSkillDocument,
  updateSkillDocument,
  deleteSkillDocument,
  fetchTemplates,
  fetchTemplateDocument,
  createTemplateDocument,
  updateTemplateDocument,
  deleteTemplateDocument,
  browseRemoteSkills,
  installRemoteSkill,
} from '../lib/api';
import type { InstalledSkill, AgentTemplate, RemoteSkill } from '../lib/api';

type SkillSource = 'hermes' | 'openclaw' | 'github';

const SOURCE_LABELS: Record<SkillSource, string> = {
  hermes: 'Hermes Agent (~150 skills)',
  openclaw: 'OpenClaw (~13,700 community skills)',
  github: 'GitHub repository',
};

const NEW_TEMPLATE_TOML = `[template]
id = "my-preset"
name = "My Preset"
description = "Describe what this preset configures"
agent_type = "monitor_operative"
tools = []
skills = []
`;

const NEW_SKILL_TOML = `[skill]
name = "my-skill"
description = "Describe what this skill does"
version = "0.1.0"
author = "openjarvis-user"
`;

type LibraryKind = 'skill' | 'preset';

interface EditorState {
  kind: LibraryKind;
  mode: 'new' | 'edit';
  /** Skill name or template id being edited; '' for new. */
  name: string;
  content: string;
  editable: boolean;
}

export function LibraryPage() {
  const [tab, setTab] = useState<'skills' | 'presets'>('skills');
  const [skills, setSkills] = useState<InstalledSkill[]>([]);
  const [templates, setTemplates] = useState<AgentTemplate[]>([]);
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [busy, setBusy] = useState(false);

  // Remote skill download panel
  const [downloadOpen, setDownloadOpen] = useState(false);
  const [dlSource, setDlSource] = useState<SkillSource>('hermes');
  const [dlUrl, setDlUrl] = useState('');
  const [dlQuery, setDlQuery] = useState('');
  const [dlWithScripts, setDlWithScripts] = useState(false);
  const [dlForce, setDlForce] = useState(false);
  const [dlResults, setDlResults] = useState<RemoteSkill[]>([]);
  const [dlSearched, setDlSearched] = useState(false);
  const [dlSearching, setDlSearching] = useState(false);
  const [dlInstalling, setDlInstalling] = useState('');

  const kind: LibraryKind = tab === 'skills' ? 'skill' : 'preset';

  const refresh = useCallback(() => {
    fetchSkills()
      .then(setSkills)
      .catch(() => setSkills([]));
    fetchTemplates()
      .then(setTemplates)
      .catch(() => setTemplates([]));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  function openNew() {
    setEditor({
      kind,
      mode: 'new',
      name: '',
      content: kind === 'skill' ? NEW_SKILL_TOML : NEW_TEMPLATE_TOML,
      editable: true,
    });
  }

  async function openEdit(itemKind: LibraryKind, name: string) {
    setBusy(true);
    try {
      const doc =
        itemKind === 'skill'
          ? await fetchSkillDocument(name)
          : await fetchTemplateDocument(name);
      setEditor({
        kind: itemKind,
        mode: 'edit',
        name,
        content: doc.content,
        editable: doc.editable === true || doc.source === 'user',
      });
    } catch (err: any) {
      toast.error(err?.message || 'Failed to load document');
    } finally {
      setBusy(false);
    }
  }

  async function handleSave() {
    if (!editor) return;
    setBusy(true);
    try {
      if (editor.kind === 'skill') {
        if (editor.mode === 'new') await createSkillDocument(editor.content);
        else await updateSkillDocument(editor.name, editor.content);
      } else if (editor.mode === 'new') {
        await createTemplateDocument(editor.content);
      } else {
        await updateTemplateDocument(editor.name, editor.content);
      }
      toast.success(editor.kind === 'skill' ? 'Skill saved' : 'Preset saved');
      setEditor(null);
      refresh();
    } catch (err: any) {
      toast.error(err?.message || 'Failed to save');
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete(itemKind: LibraryKind, name: string) {
    if (!window.confirm(`Delete ${itemKind} "${name}"? This cannot be undone.`)) {
      return;
    }
    setBusy(true);
    try {
      if (itemKind === 'skill') await deleteSkillDocument(name);
      else await deleteTemplateDocument(name);
      toast.success(itemKind === 'skill' ? 'Skill deleted' : 'Preset deleted');
      if (editor && editor.kind === itemKind && editor.name === name) {
        setEditor(null);
      }
      refresh();
    } catch (err: any) {
      toast.error(err?.message || 'Failed to delete');
    } finally {
      setBusy(false);
    }
  }

  function openDownload() {
    setEditor(null);
    setDownloadOpen(true);
  }

  async function handleBrowse() {
    if (dlSource === 'github' && !dlUrl.trim()) {
      toast.error('A GitHub repository URL is required');
      return;
    }
    setDlSearching(true);
    setDlSearched(false);
    try {
      const res = await browseRemoteSkills({
        source: dlSource,
        query: dlQuery.trim(),
        url: dlUrl.trim(),
      });
      setDlResults(res.skills);
      setDlSearched(true);
      if (res.skills.length === 0) {
        toast.message('No matching skills found in that source');
      }
    } catch (err: any) {
      toast.error(err?.message || 'Failed to browse source');
    } finally {
      setDlSearching(false);
    }
  }

  async function handleInstall(name: string) {
    setDlInstalling(name);
    try {
      const result = await installRemoteSkill({
        source: dlSource,
        name,
        url: dlUrl.trim(),
        with_scripts: dlWithScripts,
        force: dlForce,
      });
      if (result.skipped) {
        toast.message(`"${name}" is already installed (enable Overwrite to reinstall)`);
      } else {
        toast.success(`Installed "${name}"`);
      }
      if (result.untranslated_tools.length > 0) {
        toast.message(
          `Heads up: unmapped tools — ${result.untranslated_tools.join(', ')}`,
        );
      }
      refresh();
    } catch (err: any) {
      toast.error(err?.message || `Failed to install "${name}"`);
    } finally {
      setDlInstalling('');
    }
  }

  const items =
    tab === 'skills'
      ? skills.map((s) => ({
          key: s.name,
          name: s.name,
          source: s.source || 'built-in',
          description: s.description || '',
          editable: s.editable === true || s.source === 'user',
        }))
      : templates.map((t) => ({
          key: t.id,
          name: t.name || t.id,
          source: t.source,
          description: t.description || '',
          editable: t.editable === true || t.source === 'user',
        }));

  return (
    <div className="flex-1 flex flex-col overflow-hidden px-6 py-10">
      <div className="max-w-5xl mx-auto w-full flex flex-col flex-1 overflow-hidden">
        <header className="mb-6 shrink-0">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h1
                className="text-lg font-semibold"
                style={{ color: 'var(--color-text)' }}
              >
                Library
              </h1>
              <p
                className="text-sm mt-1"
                style={{ color: 'var(--color-text-tertiary)' }}
              >
                Load, edit, or delete skill and preset definitions. Built-in items are
                read-only. Assign them to individual agents from the Capability
                Inspector.
              </p>
            </div>
            <button
              onClick={refresh}
              disabled={busy}
              title="Refresh"
              className="p-2 rounded-lg cursor-pointer disabled:opacity-50 shrink-0"
              style={{
                background: 'var(--color-bg-secondary)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text-secondary)',
              }}
            >
              <RefreshCw size={16} />
            </button>
          </div>
        </header>

        <div className="flex gap-1 mb-3 shrink-0">
          {(['skills', 'presets'] as const).map((t) => (
            <button
              key={t}
              onClick={() => {
                setTab(t);
                setEditor(null);
              }}
              className="px-4 py-1.5 rounded-lg text-sm cursor-pointer"
              style={{
                background:
                  tab === t ? 'var(--color-accent-subtle)' : 'transparent',
                color:
                  tab === t ? 'var(--color-text)' : 'var(--color-text-secondary)',
                border:
                  tab === t
                    ? '1px solid var(--color-border)'
                    : '1px solid transparent',
                fontWeight: tab === t ? 500 : 400,
              }}
            >
              {t === 'skills' ? 'Skills' : 'Presets'}
            </button>
          ))}
        </div>

        <div className="flex-1 grid grid-cols-3 gap-4 overflow-hidden">
          {/* List column */}
          <div className="col-span-1 flex flex-col overflow-hidden">
            <div className="mb-2 flex items-center gap-1.5">
              <button
                onClick={openNew}
                disabled={busy}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs cursor-pointer disabled:opacity-50"
                style={{
                  background: 'var(--color-accent)',
                  color: 'var(--color-on-accent)',
                }}
              >
                <Plus size={14} /> New {kind}
              </button>
              {tab === 'skills' && (
                <button
                  onClick={openDownload}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs cursor-pointer"
                  style={{
                    background: downloadOpen
                      ? 'var(--color-accent-subtle)'
                      : 'var(--color-bg-secondary)',
                    border: '1px solid var(--color-border)',
                    color: 'var(--color-text-secondary)',
                  }}
                >
                  <Download size={14} /> Download
                </button>
              )}
            </div>
            <div className="flex-1 overflow-y-auto space-y-1.5 pr-1">
              {items.length === 0 ? (
                <div
                  className="text-sm"
                  style={{ color: 'var(--color-text-tertiary)' }}
                >
                  None yet — create one to make it assignable.
                </div>
              ) : (
                items.map((it) => {
                  const active =
                    editor &&
                    editor.kind === kind &&
                    editor.mode === 'edit' &&
                    editor.name === it.key;
                  return (
                    <div
                      key={it.key}
                      className="p-2 rounded-lg flex items-start justify-between gap-2"
                      style={{
                        background: active
                          ? 'var(--color-accent-subtle)'
                          : 'var(--color-bg-secondary)',
                        border: '1px solid var(--color-border)',
                      }}
                    >
                      <div className="min-w-0">
                        <div
                          className="text-sm truncate"
                          style={{ color: 'var(--color-text)' }}
                        >
                          {it.name}
                        </div>
                        <div
                          className="text-xs truncate"
                          style={{ color: 'var(--color-text-tertiary)' }}
                        >
                          {it.source}
                          {it.description ? ` • ${it.description}` : ''}
                        </div>
                      </div>
                      <div className="flex items-center gap-1 shrink-0">
                        <button
                          onClick={() => openEdit(kind, it.key)}
                          disabled={busy}
                          title={it.editable ? 'Edit' : 'View (read-only)'}
                          className="p-1 rounded cursor-pointer disabled:opacity-50"
                          style={{ color: 'var(--color-text-secondary)' }}
                        >
                          <Pencil size={14} />
                        </button>
                        {it.editable && (
                          <button
                            onClick={() => handleDelete(kind, it.key)}
                            disabled={busy}
                            title="Delete"
                            className="p-1 rounded cursor-pointer disabled:opacity-50"
                            style={{ color: 'var(--color-error)' }}
                          >
                            <Trash2 size={14} />
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>

          {/* Editor / download column */}
          <div className="col-span-2 flex flex-col overflow-hidden">
            {downloadOpen ? (
              <div className="flex flex-col overflow-hidden h-full">
                <div className="flex items-center justify-between mb-2">
                  <div
                    className="text-sm font-medium"
                    style={{ color: 'var(--color-text)' }}
                  >
                    Download skills
                  </div>
                  <button
                    onClick={() => setDownloadOpen(false)}
                    className="px-2 py-1 rounded-lg text-xs cursor-pointer"
                    style={{
                      background: 'var(--color-bg-secondary)',
                      border: '1px solid var(--color-border)',
                      color: 'var(--color-text-secondary)',
                    }}
                  >
                    Close
                  </button>
                </div>

                <div className="grid grid-cols-2 gap-2 mb-2">
                  <label className="text-xs">
                    <span
                      className="block mb-1"
                      style={{ color: 'var(--color-text-tertiary)' }}
                    >
                      Source
                    </span>
                    <select
                      value={dlSource}
                      onChange={(e) => {
                        setDlSource(e.target.value as SkillSource);
                        setDlResults([]);
                        setDlSearched(false);
                      }}
                      className="w-full px-2 py-1.5 rounded-lg text-xs"
                      style={{
                        background: 'var(--color-bg-secondary)',
                        border: '1px solid var(--color-border)',
                        color: 'var(--color-text)',
                      }}
                    >
                      {(['hermes', 'openclaw', 'github'] as SkillSource[]).map(
                        (s) => (
                          <option key={s} value={s}>
                            {SOURCE_LABELS[s]}
                          </option>
                        ),
                      )}
                    </select>
                  </label>
                  {dlSource === 'github' && (
                    <label className="text-xs">
                      <span
                        className="block mb-1"
                        style={{ color: 'var(--color-text-tertiary)' }}
                      >
                        Repository URL
                      </span>
                      <input
                        value={dlUrl}
                        onChange={(e) => setDlUrl(e.target.value)}
                        placeholder="https://github.com/user/repo"
                        className="w-full px-2 py-1.5 rounded-lg text-xs"
                        style={{
                          background: 'var(--color-bg-secondary)',
                          border: '1px solid var(--color-border)',
                          color: 'var(--color-text)',
                        }}
                      />
                    </label>
                  )}
                </div>

                <div className="flex items-center gap-2 mb-2">
                  <input
                    value={dlQuery}
                    onChange={(e) => setDlQuery(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleBrowse();
                    }}
                    placeholder="Filter by name / description (blank = list all)"
                    className="flex-1 px-2 py-1.5 rounded-lg text-xs"
                    style={{
                      background: 'var(--color-bg-secondary)',
                      border: '1px solid var(--color-border)',
                      color: 'var(--color-text)',
                    }}
                  />
                  <button
                    onClick={handleBrowse}
                    disabled={dlSearching}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs cursor-pointer disabled:opacity-50"
                    style={{
                      background: 'var(--color-accent)',
                      color: 'var(--color-on-accent)',
                    }}
                  >
                    <Search size={14} />
                    {dlSearching ? 'Syncing…' : 'Browse'}
                  </button>
                </div>

                <div
                  className="flex items-center gap-4 mb-2 text-xs"
                  style={{ color: 'var(--color-text-secondary)' }}
                >
                  <label className="flex items-center gap-1.5 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={dlWithScripts}
                      onChange={(e) => setDlWithScripts(e.target.checked)}
                    />
                    Include scripts/ (security-sensitive)
                  </label>
                  <label className="flex items-center gap-1.5 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={dlForce}
                      onChange={(e) => setDlForce(e.target.checked)}
                    />
                    Overwrite if installed
                  </label>
                </div>

                <div
                  className="flex-1 overflow-y-auto rounded-lg p-2 space-y-1.5"
                  style={{ border: '1px solid var(--color-border)' }}
                >
                  {dlSearching ? (
                    <div
                      className="text-xs p-2"
                      style={{ color: 'var(--color-text-tertiary)' }}
                    >
                      Syncing source… the first fetch clones the repository and can
                      take a while.
                    </div>
                  ) : dlResults.length === 0 ? (
                    <div
                      className="text-xs p-2"
                      style={{ color: 'var(--color-text-tertiary)' }}
                    >
                      {dlSearched
                        ? 'No matching skills found.'
                        : 'Choose a source and Browse to list installable skills.'}
                    </div>
                  ) : (
                    dlResults.map((r) => {
                      const id = r.category ? `${r.category}/${r.name}` : r.name;
                      const installingThis =
                        dlInstalling === id || dlInstalling === r.name;
                      return (
                        <div
                          key={`${r.source}-${id}`}
                          className="p-2 rounded-lg flex items-start justify-between gap-2"
                          style={{
                            background: 'var(--color-bg-secondary)',
                            border: '1px solid var(--color-border)',
                          }}
                        >
                          <div className="min-w-0">
                            <div
                              className="text-sm truncate"
                              style={{ color: 'var(--color-text)' }}
                            >
                              {r.name}
                            </div>
                            <div
                              className="text-xs truncate"
                              style={{ color: 'var(--color-text-tertiary)' }}
                            >
                              {r.category ? `${r.category} • ` : ''}
                              {r.description || 'No description'}
                            </div>
                          </div>
                          <button
                            onClick={() => handleInstall(id)}
                            disabled={!!dlInstalling}
                            className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs cursor-pointer disabled:opacity-50 shrink-0"
                            style={{
                              background: 'var(--color-accent)',
                              color: 'var(--color-on-accent)',
                            }}
                          >
                            <Download size={13} />
                            {installingThis ? 'Installing…' : 'Install'}
                          </button>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            ) : editor ? (
              <>
                <div
                  className="text-xs mb-2"
                  style={{ color: 'var(--color-text-tertiary)' }}
                >
                  {editor.mode === 'new'
                    ? `New ${editor.kind} — paste or edit TOML, then Save`
                    : `${editor.editable ? 'Editing' : 'Viewing'} ${editor.kind}: ${editor.name}`}
                  {!editor.editable && ' — read-only (built-in/workspace)'}
                </div>
                <textarea
                  value={editor.content}
                  onChange={(e) =>
                    setEditor((cur) =>
                      cur ? { ...cur, content: e.target.value } : cur,
                    )
                  }
                  readOnly={!editor.editable}
                  spellCheck={false}
                  className="flex-1 w-full rounded-lg p-3 text-xs font-mono resize-none"
                  style={{
                    background: 'var(--color-bg-secondary)',
                    border: '1px solid var(--color-border)',
                    color: 'var(--color-text)',
                  }}
                />
                <div className="flex justify-end gap-2 mt-2">
                  <button
                    onClick={() => setEditor(null)}
                    className="px-3 py-1.5 rounded-lg text-xs cursor-pointer"
                    style={{
                      background: 'var(--color-bg-secondary)',
                      border: '1px solid var(--color-border)',
                      color: 'var(--color-text-secondary)',
                    }}
                  >
                    Close
                  </button>
                  {editor.editable && (
                    <button
                      onClick={handleSave}
                      disabled={busy}
                      className="px-3 py-1.5 rounded-lg text-xs cursor-pointer disabled:opacity-50"
                      style={{
                        background: 'var(--color-accent)',
                        color: 'var(--color-on-accent)',
                      }}
                    >
                      {busy ? 'Saving...' : 'Save'}
                    </button>
                  )}
                </div>
              </>
            ) : (
              <div
                className="flex-1 flex items-center justify-center text-sm text-center px-6 rounded-lg"
                style={{
                  color: 'var(--color-text-tertiary)',
                  border: '1px dashed var(--color-border)',
                }}
              >
                Select a {kind} to edit, or create a new one. Changes here update the
                choices available in every agent&apos;s Capability Inspector.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
