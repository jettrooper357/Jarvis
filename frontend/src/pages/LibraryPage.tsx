import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Download,
  Loader2,
  MoreHorizontal,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react';
import { toast } from 'sonner';
import {
  browseRemoteSkills,
  createSkillDocument,
  createTemplateDocument,
  deleteSkillDocument,
  deleteTemplateDocument,
  fetchSkillDocument,
  fetchSkills,
  fetchTemplateDocument,
  fetchTemplates,
  installRemoteSkill,
  updateSkillDocument,
  updateTemplateDocument,
} from '../lib/api';
import type { AgentTemplate, InstalledSkill, RemoteSkill } from '../lib/api';

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
type TabId = 'skills' | 'presets' | 'tools' | 'data' | 'templates' | 'deprecated';

interface EditorState {
  kind: LibraryKind;
  mode: 'new' | 'edit';
  name: string;
  content: string;
  editable: boolean;
}

interface CatalogItem {
  key: string;
  name: string;
  source: string;
  description: string;
  editable: boolean;
  kind: LibraryKind;
}

const tabs: Array<{ id: TabId; label: string; count: number | 'dynamic' }> = [
  { id: 'skills', label: 'Skills', count: 'dynamic' },
  { id: 'presets', label: 'Presets', count: 'dynamic' },
  { id: 'tools', label: 'Tools', count: 21 },
  { id: 'data', label: 'Data Sources', count: 6 },
  { id: 'templates', label: 'Templates', count: 12 },
  { id: 'deprecated', label: 'Deprecated', count: 3 },
];

function sourceTone(source: string) {
  if (source === 'user') return { label: 'User', color: 'var(--color-accent-purple)', bg: 'var(--color-accent-purple-subtle)' };
  if (source === 'workspace') return { label: 'Workspace', color: 'var(--color-accent)', bg: 'var(--color-accent-subtle)' };
  return { label: 'Built-in', color: 'var(--color-text-secondary)', bg: 'var(--color-bg-tertiary)' };
}

function tagFor(item: CatalogItem) {
  const text = `${item.name} ${item.description}`.toLowerCase();
  if (text.includes('delegate') || text.includes('agent')) return { label: 'Requires approval', tone: 'warning' };
  if (text.includes('api') || text.includes('web')) return { label: 'Calls API', tone: 'purple' };
  if (text.includes('read') || text.includes('file')) return { label: 'Reads files', tone: 'warning' };
  return { label: 'Safe', tone: 'success' };
}

function riskLabel(item?: CatalogItem) {
  if (!item) return 'Low';
  const text = `${item.name} ${item.description}`.toLowerCase();
  if (text.includes('delete') || text.includes('write') || text.includes('script')) return 'High';
  if (text.includes('delegate') || text.includes('api') || text.includes('file')) return 'Medium';
  return 'Low';
}

export function LibraryPage() {
  const [tab, setTab] = useState<TabId>('skills');
  const [skills, setSkills] = useState<InstalledSkill[]>([]);
  const [templates, setTemplates] = useState<AgentTemplate[]>([]);
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState('');
  const [catalogFilter, setCatalogFilter] = useState('');
  const [selectedKey, setSelectedKey] = useState('');

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

  const kind: LibraryKind = tab === 'presets' ? 'preset' : 'skill';

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

  const catalogItems = useMemo<CatalogItem[]>(() => {
    if (tab === 'presets') {
      return templates.map((t) => ({
        key: t.id,
        name: t.name || t.id,
        source: t.source,
        description: t.description || '',
        editable: t.editable === true || t.source === 'user',
        kind: 'preset',
      }));
    }

    return skills.map((s) => ({
      key: s.name,
      name: s.name,
      source: s.source || 'built-in',
      description: s.description || '',
      editable: s.editable === true || s.source === 'user',
      kind: 'skill',
    }));
  }, [skills, tab, templates]);

  const filteredItems = useMemo(() => {
    const needle = catalogFilter.trim().toLowerCase();
    if (!needle) return catalogItems;
    return catalogItems.filter((item) =>
      `${item.name} ${item.description} ${item.source}`.toLowerCase().includes(needle),
    );
  }, [catalogFilter, catalogItems]);

  const selectedItem = filteredItems.find((item) => item.key === selectedKey) || filteredItems[0];

  useEffect(() => {
    if (filteredItems.length > 0 && !filteredItems.some((item) => item.key === selectedKey)) {
      setSelectedKey(filteredItems[0].key);
    }
  }, [filteredItems, selectedKey]);

  function openNew() {
    setDownloadOpen(false);
    setEditor({
      kind,
      mode: 'new',
      name: '',
      content: kind === 'skill' ? NEW_SKILL_TOML : NEW_TEMPLATE_TOML,
      editable: true,
    });
  }

  async function openEdit(itemKind: LibraryKind, name: string) {
    setDownloadOpen(false);
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
    if (!window.confirm(`Delete ${itemKind} "${name}"? This cannot be undone.`)) return;
    setBusy(true);
    try {
      if (itemKind === 'skill') await deleteSkillDocument(name);
      else await deleteTemplateDocument(name);
      toast.success(itemKind === 'skill' ? 'Skill deleted' : 'Preset deleted');
      if (editor && editor.kind === itemKind && editor.name === name) setEditor(null);
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
      if (res.skills.length === 0) toast.message('No matching skills found in that source');
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
      if (result.skipped) toast.message(`"${name}" is already installed (enable Overwrite to reinstall)`);
      else toast.success(`Installed "${name}"`);
      if (result.untranslated_tools.length > 0) {
        toast.message(`Heads up: unmapped tools - ${result.untranslated_tools.join(', ')}`);
      }
      refresh();
    } catch (err: any) {
      toast.error(err?.message || `Failed to install "${name}"`);
    } finally {
      setDlInstalling('');
    }
  }

  const risk = riskLabel(selectedItem);
  const riskUnits = risk === 'High' ? 5 : risk === 'Medium' ? 3 : 2;

  return (
    <div className="library-page flex-1 overflow-hidden px-6 py-10">
      <div className="mx-auto flex h-full max-w-[1560px] flex-col overflow-hidden">
        <header className="mb-8 flex shrink-0 items-start justify-between gap-6">
          <div>
            <h1 className="text-4xl font-bold leading-none tracking-normal" style={{ color: 'var(--color-text)' }}>
              Library
            </h1>
            <p className="mt-2 text-[15px]" style={{ color: 'var(--color-text-secondary)' }}>
              Inspect skills, presets, tools, and data sources before assigning them to autonomous agents.
            </p>
          </div>
          <div className="flex min-w-0 items-center gap-3">
            <div className="hidden h-11 w-[432px] items-center gap-2 rounded-xl px-4 lg:flex" style={{ background: 'rgba(8, 13, 20, 0.88)', border: '1px solid var(--color-border)' }}>
              <Search size={14} style={{ color: 'var(--color-text-tertiary)' }} />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search capabilities, tools, permissions..."
                className="min-w-0 flex-1 bg-transparent text-sm outline-none"
                style={{ color: 'var(--color-text)' }}
              />
            </div>
            <button onClick={openNew} disabled={busy} className="flex h-11 items-center gap-2 rounded-xl px-5 text-sm font-semibold disabled:opacity-50" style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)', border: '1px solid var(--color-accent)' }}>
              <Plus size={16} /> New {kind === 'skill' ? 'Skill' : 'Preset'}
            </button>
            {tab === 'skills' && (
              <button onClick={openDownload} className="h-11 rounded-xl px-5 text-sm" style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' }}>
                Import
              </button>
            )}
            <button onClick={refresh} disabled={busy} title="Refresh" className="grid h-11 w-14 place-items-center rounded-xl disabled:opacity-50" style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}>
              <RefreshCw size={15} />
            </button>
          </div>
        </header>

        <div className="mb-5 flex shrink-0 flex-wrap gap-2">
          {tabs.map((t) => {
            const active = tab === t.id;
            const count = t.count === 'dynamic' ? (t.id === 'skills' ? skills.length : templates.length) : t.count;
            return (
              <button
                key={t.id}
                onClick={() => {
                  if (t.id === 'skills' || t.id === 'presets') {
                    setTab(t.id);
                    setEditor(null);
                    setDownloadOpen(false);
                  }
                }}
                className="h-10 rounded-xl px-4 text-sm"
                style={{
                  background: active ? 'var(--color-accent-subtle)' : 'var(--color-bg-secondary)',
                  color: active ? 'var(--color-text)' : 'var(--color-text-secondary)',
                  border: active ? '1px solid var(--color-accent)' : '1px solid var(--color-border)',
                }}
              >
                {t.label} <span className="ml-1 text-xs">{count}</span>
              </button>
            );
          })}
        </div>

        <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 overflow-hidden xl:grid-cols-[432px_minmax(520px,1fr)_416px]">
          <section className="flex min-h-0 flex-col rounded-2xl p-5" style={{ background: 'rgba(9, 14, 22, 0.82)', border: '1px solid var(--color-border)' }}>
            <div className="mb-5">
              <h2 className="text-xl font-semibold" style={{ color: 'var(--color-text)' }}>Capability Catalog</h2>
              <p className="mt-1 text-sm" style={{ color: 'var(--color-text-secondary)' }}>Search, filter, and select reusable agent powers.</p>
            </div>
            <div className="mb-3 flex h-10 items-center gap-2 rounded-lg px-3" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
              <Search size={14} style={{ color: 'var(--color-text-tertiary)' }} />
              <input value={catalogFilter} onChange={(e) => setCatalogFilter(e.target.value)} placeholder={`Filter ${tab}...`} className="min-w-0 flex-1 bg-transparent text-sm outline-none" style={{ color: 'var(--color-text)' }} />
            </div>
            <div className="mb-4 flex gap-2 text-xs">
              {['All', 'Built-in', 'User', 'Risk'].map((label) => (
                <span key={label} className="rounded-full px-3 py-1" style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}>{label}</span>
              ))}
            </div>
            <div className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
              {filteredItems.length === 0 ? (
                <div className="rounded-xl border border-dashed p-6 text-sm" style={{ color: 'var(--color-text-tertiary)', borderColor: 'var(--color-border)' }}>
                  No matching capabilities.
                </div>
              ) : filteredItems.map((item, index) => {
                const active = selectedItem?.key === item.key;
                const source = sourceTone(item.source);
                const tag = tagFor(item);
                return (
                  <button
                    key={item.key}
                    onClick={() => setSelectedKey(item.key)}
                    className="group flex w-full items-start gap-3 rounded-xl p-4 text-left"
                    style={{
                      background: active ? 'rgba(9, 55, 63, 0.68)' : 'var(--color-bg-secondary)',
                      border: active ? '1px solid var(--color-accent)' : '1px solid var(--color-border)',
                    }}
                  >
                    <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg" style={{ color: index % 3 === 0 ? 'var(--color-accent)' : index % 3 === 1 ? 'var(--color-accent-amber)' : 'var(--color-accent-purple)', border: '1px solid color-mix(in srgb, currentColor 40%, transparent)' }}>
                      <Sparkles size={14} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span className="truncate text-[15px] font-semibold" style={{ color: 'var(--color-text)' }}>{item.name}</span>
                        <MoreHorizontal size={16} className="ml-auto shrink-0" style={{ color: 'var(--color-text-tertiary)' }} />
                      </span>
                      <span className="mt-1 block truncate text-xs" style={{ color: 'var(--color-text-secondary)' }}>{item.description || 'No description provided.'}</span>
                      <span className="mt-2 flex items-center gap-2 text-[10px]">
                        <span className="rounded-full px-2 py-0.5" style={{ background: source.bg, color: source.color }}>{source.label}</span>
                        <span className="rounded-full px-2 py-0.5" style={{ background: tag.tone === 'success' ? 'rgba(61, 220, 151, 0.12)' : tag.tone === 'warning' ? 'rgba(245, 165, 36, 0.12)' : 'var(--color-accent-purple-subtle)', color: tag.tone === 'success' ? 'var(--color-success)' : tag.tone === 'warning' ? 'var(--color-accent-amber)' : 'var(--color-accent-purple)' }}>{tag.label}</span>
                        <span className="ml-auto" style={{ color: 'var(--color-text-tertiary)' }}>Used by {index + 1}</span>
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          </section>

          <section className="min-h-0 overflow-hidden rounded-2xl p-7" style={{ background: 'rgba(9, 14, 22, 0.86)', border: '1px solid var(--color-border)' }}>
            {downloadOpen ? (
              <DownloadPanel
                dlSource={dlSource}
                setDlSource={setDlSource}
                dlUrl={dlUrl}
                setDlUrl={setDlUrl}
                dlQuery={dlQuery}
                setDlQuery={setDlQuery}
                dlWithScripts={dlWithScripts}
                setDlWithScripts={setDlWithScripts}
                dlForce={dlForce}
                setDlForce={setDlForce}
                dlResults={dlResults}
                dlSearched={dlSearched}
                dlSearching={dlSearching}
                dlInstalling={dlInstalling}
                onBrowse={handleBrowse}
                onInstall={handleInstall}
                onClose={() => setDownloadOpen(false)}
              />
            ) : editor ? (
              <EditorPanel editor={editor} busy={busy} setEditor={setEditor} onSave={handleSave} />
            ) : (
              <Inspector item={selectedItem} onEdit={openEdit} onDelete={handleDelete} busy={busy} />
            )}
          </section>

          <aside className="min-h-0 overflow-y-auto rounded-2xl p-6" style={{ background: 'rgba(9, 14, 22, 0.86)', border: '1px solid var(--color-border)' }}>
            <h2 className="text-xl font-semibold" style={{ color: 'var(--color-text)' }}>Runtime Impact</h2>
            <p className="mt-1 text-sm" style={{ color: 'var(--color-text-secondary)' }}>What changes if an agent receives this capability.</p>
            <ImpactCard title="Risk Level">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <div className="font-semibold" style={{ color: 'var(--color-text)' }}>{risk}</div>
                  <div className="mt-1 text-xs" style={{ color: 'var(--color-text-secondary)' }}>{risk === 'Medium' ? 'Delegation authority' : 'Policy controlled capability'}</div>
                </div>
                <div className="flex gap-1.5">
                  {Array.from({ length: 6 }).map((_, i) => (
                    <span key={i} className="h-6 w-4 rounded" style={{ background: i < riskUnits ? (i < 2 ? 'var(--color-success)' : 'var(--color-accent-amber)') : 'var(--color-bg-tertiary)' }} />
                  ))}
                </div>
              </div>
            </ImpactCard>
            <ImpactCard title="Assigned Agents">
              {['Chief Orchestrator', 'Workflow Manager', 'CTO / Architect'].map((agent, i) => (
                <div key={agent} className="mt-2 flex items-center gap-2 text-sm" style={{ color: 'var(--color-text)' }}>
                  <span className="h-3 w-3 rounded-full" style={{ background: i === 1 ? 'var(--color-accent-amber)' : 'var(--color-success)' }} />
                  {agent}
                </div>
              ))}
            </ImpactCard>
            <ImpactCard title="Dependencies">
              {['managed_agent_delegate', 'managed_agent_message', 'project_update_task', 'knowledge_search'].map((dep, i) => (
                <span key={dep} className="mr-2 mt-2 inline-flex rounded-full px-2 py-1 text-[11px]" style={{ color: i === 2 ? 'var(--color-accent-purple)' : 'var(--color-accent)', border: '1px solid var(--color-border)' }}>{dep}</span>
              ))}
            </ImpactCard>
            <ImpactCard title="Permissions">
              {['Can message subordinate agents', 'Can create task updates', 'Cannot write code directly', 'Approval required for destructive action'].map((perm, i) => (
                <div key={perm} className="mt-2 flex items-center gap-2 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                  <span className="h-3 w-3 rounded-full" style={{ background: i < 2 ? 'var(--color-success)' : 'var(--color-accent-amber)' }} />
                  {perm}
                </div>
              ))}
            </ImpactCard>
            <div className="mt-5 rounded-xl p-5" style={{ background: 'var(--color-accent-subtle)', border: '1px solid var(--color-accent)' }}>
              <h3 className="font-semibold" style={{ color: 'var(--color-text)' }}>Simulation</h3>
              <p className="mt-2 text-sm" style={{ color: 'var(--color-text-secondary)' }}>Preview behavior before assigning it.</p>
            </div>
            <button className="mt-3 h-11 w-full rounded-xl text-sm font-semibold" style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}>Run Dry Test</button>
          </aside>
        </div>
      </div>
    </div>
  );
}

function Inspector({ item, busy, onEdit, onDelete }: { item?: CatalogItem; busy: boolean; onEdit: (kind: LibraryKind, name: string) => void; onDelete: (kind: LibraryKind, name: string) => void }) {
  if (!item) {
    return <div className="grid h-full place-items-center text-sm" style={{ color: 'var(--color-text-tertiary)' }}>Select or create a capability.</div>;
  }

  const tag = tagFor(item);
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-5">
        <h2 className="text-xl font-semibold" style={{ color: 'var(--color-text)' }}>Capability Inspector</h2>
        <p className="mt-1 text-sm" style={{ color: 'var(--color-text-secondary)' }}>Read the purpose, inputs, outputs, dependencies, and runtime behavior.</p>
      </div>
      <div className="mb-5 rounded-2xl p-5" style={{ background: 'rgba(8, 42, 50, 0.72)', border: '1px solid var(--color-accent)' }}>
        <div className="flex items-center gap-4">
          <span className="grid h-14 w-14 place-items-center rounded-2xl text-3xl font-bold" style={{ color: 'var(--color-accent)', border: '1px solid var(--color-accent)' }}>{item.name.charAt(0).toUpperCase()}</span>
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-3xl font-bold leading-tight" style={{ color: 'var(--color-text)' }}>{item.name}</h3>
            <p className="mt-1 text-sm" style={{ color: 'var(--color-text-secondary)' }}>{item.kind === 'skill' ? 'Skill' : 'Preset'} - {sourceTone(item.source).label} - Agent Runtime</p>
          </div>
          <span className="rounded-full px-3 py-1 text-xs" style={{ color: tag.tone === 'warning' ? 'var(--color-accent-amber)' : 'var(--color-success)', border: '1px solid currentColor' }}>{tag.label}</span>
          <span className="rounded-full px-3 py-1 text-xs" style={{ color: 'var(--color-success)', border: '1px solid currentColor' }}>Active</span>
        </div>
      </div>
      <div className="mb-5 flex gap-2">
        {['Overview', 'Behavior', 'Inputs', 'Outputs', 'History'].map((label, i) => (
          <span key={label} className="rounded-xl px-5 py-2 text-sm" style={{ background: i === 0 ? 'var(--color-accent-subtle)' : 'transparent', color: i === 0 ? 'var(--color-text)' : 'var(--color-text-secondary)', border: i === 0 ? '1px solid var(--color-accent)' : '1px solid var(--color-border)' }}>{label}</span>
        ))}
      </div>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto pr-1">
        <InfoBlock accent="var(--color-accent)" title="What it does">
          {item.description || 'Provides a reusable capability that can be assigned to agents through the Capability Inspector.'}
        </InfoBlock>
        <InfoBlock accent="var(--color-success)" title="When to use it">
          Use this for task flows where an agent should consistently apply this capability under policy control.
        </InfoBlock>
        <InfoBlock accent="var(--color-accent-purple)" title="Runtime behavior">
          Emits task.updated, agent.message, tool.started, and tool.finished style events without exposing hidden reasoning.
        </InfoBlock>
        <div className="rounded-xl p-5" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
          <h4 className="font-semibold" style={{ color: 'var(--color-text)' }}>Required Inputs</h4>
          <p className="mt-3 text-sm" style={{ color: 'var(--color-text-secondary)' }}>task_id - target_agent_id - instruction - priority</p>
          <h4 className="mt-4 font-semibold" style={{ color: 'var(--color-text)' }}>Outputs</h4>
          <p className="mt-3 text-sm" style={{ color: 'var(--color-text-secondary)' }}>status - messages - blocker list - timeline update event</p>
        </div>
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <button onClick={() => onEdit(item.kind, item.key)} disabled={busy} className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm disabled:opacity-50" style={{ color: 'var(--color-text)', border: '1px solid var(--color-border)' }}><Pencil size={15} /> {item.editable ? 'Edit' : 'View'}</button>
        {item.editable && <button onClick={() => onDelete(item.kind, item.key)} disabled={busy} className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm disabled:opacity-50" style={{ color: 'var(--color-error)', border: '1px solid var(--color-border)' }}><Trash2 size={15} /> Delete</button>}
      </div>
    </div>
  );
}

function InfoBlock({ accent, title, children }: { accent: string; title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl p-5" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', borderLeft: `4px solid ${accent}` }}>
      <h4 className="font-semibold" style={{ color: 'var(--color-text)' }}>{title}</h4>
      <p className="mt-3 text-sm" style={{ color: 'var(--color-text-secondary)' }}>{children}</p>
    </div>
  );
}

function ImpactCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mt-5 rounded-xl p-5" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
      <h3 className="font-semibold" style={{ color: 'var(--color-text)' }}>{title}</h3>
      <div className="mt-2">{children}</div>
    </div>
  );
}

function EditorPanel({ editor, busy, setEditor, onSave }: { editor: EditorState; busy: boolean; setEditor: React.Dispatch<React.SetStateAction<EditorState | null>>; onSave: () => void }) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold" style={{ color: 'var(--color-text)' }}>{editor.mode === 'new' ? `New ${editor.kind}` : `${editor.editable ? 'Edit' : 'View'} ${editor.name}`}</h2>
          <p className="mt-1 text-sm" style={{ color: 'var(--color-text-secondary)' }}>{editor.editable ? 'Edit TOML and save it back to the local library.' : 'Built-in and workspace capabilities are read-only.'}</p>
        </div>
        <button onClick={() => setEditor(null)} className="grid h-9 w-9 place-items-center rounded-lg" style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}><X size={16} /></button>
      </div>
      <textarea
        value={editor.content}
        onChange={(e) => setEditor((cur) => (cur ? { ...cur, content: e.target.value } : cur))}
        readOnly={!editor.editable}
        spellCheck={false}
        className="min-h-0 flex-1 resize-none rounded-xl p-4 font-mono text-xs outline-none"
        style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
      />
      <div className="mt-4 flex justify-end gap-2">
        <button onClick={() => setEditor(null)} className="rounded-lg px-4 py-2 text-sm" style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}>Close</button>
        {editor.editable && <button onClick={onSave} disabled={busy} className="rounded-lg px-4 py-2 text-sm font-semibold disabled:opacity-50" style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}>{busy ? 'Saving...' : 'Save'}</button>}
      </div>
    </div>
  );
}

function DownloadPanel(props: {
  dlSource: SkillSource;
  setDlSource: (source: SkillSource) => void;
  dlUrl: string;
  setDlUrl: (url: string) => void;
  dlQuery: string;
  setDlQuery: (query: string) => void;
  dlWithScripts: boolean;
  setDlWithScripts: (value: boolean) => void;
  dlForce: boolean;
  setDlForce: (value: boolean) => void;
  dlResults: RemoteSkill[];
  dlSearched: boolean;
  dlSearching: boolean;
  dlInstalling: string;
  onBrowse: () => void;
  onInstall: (name: string) => void;
  onClose: () => void;
}) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold" style={{ color: 'var(--color-text)' }}>Import Skills</h2>
          <p className="mt-1 text-sm" style={{ color: 'var(--color-text-secondary)' }}>Browse remote skill sources and install them into the local library.</p>
        </div>
        <button onClick={props.onClose} className="grid h-9 w-9 place-items-center rounded-lg" style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}><X size={16} /></button>
      </div>
      <div className="mb-3 grid gap-3 md:grid-cols-2">
        <select value={props.dlSource} onChange={(e) => props.setDlSource(e.target.value as SkillSource)} className="rounded-lg px-3 py-2 text-sm outline-none" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
          {(['hermes', 'openclaw', 'github'] as SkillSource[]).map((s) => <option key={s} value={s}>{SOURCE_LABELS[s]}</option>)}
        </select>
        {props.dlSource === 'github' && <input value={props.dlUrl} onChange={(e) => props.setDlUrl(e.target.value)} placeholder="https://github.com/user/repo" className="rounded-lg px-3 py-2 text-sm outline-none" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }} />}
      </div>
      <div className="mb-3 flex gap-2">
        <input value={props.dlQuery} onChange={(e) => props.setDlQuery(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') props.onBrowse(); }} placeholder="Filter by name or description" className="min-w-0 flex-1 rounded-lg px-3 py-2 text-sm outline-none" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }} />
        <button onClick={props.onBrowse} disabled={props.dlSearching} className="flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold disabled:opacity-50" style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}>{props.dlSearching ? <Loader2 size={15} className="animate-spin" /> : <Search size={15} />} Browse</button>
      </div>
      <div className="mb-3 flex flex-wrap gap-4 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
        <label className="flex items-center gap-2"><input type="checkbox" checked={props.dlWithScripts} onChange={(e) => props.setDlWithScripts(e.target.checked)} /> Include scripts/</label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={props.dlForce} onChange={(e) => props.setDlForce(e.target.checked)} /> Overwrite installed</label>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto rounded-xl p-3" style={{ border: '1px solid var(--color-border)' }}>
        {props.dlSearching ? (
          <div className="grid h-full place-items-center text-sm" style={{ color: 'var(--color-text-secondary)' }}><Loader2 size={30} className="animate-spin" /></div>
        ) : props.dlResults.length === 0 ? (
          <div className="p-4 text-sm" style={{ color: 'var(--color-text-secondary)' }}>{props.dlSearched ? 'No matching skills found.' : 'Choose a source and browse installable skills.'}</div>
        ) : props.dlResults.map((r) => {
          const id = r.category ? `${r.category}/${r.name}` : r.name;
          const installing = props.dlInstalling === id || props.dlInstalling === r.name;
          return (
            <div key={`${r.source}-${id}`} className="flex items-start justify-between gap-3 rounded-xl p-4" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
              <div className="min-w-0">
                <div className="truncate font-semibold" style={{ color: 'var(--color-text)' }}>{r.name}</div>
                <div className="mt-1 truncate text-xs" style={{ color: 'var(--color-text-secondary)' }}>{r.category ? `${r.category} - ` : ''}{r.description || 'No description'}</div>
              </div>
              <button onClick={() => props.onInstall(id)} disabled={!!props.dlInstalling} className="flex shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-sm disabled:opacity-50" style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}>{installing ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />} Install</button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
