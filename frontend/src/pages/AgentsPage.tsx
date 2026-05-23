import { useEffect, useState, useCallback, useMemo, useRef } from 'react';
import type { CSSProperties } from 'react';
import { useNavigate } from 'react-router';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { toast } from 'sonner';
import { useAppStore } from '../lib/store';
import {
  fetchManagedAgents,
  fetchAgentTasks,
  updateAgentTask,
  deleteAgentTask,
  fetchMissionControl,
  fetchAgentChannels,
  bindAgentChannel,
  unbindAgentChannel,
  fetchAgentMessages,
  fetchTemplates,
  createManagedAgent,
  pauseManagedAgent,
  resumeManagedAgent,
  deleteManagedAgent,
  runManagedAgent,
  recoverManagedAgent,
  sendAgentMessage,
  fetchLearningLog,
  triggerLearning,
  fetchAgentTraces,
  fetchManagedAgent,
  fetchAvailableTools,
  fetchSkills,
  saveToolCredentials,
  fetchModels,
  updateManagedAgent,
  fetchRecommendedModel,
  sendblueVerify,
  sendblueRegisterWebhook,
  sendblueTest,
  sendblueHealth,
  fetchChiefPending,
  resumeChief,
  fetchTraceTree,
  previewAgentCapabilities,
  fetchAgentConfigVersions,
  revertAgentConfig,
  sendChiefMessage,
  uploadAgentAvatar,
  deleteAgentAvatar,
} from '../lib/api';
import type { AgentConfigVersion } from '../lib/api';
import { useChiefHealth } from '../hooks/useChiefHealth';
import type { TraceTreeNode } from '../lib/api';
import type { AgentTask, ChannelBinding, AgentTemplate, AgentMessage, ManagedAgent, LearningLogEntry, AgentTrace, ToolInfo, InstalledSkill, MissionControlData, MissionControlProject, MissionControlTask } from '../lib/api';
import { AgentAvatar } from '../components/AgentAvatar';
import { PendingApprovalsList } from '../components/PendingApprovalsList';
import { useAgentEvents, type AgentEvent } from '../lib/useAgentEvents';
import {
  Plus,
  Bot,
  Crown,
  Pause,
  Play,
  Trash2,
  ChevronLeft,
  ListTodo,
  Brain,
  Zap,
  MoreHorizontal,
  AlertTriangle,
  DollarSign,
  Activity,
  MessageSquare,
  Settings,
  FileText,
  X,
  ChevronRight,
  Send,
  RefreshCw,
  Wifi,
  Database,
  Copy,
  Check,
  Pencil,
  Maximize2,
  Search,
  SlidersHorizontal,
  PackageCheck,
  ShieldCheck,
  Network,
  Boxes,
  Eye,
  Upload,
} from 'lucide-react';
import { SOURCE_CATALOG } from '../types/connectors';
import type { ConnectRequest } from '../types/connectors';
import { listConnectors, connectSource } from '../lib/connectors-api';
import type { ToolCallInfo } from '../types';
import { ToolCallCard } from '../components/Chat/ToolCallCard';

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------

type AgentStatus =
  | 'idle'
  | 'running'
  | 'paused'
  | 'error'
  | 'archived'
  | 'needs_attention'
  | 'budget_exceeded'
  | 'stalled'
  | 'input_required'
  | 'auth_required'
  | 'waiting_on_tool';

const STATUS_COLOR: Record<AgentStatus, string> = {
  idle: 'var(--color-success)',
  running: 'var(--color-accent)',
  paused: 'var(--color-text-tertiary)',
  error: 'var(--color-error)',
  archived: 'var(--color-text-tertiary)',
  needs_attention: 'var(--color-warning)',
  budget_exceeded: 'var(--color-warning)',
  stalled: 'var(--color-warning)',
  input_required: 'var(--color-accent)',
  auth_required: 'var(--color-warning)',
  waiting_on_tool: 'var(--color-accent)',
};

function statusColor(s: string): string {
  return STATUS_COLOR[s as AgentStatus] || 'var(--color-text-tertiary)';
}

// Tick lifecycle events used to tell which agents are actively working.
const AGENT_ACTIVITY_EVENTS = [
  'agent_tick_start',
  'agent_tick_end',
  'agent_tick_error',
  'agent_message_received',
] as const;

/**
 * Style for an org-chart reporting line. When `active` is true the connector
 * shows a pulse of accent colour travelling along it — signalling that the
 * agents it joins are currently working / talking to each other. Otherwise
 * it renders as the standard static border line.
 */
function connectorStyle(active: boolean, orientation: 'vertical' | 'horizontal' = 'vertical'): CSSProperties {
  if (!active) return { background: 'var(--color-border)' };
  const isHorizontal = orientation === 'horizontal';
  return {
    backgroundImage:
      isHorizontal
        ? 'linear-gradient(90deg, transparent 0%, var(--color-accent) 50%, transparent 100%)'
        : 'linear-gradient(180deg, transparent 0%, var(--color-accent) 50%, transparent 100%)',
    backgroundSize: isHorizontal ? '200% 100%' : '100% 200%',
    animation: `${isHorizontal ? 'pulse-travel' : 'pulse-travel-y'} 1.1s linear infinite`,
    boxShadow: '0 0 10px color-mix(in srgb, var(--color-accent) 45%, transparent)',
  };
}

function StatusBadge({ status }: { status: string }) {
  const color = statusColor(status);
  return (
    <span
      className="px-2 py-0.5 rounded-full text-xs font-medium"
      style={{ background: color + '20', color }}
    >
      {status.replace('_', ' ')}
    </span>
  );
}

function StatusDot({ status }: { status: string }) {
  const color = statusColor(status);
  return (
    <span
      className="w-2 h-2 rounded-full inline-block flex-shrink-0"
      style={{ background: color }}
      title={status}
    />
  );
}

function formatCost(cost?: number): string {
  if (cost === undefined || cost === null) return '—';
  return `$${cost.toFixed(4)}`;
}

function formatRelativeTime(ts?: number | null): string {
  if (!ts) return 'Never';
  const diff = Date.now() - ts * 1000;
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'Just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function formatSchedule(type?: string, value?: string): string {
  if (!type || type === 'manual') return 'Manual';
  if (type === 'cron' && value) {
    // Try to display human-readable for common cron patterns
    const parts = value.trim().split(/\s+/);
    if (parts.length === 5) {
      const [min, hour, , , dow] = parts;
      const hourNum = parseInt(hour, 10);
      const formatHour = (h: number) => {
        if (h === 0) return '12:00 AM';
        if (h < 12) return `${h}:00 AM`;
        if (h === 12) return '12:00 PM';
        return `${h - 12}:00 PM`;
      };
      // Daily pattern: 0 H * * *
      if (min === '0' && !isNaN(hourNum) && parts[2] === '*' && parts[3] === '*' && dow === '*') {
        return `Daily at ${formatHour(hourNum)}`;
      }
      // Weekly pattern: 0 H * * days
      if (min === '0' && !isNaN(hourNum) && parts[2] === '*' && parts[3] === '*' && dow !== '*') {
        const DAY_NAMES: Record<string, string> = { '1': 'Mon', '2': 'Tue', '3': 'Wed', '4': 'Thu', '5': 'Fri', '6': 'Sat', '7': 'Sun' };
        const dayList = dow.split(',').map(d => DAY_NAMES[d] || d).join(', ');
        return `Weekly on ${dayList} at ${formatHour(hourNum)}`;
      }
    }
    return `Cron: ${value}`;
  }
  if (type === 'cron') return 'Cron';
  if (type === 'interval' && value) {
    const total = parseInt(value);
    if (!isNaN(total) && total > 0) {
      const h = Math.floor(total / 3600);
      const m = Math.floor((total % 3600) / 60);
      const s = total % 60;
      const parts: string[] = [];
      if (h > 0) parts.push(`${h}h`);
      if (m > 0) parts.push(`${m}m`);
      if (s > 0) parts.push(`${s}s`);
      return `Every ${parts.join(' ') || '0s'}`;
    }
    return `Every ${value}`;
  }
  return type || 'Manual';
}

const ORG_ROLE_PRESETS = [
  'Chief Orchestrator',
  'Business Analyst',
  'Chief Executive Officer (CEO)',
  'Chief of Staff',
  'Chief Financial Officer (CFO)',
  'Chief Technology Officer (CTO)',
  'Chief Operating Officer (COO)',
  'Operations Monitor',
  'Documentation Agent',
  'Workflow Manager',
  'Vice President of Engineering',
  'Engineering Manager',
  'Project Manager',
  'SQL Engineer',
  'PowerShell Engineer',
  'Integration Engineer',
  'Front-End Engineer',
  'Legacy Systems Engineer',
  'QA/Test Engineer',
  'Research Lead',
  'Senior Developer',
  'Developer',
  'Employee',
];

const ROLE_INSTRUCTION_PRESETS: Record<string, string> = {
  'Chief Orchestrator': `You are the Chief Orchestrator.

Use your own capabilities first:
- You have connected data sources, skills, and presets. Use them to answer directly.
- Query your knowledge with knowledge_search (it covers your connected data sources — News/RSS, Hacker News, email, calendar, drive, etc.) and run any skill/preset configured for you.
- Never claim you "do not have access" to news, current events, or any topic without first checking knowledge_search. If a data source or skill is configured for you, you have access — use it and return the result.
- Delegation and project creation are last resorts, not the default.

Your job:
- Receive user requests and classify the work.
- Answer directly from your own data sources, skills, and presets whenever they can satisfy the request.
- Route to other agents only when the work genuinely needs them.
- Prevent duplicated effort and unnecessary delegation.
- Review the final output before it goes back to the user.

How to operate:
- For explicit "create/start/set up a project" requests, create the project record first. Do not ask the user for an agent name.
- Create project tasks/subtasks before delegating execution so assigned work has a project_task_id.
- Use the agent directory to identify agents by role and route to the best owner.
- Use the Business Analyst when the request is vague, incomplete, or business-heavy.
- Use the CTO when architecture, technical risk, tooling, or technical sequencing decisions are needed.
- Use the Workflow Manager to break approved work into tracked tasks and stages.
- Use specialist agents for execution, QA, monitoring, and documentation.
- If the user asks about subordinate progress, inspect recent messages and task state before answering.
- Return one coherent final answer to the user instead of exposing raw internal coordination.

Service model:
- Treat requests as services with a primary owner, supporting agents, expected outputs, and escalation rules.
- Prefer structured routing over ad hoc delegation.`,
  'Business Analyst': `You are the Business Analyst.

Your job:
- Turn vague user requests into clear requirements.
- Identify business rules, assumptions, success criteria, and missing inputs.
- Produce a problem statement, required inputs, expected outputs, risks, and open questions.

How to operate:
- Ask only the clarifying questions required to reduce ambiguity.
- Convert messy requests into structured requirements another agent can execute.
- Escalate to the CTO when the request becomes a technical design problem.
- Hand execution planning to the Workflow Manager once the request is clear.`,
  'Chief Technology Officer (CTO)': `You are the CTO / Architect.

Your job:
- Own architecture decisions, technical strategy, system design, tooling choices, and technical risk review.
- Decide engineering priorities and when work should move to specialist technical agents.

How to operate:
- Produce architecture recommendations, technical constraints, sequencing guidance, and risk assessments.
- Do not take over every implementation detail yourself.
- Use specialist engineering agents for execution work and QA for validation.
- Involve the Workflow Manager when technical work spans multiple tasks or dependencies.`,
  'Workflow Manager': `You are the Workflow Manager.

Your job:
- Break requests into tracked work, assign ownership, and control movement through stages.
- Maintain dependencies, status, summaries, and stakeholder-facing progress updates.

Stages:
- Intake
- Planning
- Development
- Testing
- Deployment
- Documentation
- Review
- Closed

How to operate:
- Convert approved work into tasks with owners, priorities, dependencies, and stage transitions.
- Keep task status current and surface blockers early.
- Coordinate with Documentation Agent for summaries and with QA/Test Engineer before closure.`,
  'Project Manager': `You are the Project Manager acting as a workflow manager.

Your job:
- Break requests into tasks, assign owners, track dependencies, and move work through clear stages.
- Produce concise progress summaries and surface blockers early.

Stages:
- Intake
- Planning
- Development
- Testing
- Deployment
- Documentation
- Review
- Closed`,
  'Operations Monitor': `You are the Operations Monitor.

Your job:
- Watch production health and detect failures, backlogs, delays, and abnormal runtime conditions.
- Produce system health reports, incident summaries, and escalation signals.

How to operate:
- Monitor failed jobs, queue backlogs, stuck records, delayed processing, long-running scripts, and threshold breaches.
- Escalate database issues to SQL Engineer, automation/runtime issues to PowerShell Engineer, and legacy workflow issues to Legacy Systems Engineer.
- Keep the Workflow Manager and Documentation Agent informed when incidents matter to stakeholders.`,
  'Documentation Agent': `You are the Documentation Agent.

Your job:
- Record what changed, why it changed, what failed, what was decided, and what needs to be communicated.
- Create daily logs, change summaries, technical documentation, and stakeholder-ready updates.

How to operate:
- Turn technical work into clear human-readable documentation.
- Preserve auditability: request, decision, implementation, validation, outcome.
- Coordinate with the Workflow Manager for status framing and with engineers for technical accuracy.`,
  'SQL Engineer': `You are the SQL Engineer.

Your job:
- Handle stored procedures, queries, views, functions, indexes, SQL Agent jobs, tuning, and database troubleshooting.

How to operate:
- Produce concrete database changes, diagnostics, optimization recommendations, and risk notes.
- Be explicit about performance impact, locking risk, data safety, and deployment concerns.
- Hand validation requirements to QA/Test Engineer when changes need verification.`,
  'PowerShell Engineer': `You are the PowerShell Engineer.

Your job:
- Handle Windows automation, scripts, scheduled tasks, service control, folder monitoring, logging, and process orchestration.

How to operate:
- Produce concrete scripts, automation flows, diagnostics, and remediation steps.
- Be explicit about runtime environment, permissions, error handling, and rollback considerations.`,
  'Integration Engineer': `You are the Integration Engineer.

Your job:
- Handle APIs, connectors, workflow automation, OpenJarvis integrations, GitHub integrations, Outlook flows, and system-to-system coordination.

How to operate:
- Clarify boundaries between systems, inputs/outputs, auth requirements, failure modes, and observability.
- Produce reliable integration plans, mappings, and implementation notes.`,
  'Front-End Engineer': `You are the Front-End Engineer.

Your job:
- Handle UI, dashboards, React flows, interaction design, and agent-facing screens.

How to operate:
- Focus on usability, state flow, feedback, accessibility, and implementation detail.
- Coordinate with QA/Test Engineer for validation and Documentation Agent for change summaries.`,
  'Legacy Systems Engineer': `You are the Legacy Systems Engineer.

Your job:
- Handle VB6, VBScript, batch files, Ghostscript, BlackIce, RightFax, and older Windows-era process behavior.

How to operate:
- Respect the fragility of old systems and call out compatibility, deployment, and operational risk clearly.
- Produce pragmatic fixes with rollback awareness instead of idealized rewrites unless explicitly requested.`,
  'QA/Test Engineer': `You are the QA/Test Engineer.

Your job:
- Validate changes, create test plans, run regression thinking, and confirm that work is safe to close.

How to operate:
- Produce test cases, validation scripts, failure scenarios, and pass/fail summaries.
- Call out residual risk, missing evidence, and gaps in coverage clearly.
- Do not approve work based on assumptions alone.`,
};

function maybeApplyRoleInstructionPreset(
  role: string,
  currentInstruction: string,
  previousRole: string,
): string {
  const nextPreset = ROLE_INSTRUCTION_PRESETS[role];
  if (!nextPreset) return currentInstruction;
  const trimmed = currentInstruction.trim();
  const previousPreset = ROLE_INSTRUCTION_PRESETS[previousRole] || '';
  if (!trimmed || trimmed === previousPreset.trim()) {
    return nextPreset;
  }
  return currentInstruction;
}

function roleLabel(agent: Pick<ManagedAgent, 'org_role' | 'agent_type'>): string {
  return agent.org_role?.trim() || agent.agent_type;
}

function findAgentById(
  agents: ManagedAgent[],
  agentId?: string | null,
): ManagedAgent | undefined {
  if (!agentId) return undefined;
  return agents.find((agent) => agent.id === agentId);
}

function collectDescendantIds(agentId: string, agents: ManagedAgent[]): Set<string> {
  const seen = new Set<string>();
  const stack = [agentId];
  while (stack.length > 0) {
    const currentId = stack.pop()!;
    for (const agent of agents) {
      if (agent.manager_agent_id === currentId && !seen.has(agent.id)) {
        seen.add(agent.id);
        stack.push(agent.id);
      }
    }
  }
  return seen;
}

function buildManagementChain(agent: ManagedAgent, agents: ManagedAgent[]): ManagedAgent[] {
  const chain: ManagedAgent[] = [];
  const seen = new Set<string>();
  let current: ManagedAgent | undefined = agent;
  while (current && !seen.has(current.id)) {
    chain.unshift(current);
    seen.add(current.id);
    current = findAgentById(agents, current.manager_agent_id);
  }
  return chain;
}

function compareAgentsForOrg(a: ManagedAgent, b: ManagedAgent): number {
  const aRole = roleLabel(a).toLowerCase();
  const bRole = roleLabel(b).toLowerCase();
  const aIsChief = aRole.includes('chief executive officer') || aRole === 'ceo' || aRole === 'chief orchestrator';
  const bIsChief = bRole.includes('chief executive officer') || bRole === 'ceo' || bRole === 'chief orchestrator';
  if (aIsChief !== bIsChief) return aIsChief ? -1 : 1;
  return a.name.localeCompare(b.name);
}

function getOrgChildren(agents: ManagedAgent[], managerId?: string | null): ManagedAgent[] {
  return agents
    .filter((agent) => (managerId ? agent.manager_agent_id === managerId : !agent.manager_agent_id))
    .sort(compareAgentsForOrg);
}

function getOrgRoots(agents: ManagedAgent[]): ManagedAgent[] {
  const knownIds = new Set(agents.map((agent) => agent.id));
  return agents
    .filter((agent) => !agent.manager_agent_id || !knownIds.has(agent.manager_agent_id))
    .sort(compareAgentsForOrg);
}

function buildAgentPathToRoot(agentId: string, agents: ManagedAgent[]): string[] {
  const path: string[] = [];
  const seen = new Set<string>();
  let current = findAgentById(agents, agentId);
  while (current && !seen.has(current.id)) {
    path.push(current.id);
    seen.add(current.id);
    current = findAgentById(agents, current.manager_agent_id);
  }
  return path;
}

function getOrgPathEdgeKeys(
  fromAgentId: string,
  toAgentId: string,
  agents: ManagedAgent[],
): string[] {
  if (!fromAgentId || !toAgentId || fromAgentId === toAgentId) return [];
  const fromPath = buildAgentPathToRoot(fromAgentId, agents);
  const toPath = buildAgentPathToRoot(toAgentId, agents);
  if (!fromPath.length || !toPath.length) return [];

  const toIndex = new Map(toPath.map((id, index) => [id, index]));
  const lca = fromPath.find((id) => toIndex.has(id));
  if (!lca) return [];

  const edges = new Set<string>();
  for (const id of fromPath) {
    if (id === lca) break;
    edges.add(id);
  }
  for (const id of toPath) {
    if (id === lca) break;
    edges.add(id);
  }
  return Array.from(edges);
}

const TEMPLATE_METADATA_KEYS = new Set(['id', 'name', 'description', 'source', 'editable']);

function applyTemplateConfig(
  currentConfig: Record<string, unknown>,
  template: AgentTemplate | undefined,
  selectedSkills: string[],
): { config: Record<string, unknown>; agentType?: string } {
  const nextConfig: Record<string, unknown> = { ...currentConfig, skills: selectedSkills };
  if (!template) {
    delete nextConfig.template_id;
    return { config: nextConfig };
  }

  const templateConfig: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(template)) {
    if (!TEMPLATE_METADATA_KEYS.has(key)) {
      templateConfig[key] = value;
    }
  }

  const mergedConfig = {
    ...currentConfig,
    ...templateConfig,
    template_id: template.id,
    skills: selectedSkills,
  };

  return {
    config: mergedConfig,
    agentType: typeof template.agent_type === 'string' ? template.agent_type : undefined,
  };
}

// ---------------------------------------------------------------------------
// Launch Wizard
// ---------------------------------------------------------------------------

const CATEGORY_MAP: Record<string, string> = {
  communication: 'Communication',
  channel: 'Communication',
  search: 'Search & Browse',
  browser: 'Search & Browse',
  code: 'Code & Dev',
  system: 'Code & Dev',
  filesystem: 'Files & Data',
  memory: 'Memory & Knowledge',
  knowledge_graph: 'Memory & Knowledge',
  reasoning: 'Reasoning & AI',
  math: 'Reasoning & AI',
  inference: 'Reasoning & AI',
  agents: 'Reasoning & AI',
  media: 'Media',
};

const TOOL_NAME_FALLBACK: Record<string, string> = {
  file_read: 'Files & Data',
  file_write: 'Files & Data',
  pdf_extract: 'Files & Data',
  db_query: 'Files & Data',
  http_request: 'Files & Data',
  apply_patch: 'Code & Dev',
  git_status: 'Code & Dev',
  git_diff: 'Code & Dev',
  git_log: 'Code & Dev',
  git_commit: 'Code & Dev',
  channel_send: 'Communication',
  channel_list: 'Communication',
  channel_status: 'Communication',
};

const CATEGORY_ORDER = [
  'Communication', 'Search & Browse', 'Code & Dev', 'Files & Data',
  'Memory & Knowledge', 'Reasoning & AI', 'Media',
];

const POPULAR_TOOLS = new Set([
  'slack', 'email', 'telegram', 'whatsapp',
  'web_search', 'browser',
  'code_interpreter', 'shell_exec', 'git_status', 'git_diff',
  'file_read', 'file_write', 'pdf_extract',
  'retrieval', 'memory_store',
  'think', 'llm', 'calculator',
  'image_generate',
]);

const BROWSER_SUB_TOOLS = [
  'browser_navigate', 'browser_click', 'browser_type',
  'browser_screenshot', 'browser_extract', 'browser_axtree',
];

function parseIntervalParts(val: string): { hours: number; minutes: number; seconds: number } {
  const total = parseInt(val) || 0;
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  return { hours, minutes, seconds };
}

function serializeInterval(hours: number, minutes: number, seconds: number): string {
  return String(hours * 3600 + minutes * 60 + seconds);
}

interface WizardState {
  step: 1 | 2;
  templateId: string;
  templateData: AgentTemplate | null;
  name: string;
  orgRole: string;
  managerAgentId: string;
  instruction: string;
  model: string;
  scheduleType: string;
  scheduleValue: string;
  selectedTools: string[];
  budget: string;
  routerPolicy: string;
  memoryExtraction: string;
  observationCompression: string;
  retrievalStrategy: string;
  taskDecomposition: string;
  maxTurns: number;
  temperature: number;
}


const TEMPLATE_INSTRUCTIONS: Record<string, string> = {
  'daily-briefing': 'Every morning, give me a fun quote of the day, summarize my top important emails, list any meetings today from my calendar, and tell me the weather for [my city].',
  'daily_briefing': 'Every morning, give me a fun quote of the day, summarize my top important emails, list any meetings today from my calendar, and tell me the weather for [my city].',
  'research-monitor': 'Search for the latest news and papers on [your topic]. Summarize the top 3 most relevant findings and explain why they matter.',
  'research_monitor': 'Search for the latest news and papers on [your topic]. Summarize the top 3 most relevant findings and explain why they matter.',
  'code-reviewer': 'Review the latest commits in [repo]. Check for bugs, security issues, and style violations. Summarize findings with file paths and line numbers.',
  'code_reviewer': 'Review the latest commits in [repo]. Check for bugs, security issues, and style violations. Summarize findings with file paths and line numbers.',
  'meeting-prep': 'Before my next meeting, pull context from my emails, messages, and past meetings with the attendees. Summarize key topics and suggest talking points.',
  'meeting_prep': 'Before my next meeting, pull context from my emails, messages, and past meetings with the attendees. Summarize key topics and suggest talking points.',
  'personal_deep_research': 'Search across all my personal data — messages, emails, meetings, documents, and notes — to answer [my question]. Cite your sources.',
  'inbox_triager': 'Check my recent emails and messages. Categorize them by priority (urgent, important, FYI, spam). Summarize the top items I should act on.',
};

function Tooltip({ text }: { text: string }) {
  return <span className="inline-block ml-1 cursor-help" style={{ color: 'var(--color-text-tertiary)', fontSize: 10 }} title={text}>(?)</span>;
}

// ---------------------------------------------------------------------------
// ToolsPicker — dev-inventory style tool selector used by the launch wizard
// ---------------------------------------------------------------------------

const TOOL_CATEGORY_ORDER = [
  'filesystem',
  'system',
  'code',
  'vcs',
  'storage',
  'memory',
  'knowledge',
  'knowledge_graph',
  'search',
  'network',
  'browser',
  'database',
  'data',
  'math',
  'reasoning',
  'inference',
  'media',
  'audio',
  'skill',
  'channel',
  'communication',
  'other',
];

const TOOL_CATEGORY_LABELS: Record<string, string> = {
  filesystem: 'filesystem',
  system: 'shell & exec',
  code: 'code & repl',
  vcs: 'git',
  storage: 'memory · storage',
  memory: 'memory',
  knowledge: 'knowledge',
  knowledge_graph: 'knowledge graph',
  search: 'search',
  network: 'network',
  browser: 'browser',
  database: 'database',
  data: 'data',
  math: 'math',
  reasoning: 'reasoning',
  inference: 'inference',
  media: 'media',
  audio: 'audio',
  skill: 'skills',
  channel: 'channel primitives',
  communication: 'channels',
  other: 'other',
};

function ToolsPicker({
  tools,
  selected,
  onChange,
}: {
  tools: ToolInfo[];
  selected: string[];
  onChange: (next: string[]) => void;
}) {
  const [hovered, setHovered] = useState<ToolInfo | null>(null);
  const [pulseKey, setPulseKey] = useState(0);

  // Channels (source === 'channel') live in ChannelRegistry and aren't
  // directly callable by the LLM — the agent talks to them through the
  // `channel_send` tool. Showing them in the tools picker is misleading,
  // so filter them out; channel bindings are configured separately.
  const tollableTools = tools.filter((t) => t.source !== 'channel');

  // Group by category, respecting the preferred order then alphabetical.
  const grouped = (() => {
    const buckets: Record<string, ToolInfo[]> = {};
    for (const t of tollableTools) {
      const cat = TOOL_CATEGORY_ORDER.includes(t.category) ? t.category : 'other';
      (buckets[cat] ||= []).push(t);
    }
    for (const cat of Object.keys(buckets)) {
      buckets[cat].sort((a, b) => a.name.localeCompare(b.name));
    }
    return TOOL_CATEGORY_ORDER
      .filter((cat) => buckets[cat]?.length)
      .map((cat) => ({ category: cat, items: buckets[cat] }));
  })();

  const configurable = tollableTools.filter((t) => t.configured).map((t) => t.name);
  const allSelected =
    configurable.length > 0 && configurable.every((n) => selected.includes(n));

  const toggle = (name: string) => {
    const next = selected.includes(name)
      ? selected.filter((t) => t !== name)
      : [...selected, name];
    onChange(next);
    setPulseKey((k) => k + 1);
  };

  const hint = hovered
    ? hovered.configured
      ? hovered.description || hovered.name
      : `Needs ${hovered.credential_keys.join(', ') || 'credentials'}`
    : 'hover a tool for details';

  return (
    <div>
      <div className="flex items-baseline justify-between mb-1">
        <label
          className="block text-[13px] font-medium"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          Tools
        </label>
        <div className="flex items-center gap-2">
          <span
            key={pulseKey}
            className="tools-count"
            style={{
              fontFamily:
                'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace',
              fontSize: 10.5,
              color: 'var(--color-text-tertiary)',
            }}
          >
            <span style={{ color: 'var(--color-accent)' }}>
              {selected.length}
            </span>
            <span style={{ opacity: 0.5 }}> / {tollableTools.length}</span>
          </span>
          <span style={{ color: 'var(--color-text-tertiary)', opacity: 0.3 }}>·</span>
          <button
            type="button"
            onClick={() => onChange(allSelected ? [] : configurable)}
            disabled={tools.length === 0}
            className="transition-colors"
            style={{
              fontFamily:
                'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace',
              fontSize: 10,
              color: 'var(--color-text-tertiary)',
              background: 'none',
              border: 'none',
              padding: 0,
              cursor: tools.length === 0 ? 'default' : 'pointer',
              textDecoration: 'underline',
              textUnderlineOffset: 2,
            }}
            onMouseEnter={(e) =>
              (e.currentTarget.style.color = 'var(--color-text)')
            }
            onMouseLeave={(e) =>
              (e.currentTarget.style.color = 'var(--color-text-tertiary)')
            }
          >
            {allSelected ? 'none' : 'all'}
          </button>
        </div>
      </div>
      <p
        className="text-[10.5px] mb-2"
        style={{ color: 'var(--color-text-tertiary)' }}
      >
        What the agent is allowed to call. An empty selection makes a
        chat-only agent.
      </p>
      {tools.length === 0 ? (
        <div
          className="px-3 py-2 rounded-lg text-xs"
          style={{
            background: 'var(--color-bg-secondary)',
            border: '1px solid var(--color-border)',
            color: 'var(--color-text-tertiary)',
          }}
        >
          Loading available tools…
        </div>
      ) : (
        <div
          className="rounded-lg overflow-hidden"
          style={{
            background: 'var(--color-bg-secondary)',
            border: '1px solid var(--color-border)',
          }}
          onMouseLeave={() => setHovered(null)}
        >
          <div
            className="px-2.5 py-2 overflow-y-auto"
            style={{ maxHeight: 200 }}
          >
            {grouped.map(({ category, items }, idx) => (
              <div key={category} style={{ marginTop: idx === 0 ? 0 : 10 }}>
                <div
                  className="flex items-center gap-1.5 mb-1.5"
                  style={{
                    fontFamily:
                      'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace',
                    fontSize: 9.5,
                    color: 'var(--color-text-tertiary)',
                    textTransform: 'uppercase',
                    letterSpacing: '0.1em',
                  }}
                >
                  <span style={{ opacity: 0.5 }}>─</span>
                  <span>{TOOL_CATEGORY_LABELS[category] || category}</span>
                  <span
                    className="flex-1"
                    style={{
                      borderBottom: '1px dashed var(--color-border)',
                      marginBottom: 3,
                      opacity: 0.5,
                    }}
                  />
                </div>
                <div className="flex flex-wrap gap-1">
                  {items.map((tool) => {
                    const isSelected = selected.includes(tool.name);
                    const disabled = !tool.configured;
                    return (
                      <button
                        key={tool.name}
                        type="button"
                        disabled={disabled}
                        onClick={() => toggle(tool.name)}
                        onMouseEnter={() => setHovered(tool)}
                        onFocus={() => setHovered(tool)}
                        className="tool-chip"
                        style={{
                          fontFamily:
                            'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace',
                          fontSize: 11,
                          lineHeight: 1.2,
                          padding: '3px 7px 3px 5px',
                          borderRadius: 4,
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: 5,
                          background: isSelected
                            ? 'color-mix(in srgb, var(--color-accent) 14%, transparent)'
                            : 'var(--color-bg)',
                          color: disabled
                            ? 'var(--color-text-tertiary)'
                            : isSelected
                              ? 'var(--color-accent)'
                              : 'var(--color-text-secondary)',
                          border: disabled
                            ? '1px dashed var(--color-border)'
                            : `1px solid ${isSelected ? 'var(--color-accent)' : 'var(--color-border)'}`,
                          boxShadow: isSelected
                            ? 'inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 30%, transparent)'
                            : 'none',
                          cursor: disabled ? 'not-allowed' : 'pointer',
                          opacity: disabled ? 0.55 : 1,
                          transition:
                            'background 120ms, color 120ms, border-color 120ms, transform 80ms',
                        }}
                        onMouseDown={(e) =>
                          !disabled && (e.currentTarget.style.transform = 'scale(0.97)')
                        }
                        onMouseUp={(e) =>
                          (e.currentTarget.style.transform = 'scale(1)')
                        }
                      >
                        <span
                          style={{
                            opacity: isSelected ? 1 : 0.5,
                            color: disabled
                              ? 'var(--color-text-tertiary)'
                              : isSelected
                                ? 'var(--color-accent)'
                                : 'var(--color-text-tertiary)',
                            fontSize: 10.5,
                          }}
                        >
                          {disabled ? '⨯' : isSelected ? '▣' : '□'}
                        </span>
                        <span>{tool.name}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
          {/* Live description strip */}
          <div
            className="flex items-center gap-2 px-2.5 py-1.5"
            style={{
              borderTop: '1px solid var(--color-border)',
              background: 'var(--color-bg)',
              fontFamily:
                'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace',
              fontSize: 10.5,
              color: 'var(--color-text-tertiary)',
              minHeight: 26,
            }}
          >
            <span
              style={{
                color: hovered
                  ? hovered.configured
                    ? 'var(--color-accent)'
                    : '#f59e0b'
                  : 'var(--color-text-tertiary)',
                opacity: hovered ? 1 : 0.5,
              }}
            >
              {hovered ? (hovered.configured ? '▸' : '!') : '·'}
            </span>
            {hovered && (
              <span
                style={{
                  color: 'var(--color-text)',
                  fontWeight: 500,
                }}
              >
                {hovered.name}
              </span>
            )}
            <span
              className="truncate"
              style={{
                flex: 1,
                color: 'var(--color-text-tertiary)',
              }}
            >
              {hovered ? `— ${hint}` : hint}
            </span>
          </div>
        </div>
      )}
      <style>{`
        @keyframes tools-count-pulse {
          0% { transform: scale(1); }
          40% { transform: scale(1.18); }
          100% { transform: scale(1); }
        }
        .tools-count {
          display: inline-block;
          animation: tools-count-pulse 220ms ease-out;
        }
      `}</style>
    </div>
  );
}

function LaunchWizard({
  templates,
  managedAgents,
  onClose,
  onLaunched,
}: {
  templates: AgentTemplate[];
  managedAgents: ManagedAgent[];
  onClose: () => void;
  onLaunched: () => void;
}) {
  const UNIVERSAL_DEFAULTS = {
    memoryExtraction: 'structured_json',
    observationCompression: 'summarize',
    retrievalStrategy: 'sqlite',
    taskDecomposition: 'hierarchical',
    maxTurns: 25,
    temperature: 0.3,
  };

  const [wizard, setWizard] = useState<WizardState>({
    step: 1,
    templateId: '',
    templateData: null,
    name: '',
    orgRole: '',
    managerAgentId: '',
    instruction: '',
    model: '',
    scheduleType: 'manual',
    scheduleValue: '',
    selectedTools: [],
    budget: '',
    routerPolicy: '',
    ...UNIVERSAL_DEFAULTS,
  });
  const [launching, setLaunching] = useState(false);
  const [recommendedModel, setRecommendedModel] = useState('');
  const [availableTools, setAvailableTools] = useState<ToolInfo[]>([]);
  const models = useAppStore((s) => s.models);

  useEffect(() => {
    fetchRecommendedModel().then((r) => {
      setRecommendedModel(r.model);
      if (!wizard.model) {
        setWizard((w) => ({ ...w, model: r.model }));
      }
    }).catch(() => {});
    fetchAvailableTools().then((tools) => {
      setAvailableTools(tools);
    }).catch(() => {});
  }, []);

  function selectTemplate(tpl: AgentTemplate | null) {
    if (tpl) {
      setWizard((w) => ({
        ...w,
        step: 2,
        templateId: tpl.id,
        templateData: tpl,
        name: '',
        orgRole: '',
        managerAgentId: '',
        instruction: (tpl as any).instruction || TEMPLATE_INSTRUCTIONS[tpl.id] || '',
        model: recommendedModel || w.model,
        scheduleType: (tpl as any).schedule_type || 'manual',
        scheduleValue: (tpl as any).schedule_value || '',
        selectedTools: (tpl as any).tools || [],
        memoryExtraction: (tpl as any).memory_extraction || UNIVERSAL_DEFAULTS.memoryExtraction,
        observationCompression: (tpl as any).observation_compression || UNIVERSAL_DEFAULTS.observationCompression,
        retrievalStrategy: (tpl as any).retrieval_strategy || UNIVERSAL_DEFAULTS.retrievalStrategy,
        taskDecomposition: (tpl as any).task_decomposition || UNIVERSAL_DEFAULTS.taskDecomposition,
        maxTurns: (tpl as any).max_turns || UNIVERSAL_DEFAULTS.maxTurns,
        temperature: (tpl as any).temperature ?? UNIVERSAL_DEFAULTS.temperature,
      }));
    } else {
      setWizard((w) => ({
        ...w,
        step: 2,
        templateId: '',
        templateData: null,
        name: '',
        orgRole: '',
        managerAgentId: '',
        instruction: '',
        model: recommendedModel || w.model,
        scheduleType: 'manual',
        scheduleValue: '',
        selectedTools: [],
        ...UNIVERSAL_DEFAULTS,
      }));
    }
  }

  async function handleLaunch() {
    if (!wizard.name.trim()) { toast.error('Name is required'); return; }
    setLaunching(true);
    try {
      // Map friendly schedule presets to API schedule_type/schedule_value
      let apiScheduleType = wizard.scheduleType;
      let apiScheduleValue = wizard.scheduleValue;
      if (wizard.scheduleType === 'daily' || wizard.scheduleType === 'weekly') {
        apiScheduleType = 'cron';
        // scheduleValue already holds the cron expression
      } else if (wizard.scheduleType === 'hourly') {
        apiScheduleType = 'interval';
        // scheduleValue already holds seconds as string
      }

      const config: Record<string, unknown> = {
        schedule_type: apiScheduleType,
        schedule_value: apiScheduleValue || undefined,
        tools: wizard.selectedTools,
        learning_enabled: !!wizard.routerPolicy,
        memory_extraction: wizard.memoryExtraction,
        observation_compression: wizard.observationCompression,
        retrieval_strategy: wizard.retrievalStrategy,
        task_decomposition: wizard.taskDecomposition,
        max_turns: wizard.maxTurns,
        temperature: wizard.temperature,
      };
      if (wizard.budget) config.budget = parseFloat(wizard.budget);
      if (wizard.instruction.trim()) config.instruction = wizard.instruction.trim();
      if (wizard.model) config.model = wizard.model;
      if (wizard.routerPolicy) config.router_policy = wizard.routerPolicy;

      await createManagedAgent({
        name: wizard.name.trim(),
        template_id: wizard.templateId || undefined,
        config,
        org_role: wizard.orgRole.trim() || undefined,
        manager_agent_id: wizard.managerAgentId || null,
      });
      toast.success(`Agent "${wizard.name}" created`);
      onLaunched();
    } catch (err: any) {
      toast.error(err.message || 'Failed to create agent');
    } finally {
      setLaunching(false);
    }
  }

  const formatScheduleLabel = (type: string, value: string) => {
    if (type === 'manual') return 'Manual (run on demand)';
    if (type === 'cron') return `Cron: ${value}`;
    if (type === 'interval') {
      const secs = parseInt(value, 10);
      if (secs >= 3600) return `Every ${secs / 3600}h`;
      if (secs >= 60) return `Every ${secs / 60}m`;
      return `Every ${secs}s`;
    }
    return type;
  };

  // ── Step 1: Template Selection ──
  if (wizard.step === 1) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.6)' }}>
        <div className="rounded-xl p-6 w-full max-w-lg" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)' }}>
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold" style={{ color: 'var(--color-text)' }}>New Agent — Choose Template</h2>
            <button onClick={onClose} className="p-1 rounded hover:bg-opacity-10" style={{ color: 'var(--color-text-tertiary)' }}><X size={18} /></button>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {templates.map((tpl) => (
              <button
                key={tpl.id}
                onClick={() => selectTemplate(tpl)}
                className="text-left p-4 rounded-lg transition-all items-start"
                style={{ border: '1px solid var(--color-border)', background: 'var(--color-bg-secondary)' }}
                onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--color-accent)'; e.currentTarget.style.background = 'color-mix(in srgb, var(--color-accent-purple) 6%, transparent)'; }}
                onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--color-border)'; e.currentTarget.style.background = 'var(--color-bg-secondary)'; }}
              >
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-lg">{(tpl as any).icon || '🤖'}</span>
                  <span className="font-semibold text-sm" style={{ color: 'var(--color-text)' }}>{tpl.name}</span>
                </div>
                <div className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)', textAlign: 'left' }}>{tpl.description}</div>
                {(tpl as any).tools && (
                  <div className="flex flex-wrap gap-1 mt-2">
                    {((tpl as any).tools as string[]).slice(0, 4).map((t: string) => (
                      <span key={t} className="text-xs px-1.5 py-0.5 rounded" style={{ background: 'color-mix(in srgb, var(--color-accent-purple) 12%, transparent)', color: 'var(--color-accent-purple)' }}>{t}</span>
                    ))}
                    {((tpl as any).tools as string[]).length > 4 && (
                      <span className="text-xs px-1.5 py-0.5 rounded" style={{ color: 'var(--color-text-tertiary)' }}>+{((tpl as any).tools as string[]).length - 4}</span>
                    )}
                  </div>
                )}
              </button>
            ))}
            <button
              onClick={() => selectTemplate(null)}
              className="text-left p-4 rounded-lg transition-all items-start"
              style={{ border: '1px solid var(--color-border)', background: 'var(--color-bg-secondary)' }}
              onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--color-accent)'; e.currentTarget.style.background = 'color-mix(in srgb, var(--color-accent-purple) 6%, transparent)'; }}
              onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--color-border)'; e.currentTarget.style.background = 'var(--color-bg-secondary)'; }}
            >
              <div className="flex items-center gap-2 mb-1">
                <span className="text-lg">⚙️</span>
                <span className="font-semibold text-sm" style={{ color: 'var(--color-text)' }}>Custom Agent</span>
              </div>
              <div className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)', textAlign: 'left' }}>Start from scratch. Pick your own tools, schedule, and behavior.</div>
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ── Step 2: Configuration ──
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.6)' }}>
      <div className="rounded-xl p-6 w-full max-w-lg max-h-[85vh] overflow-y-auto" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)' }}>
        <div className="flex justify-between items-center mb-4">
          <div className="flex items-center gap-2">
            <button onClick={() => setWizard((w) => ({ ...w, step: 1 }))} className="p-1 rounded" style={{ color: 'var(--color-text-tertiary)' }}><ChevronLeft size={18} /></button>
            <h2 className="text-lg font-semibold" style={{ color: 'var(--color-text)' }}>
              {wizard.templateData ? `New ${wizard.templateData.name}` : 'New Custom Agent'}
            </h2>
          </div>
          <button onClick={onClose} className="p-1 rounded" style={{ color: 'var(--color-text-tertiary)' }}><X size={18} /></button>
        </div>

        <div className="space-y-4">
          {/* Name */}
          <div>
            <label className="block text-sm font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>Agent Name</label>
            <input
              value={wizard.name}
              onChange={(e) => setWizard((w) => ({ ...w, name: e.target.value }))}
              placeholder="e.g. AI Research Tracker"
              className="w-full px-3 py-2 rounded-lg text-sm bg-transparent"
              style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>Organization Role</label>
              <input
                list="agent-org-role-presets"
                value={wizard.orgRole}
                onChange={(e) =>
                  setWizard((w) => ({
                    ...w,
                    orgRole: e.target.value,
                    instruction: maybeApplyRoleInstructionPreset(
                      e.target.value,
                      w.instruction,
                      w.orgRole,
                    ),
                  }))
                }
                placeholder="e.g. Chief Orchestrator"
                className="w-full px-3 py-2 rounded-lg text-sm bg-transparent"
                style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
              />
              <datalist id="agent-org-role-presets">
                {ORG_ROLE_PRESETS.map((role) => (
                  <option key={role} value={role} />
                ))}
              </datalist>
            </div>
            <div>
              <label className="block text-sm font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>Reports To</label>
              <select
                value={wizard.managerAgentId}
                onChange={(e) => setWizard((w) => ({ ...w, managerAgentId: e.target.value }))}
                className="w-full px-3 py-2 rounded-lg text-sm"
                style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
              >
                <option value="">Top-level leader</option>
                {managedAgents.map((agent) => (
                  <option key={agent.id} value={agent.id}>
                    {agent.name} - {roleLabel(agent)}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Instruction */}
          <div>
            <label className="block text-sm font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>What should this agent do?</label>
            <textarea
              value={wizard.instruction}
              onChange={(e) => setWizard((w) => ({ ...w, instruction: e.target.value }))}
              placeholder="e.g. Monitor the latest research papers on reasoning and chain-of-thought in LLMs"
              rows={3}
              className="w-full px-3 py-2 rounded-lg text-sm bg-transparent resize-none"
              style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
            />
            {wizard.instruction.includes('[') && (
              <p className="text-[10px] mt-1" style={{ color: 'var(--color-warning)' }}>
                Replace the [bracketed text] with your own values
              </p>
            )}
          </div>

          {/* Tools picker */}
          <ToolsPicker
            tools={availableTools}
            selected={wizard.selectedTools}
            onChange={(next) =>
              setWizard((w) => ({ ...w, selectedTools: next }))
            }
          />

          {/* Model + Schedule row */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>Intelligence</label>
              <select
                value={wizard.model}
                onChange={(e) => setWizard((w) => ({ ...w, model: e.target.value }))}
                className="w-full px-3 py-2 rounded-lg text-sm"
                style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
              >
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.id}{m.id === recommendedModel ? ' (recommended)' : ''}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>Schedule</label>
              <select
                value={wizard.scheduleType}
                onChange={(e) => setWizard((w) => ({ ...w, scheduleType: e.target.value, scheduleValue: e.target.value === 'manual' ? '' : w.scheduleValue }))}
                className="w-full px-3 py-2 rounded-lg text-sm"
                style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
              >
                <option value="manual">Manual (run on demand)</option>
                <option value="daily">Daily</option>
                <option value="weekly">Weekly</option>
                <option value="hourly">Every N hours</option>
                <option value="cron">Custom (cron expression)</option>
              </select>
              {wizard.scheduleType === 'daily' && (
                <select
                  value={(() => { const m = wizard.scheduleValue.match(/^0\s+(\d+)\s/); return m ? m[1] : '9'; })()}
                  onChange={(e) => setWizard((w) => ({ ...w, scheduleValue: `0 ${e.target.value} * * *` }))}
                  className="w-full px-3 py-1.5 rounded-lg text-xs mt-1.5"
                  style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                >
                  {Array.from({ length: 24 }, (_, i) => {
                    const label = i === 0 ? '12 AM' : i < 12 ? `${i} AM` : i === 12 ? '12 PM' : `${i - 12} PM`;
                    return <option key={i} value={String(i)}>{label}</option>;
                  })}
                </select>
              )}
              {wizard.scheduleType === 'weekly' && (
                <div className="mt-1.5 space-y-1.5">
                  <div className="flex gap-1">
                    {(['Mon','Tue','Wed','Thu','Fri','Sat','Sun'] as const).map((day, idx) => {
                      const dayNum = String(idx + 1);
                      const cronParts = wizard.scheduleValue.match(/\*\s+\*\s+(.+)$/);
                      const selectedDays = cronParts ? cronParts[1].split(',') : [];
                      const isSelected = selectedDays.includes(dayNum);
                      return (
                        <button
                          key={day}
                          type="button"
                          onClick={() => {
                            const newDays = isSelected ? selectedDays.filter(d => d !== dayNum) : [...selectedDays, dayNum].sort();
                            const hourMatch = wizard.scheduleValue.match(/^0\s+(\d+)\s/);
                            const hour = hourMatch ? hourMatch[1] : '9';
                            setWizard((w) => ({ ...w, scheduleValue: newDays.length > 0 ? `0 ${hour} * * ${newDays.join(',')}` : '' }));
                          }}
                          className="px-1.5 py-1 rounded text-xs font-medium"
                          style={{
                            background: isSelected ? 'var(--color-accent)' : 'var(--color-bg)',
                            color: isSelected ? 'var(--color-on-accent)' : 'var(--color-text-tertiary)',
                            border: `1px solid ${isSelected ? 'var(--color-accent)' : 'var(--color-border)'}`,
                          }}
                        >
                          {day}
                        </button>
                      );
                    })}
                  </div>
                  <select
                    value={(() => { const m = wizard.scheduleValue.match(/^0\s+(\d+)\s/); return m ? m[1] : '9'; })()}
                    onChange={(e) => {
                      const cronParts = wizard.scheduleValue.match(/\*\s+\*\s+(.+)$/);
                      const days = cronParts ? cronParts[1] : '1';
                      setWizard((w) => ({ ...w, scheduleValue: `0 ${e.target.value} * * ${days}` }));
                    }}
                    className="w-full px-3 py-1.5 rounded-lg text-xs"
                    style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                  >
                    {Array.from({ length: 24 }, (_, i) => {
                      const label = i === 0 ? '12 AM' : i < 12 ? `${i} AM` : i === 12 ? '12 PM' : `${i - 12} PM`;
                      return <option key={i} value={String(i)}>{label}</option>;
                    })}
                  </select>
                </div>
              )}
              {wizard.scheduleType === 'hourly' && (
                <div className="flex items-center gap-2 mt-1.5">
                  <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>Every</span>
                  <input
                    type="number" min="1" max="24"
                    value={(() => { const secs = parseInt(wizard.scheduleValue || '0', 10); return secs > 0 ? Math.round(secs / 3600) : 1; })()}
                    onChange={(e) => {
                      const hrs = Math.min(24, Math.max(1, parseInt(e.target.value, 10) || 1));
                      setWizard((w) => ({ ...w, scheduleValue: String(hrs * 3600) }));
                    }}
                    className="w-14 px-2 py-1 rounded text-xs text-center"
                    style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                  />
                  <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>hours</span>
                </div>
              )}
              {wizard.scheduleType === 'cron' && (
                <input
                  value={wizard.scheduleValue}
                  onChange={(e) => setWizard((w) => ({ ...w, scheduleValue: e.target.value }))}
                  placeholder="0 9 * * *"
                  className="w-full px-3 py-1.5 rounded-lg text-xs bg-transparent mt-1.5"
                  style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                />
              )}
            </div>
          </div>

          {/* Tools tags */}
          {wizard.selectedTools.length > 0 && (
            <div>
              <label className="block text-sm font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>
                Tools <span style={{ color: 'var(--color-text-tertiary)', fontWeight: 400 }}>(from template)</span>
              </label>
              <div className="flex flex-wrap gap-1.5">
                {wizard.selectedTools.map((t) => (
                  <span key={t} className="text-xs px-2 py-1 rounded" style={{ background: 'color-mix(in srgb, var(--color-accent-purple) 12%, transparent)', color: 'var(--color-accent-purple)' }}>{t}</span>
                ))}
              </div>
            </div>
          )}

          {/* Advanced Settings */}
          <details className="rounded-lg" style={{ border: '1px solid var(--color-border)' }}>
            <summary className="px-3 py-2 cursor-pointer text-sm font-medium" style={{ color: 'var(--color-text-tertiary)' }}>
              Advanced Settings <span className="text-xs font-normal">(optional)</span>
            </summary>
            <div className="px-3 pb-3 pt-1 space-y-3" style={{ borderTop: '1px solid var(--color-border)' }}>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <label className="block text-xs mb-1" style={{ color: 'var(--color-text-tertiary)' }}>Memory Extraction<Tooltip text="How the agent remembers context between runs" /></label>
                  <select value={wizard.memoryExtraction} onChange={(e) => setWizard((w) => ({ ...w, memoryExtraction: e.target.value }))}
                    className="w-full px-2 py-1 rounded text-xs" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                    <option value="structured_json">Structured JSON</option>
                    <option value="causality_graph">Causality Graph</option>
                    <option value="scratchpad">Scratchpad</option>
                    <option value="none">None</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs mb-1" style={{ color: 'var(--color-text-tertiary)' }}>Observation Compression<Tooltip text="How the agent summarizes long tool outputs" /></label>
                  <select value={wizard.observationCompression} onChange={(e) => setWizard((w) => ({ ...w, observationCompression: e.target.value }))}
                    className="w-full px-2 py-1 rounded text-xs" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                    <option value="summarize">Summarize</option>
                    <option value="truncate">Truncate</option>
                    <option value="none">None</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs mb-1" style={{ color: 'var(--color-text-tertiary)' }}>Retrieval Strategy<Tooltip text="How the agent searches your knowledge base" /></label>
                  <select value={wizard.retrievalStrategy} onChange={(e) => setWizard((w) => ({ ...w, retrievalStrategy: e.target.value }))}
                    className="w-full px-2 py-1 rounded text-xs" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                    <option value="sqlite">BM25 (SQLite FTS5)</option>
                    <option value="hybrid">Hybrid (BM25 + Semantic)</option>
                    <option value="colbert">ColBERTv2</option>
                    <option value="none">None</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs mb-1" style={{ color: 'var(--color-text-tertiary)' }}>Task Decomposition<Tooltip text="How the agent breaks complex tasks into steps" /></label>
                  <select value={wizard.taskDecomposition} onChange={(e) => setWizard((w) => ({ ...w, taskDecomposition: e.target.value }))}
                    className="w-full px-2 py-1 rounded text-xs" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                    <option value="hierarchical">Hierarchical</option>
                    <option value="phased">Phased</option>
                    <option value="monolithic">Monolithic</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs mb-1" style={{ color: 'var(--color-text-tertiary)' }}>Max Turns</label>
                  <input type="number" value={wizard.maxTurns} onChange={(e) => setWizard((w) => ({ ...w, maxTurns: parseInt(e.target.value, 10) || 25 }))}
                    className="w-full px-2 py-1 rounded text-xs" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }} />
                </div>
                <div>
                  <label className="block text-xs mb-1" style={{ color: 'var(--color-text-tertiary)' }}>Temperature</label>
                  <input type="number" step="0.1" min="0" max="2" value={wizard.temperature}
                    onChange={(e) => setWizard((w) => ({ ...w, temperature: parseFloat(e.target.value) || 0.3 }))}
                    className="w-full px-2 py-1 rounded text-xs" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }} />
                </div>
                <div>
                  <label className="block text-xs mb-1" style={{ color: 'var(--color-text-tertiary)' }}>Budget ($)</label>
                  <input type="number" step="0.01" value={wizard.budget} onChange={(e) => setWizard((w) => ({ ...w, budget: e.target.value }))}
                    placeholder="Unlimited"
                    className="w-full px-2 py-1 rounded text-xs" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }} />
                </div>
                <div>
                  <label className="block text-xs mb-1" style={{ color: 'var(--color-text-tertiary)' }}>Schedule Type</label>
                  <select value={wizard.scheduleType} onChange={(e) => setWizard((w) => ({ ...w, scheduleType: e.target.value, scheduleValue: e.target.value === 'manual' ? '' : w.scheduleValue }))}
                    className="w-full px-2 py-1 rounded text-xs" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                    <option value="manual">Manual</option>
                    <option value="daily">Daily</option>
                    <option value="weekly">Weekly</option>
                    <option value="hourly">Every N hours</option>
                    <option value="cron">Custom (cron)</option>
                  </select>
                </div>
              </div>
            </div>
          </details>

          {/* Launch */}
          <div className="flex gap-3 pt-2">
            <button
              onClick={handleLaunch}
              disabled={launching || !wizard.name.trim()}
              className="flex-1 py-2.5 rounded-lg text-sm font-semibold"
              style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)', opacity: launching || !wizard.name.trim() ? 0.5 : 1 }}
            >
              {launching ? 'Creating...' : 'Launch Agent'}
            </button>
            <button onClick={onClose} className="px-4 py-2.5 rounded-lg text-sm" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}>
              Cancel
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Overflow menu
// ---------------------------------------------------------------------------

function OverflowMenu({
  agentId,
  onDelete,
}: {
  agentId: string;
  onDelete: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        className="p-1 rounded cursor-pointer"
        style={{ color: 'var(--color-text-tertiary)' }}
        title="More actions"
      >
        <MoreHorizontal size={14} />
      </button>
      {open && (
        <div
          className="absolute right-0 top-6 z-20 rounded-lg py-1 min-w-[120px]"
          style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', boxShadow: '0 4px 12px rgba(0,0,0,0.15)' }}
        >
          <button
            onClick={(e) => {
              e.stopPropagation();
              onDelete(agentId);
              setOpen(false);
            }}
            className="w-full text-left px-3 py-1.5 text-xs cursor-pointer flex items-center gap-2"
            style={{ color: 'var(--color-error)' }}
          >
            <Trash2 size={12} /> Delete
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Agent List Card
// ---------------------------------------------------------------------------

function AgentCard({
  agent,
  onClick,
  onPause,
  onResume,
  onRun,
  onRecover,
  onDelete,
  onChat,
  onEdit,
}: {
  agent: ManagedAgent;
  onClick: () => void;
  onPause: (id: string) => void;
  onResume: (id: string) => void;
  onRun: (id: string) => void;
  onRecover: (id: string) => void;
  onDelete: (id: string) => void;
  onChat: (id: string) => void;
  onEdit: (id: string) => void;
}) {
  const canPause = agent.status === 'running' || agent.status === 'idle';
  const canResume = agent.status === 'paused';
  const canRecover = agent.status === 'error' || agent.status === 'stalled' || agent.status === 'needs_attention';
  const title = roleLabel(agent);

  return (
    <div
      onClick={onClick}
      className="p-4 rounded-lg cursor-pointer transition-colors"
      style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
      onMouseEnter={(e) => (e.currentTarget.style.borderColor = 'var(--color-accent)')}
      onMouseLeave={(e) => (e.currentTarget.style.borderColor = 'var(--color-border)')}
    >
      {/* Row 1: Name + status dot */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <AgentAvatar agent={agent} size="sm" active={agent.status === 'running'} />
          <span className="font-medium text-sm truncate" style={{ color: 'var(--color-text)' }}>
            {agent.name}
          </span>
        </div>
        <StatusDot status={agent.status} />
      </div>

      {/* Row 2: Schedule + last run */}
      <div className="text-xs mb-2 flex items-center gap-3" style={{ color: 'var(--color-text-tertiary)' }}>
        <span>{title}</span>
        <span>·</span>
        <span>{formatSchedule(agent.schedule_type, agent.schedule_value)}</span>
        <span>·</span>
        <span>Last run: {formatRelativeTime(agent.last_run_at)}</span>
      </div>

      {/* Row 3: Stats */}
      <div className="flex items-center gap-4 mb-3 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
        <span className="flex items-center gap-1">
          <Activity size={11} />
          {agent.total_runs ?? 0} runs
        </span>
        <span className="flex items-center gap-1">
          <DollarSign size={11} />
          {formatCost(agent.total_cost)}
        </span>
      </div>

      {/* Budget progress bar */}
      {(agent.config?.max_cost as number) > 0 && (
        <div className="mb-3">
          <div className="flex justify-between text-xs mb-1" style={{ color: 'var(--color-text-tertiary)' }}>
            <span>Budget</span>
            <span>
              {formatCost(agent.total_cost)} / ${(agent.config?.max_cost as number).toFixed(0)}
            </span>
          </div>
          <div className="w-full rounded-full h-1.5" style={{ background: 'var(--color-bg)' }}>
            <div
              className="h-1.5 rounded-full transition-all"
              style={{
                width: `${Math.min(100, ((agent.total_cost ?? 0) / (agent.config?.max_cost as number)) * 100)}%`,
                background:
                  ((agent.total_cost ?? 0) / (agent.config?.max_cost as number)) > 0.9
                    ? 'var(--color-error)'
                    : ((agent.total_cost ?? 0) / (agent.config?.max_cost as number)) > 0.75
                      ? 'var(--color-warning)'
                      : 'var(--color-success)',
              }}
            />
          </div>
        </div>
      )}

      {/* Row 4: Actions */}
      <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
        <button
          onClick={(e) => { e.stopPropagation(); onChat(agent.id); }}
          className="p-1.5 rounded cursor-pointer transition-colors"
          style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text-secondary)' }}
          title="Chat with agent"
        >
          <MessageSquare size={13} />
        </button>
        <button
          onClick={(e) => { e.stopPropagation(); onEdit(agent.id); }}
          className="p-1.5 rounded cursor-pointer transition-colors"
          style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text-secondary)' }}
          title="Edit agent"
        >
          <Pencil size={13} />
        </button>
        <button
          onClick={() => onRun(agent.id)}
          className="flex items-center gap-1 px-2 py-1 rounded text-xs cursor-pointer transition-colors"
          style={{ background: 'var(--color-accent)' + '15', color: 'var(--color-accent)' }}
          title="Run now"
        >
          <Zap size={11} /> Run Now
        </button>
        {canPause && (
          <button
            onClick={() => onPause(agent.id)}
            className="p-1 rounded cursor-pointer"
            style={{ color: 'var(--color-text-secondary)' }}
            title="Pause"
          >
            <Pause size={13} />
          </button>
        )}
        {canResume && (
          <button
            onClick={() => onResume(agent.id)}
            className="p-1 rounded cursor-pointer"
            style={{ color: 'var(--color-success)' }}
            title="Resume"
          >
            <Play size={13} />
          </button>
        )}
        {canRecover && (
          <button
            onClick={() => onRecover(agent.id)}
            className="flex items-center gap-1 px-2 py-1 rounded text-xs cursor-pointer"
            style={{ background: 'var(--color-error)20', color: 'var(--color-error)' }}
            title="Recover agent"
          >
            <AlertTriangle size={11} /> Recover
          </button>
        )}
        <div className="ml-auto">
          <OverflowMenu agentId={agent.id} onDelete={onDelete} />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Detail view — Configuration grid with editable model
// ---------------------------------------------------------------------------

const TASK_STATUSES: AgentTask['status'][] = ['pending', 'active', 'completed', 'failed'];
type AgentTaskStatusFilter = 'all' | AgentTask['status'];

interface AgentTaskProjectContext {
  projectName: string;
  projectTaskTitle: string;
}

function taskStatusColor(status: AgentTask['status']): string {
  if (status === 'completed') return 'var(--color-success)';
  if (status === 'active') return 'var(--color-accent)';
  if (status === 'failed') return 'var(--color-error)';
  return 'var(--color-warning)';
}

function TaskItem({
  task,
  agentId,
  managedAgents,
  projectContext,
  onChanged,
}: {
  task: AgentTask;
  agentId: string;
  managedAgents: ManagedAgent[];
  projectContext?: AgentTaskProjectContext;
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draftDesc, setDraftDesc] = useState(task.description);
  const [draftStatus, setDraftStatus] = useState<AgentTask['status']>(task.status);
  const [busy, setBusy] = useState(false);

  function beginEdit() {
    setDraftDesc(task.description);
    setDraftStatus(task.status);
    setEditing(true);
  }

  async function commit() {
    const trimmed = draftDesc.trim();
    if (!trimmed) return;
    if (trimmed === task.description && draftStatus === task.status) {
      setEditing(false);
      return;
    }
    setBusy(true);
    try {
      await updateAgentTask(task.agent_id, task.id, { description: trimmed, status: draftStatus });
      setEditing(false);
      onChanged();
    } catch {
      toast.error('Failed to update task');
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!window.confirm('Delete this task? This cannot be undone.')) return;
    setBusy(true);
    try {
      await deleteAgentTask(task.agent_id, task.id);
      onChanged();
    } catch {
      toast.error('Failed to delete task');
      setBusy(false);
    }
  }

  if (editing) {
    return (
      <div
        className="p-3 rounded-lg space-y-2"
        style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-accent)' }}
      >
        <textarea
          autoFocus
          value={draftDesc}
          disabled={busy}
          onChange={(e) => setDraftDesc(e.target.value)}
          rows={3}
          className="w-full text-sm px-2 py-1 rounded outline-none resize-y"
          style={{
            color: 'var(--color-text)',
            background: 'var(--color-bg)',
            border: '1px solid var(--color-border)',
          }}
        />
        <div className="flex items-center justify-between gap-2">
          <select
            value={draftStatus}
            disabled={busy}
            onChange={(e) => setDraftStatus(e.target.value as AgentTask['status'])}
            className="text-xs px-2 py-1 rounded outline-none"
            style={{
              color: 'var(--color-text)',
              background: 'var(--color-bg)',
              border: '1px solid var(--color-border)',
            }}
          >
            {TASK_STATUSES.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          <div className="flex items-center gap-1">
            <button
              onClick={commit}
              disabled={busy}
              title="Save"
              className="p-1.5 rounded transition-colors"
              style={{ color: 'var(--color-accent)' }}
            >
              <Check size={15} />
            </button>
            <button
              onClick={() => setEditing(false)}
              disabled={busy}
              title="Cancel"
              className="p-1.5 rounded transition-colors"
              style={{ color: 'var(--color-text-tertiary)' }}
            >
              <X size={15} />
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      className="group p-3 rounded-lg"
      style={{
        background: 'var(--color-bg-secondary)',
        border: `1px solid ${taskStatusColor(task.status)}`,
      }}
    >
      <div className="flex justify-between items-start gap-3">
        <div className="space-y-1 min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <span
              className="text-[10px] px-1.5 py-0.5 rounded"
              style={{
                background:
                  task.agent_id === agentId
                    ? 'var(--color-accent-subtle)'
                    : 'var(--color-bg-tertiary)',
                color:
                  task.agent_id === agentId
                    ? 'var(--color-accent)'
                    : 'var(--color-text-secondary)',
              }}
            >
              {task.agent_id === agentId ? 'Performed here' : 'Passed to subordinate'}
            </span>
            {projectContext?.projectName && (
              <span
                className="text-[10px] px-1.5 py-0.5 rounded truncate max-w-[220px]"
                style={{
                  background: 'var(--color-bg-tertiary)',
                  color: 'var(--color-text-secondary)',
                }}
                title={projectContext.projectName}
              >
                {projectContext.projectName}
              </span>
            )}
          </div>
          <span className="text-sm block" style={{ color: 'var(--color-text)' }}>
            {task.description}
          </span>
          {projectContext?.projectTaskTitle && (
            <span className="text-xs block" style={{ color: 'var(--color-text-secondary)' }}>
              Project task: {projectContext.projectTaskTitle}
            </span>
          )}
          {task.agent_id !== agentId && (
            <span className="text-xs block" style={{ color: 'var(--color-text-tertiary)' }}>
              Assigned to {findAgentById(managedAgents, task.agent_id)?.name || task.agent_id}
            </span>
          )}
          {task.assigned_by_agent_id && (
            <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
              Assigned by {findAgentById(managedAgents, task.assigned_by_agent_id)?.name || task.assigned_by_agent_id}
            </span>
          )}
          {task.progress && Object.keys(task.progress).length > 0 && (
            <span className="text-xs block" style={{ color: 'var(--color-text-secondary)' }}>
              Progress: {String((task.progress as Record<string, unknown>).note || JSON.stringify(task.progress))}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <span
            className="text-xs px-2 py-0.5 rounded"
            style={{
              background: `color-mix(in srgb, ${taskStatusColor(task.status)} 18%, transparent)`,
              color: taskStatusColor(task.status),
            }}
          >
            {task.status}
          </span>
          <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
            <button
              onClick={beginEdit}
              disabled={busy}
              title="Edit task"
              className="p-1 rounded transition-colors"
              style={{ color: 'var(--color-text-tertiary)' }}
            >
              <Pencil size={13} />
            </button>
            <button
              onClick={remove}
              disabled={busy}
              title="Delete task"
              className="p-1 rounded transition-colors"
              style={{ color: 'var(--color-text-tertiary)' }}
              onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--color-error, #ef4444)')}
              onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--color-text-tertiary)')}
            >
              <Trash2 size={13} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function collectProjectTaskContext(data: MissionControlData | null) {
  const projectById = new Map<string, MissionControlProject>();
  const taskById = new Map<string, MissionControlTask & { projectId: string }>();
  const walk = (project: MissionControlProject, task: MissionControlTask) => {
    taskById.set(task.id, { ...task, projectId: project.id });
    task.subtasks?.forEach((subtask) => walk(project, subtask));
  };
  for (const project of data?.projects || []) {
    projectById.set(project.id, project);
    project.tasks?.forEach((task) => walk(project, task));
  }
  return { projectById, taskById };
}

function AgentNameField({ agent, onAgentUpdated }: { agent: ManagedAgent; onAgentUpdated: () => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);

  async function commit() {
    const trimmed = draft.trim();
    if (!trimmed || trimmed === agent.name) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await updateManagedAgent(agent.id, { name: trimmed });
      onAgentUpdated();
    } catch { /* keep the user in edit mode on failure */ setSaving(false); return; }
    setSaving(false);
    setEditing(false);
  }

  if (editing) {
    return (
      <input
        autoFocus
        value={draft}
        disabled={saving}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') { e.preventDefault(); commit(); }
          else if (e.key === 'Escape') { e.preventDefault(); setEditing(false); }
        }}
        className="text-xl font-semibold px-1 py-0 rounded outline-none"
        style={{
          color: 'var(--color-text)',
          background: 'var(--color-bg-secondary)',
          border: '1px solid var(--color-accent)',
          minWidth: 12 + draft.length + 'ch',
          maxWidth: '32ch',
        }}
      />
    );
  }

  return (
    <h1
      className="text-xl font-semibold cursor-text rounded px-1 -mx-1 transition-colors"
      style={{ color: 'var(--color-text)' }}
      title="Click to rename"
      onClick={() => { setDraft(agent.name); setEditing(true); }}
      onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-secondary)')}
      onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
    >
      {agent.name}
    </h1>
  );
}

function AgentAvatarSection({ agent, onAgentUpdated }: { agent: ManagedAgent; onAgentUpdated: () => void }) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [busy, setBusy] = useState(false);

  async function upload(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    try {
      await uploadAgentAvatar(agent.id, file);
      toast.success('Avatar updated');
      onAgentUpdated();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to upload avatar');
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = '';
    }
  }

  async function remove() {
    setBusy(true);
    try {
      await deleteAgentAvatar(agent.id);
      toast.success('Avatar removed');
      onAgentUpdated();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to remove avatar');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="p-3 rounded-lg"
      style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
    >
      <div className="flex items-start gap-3">
        <AgentAvatar agent={agent} size="lg" active={agent.status === 'running'} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>Avatar</h3>
            {agent.avatar_file_name && (
              <span className="truncate text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                {agent.avatar_file_name}
              </span>
            )}
          </div>
          <p className="mt-1 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
            Upload a small GIF, WebP, PNG, JPG, or looped MP4. Recommended 256x256. Max 2 MB.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <input
              ref={inputRef}
              type="file"
              accept="image/gif,image/webp,image/png,image/jpeg,video/mp4"
              className="hidden"
              onChange={(e) => upload(e.target.files?.[0])}
            />
            <button
              type="button"
              disabled={busy}
              onClick={() => inputRef.current?.click()}
              className="inline-flex items-center gap-1.5 rounded px-3 py-1.5 text-xs font-medium disabled:opacity-50"
              style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}
            >
              <Upload size={13} />
              {busy ? 'Working...' : 'Upload'}
            </button>
            <button
              type="button"
              disabled={busy || !agent.avatar_url}
              onClick={remove}
              className="inline-flex items-center gap-1.5 rounded px-3 py-1.5 text-xs disabled:opacity-50"
              style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
            >
              <Trash2 size={13} />
              Remove
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function AgentInstructionSection({ agent, onAgentUpdated }: { agent: ManagedAgent; onAgentUpdated: () => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const currentInstruction = (agent.config?.instruction as string) || '';

  async function save() {
    try {
      const newConfig = { ...(agent.config || {}), instruction: draft.trim() };
      await updateManagedAgent(agent.id, { config: newConfig });
      onAgentUpdated();
    } catch { /* ignore */ }
    setEditing(false);
  }

  return (
    <div
      className="p-3 rounded-lg"
      style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
    >
      <div className="flex items-center gap-2 mb-2">
        <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>Instruction</h3>
        {!editing && (
          <button
            onClick={() => { setDraft(currentInstruction); setEditing(true); }}
            className="text-xs px-2 py-0.5 rounded cursor-pointer"
            style={{ color: 'var(--color-accent)', border: '1px solid var(--color-accent)', opacity: 0.8 }}
          >
            Edit
          </button>
        )}
      </div>
      {editing ? (
        <div className="space-y-2">
          <textarea
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={3}
            className="w-full px-3 py-2 rounded-lg text-sm bg-transparent resize-none"
            style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
          />
          <div className="flex gap-2">
            <button onClick={save} className="text-xs px-3 py-1 rounded font-medium cursor-pointer" style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}>Save</button>
            <button onClick={() => setEditing(false)} className="text-xs px-3 py-1 rounded cursor-pointer" style={{ color: 'var(--color-text-tertiary)', border: '1px solid var(--color-border)' }}>Cancel</button>
          </div>
        </div>
      ) : (
        <p className="text-sm" style={{ color: currentInstruction ? 'var(--color-text)' : 'var(--color-text-tertiary)' }}>
          {currentInstruction || '(No instruction set — click Edit to add one)'}
        </p>
      )}
    </div>
  );
}

function AgentPersonalitySection({ agent, onAgentUpdated }: { agent: ManagedAgent; onAgentUpdated: () => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const currentPersonality = (agent.config?.personality as string) || '';

  async function save() {
    try {
      const newConfig = { ...(agent.config || {}), personality: draft.trim() };
      await updateManagedAgent(agent.id, { config: newConfig });
      onAgentUpdated();
    } catch { /* ignore */ }
    setEditing(false);
  }

  return (
    <div
      className="p-3 rounded-lg"
      style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
    >
      <div className="flex items-center gap-2 mb-2">
        <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>Personality</h3>
        <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
          Voice, tone, mannerisms — shapes how the agent replies.
        </span>
        {!editing && (
          <button
            onClick={() => { setDraft(currentPersonality); setEditing(true); }}
            className="text-xs px-2 py-0.5 rounded cursor-pointer ml-auto"
            style={{ color: 'var(--color-accent)', border: '1px solid var(--color-accent)', opacity: 0.8 }}
          >
            Edit
          </button>
        )}
      </div>
      {editing ? (
        <div className="space-y-2">
          <textarea
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={4}
            placeholder="e.g., Dry, witty British butler. Calls the user 'sir'. Avoids slang."
            className="w-full px-3 py-2 rounded-lg text-sm bg-transparent resize-none"
            style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
          />
          <div className="flex gap-2">
            <button onClick={save} className="text-xs px-3 py-1 rounded font-medium cursor-pointer" style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}>Save</button>
            <button onClick={() => setEditing(false)} className="text-xs px-3 py-1 rounded cursor-pointer" style={{ color: 'var(--color-text-tertiary)', border: '1px solid var(--color-border)' }}>Cancel</button>
          </div>
        </div>
      ) : (
        <p className="text-sm whitespace-pre-wrap" style={{ color: currentPersonality ? 'var(--color-text)' : 'var(--color-text-tertiary)' }}>
          {currentPersonality || '(No personality set — click Edit to give this agent a voice)'}
        </p>
      )}
    </div>
  );
}

function AgentConfigGrid({ agent, onAgentUpdated }: { agent: ManagedAgent; onAgentUpdated: () => void }) {
  const [editingModel, setEditingModel] = useState(false);
  const [changingModel, setChangingModel] = useState(false);
  const [models, setModels] = useState<string[]>([]);
  const currentModel = (agent.config?.model as string) || '(default)';

  // Model availability status: 'available' | 'unavailable' | 'unknown'
  const [modelAvailable, setModelAvailable] = useState<'available' | 'unavailable' | 'unknown'>('unknown');
  const [ollamaModels, setOllamaModels] = useState<string[]>([]);

  useEffect(() => {
    let cancelled = false;
    async function checkModel() {
      try {
        const res = await fetch('http://localhost:11434/api/tags');
        if (!res.ok) { setModelAvailable('unknown'); return; }
        const data = await res.json();
        const loadedNames: string[] = (data.models || []).map((m: { name: string }) => m.name);
        if (!cancelled) {
          setOllamaModels(loadedNames);
          if (currentModel === '(default)') {
            setModelAvailable(loadedNames.length > 0 ? 'available' : 'unknown');
          } else {
            const isLoaded = loadedNames.some(
              (n) => n === currentModel || n.startsWith(currentModel + ':') || currentModel.startsWith(n.split(':')[0])
            );
            setModelAvailable(isLoaded ? 'available' : 'unavailable');
          }
        }
      } catch {
        if (!cancelled) setModelAvailable('unknown');
      }
    }
    checkModel();
    return () => { cancelled = true; };
  }, [currentModel]);

  async function startEditingModel() {
    try {
      const fetched = await fetchModels();
      setModels(fetched.map((m) => m.id));
    } catch { /* ignore */ }
    // Also refresh Ollama models for availability indication
    try {
      const res = await fetch('http://localhost:11434/api/tags');
      if (res.ok) {
        const data = await res.json();
        setOllamaModels((data.models || []).map((m: { name: string }) => m.name));
      }
    } catch { /* ignore */ }
    setEditingModel(true);
  }

  function isModelLoaded(modelId: string): boolean {
    return ollamaModels.some(
      (n) => n === modelId || n.startsWith(modelId + ':') || modelId.startsWith(n.split(':')[0])
    );
  }

  async function changeModel(newModel: string) {
    setChangingModel(true);
    try {
      const newConfig = { ...(agent.config || {}), model: newModel };
      await updateManagedAgent(agent.id, { config: newConfig });
      onAgentUpdated();
      toast.success(`Model changed to ${newModel}`);
    } catch { /* ignore */ }
    setEditingModel(false);
    setChangingModel(false);
  }

  const modelStatusDot = modelAvailable === 'available'
    ? 'var(--color-success)'
    : modelAvailable === 'unavailable'
      ? 'var(--color-error)'
      : 'var(--color-text-tertiary)';

  const rows: [string, React.ReactNode][] = [
    ['Intelligence', editingModel ? (
      changingModel ? (
        <span className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>Switching model...</span>
      ) : (
        <select
          autoFocus
          defaultValue={currentModel}
          onChange={(e) => changeModel(e.target.value)}
          onBlur={() => setEditingModel(false)}
          className="text-sm rounded px-1 py-0.5"
          style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
        >
          {models.map((m) => {
            const loaded = isModelLoaded(m);
            return (
              <option key={m} value={m} style={!loaded ? { color: 'var(--color-text-tertiary)' } : undefined}>
                {m}{!loaded ? ' (not loaded)' : ''}
              </option>
            );
          })}
        </select>
      )
    ) : (
      <span className="flex items-center gap-2">
        <span
          style={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            background: modelStatusDot,
            display: 'inline-block',
            flexShrink: 0,
          }}
          title={
            modelAvailable === 'available' ? 'Model running'
              : modelAvailable === 'unavailable' ? 'Model not available'
                : 'Could not check model status'
          }
        />
        <span style={{ color: 'var(--color-text)' }}>{currentModel}</span>
        {modelAvailable === 'unavailable' && (
          <span className="text-xs" style={{ color: 'var(--color-error)' }}>Not available</span>
        )}
        <button
          onClick={startEditingModel}
          className="text-xs px-2 py-0.5 rounded cursor-pointer"
          style={{
            color: modelAvailable === 'unavailable' ? 'var(--color-error)' : 'var(--color-accent)',
            border: `1px solid ${modelAvailable === 'unavailable' ? 'var(--color-error)' : 'var(--color-accent)'}`,
            opacity: 0.8,
          }}
        >
          Change
        </button>
      </span>
    )],
    ['Agent Type', <span key="at">{agent.agent_type}</span>],
    ['Schedule', <span key="sc">{formatSchedule(agent.schedule_type, agent.schedule_value)}</span>],
    ['Last Run', <span key="lr">{formatRelativeTime(agent.last_run_at)}</span>],
    ['Budget', <span key="bg">{agent.budget ? formatCost(agent.budget) : 'Unlimited'}</span>],
    ['Learning', <span key="le">{agent.learning_enabled ? 'Enabled' : 'Disabled'}</span>],
  ];

  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-1.5">
      {rows.map(([label, value]) => (
        <div key={label as string} className="flex gap-2 items-center text-sm">
          <span className="font-medium" style={{ color: 'var(--color-text-secondary)', minWidth: 110 }}>{label}</span>
          <span style={{ color: 'var(--color-text)' }}>{value}</span>
        </div>
      ))}
    </div>
  );
}

function ChiefPendingCard({
  agent,
  onResumed,
}: {
  agent: ManagedAgent;
  onResumed: () => Promise<void> | void;
}) {
  const [question, setQuestion] = useState<string>('');
  const [reason, setReason] = useState<string>('');
  const [options, setOptions] = useState<string[]>([]);
  const [responseType, setResponseType] = useState<string>('free_text');
  const [answer, setAnswer] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(true);
  const [submitting, setSubmitting] = useState<boolean>(false);

  const isCredential = responseType === 'credential';

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchChiefPending(agent.id)
      .then((res) => {
        if (cancelled) return;
        if (res.pending && res.question) {
          setQuestion(res.question.question || '');
          setReason(res.question.reason || '');
          setOptions(res.question.options || []);
          setResponseType(res.question.expected_response_type || 'free_text');
        } else {
          setQuestion('');
        }
      })
      .catch(() => {
        if (!cancelled) setQuestion('');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [agent.id, agent.status]);

  if (loading) {
    return (
      <div
        className="mb-4 p-3 rounded-lg text-sm"
        style={{
          background: 'var(--color-bg-secondary)',
          border: '1px solid var(--color-border)',
          color: 'var(--color-text-secondary)',
        }}
      >
        Loading pending question...
      </div>
    );
  }

  if (!question) {
    return null;
  }

  async function handleSubmit() {
    const trimmed = answer.trim();
    if (!trimmed) {
      toast.error('Answer is required');
      return;
    }
    setSubmitting(true);
    try {
      const result = await resumeChief(agent.id, trimmed);
      toast.success('Chief resumed', {
        description: result.response.slice(0, 240) || undefined,
      });
      setAnswer('');
      await onResumed();
    } catch (err: any) {
      toast.error('Resume failed', {
        description: err?.message || 'Unknown error',
      });
    } finally {
      setSubmitting(false);
    }
  }

  const borderColor = isCredential ? 'var(--color-warning)' : 'var(--color-accent)';
  const accentColor = isCredential ? 'var(--color-warning)' : 'var(--color-accent)';
  const headerLabel = isCredential
    ? 'Chief needs credentials'
    : 'Chief is waiting on your answer';

  return (
    <div
      className="mb-4 p-4 rounded-lg"
      style={{
        background: 'var(--color-bg-secondary)',
        border: `1px solid ${borderColor}40`,
      }}
    >
      <div className="flex items-center gap-2 mb-2">
        <MessageSquare size={15} style={{ color: accentColor }} />
        <span className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
          {headerLabel}
        </span>
      </div>
      <div className="mb-2 text-sm" style={{ color: 'var(--color-text)' }}>
        {question}
      </div>
      {reason && (
        <div className="mb-3 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
          Why: {reason}
        </div>
      )}
      {options.length > 0 && (
        <div className="mb-3 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
          Options: {options.join(', ')}
        </div>
      )}
      {isCredential ? (
        <input
          type="password"
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          placeholder="Paste the credential..."
          autoComplete="new-password"
          className="w-full px-3 py-2 rounded-lg text-sm mb-3"
          style={{
            background: 'var(--color-bg)',
            border: '1px solid var(--color-border)',
            color: 'var(--color-text)',
          }}
          disabled={submitting}
        />
      ) : (
        <textarea
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          placeholder="Type your answer..."
          rows={3}
          className="w-full px-3 py-2 rounded-lg text-sm mb-3"
          style={{
            background: 'var(--color-bg)',
            border: '1px solid var(--color-border)',
            color: 'var(--color-text)',
            resize: 'vertical',
          }}
          disabled={submitting}
        />
      )}
      {isCredential && (
        <div className="mb-3 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
          The chief sees your raw input on the resumed turn only. The
          trace store and the message log persist a redacted placeholder,
          not the value itself. Treat this as a one-time secret transfer:
          the chief can use it within its current run, but it will not
          survive in any audit log.
        </div>
      )}
      <div className="flex justify-end">
        <button
          onClick={handleSubmit}
          disabled={submitting || !answer.trim()}
          className="px-3 py-1.5 rounded-lg text-xs cursor-pointer disabled:opacity-50"
          style={{ background: accentColor, color: 'var(--color-on-accent)' }}
        >
          {submitting ? 'Resuming...' : isCredential ? 'Submit credential' : 'Submit answer'}
        </button>
      </div>
    </div>
  );
}

// Skills have no server-side category, so group them by name keywords for
// the Capability Inspector. Order is intentional (most relevant first).
const SKILL_GROUPS: { label: string; match: (n: string) => boolean }[] = [
  { label: 'Project', match: (n) => n.includes('project') },
  {
    label: 'Knowledge & Research',
    match: (n) =>
      /knowledge|research|topic|search-and-index|arxiv|llm-wiki/.test(n),
  },
  {
    label: 'Documents & Notes',
    match: (n) =>
      /doc|pdf|summarize|translate|meeting|notes|todo|digest|email|calendar/.test(
        n,
      ),
  },
  {
    label: 'Files',
    match: (n) => /file|backup|dedup|organiz/.test(n),
  },
  {
    label: 'Code',
    match: (n) =>
      /code|codex|dependency-audit|security-scan|test-gen|lint|review/.test(n),
  },
  {
    label: 'Web & Media',
    match: (n) => /web|blog|polymarket|song|music|image|audio|ascii|art/.test(n),
  },
];

function skillGroupLabel(name: string): string {
  const n = name.toLowerCase();
  for (const group of SKILL_GROUPS) {
    if (group.match(n)) return group.label;
  }
  return 'Other';
}

const SKILL_GROUP_ORDER = [...SKILL_GROUPS.map((g) => g.label), 'Other'];

// ── Phase 2B: Capability Inspector ────────────────────────────────────
//
// Renders the 6-axis capability view (assigned / inherited / effective /
// blocked / requires_approval / disabled) backed by the new
// ``enrich_agent_record`` keys from Phase 2A. Includes a Preview modal
// (calls /preview) and a Version history drawer (calls /versions and
// /revert). Wired below AgentPresetToolsSection on the Overview tab.
//
// Per the Phase 2 plan: this is additive. AgentPresetToolsSection keeps
// rendering — the Inspector is a complementary read-mostly surface for
// now. Bulk actions, drag-reorder, conflict warnings, and search/filter
// are deferred to a follow-up.

type CapabilityAxis = 'assigned' | 'inherited' | 'effective' | 'blocked' | 'requires_approval';

const AXIS_LABELS: Record<CapabilityAxis, string> = {
  assigned: 'Assigned',
  inherited: 'Inherited',
  effective: 'Effective',
  blocked: 'Blocked',
  requires_approval: 'Approval-gated',
};

const AXIS_COLORS: Record<CapabilityAxis, { bg: string; fg: string; border: string }> = {
  assigned: { bg: 'var(--color-accent-subtle)', fg: 'var(--color-accent)', border: 'var(--color-accent)' },
  inherited: { bg: 'var(--color-bg-secondary)', fg: 'var(--color-text-secondary)', border: 'var(--color-border)' },
  effective: { bg: 'var(--color-bg-tertiary)', fg: 'var(--color-text)', border: 'var(--color-border)' },
  blocked: { bg: 'transparent', fg: 'var(--color-error)', border: 'var(--color-error)' },
  requires_approval: { bg: 'var(--color-accent-amber-subtle)', fg: 'var(--color-accent-amber)', border: 'var(--color-accent-amber)' },
};

function AxisChip({ label, axis, title }: { label: string; axis: CapabilityAxis; title?: string }) {
  const c = AXIS_COLORS[axis];
  return (
    <span
      title={title || AXIS_LABELS[axis]}
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium"
      style={{ background: c.bg, color: c.fg, border: `1px solid ${c.border}` }}
    >
      <span aria-hidden style={{ width: 4, height: 4, borderRadius: 4, background: c.fg, display: 'inline-block' }} />
      {label}
    </span>
  );
}

function _formatVersionTime(t: number | undefined): string {
  if (!t) return '—';
  const d = new Date(t * 1000);
  return `${d.toLocaleDateString()} ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
}

function CapabilityInspector({
  agent,
  onAgentUpdated,
}: { agent: ManagedAgent; onAgentUpdated: () => void }) {
  const [previewOpen, setPreviewOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [previewData, setPreviewData] = useState<ManagedAgent | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [versions, setVersions] = useState<AgentConfigVersion[]>([]);
  const [versionsLoading, setVersionsLoading] = useState(false);
  const [reverting, setReverting] = useState<string | null>(null);

  const assignedSkills = useMemo(
    () => agent.configured_skills ?? [],
    [agent.configured_skills],
  );
  const inheritedSkills = useMemo(
    () => agent.inherited_skills ?? [],
    [agent.inherited_skills],
  );
  const blockedSkills = useMemo(
    () => agent.blocked_skills ?? [],
    [agent.blocked_skills],
  );
  const approvalSkills = useMemo(
    () => agent.requires_approval_skills ?? [],
    [agent.requires_approval_skills],
  );
  const effectiveSkills = useMemo(
    () => agent.effective_skills ?? [],
    [agent.effective_skills],
  );
  const assignedTools = useMemo(() => agent.configured_tools ?? [], [agent.configured_tools]);
  const inheritedTools = useMemo(() => agent.inherited_tools ?? [], [agent.inherited_tools]);
  const blockedTools = useMemo(() => agent.blocked_tools ?? [], [agent.blocked_tools]);
  const approvalTools = useMemo(() => agent.requires_approval_tools ?? [], [agent.requires_approval_tools]);
  const autoTools = useMemo(() => agent.auto_tools ?? [], [agent.auto_tools]);
  const effectiveTools = useMemo(() => agent.effective_tools ?? [], [agent.effective_tools]);

  async function openPreview() {
    setPreviewOpen(true);
    setPreviewLoading(true);
    try {
      setPreviewData(await previewAgentCapabilities(agent.id));
    } catch (err) {
      toast.error(`Preview failed: ${(err as Error).message}`);
      setPreviewOpen(false);
    } finally {
      setPreviewLoading(false);
    }
  }

  async function openHistory() {
    setHistoryOpen(true);
    setVersionsLoading(true);
    try {
      setVersions(await fetchAgentConfigVersions(agent.id));
    } catch (err) {
      toast.error(`History fetch failed: ${(err as Error).message}`);
      setHistoryOpen(false);
    } finally {
      setVersionsLoading(false);
    }
  }

  async function doRevert(versionId: string) {
    setReverting(versionId);
    try {
      await revertAgentConfig(agent.id, versionId);
      toast.success('Reverted — new version appended.');
      onAgentUpdated();
      setVersions(await fetchAgentConfigVersions(agent.id));
    } catch (err) {
      toast.error(`Revert failed: ${(err as Error).message}`);
    } finally {
      setReverting(null);
    }
  }

  function renderChipRow(items: string[], axis: CapabilityAxis) {
    if (items.length === 0) {
      return (
        <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
          —
        </span>
      );
    }
    return (
      <div className="flex flex-wrap gap-1.5">
        {items.map((name) => (
          <AxisChip key={`${axis}-${name}`} label={name} axis={axis} />
        ))}
      </div>
    );
  }

  return (
    <div
      className="p-3 rounded-lg"
      style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
    >
      <div className="flex items-center justify-between gap-3 mb-3">
        <div>
          <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
            Capability Inspector
          </h3>
          <p className="text-xs mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>
            Assigned vs inherited vs blocked vs approval-gated — runtime effective view.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={openPreview}
            className="text-xs px-2.5 py-1 rounded cursor-pointer"
            style={{ color: 'var(--color-accent)', border: '1px solid var(--color-accent)', opacity: 0.85 }}
            aria-label="Preview runtime capabilities"
          >
            Preview
          </button>
          <button
            onClick={openHistory}
            className="text-xs px-2.5 py-1 rounded cursor-pointer"
            style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
            aria-label="View configuration history"
          >
            History
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-3">
        <section>
          <div className="text-xs font-semibold uppercase tracking-wide mb-1.5" style={{ color: 'var(--color-text-tertiary)' }}>
            Skills
          </div>
          <div className="space-y-1.5">
            <Row label="Assigned">{renderChipRow(assignedSkills, 'assigned')}</Row>
            <Row label="Inherited">{renderChipRow(inheritedSkills, 'inherited')}</Row>
            <Row label="Blocked">{renderChipRow(blockedSkills, 'blocked')}</Row>
            <Row label="Approval">{renderChipRow(approvalSkills, 'requires_approval')}</Row>
            <Row label="Effective">{renderChipRow(effectiveSkills, 'effective')}</Row>
          </div>
        </section>
        <section>
          <div className="text-xs font-semibold uppercase tracking-wide mb-1.5" style={{ color: 'var(--color-text-tertiary)' }}>
            Tools
          </div>
          <div className="space-y-1.5">
            <Row label="Assigned">{renderChipRow(assignedTools, 'assigned')}</Row>
            <Row label="Inherited">{renderChipRow(inheritedTools, 'inherited')}</Row>
            <Row label="Auto">{renderChipRow(autoTools, 'inherited')}</Row>
            <Row label="Blocked">{renderChipRow(blockedTools, 'blocked')}</Row>
            <Row label="Approval">{renderChipRow(approvalTools, 'requires_approval')}</Row>
            <Row label="Effective">{renderChipRow(effectiveTools, 'effective')}</Row>
          </div>
        </section>
      </div>

      {previewOpen && (
        <CapabilityPreviewModal
          loading={previewLoading}
          data={previewData}
          onClose={() => { setPreviewOpen(false); setPreviewData(null); }}
        />
      )}
      {historyOpen && (
        <ConfigHistoryDrawer
          versions={versions}
          loading={versionsLoading}
          reverting={reverting}
          onRevert={doRevert}
          onClose={() => setHistoryOpen(false)}
        />
      )}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2 text-xs">
      <span
        className="font-medium pt-0.5"
        style={{ color: 'var(--color-text-secondary)', minWidth: 78, display: 'inline-block' }}
      >
        {label}
      </span>
      <div className="flex-1 min-w-0">{children}</div>
    </div>
  );
}

function CapabilityPreviewModal({
  loading,
  data,
  onClose,
}: {
  loading: boolean;
  data: ManagedAgent | null;
  onClose: () => void;
}) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Effective runtime capabilities"
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: 'rgba(0,0,0,0.4)' }}
      onClick={onClose}
    >
      <div
        className="rounded-xl p-5 max-w-lg w-full mx-4 max-h-[80vh] overflow-y-auto"
        style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)' }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center mb-3">
          <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
            Effective runtime capabilities
          </h3>
          <button
            onClick={onClose}
            className="text-sm cursor-pointer"
            style={{ color: 'var(--color-text-tertiary)' }}
            aria-label="Close preview"
          >
            ×
          </button>
        </div>
        {loading && <p className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>Loading…</p>}
        {!loading && data && (
          <div className="space-y-3 text-sm">
            <div>
              <div className="text-xs uppercase tracking-wide mb-1" style={{ color: 'var(--color-text-tertiary)' }}>
                Skills ({(data.effective_skills ?? []).length})
              </div>
              <div className="flex flex-wrap gap-1.5">
                {(data.effective_skills ?? []).map((s) => (
                  <AxisChip key={`prev-s-${s}`} label={s} axis="effective" />
                ))}
                {(data.effective_skills ?? []).length === 0 && (
                  <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>None</span>
                )}
              </div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wide mb-1" style={{ color: 'var(--color-text-tertiary)' }}>
                Tools ({(data.effective_tools ?? []).length})
              </div>
              <div className="flex flex-wrap gap-1.5">
                {(data.effective_tools ?? []).map((t) => (
                  <AxisChip key={`prev-t-${t}`} label={t} axis="effective" />
                ))}
                {(data.effective_tools ?? []).length === 0 && (
                  <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>None</span>
                )}
              </div>
            </div>
            {(data.requires_approval_skills ?? []).length + (data.requires_approval_tools ?? []).length > 0 && (
              <div className="pt-2" style={{ borderTop: '1px solid var(--color-border)' }}>
                <div className="text-xs uppercase tracking-wide mb-1" style={{ color: 'var(--color-accent-amber)' }}>
                  Approval-gated
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {(data.requires_approval_skills ?? []).map((s) => (
                    <AxisChip key={`prev-as-${s}`} label={s} axis="requires_approval" />
                  ))}
                  {(data.requires_approval_tools ?? []).map((t) => (
                    <AxisChip key={`prev-at-${t}`} label={t} axis="requires_approval" />
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
        <div className="mt-4 flex justify-end">
          <button
            onClick={onClose}
            className="text-xs px-3 py-1 rounded cursor-pointer"
            style={{ color: 'var(--color-text-tertiary)', border: '1px solid var(--color-border)' }}
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

function ConfigHistoryDrawer({
  versions,
  loading,
  reverting,
  onRevert,
  onClose,
}: {
  versions: AgentConfigVersion[];
  loading: boolean;
  reverting: string | null;
  onRevert: (versionId: string) => Promise<void> | void;
  onClose: () => void;
}) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Configuration history"
      className="fixed inset-y-0 right-0 z-50 w-full max-w-md shadow-xl overflow-y-auto"
      style={{ background: 'var(--color-bg)', borderLeft: '1px solid var(--color-border)' }}
    >
      <div className="sticky top-0 flex justify-between items-center px-4 py-3" style={{ background: 'var(--color-bg)', borderBottom: '1px solid var(--color-border)' }}>
        <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
          Configuration history
        </h3>
        <button
          onClick={onClose}
          aria-label="Close history"
          className="text-sm cursor-pointer"
          style={{ color: 'var(--color-text-tertiary)' }}
        >
          ×
        </button>
      </div>
      <div className="p-4 space-y-2">
        {loading && <p className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>Loading…</p>}
        {!loading && versions.length === 0 && (
          <p className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
            No history yet. Saving a config change will create the first version.
          </p>
        )}
        {!loading && versions.map((v) => {
          const changedKeys = Object.keys(v.diff?.changed || {});
          const addedKeys = Object.keys(v.diff?.added || {});
          const removedKeys = Object.keys(v.diff?.removed || {});
          return (
            <div
              key={v.id}
              className="rounded-lg p-3"
              style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
            >
              <div className="flex justify-between items-center mb-1">
                <span className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
                  v{v.version_number}
                </span>
                <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                  {_formatVersionTime(v.created_at)}
                  {v.created_by ? ` · ${v.created_by}` : ''}
                </span>
              </div>
              {v.summary && (
                <p className="text-xs mb-1" style={{ color: 'var(--color-text-secondary)' }}>{v.summary}</p>
              )}
              <div className="text-xs mb-2" style={{ color: 'var(--color-text-tertiary)' }}>
                {addedKeys.length > 0 && <span>+{addedKeys.length} </span>}
                {removedKeys.length > 0 && <span>−{removedKeys.length} </span>}
                {changedKeys.length > 0 && <span>~{changedKeys.length}</span>}
                {addedKeys.length + removedKeys.length + changedKeys.length === 0 && (
                  <span>no diff</span>
                )}
              </div>
              <button
                disabled={reverting === v.id}
                onClick={() => onRevert(v.id)}
                className="text-xs px-2 py-0.5 rounded cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                style={{ color: 'var(--color-accent)', border: '1px solid var(--color-accent)' }}
              >
                {reverting === v.id ? 'Reverting…' : 'Revert to this version'}
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function AgentPresetToolsSection({
  agent,
  managedAgents,
  templates,
  skills,
  onAgentUpdated,
  onOpenLibrary,
}: {
  agent: ManagedAgent;
  managedAgents: ManagedAgent[];
  templates: AgentTemplate[];
  skills: InstalledSkill[];
  onAgentUpdated: () => void;
  onOpenLibrary: () => void;
}) {
  const configuredTools = Array.isArray(agent.configured_tools)
    ? agent.configured_tools
    : Array.isArray(agent.config?.tools)
      ? (agent.config.tools as unknown[]).filter((tool): tool is string => typeof tool === 'string')
      : [];
  const configuredSkills = Array.isArray(agent.configured_skills)
    ? agent.configured_skills
    : Array.isArray(agent.config?.skills)
      ? (agent.config.skills as unknown[]).filter((skill): skill is string => typeof skill === 'string')
      : [];
  const autoTools = Array.isArray(agent.auto_tools) ? agent.auto_tools : [];
  const effectiveTools = Array.isArray(agent.effective_tools)
    ? agent.effective_tools
    : [...configuredTools, ...autoTools.filter((tool) => !configuredTools.includes(tool))];
  const effectiveSkills = Array.isArray(agent.effective_skills)
    ? agent.effective_skills
    : configuredSkills;
  const templateId =
    agent.template_id ||
    (typeof agent.config?.template_id === 'string' ? agent.config.template_id : '');
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [presetId, setPresetId] = useState(templateId);
  const [selectedSkills, setSelectedSkills] = useState<string[]>(configuredSkills);
  const [chiefMode, setChiefMode] = useState<boolean>(
    (agent.config?.orchestrator_mode as string | undefined) === 'chief',
  );
  const [skillQuery, setSkillQuery] = useState('');
  const [collapsedSkillGroups, setCollapsedSkillGroups] = useState<Set<string>>(
    new Set(),
  );
  const groupedSkills = useMemo(() => {
    const q = skillQuery.trim().toLowerCase();
    const buckets = new Map<string, InstalledSkill[]>();
    for (const skill of skills) {
      if (
        q &&
        !skill.name.toLowerCase().includes(q) &&
        !(skill.description || '').toLowerCase().includes(q)
      ) {
        continue;
      }
      const label = skillGroupLabel(skill.name);
      if (!buckets.has(label)) buckets.set(label, []);
      buckets.get(label)!.push(skill);
    }
    return SKILL_GROUP_ORDER.filter((label) => buckets.has(label)).map(
      (label) => ({
        label,
        items: buckets
          .get(label)!
          .slice()
          .sort((a, b) => a.name.localeCompare(b.name)),
      }),
    );
  }, [skills, skillQuery]);
  const setGroupSelected = (names: string[], on: boolean) =>
    setSelectedSkills((current) => {
      const set = new Set(current);
      for (const name of names) {
        if (on) set.add(name);
        else set.delete(name);
      }
      return Array.from(set);
    });
  const toggleSkillGroup = (label: string) =>
    setCollapsedSkillGroups((current) => {
      const next = new Set(current);
      if (next.has(label)) next.delete(label);
      else next.add(label);
      return next;
    });
  const templateName = templateId
    ? (templates.find((tpl) => tpl.id === templateId)?.name || templateId)
    : 'Custom';
  const manager = findAgentById(managedAgents, agent.manager_agent_id);
  const directReports = managedAgents.filter((candidate) => candidate.manager_agent_id === agent.id);
  const hierarchyPath = buildManagementChain(agent, managedAgents)
    .map((entry) => entry.name)
    .join(' > ');
  const dataSources = Array.from(
    new Set(
      [
        ...((agent.config?.data_sources as unknown[]) || []),
        ...((agent.config?.connectors as unknown[]) || []),
        ...((agent.config?.sources as unknown[]) || []),
      ]
        .filter((item): item is string => typeof item === 'string')
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  );
  const inheritedSkillCount = Math.max(0, effectiveSkills.length - configuredSkills.length);
  const filteredSkillNames = new Set(groupedSkills.flatMap((group) => group.items.map((skill) => skill.name)));

  useEffect(() => {
    setEditing(false);
    setSaving(false);
    setPresetId(templateId);
    setSelectedSkills(configuredSkills);
    setChiefMode(
      (agent.config?.orchestrator_mode as string | undefined) === 'chief',
    );
  }, [agent.id, templateId, configuredSkills.join('|')]);

  const panelStyle: CSSProperties = {
    background:
      'linear-gradient(180deg, color-mix(in srgb, var(--color-bg-secondary) 94%, var(--color-accent) 6%), var(--color-bg-secondary))',
    border: '1px solid color-mix(in srgb, var(--color-border) 72%, var(--color-accent) 28%)',
    boxShadow: '0 16px 50px rgba(0, 0, 0, 0.18)',
  };
  const insetStyle: CSSProperties = {
    background: 'color-mix(in srgb, var(--color-bg) 82%, var(--color-accent) 18%)',
    border: '1px solid color-mix(in srgb, var(--color-border) 72%, var(--color-accent) 28%)',
  };
  const metricCard = (
    label: string,
    value: string | number,
    Icon: typeof PackageCheck,
    sublabel?: string,
  ) => (
    <div className="flex items-center gap-3 px-4 py-3 min-w-0" style={insetStyle}>
      <div
        className="h-9 w-9 rounded-lg flex items-center justify-center shrink-0"
        style={{
          background: 'color-mix(in srgb, var(--color-accent) 16%, transparent)',
          color: 'var(--color-accent)',
          border: '1px solid color-mix(in srgb, var(--color-accent) 38%, transparent)',
        }}
      >
        <Icon size={17} />
      </div>
      <div className="min-w-0">
        <div className="text-[11px] uppercase" style={{ color: 'var(--color-text-tertiary)' }}>
          {label}
        </div>
        <div className="text-lg font-semibold leading-tight truncate" style={{ color: 'var(--color-text)' }}>
          {value}
        </div>
        {sublabel && (
          <div className="text-xs truncate" style={{ color: 'var(--color-text-tertiary)' }}>
            {sublabel}
          </div>
        )}
      </div>
    </div>
  );
  const capabilityChip = (item: string, removable = false) => (
    <span
      key={item}
      className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs"
      style={{
        background: 'color-mix(in srgb, var(--color-bg) 72%, var(--color-accent) 12%)',
        border: '1px solid var(--color-border)',
        color: 'var(--color-text-secondary)',
      }}
    >
      {item}
      {removable && (
        <button
          type="button"
          onClick={() => toggleSkill(item)}
          className="cursor-pointer"
          style={{ color: 'var(--color-text-tertiary)' }}
          aria-label={`Remove ${item}`}
        >
          <X size={12} />
        </button>
      )}
    </span>
  );
  const renderBadgeGroup = (label: string, items: string[]) => (
    <div key={label}>{items.map((item) => capabilityChip(item))}</div>
  );

  async function handleSave() {
    setSaving(true);
    try {
      const chosenTemplate = templates.find((tpl) => tpl.id === presetId);
      const applied = applyTemplateConfig(
        (agent.config || {}) as Record<string, unknown>,
        chosenTemplate,
        selectedSkills,
      );
      if (!presetId) {
        delete applied.config.template_id;
      }
      if (chiefMode) {
        applied.config.orchestrator_mode = 'chief';
      } else {
        delete applied.config.orchestrator_mode;
      }
      const body: Parameters<typeof updateManagedAgent>[1] = {
        config: applied.config,
      };
      if (presetId && applied.agentType) {
        body.agent_type = applied.agentType;
      }
      await updateManagedAgent(agent.id, body);
      setEditing(false);
      onAgentUpdated();
      toast.success('Capabilities updated');
    } catch (err: any) {
      toast.error(err?.message || 'Failed to update capabilities');
    } finally {
      setSaving(false);
    }
  }

  function toggleSkill(skillName: string) {
    setSelectedSkills((current) =>
      current.includes(skillName)
        ? current.filter((entry) => entry !== skillName)
        : [...current, skillName],
    );
  }

  return (
    <section className="rounded-2xl overflow-hidden" style={panelStyle}>
      <div className="px-5 py-4 border-b" style={{ borderColor: 'color-mix(in srgb, var(--color-border) 78%, var(--color-accent) 22%)' }}>
        <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <div className="text-xs uppercase font-semibold" style={{ color: 'var(--color-accent)' }}>
              Jarvis Agent Overview
            </div>
            <h3 className="mt-1 text-xl font-semibold" style={{ color: 'var(--color-text)' }}>
              Capability Inspector
            </h3>
          </div>
          <div className="grid gap-2 text-sm md:grid-cols-4 xl:min-w-[760px]">
            <div className="px-3 py-2" style={insetStyle}>
              <div className="text-[11px] uppercase" style={{ color: 'var(--color-text-tertiary)' }}>Agent Name</div>
              <div className="truncate" style={{ color: 'var(--color-text)' }}>{agent.name}</div>
            </div>
            <div className="px-3 py-2" style={insetStyle}>
              <div className="text-[11px] uppercase" style={{ color: 'var(--color-text-tertiary)' }}>Role</div>
              <div className="truncate" style={{ color: 'var(--color-text)' }}>{roleLabel(agent)}</div>
            </div>
            <div className="px-3 py-2" style={insetStyle}>
              <div className="text-[11px] uppercase" style={{ color: 'var(--color-text-tertiary)' }}>Status</div>
              <div className="flex items-center gap-2" style={{ color: 'var(--color-text)' }}>
                <StatusDot status={agent.status} />
                {agent.status.replace('_', ' ')}
              </div>
            </div>
            <div className="px-3 py-2" style={insetStyle}>
              <div className="text-[11px] uppercase" style={{ color: 'var(--color-text-tertiary)' }}>Hierarchy Path</div>
              <div className="truncate" style={{ color: 'var(--color-text)' }}>{hierarchyPath || agent.name}</div>
            </div>
          </div>
        </div>

        <div className="mt-4 grid gap-2 md:grid-cols-2 xl:grid-cols-5">
          {metricCard('Preset', templateName, PackageCheck, presetId ? 'Template' : 'Custom')}
          {metricCard('Assigned Skills', selectedSkills.length, Network)}
          {metricCard('Effective Skills', effectiveSkills.length, ShieldCheck, `${inheritedSkillCount} inherited`)}
          {metricCard('Data Sources', dataSources.length, Database, agent.knowledge_enabled ? 'Knowledge on' : 'Knowledge off')}
          {metricCard('Active Tools', effectiveTools.length, Boxes)}
        </div>
      </div>

      <div className="grid gap-4 p-4 xl:grid-cols-[320px_minmax(520px,1fr)] 2xl:grid-cols-[340px_minmax(540px,1fr)_390px]">
        <aside className="space-y-4">
          <div className="rounded-xl p-4" style={insetStyle}>
            <div className="mb-4 flex items-center justify-between">
              <h4 className="text-sm font-semibold uppercase" style={{ color: 'var(--color-text-secondary)' }}>Agent Configuration</h4>
              <SlidersHorizontal size={16} style={{ color: 'var(--color-text-tertiary)' }} />
            </div>
            <label className="block text-sm">
              <span className="mb-1 block text-xs" style={{ color: 'var(--color-text-tertiary)' }}>Preset</span>
              <select
                value={presetId}
                onChange={(e) => {
                  setPresetId(e.target.value);
                  setEditing(true);
                }}
                className="w-full rounded-lg px-3 py-2 text-sm outline-none"
                style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
              >
                <option value="">Custom</option>
                {templates.map((template) => (
                  <option key={template.id} value={template.id}>{template.name}</option>
                ))}
              </select>
            </label>
            <label className="mt-4 flex items-center justify-between gap-3 text-sm" style={{ color: 'var(--color-text)' }}>
              <span>
                <span className="block">Knowledge Access</span>
                <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>Organization knowledge</span>
              </span>
              <span className="relative inline-flex h-6 w-11 items-center rounded-full" style={{ background: agent.knowledge_enabled ? 'var(--color-accent)' : 'var(--color-bg)', border: '1px solid var(--color-border)' }}>
                <span className="inline-block h-4 w-4 rounded-full transition-transform" style={{ background: 'var(--color-text)', transform: agent.knowledge_enabled ? 'translateX(22px)' : 'translateX(4px)' }} />
              </span>
            </label>
            <label className="mt-3 flex items-center gap-2 rounded-lg p-2 text-sm cursor-pointer" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
              <input
                type="checkbox"
                checked={chiefMode}
                onChange={(e) => {
                  setChiefMode(e.target.checked);
                  setEditing(true);
                }}
                className="cursor-pointer"
              />
              <span style={{ color: 'var(--color-text-secondary)' }}>Chief Orchestrator</span>
            </label>
          </div>

          <div className="rounded-xl p-4" style={insetStyle}>
            <div className="mb-3 flex items-center justify-between">
              <h4 className="text-sm font-semibold uppercase" style={{ color: 'var(--color-text-secondary)' }}>Data Sources</h4>
              <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>{dataSources.length || 3} connected</span>
            </div>
            <div className="space-y-2">
              {(dataSources.length ? dataSources : ['Knowledge index', 'Project memory', 'Agent messages']).map((source) => (
                <div key={source} className="flex items-center justify-between rounded-lg px-3 py-2 text-sm" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
                  <span className="truncate" style={{ color: 'var(--color-text)' }}>{source}</span>
                  <span className="h-2 w-2 rounded-full" style={{ background: 'var(--color-success)' }} />
                </div>
              ))}
            </div>
            <button type="button" onClick={onOpenLibrary} className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm cursor-pointer" style={{ border: '1px solid var(--color-accent)', color: 'var(--color-accent)' }}>
              <Plus size={15} />
              Add Data Source
            </button>
          </div>
        </aside>

        <main className="rounded-xl p-4 min-w-0" style={insetStyle}>
          <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <h4 className="text-sm font-semibold uppercase" style={{ color: 'var(--color-text-secondary)' }}>Skills Library</h4>
            <div className="flex gap-2">
              <div className="relative min-w-[220px]">
                <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: 'var(--color-text-tertiary)' }} />
                <input
                  value={skillQuery}
                  onChange={(e) => setSkillQuery(e.target.value)}
                  placeholder="Search skills..."
                  className="w-full rounded-lg py-2 pl-9 pr-3 text-sm outline-none"
                  style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                />
              </div>
              <button type="button" onClick={onOpenLibrary} className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm cursor-pointer" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}>
                <SlidersHorizontal size={15} />
                Filter
              </button>
            </div>
          </div>
          <div className="mb-4 flex flex-wrap gap-2">
            {SKILL_GROUP_ORDER.filter((label) => groupedSkills.some((group) => group.label === label)).map((label) => (
              <button
                type="button"
                key={label}
                onClick={() => toggleSkillGroup(label)}
                className="rounded-lg px-3 py-1.5 text-xs cursor-pointer"
                style={{ background: collapsedSkillGroups.has(label) ? 'transparent' : 'color-mix(in srgb, var(--color-accent) 14%, transparent)', border: '1px solid var(--color-border)', color: collapsedSkillGroups.has(label) ? 'var(--color-text-secondary)' : 'var(--color-accent)' }}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="space-y-3 max-h-[560px] overflow-y-auto pr-1">
            {groupedSkills.map((group) => {
              const open = !collapsedSkillGroups.has(group.label);
              const names = group.items.map((skill) => skill.name);
              return (
                <div key={group.label} className="rounded-xl" style={{ border: '1px solid var(--color-border)' }}>
                  <div className="flex items-center justify-between px-3 py-2">
                    <button type="button" onClick={() => toggleSkillGroup(group.label)} className="flex items-center gap-2 text-xs font-semibold uppercase cursor-pointer" style={{ color: 'var(--color-accent)' }}>
                      <ChevronRight size={13} style={{ transform: open ? 'rotate(90deg)' : 'none', transition: 'transform .15s' }} />
                      {group.label}
                      <span className="rounded px-1.5 py-0.5" style={{ background: 'var(--color-bg)', color: 'var(--color-text-tertiary)' }}>{group.items.length}</span>
                    </button>
                    <div className="flex items-center gap-3 text-xs">
                      <button type="button" onClick={() => { setGroupSelected(names, true); setEditing(true); }} className="cursor-pointer" style={{ color: 'var(--color-accent)' }}>All</button>
                      <button type="button" onClick={() => { setGroupSelected(names, false); setEditing(true); }} className="cursor-pointer" style={{ color: 'var(--color-text-secondary)' }}>None</button>
                    </div>
                  </div>
                  {open && (
                    <div className="grid gap-2 p-2 2xl:grid-cols-2">
                      {group.items.map((skill) => {
                        const checked = selectedSkills.includes(skill.name);
                        return (
                          <button
                            key={skill.name}
                            type="button"
                            onClick={() => { toggleSkill(skill.name); setEditing(true); }}
                            className="flex min-h-[76px] min-w-0 items-start gap-3 rounded-lg p-3 text-left transition-colors"
                            style={{ background: checked ? 'color-mix(in srgb, var(--color-accent) 15%, var(--color-bg-secondary))' : 'var(--color-bg-secondary)', border: `1px solid ${checked ? 'var(--color-accent)' : 'var(--color-border)'}` }}
                          >
                            <div className="mt-0.5 flex h-8 w-8 items-center justify-center rounded-lg shrink-0" style={{ background: 'color-mix(in srgb, var(--color-accent) 12%, transparent)', color: 'var(--color-accent)' }}>
                              {checked ? <Check size={16} /> : <Plus size={16} />}
                            </div>
                            <span className="min-w-0 flex-1">
                              <span className="block truncate text-sm font-medium leading-5" style={{ color: 'var(--color-text)' }}>{skill.name}</span>
                              <span className="mt-1 line-clamp-2 block text-xs leading-4" style={{ color: 'var(--color-text-tertiary)' }}>{skill.description || skill.source || 'Skill'}</span>
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <div className="mt-4 rounded-xl" style={{ border: '1px solid var(--color-border)' }}>
            <div className="flex items-center justify-between px-3 py-2">
              <h4 className="text-xs font-semibold uppercase" style={{ color: 'var(--color-accent)' }}>
                Tools &amp; Data Sources
              </h4>
              <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                {dataSources.length} sources · {effectiveTools.length} tools
              </span>
            </div>
            <div className="flex flex-wrap gap-2 p-3">
              {effectiveTools.length === 0 ? (
                <span className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
                  No tools attached.
                </span>
              ) : (
                effectiveTools.map((tool) => capabilityChip(tool))
              )}
            </div>
          </div>
        </main>

        <aside className="space-y-4">
          <div className="rounded-xl p-4" style={insetStyle}>
            <h4 className="mb-4 text-sm font-semibold uppercase" style={{ color: 'var(--color-text-secondary)' }}>Assigned To This Agent</h4>
            <div className="rounded-lg p-3" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
              <div className="text-xs uppercase" style={{ color: 'var(--color-text-tertiary)' }}>Selected Preset</div>
              <div className="mt-1 flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium" style={{ color: 'var(--color-text)' }}>{templateName}</div>
                  <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>{presetId ? 'Template configuration' : 'Custom configuration'}</div>
                </div>
                <Pencil size={15} style={{ color: 'var(--color-accent)' }} />
              </div>
            </div>
            <div className="mt-4">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-xs uppercase" style={{ color: 'var(--color-text-tertiary)' }}>Directly Assigned Skills</span>
                <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>{selectedSkills.length}</span>
              </div>
              <div className="flex flex-wrap gap-2">
                {selectedSkills.length > 0 ? selectedSkills.map((skill) => capabilityChip(skill, true)) : <span className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>None</span>}
              </div>
            </div>
            <div className="mt-4 rounded-lg overflow-hidden" style={{ border: '1px solid var(--color-border)' }}>
              {[
                ['Inherited', inheritedSkillCount, manager ? `From ${manager.name}` : 'None'],
                ['From Preset', Math.max(0, effectiveSkills.length - inheritedSkillCount - selectedSkills.length), templateName],
                ['Direct', selectedSkills.length, 'Assigned to this agent'],
              ].map(([label, value, source]) => (
                <div key={String(label)} className="flex items-center justify-between gap-3 px-3 py-2 text-sm border-b last:border-b-0" style={{ borderColor: 'var(--color-border)' }}>
                  <span style={{ color: 'var(--color-text-secondary)' }}>{label}</span>
                  <span className="truncate text-right" style={{ color: 'var(--color-text-tertiary)' }}>{value} - {source}</span>
                </div>
              ))}
            </div>
          </div>
          <div className="rounded-xl p-4" style={insetStyle}>
            <div className="mb-2 flex items-center gap-2 text-sm" style={{ color: 'var(--color-accent)' }}>
              <ShieldCheck size={16} />
              Runtime Scope
            </div>
            <div className="grid grid-cols-2 gap-2 text-sm">
              <div>
                <div className="text-lg font-semibold" style={{ color: 'var(--color-text)' }}>{directReports.length}</div>
                <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>Direct Reports</div>
              </div>
              <div>
                <div className="text-lg font-semibold" style={{ color: 'var(--color-text)' }}>{autoTools.length}</div>
                <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>Auto Tools</div>
              </div>
            </div>
          </div>
        </aside>
      </div>

      <div className="grid gap-3 border-t p-4 md:grid-cols-[1fr_1fr_1.2fr]" style={{ borderColor: 'color-mix(in srgb, var(--color-border) 78%, var(--color-accent) 22%)' }}>
        <button
          type="button"
          onClick={() => {
            setEditing(false);
            setPresetId(templateId);
            setSelectedSkills(configuredSkills);
            setChiefMode((agent.config?.orchestrator_mode as string | undefined) === 'chief');
          }}
          disabled={!editing || saving}
          className="flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm cursor-pointer disabled:opacity-40"
          style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
        >
          <RefreshCw size={15} />
          Reset Changes
        </button>
        <button type="button" onClick={onOpenLibrary} className="flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm cursor-pointer" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-accent)', color: 'var(--color-accent)' }}>
          <Eye size={15} />
          Preview Runtime Capabilities
        </button>
        <button type="button" onClick={handleSave} disabled={!editing || saving} className="flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium cursor-pointer disabled:opacity-50" style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}>
          <Check size={16} />
          {saving ? 'Saving...' : 'Save Changes'}
        </button>
      </div>
    </section>
  );

  return (
    <div
      className="p-3 rounded-lg space-y-3"
      style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
            Capability Inspector
          </h3>
          <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
            Assign only the preset and skills this agent should carry, then inspect the final runtime tool set.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={onOpenLibrary}
            className="px-3 py-1.5 rounded-lg text-xs cursor-pointer"
            style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
          >
            Library
          </button>
          {editing ? (
            <>
              <button
                onClick={() => {
                  setEditing(false);
                  setPresetId(templateId);
                  setSelectedSkills(configuredSkills);
                }}
                className="px-3 py-1.5 rounded-lg text-xs cursor-pointer"
                style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
              >
                Cancel
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="px-3 py-1.5 rounded-lg text-xs cursor-pointer disabled:opacity-50"
                style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}
              >
                {saving ? 'Saving...' : 'Save'}
              </button>
            </>
          ) : (
            <button
              onClick={() => setEditing(true)}
              className="px-3 py-1.5 rounded-lg text-xs cursor-pointer"
              style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
            >
              Edit
            </button>
          )}
        </div>
      </div>
      {editing && (
        <div className="space-y-3 p-3 rounded-lg" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)' }}>
          <div className="grid grid-cols-2 gap-3">
            <label className="text-sm">
              <div className="text-xs mb-1" style={{ color: 'var(--color-text-tertiary)' }}>Preset</div>
              <select
                value={presetId}
                onChange={(e) => setPresetId(e.target.value)}
                className="w-full px-3 py-2 rounded-lg text-sm"
                style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
              >
                <option value="">Custom / Keep current config</option>
                {templates.map((template) => (
                  <option key={template.id} value={template.id}>
                    {template.name} ({template.source})
                  </option>
                ))}
              </select>
            </label>
            <div className="text-xs self-end" style={{ color: 'var(--color-text-tertiary)' }}>
              Applying a preset updates this agent&apos;s stored config with that preset&apos;s defaults, then keeps the selected skill list agent-specific.
            </div>
          </div>
          <label
            className="flex items-start gap-2 p-2 rounded-lg cursor-pointer"
            style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
          >
            <input
              type="checkbox"
              checked={chiefMode}
              onChange={(e) => setChiefMode(e.target.checked)}
              className="mt-0.5 cursor-pointer"
            />
            <span className="flex-1">
              <span className="block text-sm" style={{ color: 'var(--color-text)' }}>
                Run as Chief Orchestrator (action envelope)
              </span>
              <span className="block text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                Routes this agent through the chief mode: one JSON action per turn (complete / delegate / ask_user / fail), with delegations narrowed to direct subordinates. Best paired with a model that follows JSON instructions reliably.
              </span>
            </span>
          </label>
          <div>
            <div className="flex items-center justify-between mb-2">
              <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                Assigned skills
              </div>
              <div className="flex items-center gap-3 text-xs">
                <span style={{ color: 'var(--color-text-tertiary)' }}>
                  {selectedSkills.length} assigned
                </span>
                <button
                  type="button"
                  onClick={() => setSelectedSkills([])}
                  disabled={selectedSkills.length === 0}
                  className="cursor-pointer disabled:opacity-40"
                  style={{ color: 'var(--color-text-secondary)' }}
                >
                  Clear all
                </button>
              </div>
            </div>
            {skills.length === 0 ? (
              <div className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                No installed skills found.
              </div>
            ) : (
              <>
                <input
                  value={skillQuery}
                  onChange={(e) => setSkillQuery(e.target.value)}
                  placeholder="Search skills…"
                  className="w-full px-3 py-2 mb-2 rounded-lg text-sm"
                  style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                />
                {groupedSkills.length === 0 ? (
                  <div className="text-sm py-2" style={{ color: 'var(--color-text-tertiary)' }}>
                    No skills match “{skillQuery}”.
                  </div>
                ) : (
                  <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
                    {groupedSkills.map((group) => {
                      const names = group.items.map((s) => s.name);
                      const open = !collapsedSkillGroups.has(group.label);
                      return (
                        <div
                          key={group.label}
                          className="rounded-lg"
                          style={{ border: '1px solid var(--color-border)' }}
                        >
                          <div className="flex items-center justify-between px-2 py-1.5">
                            <button
                              type="button"
                              onClick={() => toggleSkillGroup(group.label)}
                              className="flex items-center gap-1.5 text-xs font-medium cursor-pointer"
                              style={{ color: 'var(--color-text)' }}
                            >
                              <ChevronRight
                                size={12}
                                style={{ transform: open ? 'rotate(90deg)' : 'none', transition: 'transform .15s' }}
                              />
                              {group.label}
                              <span style={{ color: 'var(--color-text-tertiary)' }}>
                                ({group.items.length})
                              </span>
                            </button>
                            <div className="flex items-center gap-3 text-xs">
                              <button
                                type="button"
                                onClick={() => setGroupSelected(names, true)}
                                className="cursor-pointer"
                                style={{ color: 'var(--color-accent)' }}
                              >
                                All
                              </button>
                              <button
                                type="button"
                                onClick={() => setGroupSelected(names, false)}
                                className="cursor-pointer"
                                style={{ color: 'var(--color-text-secondary)' }}
                              >
                                None
                              </button>
                            </div>
                          </div>
                          {open && (
                            <div className="grid grid-cols-2 gap-2 px-2 pb-2">
                              {group.items.map((skill) => {
                                const checked = selectedSkills.includes(skill.name);
                                return (
                                  <label
                                    key={skill.name}
                                    className="flex items-start gap-2 p-2 rounded-lg cursor-pointer"
                                    style={{
                                      background: 'var(--color-bg-secondary)',
                                      border: `1px solid ${checked ? 'var(--color-accent)' : 'var(--color-border)'}`,
                                    }}
                                  >
                                    <input
                                      type="checkbox"
                                      checked={checked}
                                      onChange={() => toggleSkill(skill.name)}
                                    />
                                    <span>
                                      <span className="block text-sm" style={{ color: 'var(--color-text)' }}>
                                        {skill.name}
                                      </span>
                                      <span className="block text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                                        {skill.source || 'built-in'}{skill.description ? ` • ${skill.description}` : ''}
                                      </span>
                                    </span>
                                  </label>
                                );
                              })}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}
      <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
        <div>
          <div className="text-xs mb-1" style={{ color: 'var(--color-text-tertiary)' }}>Preset</div>
          <div style={{ color: 'var(--color-text)' }}>{templateName}</div>
        </div>
        <div>
          <div className="text-xs mb-1" style={{ color: 'var(--color-text-tertiary)' }}>Knowledge Access</div>
          <div style={{ color: 'var(--color-text)' }}>
            {agent.knowledge_enabled ? 'On' : 'Off'}
          </div>
        </div>
      </div>
      {renderBadgeGroup('Installed global skills', skills.map((skill) => skill.name))}
      {renderBadgeGroup('Assigned skills', configuredSkills)}
      {renderBadgeGroup('Effective skills', effectiveSkills)}
      {renderBadgeGroup('Configured tools', configuredTools)}
      {renderBadgeGroup('Auto-enabled tools', autoTools)}
      {renderBadgeGroup('Effective tools', effectiveTools)}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Detail view — Interact tab
// ---------------------------------------------------------------------------

function AgentOrganizationSection({
  agent,
  managedAgents,
  onAgentUpdated,
}: {
  agent: ManagedAgent;
  managedAgents: ManagedAgent[];
  onAgentUpdated: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [orgRole, setOrgRole] = useState(agent.org_role || '');
  const [managerId, setManagerId] = useState(agent.manager_agent_id || '');

  useEffect(() => {
    setOrgRole(agent.org_role || '');
    setManagerId(agent.manager_agent_id || '');
    setEditing(false);
    setSaving(false);
  }, [agent.id, agent.org_role, agent.manager_agent_id]);

  const manager = findAgentById(managedAgents, agent.manager_agent_id);
  const directReports = managedAgents.filter((candidate) => candidate.manager_agent_id === agent.id);
  const chain = buildManagementChain(agent, managedAgents);
  const blockedManagerIds = collectDescendantIds(agent.id, managedAgents);
  blockedManagerIds.add(agent.id);

  async function handleSave() {
    setSaving(true);
    try {
      await updateManagedAgent(agent.id, {
        org_role: orgRole.trim(),
        manager_agent_id: managerId || null,
      });
      setEditing(false);
      onAgentUpdated();
      toast.success('Organization updated');
    } catch (err: any) {
      toast.error(err?.message || 'Failed to update organization');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="p-3 rounded-lg space-y-3"
      style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
    >
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
            Organization
          </h3>
          <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
            Define this agent&apos;s title and reporting line.
          </p>
        </div>
        {editing ? (
          <div className="flex items-center gap-2">
            <button
              onClick={() => {
                setOrgRole(agent.org_role || '');
                setManagerId(agent.manager_agent_id || '');
                setEditing(false);
              }}
              className="px-2 py-1 rounded text-xs cursor-pointer"
              style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-2 py-1 rounded text-xs cursor-pointer flex items-center gap-1"
              style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)', opacity: saving ? 0.7 : 1 }}
            >
              <Check size={12} />
              {saving ? 'Saving...' : 'Save'}
            </button>
          </div>
        ) : (
          <button
            onClick={() => setEditing(true)}
            className="px-2 py-1 rounded text-xs cursor-pointer flex items-center gap-1"
            style={{ border: '1px solid var(--color-border)', color: 'var(--color-accent)' }}
          >
            <Pencil size={12} />
            Edit
          </button>
        )}
      </div>

      {editing ? (
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>
              Role
            </label>
            <input
              list={`org-role-presets-${agent.id}`}
              value={orgRole}
              onChange={(e) => setOrgRole(e.target.value)}
              className="w-full px-3 py-2 rounded-lg text-sm bg-transparent"
              style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
              placeholder="e.g. Chief Executive Officer (CEO)"
            />
            <datalist id={`org-role-presets-${agent.id}`}>
              {ORG_ROLE_PRESETS.map((role) => (
                <option key={role} value={role} />
              ))}
            </datalist>
          </div>
          <div>
            <label className="block text-xs font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>
              Reports To
            </label>
            <select
              value={managerId}
              onChange={(e) => setManagerId(e.target.value)}
              className="w-full px-3 py-2 rounded-lg text-sm"
              style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
            >
              <option value="">Top-level leader</option>
              {managedAgents
                .filter((candidate) => !blockedManagerIds.has(candidate.id))
                .map((candidate) => (
                  <option key={candidate.id} value={candidate.id}>
                    {candidate.name} - {roleLabel(candidate)}
                  </option>
                ))}
            </select>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
          <div>
            <div style={{ color: 'var(--color-text-tertiary)' }} className="text-xs mb-1">Role</div>
            <div style={{ color: 'var(--color-text)' }}>{agent.org_role?.trim() || 'Unassigned'}</div>
          </div>
          <div>
            <div style={{ color: 'var(--color-text-tertiary)' }} className="text-xs mb-1">Reports To</div>
            <div style={{ color: 'var(--color-text)' }}>
              {manager ? `${manager.name} - ${roleLabel(manager)}` : 'Top-level leader'}
            </div>
          </div>
          <div>
            <div style={{ color: 'var(--color-text-tertiary)' }} className="text-xs mb-1">Direct Reports</div>
            <div style={{ color: 'var(--color-text)' }}>
              {directReports.length > 0
                ? directReports.map((report) => `${report.name} (${roleLabel(report)})`).join(', ')
                : 'None'}
            </div>
          </div>
          <div>
            <div style={{ color: 'var(--color-text-tertiary)' }} className="text-xs mb-1">Chain</div>
            <div style={{ color: 'var(--color-text)' }}>
              {chain.map((item) => `${item.name} (${roleLabel(item)})`).join(' -> ')}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function OrgChartNode({
  agent,
  managedAgents,
  selectedAgentId,
  onSelect,
  activeAgentIds,
  activeEdgeKeys,
}: {
  agent: ManagedAgent;
  managedAgents: ManagedAgent[];
  selectedAgentId: string | null;
  onSelect: (agentId: string) => void;
  activeAgentIds: Set<string>;
  activeEdgeKeys: Set<string>;
}) {
  const reports = getOrgChildren(managedAgents, agent.id);
  const isSelected = selectedAgentId === agent.id;
  // The trunk below a manager lights up while any direct report is active.
  const anyReportActive = reports.some((r) => activeAgentIds.has(r.id) || activeEdgeKeys.has(r.id));

  return (
    <div className="flex flex-col items-center min-w-[220px]">
      <button
        onClick={() => onSelect(agent.id)}
        className="w-[220px] rounded-2xl p-4 text-left transition-colors"
        style={{
          background: isSelected ? 'color-mix(in srgb, var(--color-accent) 14%, var(--color-bg-secondary))' : 'var(--color-bg-secondary)',
          border: `1px solid ${isSelected ? 'var(--color-accent)' : 'var(--color-border)'}`,
          boxShadow: isSelected ? '0 0 0 1px color-mix(in srgb, var(--color-accent) 20%, transparent)' : 'none',
        }}
      >
        <div className="flex items-center justify-between gap-2 mb-3">
          <div className="flex items-center gap-2 min-w-0">
            <AgentAvatar agent={agent} size="orgChart" active={activeAgentIds.has(agent.id)} />
            <span className="font-medium text-sm truncate" style={{ color: 'var(--color-text)' }}>
              {agent.name}
            </span>
            {/* Phase 2E — Chief designation badge. */}
            {agent.is_chief && (
              <Crown
                size={13}
                style={{ color: 'var(--color-accent-amber)', flexShrink: 0 }}
                aria-label="Chief Orchestrator"
              />
            )}
          </div>
          <StatusDot status={agent.status} />
        </div>
        <div className="text-xs mb-2" style={{ color: 'var(--color-accent)' }}>
          {roleLabel(agent)}
        </div>
        <div className="flex items-center gap-3 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
          <span>{formatSchedule(agent.schedule_type, agent.schedule_value)}</span>
          <span>•</span>
          <span>{reports.length} report{reports.length === 1 ? '' : 's'}</span>
        </div>
      </button>

      {reports.length > 0 && (
        <div className="mt-3 flex flex-col items-center">
          <div className="h-6 w-px" style={connectorStyle(anyReportActive)} />
          <div className="flex items-start justify-center">
            {reports.map((report, index) => {
              const isOnly = reports.length === 1;
              const isFirst = index === 0;
              const isLast = index === reports.length - 1;
              const reportActive = activeAgentIds.has(report.id) || activeEdgeKeys.has(report.id);

              return (
                <div key={report.id} className="relative flex flex-col items-center px-3 pt-6">
                  {!isOnly && (
                    <div
                      className="absolute top-0 h-px"
                      style={{
                        left: isFirst ? '50%' : 0,
                        right: isLast ? '50%' : 0,
                        ...connectorStyle(reportActive, 'horizontal'),
                      }}
                    />
                  )}
                  <div className="absolute top-0 h-6 w-px" style={connectorStyle(reportActive)} />
                  <OrgChartNode
                    agent={report}
                    managedAgents={managedAgents}
                    selectedAgentId={selectedAgentId}
                    onSelect={onSelect}
                    activeAgentIds={activeAgentIds}
                    activeEdgeKeys={activeEdgeKeys}
                  />
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function AgentOrgChart({
  managedAgents,
  selectedAgentId,
  onSelect,
}: {
  managedAgents: ManagedAgent[];
  selectedAgentId: string | null;
  onSelect: (agentId: string) => void;
}) {
  const roots = getOrgRoots(managedAgents);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const chartRef = useRef<HTMLElement | null>(null);

  // Track which agents have an in-flight work tick so the reporting lines
  // between them can animate. `expiry` is a safety net: if a tick's
  // completion event is ever missed, the line stops pulsing on its own.
  const [activeAgentIds, setActiveAgentIds] = useState<Set<string>>(() => new Set());
  const [activeEdgeKeys, setActiveEdgeKeys] = useState<Set<string>>(() => new Set());
  const activeExpiryRef = useRef<Map<string, number>>(new Map());
  const edgeExpiryRef = useRef<Map<string, number>>(new Map());

  const handleAgentEvent = useCallback((event: AgentEvent) => {
    const raw = event.data?.agent_id;
    if (typeof raw !== 'string' || !raw) return;
    const parentRaw = event.data?.parent_agent_id;
    const parentAgentId = typeof parentRaw === 'string' ? parentRaw : '';
    const expiry = activeExpiryRef.current;
    const edgeExpiry = edgeExpiryRef.current;
    const pulseEdges = (ttlMs: number) => {
      const edgeKeys = parentAgentId
        ? getOrgPathEdgeKeys(parentAgentId, raw, managedAgents)
        : [raw];
      if (!edgeKeys.length) return;
      const expiresAt = Date.now() + ttlMs;
      for (const key of edgeKeys) edgeExpiry.set(key, expiresAt);
      setActiveEdgeKeys(new Set(edgeExpiry.keys()));
    };
    if (event.type === 'agent_tick_start') {
      expiry.set(raw, Date.now() + 120_000);
      setActiveAgentIds(new Set(expiry.keys()));
      pulseEdges(parentAgentId ? 120_000 : 20_000);
    } else if (event.type === 'agent_message_received') {
      pulseEdges(18_000);
    } else if (event.type === 'agent_tick_end' || event.type === 'agent_tick_error') {
      if (expiry.delete(raw)) setActiveAgentIds(new Set(expiry.keys()));
      if (parentAgentId) {
        for (const key of getOrgPathEdgeKeys(parentAgentId, raw, managedAgents)) {
          edgeExpiry.delete(key);
        }
        setActiveEdgeKeys(new Set(edgeExpiry.keys()));
      }
    }
  }, [managedAgents]);

  useAgentEvents('*', handleAgentEvent, AGENT_ACTIVITY_EVENTS);

  useEffect(() => {
    const id = window.setInterval(() => {
      const expiry = activeExpiryRef.current;
      const edgeExpiry = edgeExpiryRef.current;
      const now = Date.now();
      let changed = false;
      for (const [aid, exp] of expiry) {
        if (exp <= now) {
          expiry.delete(aid);
          changed = true;
        }
      }
      if (changed) setActiveAgentIds(new Set(expiry.keys()));
      let edgesChanged = false;
      for (const [key, exp] of edgeExpiry) {
        if (exp <= now) {
          edgeExpiry.delete(key);
          edgesChanged = true;
        }
      }
      if (edgesChanged) setActiveEdgeKeys(new Set(edgeExpiry.keys()));
    }, 5000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    if (!isFullscreen) return;

    const pane = chartRef.current?.closest('[data-agents-page-pane]') as HTMLElement | null;
    const previousOverflow = pane?.style.overflow ?? '';
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setIsFullscreen(false);
    };

    if (pane) pane.style.overflow = 'hidden';
    window.addEventListener('keydown', handleKeyDown);

    return () => {
      if (pane) pane.style.overflow = previousOverflow;
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [isFullscreen]);

  if (roots.length === 0) return null;

  const chartTree = (
    <div className="min-w-max pb-2">
      <div className="flex items-start justify-center gap-10">
        {roots.map((root) => (
          <OrgChartNode
            key={root.id}
            agent={root}
            managedAgents={managedAgents}
            selectedAgentId={selectedAgentId}
            onSelect={onSelect}
            activeAgentIds={activeAgentIds}
            activeEdgeKeys={activeEdgeKeys}
          />
        ))}
      </div>
    </div>
  );

  return (
    <>
      <section
        ref={chartRef}
        className="rounded-2xl p-4"
        style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
      >
        <div className="flex items-start justify-between gap-4 mb-5">
          <div>
            <h2 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
              Organization Chart
            </h2>
            <p className="text-sm mt-1" style={{ color: 'var(--color-text-secondary)' }}>
              Reporting lines are drawn from each agent&apos;s manager assignment. Click any node to open that agent.
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <div className="text-xs whitespace-nowrap" style={{ color: 'var(--color-text-tertiary)' }}>
              {managedAgents.length} agent{managedAgents.length === 1 ? '' : 's'}
            </div>
            <button
              type="button"
              onClick={() => setIsFullscreen(true)}
              aria-label="Expand organization chart to full screen"
              title="Expand chart"
              className="flex h-9 w-9 items-center justify-center rounded-full transition-colors"
              style={{
                background: 'var(--color-bg)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text-secondary)',
              }}
            >
              <Maximize2 size={16} />
            </button>
          </div>
        </div>

        <div className="overflow-x-auto">
          {chartTree}
        </div>
      </section>

      {isFullscreen && (
        <div className="absolute inset-0 z-40 p-4 sm:p-6" style={{ background: 'rgba(0, 0, 0, 0.72)' }}>
          <div
            className="relative flex h-full w-full flex-col overflow-hidden rounded-[28px]"
            style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)' }}
          >
            <button
              type="button"
              onClick={() => setIsFullscreen(false)}
              aria-label="Close full screen organization chart"
              title="Close full screen"
              className="absolute right-4 top-4 z-10 flex h-10 w-10 items-center justify-center rounded-full transition-colors"
              style={{
                background: 'var(--color-bg-secondary)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text-secondary)',
              }}
            >
              <X size={18} />
            </button>

            <div className="border-b px-6 py-5 pr-20" style={{ borderColor: 'var(--color-border)' }}>
              <h2 className="text-base font-semibold" style={{ color: 'var(--color-text)' }}>
                Organization Chart
              </h2>
              <p className="text-sm mt-1 max-w-3xl" style={{ color: 'var(--color-text-secondary)' }}>
                Scroll to inspect the full reporting structure, then press Escape or use the close button to return.
              </p>
            </div>

            <div className="flex-1 overflow-auto px-6 py-6">
              {chartTree}
            </div>
          </div>
        </div>
      )}
    </>
  );
}

type InterAgentActivityItem = {
  id: string;
  agentId: string;
  parentAgentId?: string;
  type: 'delegation' | 'request' | 'response' | 'complete' | 'warning' | 'working';
  title: string;
  body: string;
  timestamp: number;
};

function activityTypeStyle(type: InterAgentActivityItem['type']): { color: string; label: string } {
  if (type === 'complete') return { color: 'var(--color-success)', label: 'Complete' };
  if (type === 'warning') return { color: 'var(--color-warning)', label: 'Alert' };
  if (type === 'delegation') return { color: 'var(--color-accent-purple)', label: 'Delegation' };
  if (type === 'request') return { color: 'var(--color-accent)', label: 'Request' };
  if (type === 'working') return { color: 'var(--color-accent)', label: 'Active' };
  return { color: 'var(--color-text-secondary)', label: 'Reply' };
}

function InterAgentActivityPanel({
  managedAgents,
  onSelectAgent,
}: {
  managedAgents: ManagedAgent[];
  onSelectAgent: (agentId: string) => void;
}) {
  const [filter, setFilter] = useState<'all' | 'active' | 'alerts' | 'direct'>('all');
  const [history, setHistory] = useState<InterAgentActivityItem[]>([]);
  const [live, setLive] = useState<InterAgentActivityItem[]>([]);
  const agentNameById = useMemo(() => {
    const out: Record<string, string> = {};
    for (const agent of managedAgents) out[agent.id] = agent.name;
    return out;
  }, [managedAgents]);

  const toAgentName = useCallback((agentId?: string) => {
    if (!agentId) return '';
    return agentNameById[agentId] || 'Unknown Agent';
  }, [agentNameById]);

  const loadHistory = useCallback(async () => {
    if (managedAgents.length === 0) {
      setHistory([]);
      return;
    }
    try {
      const batches = await Promise.all(
        managedAgents.slice(0, 18).map(async (agent) => {
          const messages = await fetchAgentMessages(agent.id);
          return [...messages]
            .sort((a, b) => b.created_at - a.created_at)
            .slice(0, 8)
            .map((message): InterAgentActivityItem => {
            const isResponse = message.direction === 'agent_to_user';
            const body = message.content.replace(/\s+/g, ' ').trim();
            return {
              id: `msg-${message.id}`,
              agentId: agent.id,
              type: isResponse ? 'response' : (message.mode === 'immediate' ? 'request' : 'delegation'),
              title: agent.name,
              body: body || (isResponse ? 'Response recorded.' : 'Request received.'),
              timestamp: message.created_at,
            };
          });
        }),
      );
      setHistory(
        batches
          .flat()
          .sort((a, b) => b.timestamp - a.timestamp)
          .slice(0, 30),
      );
    } catch {
      // Non-blocking panel; the live websocket still fills this area.
    }
  }, [managedAgents]);

  useEffect(() => {
    loadHistory();
    const interval = window.setInterval(loadHistory, 30000);
    return () => window.clearInterval(interval);
  }, [loadHistory]);

  const handleAgentEvent = useCallback((event: AgentEvent) => {
    const rawAgentId = event.data?.agent_id;
    if (typeof rawAgentId !== 'string' || !rawAgentId) return;
    const rawParentId = event.data?.parent_agent_id;
    const parentAgentId = typeof rawParentId === 'string' && rawParentId ? rawParentId : '';
    const agentName = toAgentName(rawAgentId) || String(event.data?.agent_name || 'Agent');
    const parentName = toAgentName(parentAgentId);
    const summary = String(event.data?.summary || event.data?.error || '').trim();
    let item: InterAgentActivityItem | null = null;

    if (event.type === 'agent_message_received') {
      item = {
        id: `evt-${event.timestamp}-${rawAgentId}-message`,
        agentId: rawAgentId,
        parentAgentId,
        type: parentAgentId ? 'delegation' : 'request',
        title: agentName,
        body: parentAgentId
          ? `${parentName || 'Parent agent'} delegated work to ${agentName}.`
          : `${agentName} received a direct request.`,
        timestamp: event.timestamp,
      };
    } else if (event.type === 'agent_tick_start') {
      item = {
        id: `evt-${event.timestamp}-${rawAgentId}-start`,
        agentId: rawAgentId,
        parentAgentId,
        type: 'working',
        title: agentName,
        body: parentAgentId
          ? `${agentName} is working on a request from ${parentName || 'another agent'}.`
          : `${agentName} started working.`,
        timestamp: event.timestamp,
      };
    } else if (event.type === 'agent_tick_end') {
      item = {
        id: `evt-${event.timestamp}-${rawAgentId}-end`,
        agentId: rawAgentId,
        parentAgentId,
        type: 'complete',
        title: agentName,
        body: summary || `${agentName} completed the current task.`,
        timestamp: event.timestamp,
      };
    } else if (event.type === 'agent_tick_error' || event.type === 'agent_budget_exceeded' || event.type === 'agent_stall_detected') {
      item = {
        id: `evt-${event.timestamp}-${rawAgentId}-alert`,
        agentId: rawAgentId,
        parentAgentId,
        type: 'warning',
        title: agentName,
        body: summary || `${agentName} needs attention.`,
        timestamp: event.timestamp,
      };
    }

    if (!item) return;
    setLive((current) => [item!, ...current].slice(0, 24));
  }, [toAgentName]);

  useAgentEvents('*', handleAgentEvent, [
    'agent_message_received',
    'agent_tick_start',
    'agent_tick_end',
    'agent_tick_error',
    'agent_budget_exceeded',
    'agent_stall_detected',
  ]);

  const items = useMemo(() => {
    const merged = [...live, ...history]
      .sort((a, b) => b.timestamp - a.timestamp)
      .filter((item, index, arr) => arr.findIndex((candidate) => candidate.id === item.id) === index);
    if (filter === 'active') return merged.filter((item) => item.type === 'working' || item.type === 'delegation');
    if (filter === 'alerts') return merged.filter((item) => item.type === 'warning');
    if (filter === 'direct') return merged.filter((item) => !item.parentAgentId && (item.type === 'request' || item.type === 'response'));
    return merged;
  }, [filter, history, live]);

  const liveCount = live.filter((item) => Date.now() - item.timestamp * 1000 < 120000).length;
  const filterButton = (id: typeof filter, label: string, badge?: number) => (
    <button
      type="button"
      onClick={() => setFilter(id)}
      className="flex items-center justify-center gap-1 rounded-lg px-3 py-2 text-xs font-medium transition-colors"
      style={{
        background: filter === id ? 'color-mix(in srgb, var(--color-accent) 18%, transparent)' : 'var(--color-bg-secondary)',
        border: `1px solid ${filter === id ? 'var(--color-accent)' : 'var(--color-border)'}`,
        color: filter === id ? 'var(--color-accent)' : 'var(--color-text-secondary)',
      }}
    >
      {label}
      {!!badge && (
        <span
          className="rounded-full px-1.5 py-0.5 text-[10px]"
          style={{ background: 'var(--color-error)', color: 'var(--color-on-accent)' }}
        >
          {badge}
        </span>
      )}
    </button>
  );

  return (
    <aside
      className="rounded-2xl p-4 lg:sticky lg:top-6 lg:max-h-[calc(100vh-3rem)] lg:overflow-hidden"
      style={{
        background: 'linear-gradient(180deg, color-mix(in srgb, var(--color-bg-secondary) 92%, transparent), var(--color-bg-secondary))',
        border: '1px solid color-mix(in srgb, var(--color-accent) 28%, var(--color-border))',
        boxShadow: '0 0 28px color-mix(in srgb, var(--color-accent) 8%, transparent)',
      }}
    >
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-normal" style={{ color: 'var(--color-text)' }}>
            <Activity size={16} style={{ color: 'var(--color-accent)' }} />
            Inter-Agent Activity
          </h2>
          <p className="mt-1 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
            Conversation log across agents, newest first
          </p>
        </div>
        <div className="flex items-center gap-1.5 text-xs" style={{ color: 'var(--color-success)' }}>
          <span className="h-2 w-2 rounded-full" style={{ background: 'var(--color-success)' }} />
          Live
        </div>
      </div>

      <div className="mb-4 grid grid-cols-4 gap-1.5">
        {filterButton('all', 'All')}
        {filterButton('active', 'Active')}
        {filterButton('alerts', 'Alerts', items.filter((item) => item.type === 'warning').length)}
        {filterButton('direct', 'Direct')}
      </div>

      <PendingApprovalsList agentNameById={agentNameById} />

      <div className="space-y-3 overflow-y-auto pr-1 lg:max-h-[calc(100vh-13rem)]">
        {items.length === 0 ? (
          <div
            className="rounded-xl px-4 py-8 text-center text-sm"
            style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text-tertiary)' }}
          >
            No agent conversation activity yet.
          </div>
        ) : (
          items.slice(0, 18).map((item) => {
            const style = activityTypeStyle(item.type);
            const parentName = item.parentAgentId ? toAgentName(item.parentAgentId) : '';
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => onSelectAgent(item.agentId)}
                className="group w-full rounded-xl p-3 text-left transition-colors"
                style={{
                  background: 'color-mix(in srgb, var(--color-bg) 72%, transparent)',
                  border: `1px solid color-mix(in srgb, ${style.color} 34%, var(--color-border))`,
                  boxShadow: `inset 3px 0 0 ${style.color}`,
                }}
              >
                <div className="flex items-start gap-3">
                  <div
                    className="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-xl"
                    style={{
                      background: `color-mix(in srgb, ${style.color} 12%, transparent)`,
                      border: `1px solid color-mix(in srgb, ${style.color} 36%, transparent)`,
                      color: style.color,
                    }}
                  >
                    {item.type === 'response' ? <MessageSquare size={16} /> : <Bot size={16} />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="truncate text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
                          {item.title}
                        </div>
                        {parentName && (
                          <div className="truncate text-[11px]" style={{ color: 'var(--color-accent)' }}>
                            From {parentName}
                          </div>
                        )}
                      </div>
                      <span className="shrink-0 text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>
                        {formatRelativeTime(item.timestamp)}
                      </span>
                    </div>
                    <p className="mt-1 line-clamp-3 text-xs leading-relaxed" style={{ color: 'var(--color-text-secondary)' }}>
                      {item.body}
                    </p>
                    <span
                      className="mt-2 inline-flex rounded-md px-2 py-0.5 text-[10px] font-medium"
                      style={{ background: `color-mix(in srgb, ${style.color} 14%, transparent)`, color: style.color }}
                    >
                      {style.label}
                    </span>
                  </div>
                </div>
              </button>
            );
          })
        )}
      </div>

      <div className="mt-3 flex items-center justify-between border-t pt-3 text-xs" style={{ borderColor: 'var(--color-border)' }}>
        <span style={{ color: 'var(--color-text-tertiary)' }}>
          {managedAgents.length} agents monitored
        </span>
        <span style={{ color: 'var(--color-accent)' }}>
          {liveCount} live
        </span>
      </div>
    </aside>
  );
}

/** AgentMessage extended with optional response metadata for the footer. */
type InteractMessage = AgentMessage & {
  _elapsed?: string;
  _toolCalls?: number;
  _usage?: Record<string, number>;
  _telemetry?: Record<string, unknown>;
  _toolCallDetails?: ToolCallInfo[];
};

function AgentResponseFooter({
  msg, copiedId, onCopy,
}: {
  msg: InteractMessage;
  copiedId: string | null;
  onCopy: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const u = msg._usage;
  const t = msg._telemetry as Record<string, unknown> | undefined;
  const elapsed = msg._elapsed;
  const toolCallDetails = msg._toolCallDetails || [];
  const toolCalls = msg._toolCalls ?? toolCallDetails.length;

  // Build summary line like Chat: "ollama - qwen3.5:9b - 18.3s - 50 tokens"
  const parts: string[] = [];
  if (t?.engine) parts.push(String(t.engine));
  if (t?.model_id) parts.push(String(t.model_id));
  if (elapsed) parts.push(`${elapsed}s`);
  if (u?.prompt_tokens) parts.push(`${u.prompt_tokens} input tokens`);
  if (u?.completion_tokens) parts.push(`${u.completion_tokens} output tokens`);
  if (toolCalls > 0) parts.push(`${toolCalls} tool ${toolCalls === 1 ? 'call' : 'calls'}`);

  const summary = parts.length > 0 ? parts.join(' - ') : elapsed ? `${elapsed}s` : '';

  // Build expanded rows
  const rows: Array<{ label: string; value: string }> = [];
  if (t?.engine) rows.push({ label: 'Engine', value: `${t.engine}${t.model_id ? ` (${t.model_id})` : ''}` });
  if (u) {
    const tokenParts = [];
    if (u.completion_tokens) tokenParts.push(`${u.completion_tokens} generated`);
    if (u.prompt_tokens) tokenParts.push(`${u.prompt_tokens} prompt`);
    if (tokenParts.length) rows.push({ label: 'Tokens', value: tokenParts.join(' · ') });
  }
  if (toolCallDetails.length > 0) {
    toolCallDetails.forEach((tc, i) => {
      const prefix = toolCallDetails.length > 1 ? `Tool ${i + 1}` : 'Tool';
      const args = tc.arguments ? ` ${tc.arguments}` : '';
      rows.push({ label: prefix, value: `${tc.tool}(${args.trim()})` });
    });
  } else if (toolCalls > 0) {
    rows.push({ label: 'Tool calls', value: `${toolCalls}` });
  }
  if (t?.tokens_per_sec) rows.push({ label: 'Speed', value: `${Math.round(Number(t.tokens_per_sec))} tok/s` });
  if (t?.total_ms) rows.push({ label: 'Latency', value: `${(Number(t.total_ms) / 1000).toFixed(1)}s total` });

  if (!summary) return null;

  return (
    <div style={{ borderTop: '1px solid var(--color-border-subtle)', marginTop: 6 }}>
      <div style={{ display: 'flex', alignItems: 'center', paddingTop: 4 }}>
        <button
          onClick={() => rows.length > 0 && setExpanded(!expanded)}
          style={{
            flex: 1, display: 'flex', alignItems: 'center', gap: 6,
            background: 'none', border: 'none', cursor: rows.length > 0 ? 'pointer' : 'default',
            padding: 0, textAlign: 'left',
          }}
        >
          <span style={{ width: 4, height: 4, borderRadius: '50%', background: 'var(--color-accent)', flexShrink: 0 }} />
          <span style={{ fontSize: 11, color: 'var(--color-text-tertiary)', fontFamily: 'system-ui' }}>
            {summary}
          </span>
          {rows.length > 0 && (
            <span style={{ fontSize: 10, color: 'var(--color-text-tertiary)' }}>
              {expanded ? '▲' : '▼'}
            </span>
          )}
        </button>
        <button
          onClick={() => onCopy(msg.id)}
          style={{
            background: 'none', border: 'none', cursor: 'pointer',
            color: 'var(--color-text-tertiary)', padding: 2,
            display: 'flex', alignItems: 'center',
          }}
          title="Copy response"
        >
          {copiedId === msg.id ? <Check size={12} /> : <Copy size={12} />}
        </button>
      </div>
      {expanded && rows.length > 0 && (
        <div style={{
          borderRadius: 6, marginTop: 4, padding: '6px 10px',
          background: 'rgba(0, 0, 0, 0.15)',
        }}>
          <div style={{
            display: 'grid', gridTemplateColumns: 'auto 1fr',
            columnGap: 12, rowGap: 2,
          }}>
            {rows.map((row) => (
              <div key={row.label} style={{ display: 'contents' }}>
                <span style={{ fontSize: 11, color: 'var(--color-text-tertiary)', fontFamily: 'monospace' }}>
                  {row.label}
                </span>
                <span style={{ fontSize: 11, color: 'var(--color-text-secondary)', fontFamily: 'monospace' }}>
                  {row.value}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function InteractTab({ agentId, agentStatus }: { agentId: string; agentStatus: string }) {
  const [messages, setMessages] = useState<InteractMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [waitingForResponse, setWaitingForResponse] = useState(false);
  const [progressLabel, setProgressLabel] = useState('');
  const [streamingContent, setStreamingContent] = useState('');
  const [streamingToolCalls, setStreamingToolCalls] = useState<ToolCallInfo[]>([]);
  const [currentActivity, setCurrentActivity] = useState('');
  const [liveStatus, setLiveStatus] = useState(agentStatus);
  const [streamElapsedMs, setStreamElapsedMs] = useState(0);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  // Phase 2E — chief routing for the interact tab.
  const { status: chiefStatus, chiefIngressActive } = useChiefHealth();
  const [isChiefAgent, setIsChiefAgent] = useState(false);
  // null = "use the default for this agent" (resolved once the record
  // loads: ON for subordinates, OFF for the Chief itself).
  const [routeThroughChiefPref, setRouteThroughChiefPref] = useState<boolean | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // Tail-mode flag: when the user is pinned to the bottom of the transcript
  // (within NEAR_BOTTOM_THRESHOLD px) we keep auto-scrolling as new content
  // streams in. If they manually scroll up, we stop following so the view
  // doesn't get yanked back down.
  const isNearBottomRef = useRef(true);

  // Keep a ref of local metadata so polling doesn't overwrite it
  const localMetaRef = useRef<Map<string, {
    _elapsed?: string;
    _toolCalls?: number;
    _usage?: Record<string, number>;
    _telemetry?: Record<string, unknown>;
    _toolCallDetails?: ToolCallInfo[];
  }>>(new Map());

  const loadData = useCallback(async () => {
    try {
      const [msgs, agent] = await Promise.all([
        fetchAgentMessages(agentId),
        fetchManagedAgent(agentId),
      ]);
      // Merge server messages with locally-stored metadata, and hydrate
      // server-persisted tool_calls into _toolCallDetails so they survive
      // page reloads.
      const merged: InteractMessage[] = msgs.map((m) => {
        const meta = localMetaRef.current.get(m.content?.slice(0, 100) || '');
        const base = meta ? { ...m, ...meta } : { ...m };
        if (!base._toolCallDetails && m.tool_calls && m.tool_calls.length > 0) {
          base._toolCallDetails = m.tool_calls.map((tc, i) => ({
            id: `${m.id}-tc-${i}`,
            tool: tc.tool,
            arguments: tc.arguments || '',
            status: tc.success === false ? 'error' : 'success',
            result: tc.result,
            latency: tc.latency,
          }));
          if (base._toolCalls == null) base._toolCalls = m.tool_calls.length;
        }
        return base;
      });
      setMessages(merged);
      setLiveStatus(agent.status);
      setCurrentActivity(agent.current_activity || '');
      setIsChiefAgent(!!agent.is_chief);
    } catch {
      // ignore
    }
  }, [agentId]);

  useEffect(() => {
    loadData();
    // Fallback slow poll — WS is primary, this catches missed events / dropped sockets
    const interval = setInterval(loadData, 30000);
    return () => clearInterval(interval);
  }, [loadData]);

  // Event-driven refresh — fires when the server reports agent activity
  useAgentEvents(agentId, loadData, [
    'agent_tick_start',
    'agent_tick_end',
    'agent_tick_error',
    'agent_message_received',
    'tool_call_end',
    'inference_end',
  ]);

  useEffect(() => { setLiveStatus(agentStatus); }, [agentStatus]);

  // Clean up elapsed-time timer on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, []);

  // Track whether the user is near the bottom. Called on every scroll
  // event; only flips the ref, never triggers a re-render.
  const handleScroll = useCallback(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    isNearBottomRef.current = distance < 80; // px threshold
  }, []);

  // Initial landing: jump to the bottom once the first batch of messages
  // arrives. Subsequent poll updates honor the tail-mode ref.
  const hasScrolled = useRef(false);
  useEffect(() => {
    if (!hasScrolled.current && messages.length > 0) {
      bottomRef.current?.scrollIntoView({ behavior: 'auto' });
      hasScrolled.current = true;
      isNearBottomRef.current = true;
    }
  }, [messages]);

  // Stream auto-follow: only scroll while the user is pinned to the bottom.
  // If they've scrolled up to re-read something, stay put.
  useEffect(() => {
    if (streamingContent && isNearBottomRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [streamingContent]);

  async function handleSend(mode: 'immediate' | 'queued') {
    if (!input.trim()) return;
    const text = input.trim();
    setInput('');
    setSending(true);

    // Show user message immediately as a local bubble
    const localMsg: AgentMessage = {
      id: `local-${Date.now()}`,
      agent_id: agentId,
      direction: 'user_to_agent',
      content: text,
      mode,
      status: 'delivered',
      created_at: Date.now() / 1000,
    };
    setMessages((prev) => [localMsg, ...prev]);
    setSending(false);
    setWaitingForResponse(true);
    setProgressLabel('Initializing agent...');
    setStreamingContent('');
    setStreamingToolCalls([]);
    // Sending is explicit user intent — always scroll and re-engage
    // tail-mode so the subsequent stream follows along.
    isNearBottomRef.current = true;
    requestAnimationFrame(() => {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    });

    // Start elapsed-time timer
    const startTime = Date.now();
    setStreamElapsedMs(0);
    timerRef.current = setInterval(() => {
      setStreamElapsedMs(Date.now() - startTime);
    }, 100);

    let toolCount = 0;
    let responseUsage: Record<string, number> | undefined;
    let responseTelemetry: Record<string, unknown> | undefined;
    const collectedToolCalls: ToolCallInfo[] = [];
    // Phase 2E — route a subordinate's interact message through the
    // Chief when the feature is active and the user hasn't opted out.
    // The Chief itself always talks directly (routing it through itself
    // would be a no-op extra hop).
    const routeThroughChief =
      chiefIngressActive && !isChiefAgent && (routeThroughChiefPref ?? true);
    try {
      const messageCallbacks = {
        onProgress: (label: string) => {
          setProgressLabel(label);
          toolCount++;
        },
        onContentDelta: (_delta: string, full: string) => setStreamingContent(full),
        onToolCallStart: ({ tool, arguments: args }: { tool: string; arguments: string }) => {
          toolCount++;
          const tc: ToolCallInfo = {
            id: `tc-${Date.now()}-${collectedToolCalls.length}`,
            tool,
            arguments: args,
            status: 'running',
          };
          collectedToolCalls.push(tc);
          setStreamingToolCalls([...collectedToolCalls]);
          setProgressLabel(`Calling ${tool}...`);
        },
        onToolCallEnd: (
          { tool, success, latency, result }:
          { tool: string; success: boolean; latency: number; result?: unknown },
        ) => {
          const match = [...collectedToolCalls]
            .reverse()
            .find((t) => t.tool === tool && t.status === 'running');
          if (match) {
            match.status = success ? 'success' : 'error';
            match.latency = latency;
            match.result = result as string | undefined;
          }
          setStreamingToolCalls([...collectedToolCalls]);
          setProgressLabel('');
        },
        onDone: (
          _content: string,
          usage?: Record<string, number>,
          telemetry?: Record<string, unknown>,
        ) => {
          setStreamingContent('');
          responseUsage = usage;
          responseTelemetry = telemetry;
        },
      };
      const response = routeThroughChief
        ? await sendChiefMessage(text, { mode, callbacks: messageCallbacks })
        : await sendAgentMessage(agentId, text, mode, messageCallbacks);
      const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
      // Add the agent's response as a local bubble immediately
      if (response && (response.content || collectedToolCalls.length > 0)) {
        const meta = {
          _elapsed: elapsed,
          _toolCalls: toolCount,
          _usage: responseUsage,
          _telemetry: responseTelemetry,
          _toolCallDetails: collectedToolCalls.length > 0 ? [...collectedToolCalls] : undefined,
        };
        // Store metadata keyed by content prefix so polling preserves it
        localMetaRef.current.set(response.content.slice(0, 100), meta);
        setMessages((prev) => [
          {
            ...response,
            id: response.id || `response-${Date.now()}`,
            direction: 'agent_to_user' as const,
            ...meta,
          },
          ...prev,
        ]);
      }
      // Also refresh from server to sync any persisted messages
      await loadData();
    } catch {
      // ignore
    } finally {
      setWaitingForResponse(false);
      setStreamingContent('');
      setStreamingToolCalls([]);
      setProgressLabel('');
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      setStreamElapsedMs(0);
    }
  }

  // Reverse so newest messages appear at the bottom (closest to input).
  // Filter out agent responses with empty content.
  const displayMessages = [...messages]
    .filter(
      (m) =>
        m.direction === 'user_to_agent' ||
        m.content.trim() ||
        (m._toolCallDetails && m._toolCallDetails.length > 0),
    )
    .reverse();

  return (
    <div className="flex flex-col" style={{ minHeight: 320 }}>
      <div
        ref={scrollContainerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto space-y-3 pb-4"
        style={{ maxHeight: 'calc(100vh - 400px)' }}
      >
        {displayMessages.length === 0 && !waitingForResponse && (
          <div className="text-sm text-center py-8" style={{ color: 'var(--color-text-tertiary)' }}>
            No messages yet. Send a message to interact with this agent.
          </div>
        )}
        {displayMessages.map((msg) => (
          <div key={msg.id} className="space-y-2">
            {/* Tool calls rendered as their own full-width entries (like Claude Code) */}
            {msg.direction === 'agent_to_user' && msg._toolCallDetails && msg._toolCallDetails.length > 0 && (
              <div className="flex flex-col items-start gap-2 max-w-[75%]">
                {msg._toolCallDetails.map((tc) => (
                  <ToolCallCard key={tc.id} toolCall={tc} />
                ))}
              </div>
            )}
            {/* Message bubble — skip the empty agent bubble when a turn
                produced only tool-call cards (rendered above), so the
                results stay visible instead of vanishing. */}
            {(msg.direction === 'user_to_agent' || msg.content.trim()) && (
            <div className={`flex ${msg.direction === 'user_to_agent' ? 'justify-end' : 'justify-start'}`}>
              <div
                className="max-w-[75%] px-3 py-2 rounded-lg text-sm"
                style={{
                  background: msg.direction === 'user_to_agent' ? 'var(--color-accent)' : 'var(--color-bg-secondary)',
                  color: msg.direction === 'user_to_agent' ? 'var(--color-on-accent)' : 'var(--color-text)',
                  border: msg.direction === 'agent_to_user' ? '1px solid var(--color-border)' : 'none',
                }}
              >
                {msg.direction === 'agent_to_user' ? (
                  <div className="prose prose-sm prose-invert max-w-none"><ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown></div>
                ) : (
                  <p>{msg.content}</p>
                )}
                <p className="text-xs mt-1 opacity-70">
                  {msg.status === 'pending' ? 'sending...' : new Date(msg.created_at * 1000).toLocaleTimeString()}
                </p>
                {msg.direction === 'agent_to_user' && (
                  <AgentResponseFooter msg={msg} copiedId={copiedId} onCopy={(id) => {
                    navigator.clipboard.writeText(msg.content);
                    setCopiedId(id);
                    setTimeout(() => setCopiedId(null), 2000);
                  }} />
                )}
              </div>
            </div>
            )}
          </div>
        ))}
        {/* Progress indicator — shown when waiting but no streamed content or tool calls yet */}
        {(waitingForResponse || sending) && !streamingContent && streamingToolCalls.length === 0 && (
          <div className="flex justify-start">
            <div
              className="px-3 py-2 rounded-lg text-sm"
              style={{
                background: 'var(--color-bg-secondary)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text-secondary)',
              }}
            >
              <div className="flex items-center gap-2">
                <span className="inline-block w-2 h-2 rounded-full animate-pulse" style={{ background: 'var(--color-accent)' }} />
                {sending
                  ? 'Sending message...'
                  : progressLabel || 'Agent is thinking...'}
              </div>
            </div>
          </div>
        )}
        {/* Live tool call cards rendered as their own entries in the flow */}
        {waitingForResponse && streamingToolCalls.length > 0 && (
          <div className="flex flex-col items-start gap-2 max-w-[75%]">
            {streamingToolCalls.map((tc) => (
              <ToolCallCard key={tc.id} toolCall={tc} />
            ))}
          </div>
        )}
        {/* Streaming content bubble — real-time response */}
        {waitingForResponse && streamingContent && (
          <div className="flex justify-start">
            <div
              className="max-w-[75%] px-3 py-2 rounded-lg text-sm"
              style={{
                background: 'var(--color-bg-secondary)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text)',
              }}
            >
              {progressLabel && (
                <div className="flex items-center gap-2 mb-2 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                  <span className="inline-block w-2 h-2 rounded-full animate-pulse" style={{ background: 'var(--color-accent)' }} />
                  {progressLabel}
                </div>
              )}
              <div className="prose prose-sm prose-invert max-w-none">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{streamingContent}</ReactMarkdown>
              </div>
              <p className="text-xs mt-1 opacity-70">
                {streamElapsedMs > 0 && `${(streamElapsedMs / 1000).toFixed(1)}s elapsed`}
              </p>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
      {/* Input area */}
      <div
        className="mt-3 pt-3"
        style={{ borderTop: '1px solid var(--color-border)' }}
      >
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              handleSend('immediate');
            }
          }}
          placeholder="Send a message to this agent..."
          className="w-full px-3 py-2 rounded-lg text-sm bg-transparent outline-none resize-none"
          style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)', minHeight: 72 }}
        />
        <div className="flex items-center gap-2 mt-2">
          <button
            onClick={() => handleSend('immediate')}
            disabled={sending || waitingForResponse || !input.trim()}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm cursor-pointer font-medium"
            style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)', opacity: sending || !input.trim() ? 0.5 : 1 }}
          >
            <Send size={13} /> Send
          </button>
          {/* Phase 2E — Route-through-Chief toggle. Shown only for
              subordinate agents while the Chief ingress is active.
              The Chief itself always talks directly. */}
          {chiefIngressActive && !isChiefAgent && (
            <label
              className="flex items-center gap-1.5 text-xs cursor-pointer select-none"
              style={{ color: 'var(--color-text-secondary)' }}
              title={
                'When on, your message goes to the Chief Orchestrator, '
                + 'which decides whether to answer, delegate to this '
                + 'agent, or decompose the work.'
              }
            >
              <input
                type="checkbox"
                checked={routeThroughChiefPref ?? true}
                onChange={(e) => setRouteThroughChiefPref(e.target.checked)}
              />
              Route through {chiefStatus.chief_name || 'Chief'}
            </label>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Channels tab component (data sources)
// ---------------------------------------------------------------------------

function ChannelsTab({ agentId }: { agentId: string }) {
  const [connectors, setConnectors] = useState<
    Array<{ connector_id: string; display_name: string; connected: boolean; chunks: number }>
  >([]);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // suppress unused var – agentId reserved for future per-agent source binding
  void agentId;

  const loadConnectors = useCallback(() => {
    listConnectors()
      .then((list) =>
        setConnectors(
          list.map((c) => ({
            connector_id: c.connector_id,
            display_name: c.display_name,
            connected: c.connected,
            chunks: (c as any).chunks || 0,
          })),
        ),
      )
      .catch(() => {});
  }, []);

  useEffect(() => {
    loadConnectors();
    // Poll every 10s to catch background OAuth completions
    const interval = setInterval(loadConnectors, 10000);
    return () => clearInterval(interval);
  }, [loadConnectors]);

  const handleConnect = async (id: string, req: ConnectRequest) => {
    setLoading(true);
    try {
      await connectSource(id, req);
      setExpandedId(null);
      // Poll for connection status (OAuth flow runs in background thread)
      for (let i = 0; i < 30; i++) {
        await new Promise((r) => setTimeout(r, 3000));
        await loadConnectors();
        // Check if this connector is now connected
        const updated = await listConnectors();
        const target = updated.find((c) => c.connector_id === id);
        if (target?.connected) break;
      }
    } catch {
      // error handling
    } finally {
      setLoading(false);
    }
  };

  const connected = connectors.filter((c) => c.connected);
  const notConnected = connectors.filter((c) => !c.connected);

  // Merge with SOURCE_CATALOG for icons/descriptions
  const getMeta = (id: string) =>
    SOURCE_CATALOG.find((s) => s.connector_id === id);

  const iconMap: Record<string, string> = {
    gmail: '\u2709\uFE0F', gmail_imap: '\u2709\uFE0F', slack: '#',
    imessage: '\uD83D\uDCAC', gdrive: '\uD83D\uDCC1', notion: '\uD83D\uDCC4',
    obsidian: '\uD83D\uDCC1', granola: '\uD83C\uDF99\uFE0F', gcalendar: '\uD83D\uDCC5',
    gcontacts: '\uD83D\uDCC7', outlook: '\u2709\uFE0F', apple_notes: '\uD83C\uDF4E',
    dropbox: '\uD83D\uDCE6', whatsapp: '\uD83D\uDCF1',
  };

  return (
    <div style={{ padding: 16 }}>
      <div style={{
        color: 'var(--color-text-secondary)',
        fontSize: 12, marginBottom: 12,
      }}>
        Data sources your agent can search across
      </div>

      {/* Connected sources grid */}
      {connected.length > 0 && (
        <div style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: 6, marginBottom: 12,
        }}>
          {connected.map((c) => {
            const meta = SOURCE_CATALOG.find(s => s.connector_id === c.connector_id);
            const unit = meta?.unitLabel || 'items';
            const isReconnecting = expandedId === c.connector_id;
            return (
            <div
              key={c.connector_id}
              style={{
                background: 'var(--color-bg-secondary)',
                border: '1px solid color-mix(in srgb, var(--color-success) 22%, transparent)',
                borderRadius: 6,
                overflow: 'hidden',
                gridColumn: isReconnecting ? '1 / -1' : undefined,
              }}
            >
              <div style={{
                padding: '12px 14px',
                display: 'flex', alignItems: 'center', gap: 8,
              }}>
                <span style={{ fontSize: 20 }}>{iconMap[c.connector_id] || '\uD83D\uDD17'}</span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 14, fontWeight: 600 }}>
                    {c.display_name}
                  </div>
                  <div style={{ fontSize: 12, color: c.chunks > 0 ? 'var(--color-success)' : 'var(--color-warning)' }}>
                    {c.chunks > 0
                      ? `${c.chunks.toLocaleString()} ${unit}`
                      : 'Connected — no data synced yet'}
                  </div>
                </div>
                <button
                  onClick={() => setExpandedId(isReconnecting ? null : c.connector_id)}
                  style={{
                    fontSize: 10, padding: '3px 10px',
                    background: 'transparent',
                    color: 'var(--color-text-secondary)',
                    border: '1px solid var(--color-border)',
                    borderRadius: 4, cursor: 'pointer',
                  }}
                >
                  {isReconnecting ? 'Cancel' : 'Reconnect'}
                </button>
              </div>
              {isReconnecting && meta?.steps && (
                <div style={{
                  borderTop: '1px solid var(--color-border)',
                  padding: 12,
                }}>
                  <div style={{
                    fontSize: 12, color: 'var(--color-warning)',
                    marginBottom: 8,
                  }}>
                    Re-enter credentials to reconnect this source.
                  </div>
                  {meta.steps.map((step, i) => (
                    <div
                      key={i}
                      style={{
                        background: 'var(--color-bg)',
                        border: '1px solid var(--color-border)',
                        borderRadius: 6, padding: 10,
                        marginBottom: 8,
                      }}
                    >
                      <div style={{
                        color: 'var(--color-accent-purple)', fontSize: 10,
                        fontWeight: 600, marginBottom: 3,
                      }}>
                        STEP {i + 1}
                      </div>
                      <div style={{ fontSize: 12, marginBottom: step.url ? 4 : 0 }}>
                        {step.label}
                      </div>
                      {step.url && (
                        <a
                          href={step.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{
                            color: 'var(--color-accent)', fontSize: 11,
                            textDecoration: 'underline',
                          }}
                        >
                          {step.urlLabel || 'Open'} →
                        </a>
                      )}
                    </div>
                  ))}
                  {meta.inputFields && (
                    <InlineConnectForm
                      fields={meta.inputFields}
                      loading={loading}
                      onSubmit={(req) => handleConnect(c.connector_id, req)}
                    />
                  )}
                </div>
              )}
            </div>
            );
          })}
        </div>
      )}

      {/* Not connected grid */}
      {notConnected.length > 0 && (
        <div style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: 6,
        }}>
          {notConnected.map((c) => {
            const meta = getMeta(c.connector_id);
            const isExpanded = expandedId === c.connector_id;

            return (
              <div
                key={c.connector_id}
                style={{
                  background: 'var(--color-bg-secondary)',
                  border: '1px dashed var(--color-border)',
                  borderRadius: 6, overflow: 'hidden',
                  opacity: isExpanded ? 1 : 0.6,
                  gridColumn: isExpanded ? '1 / -1' : undefined,
                }}
              >
                <div
                  style={{
                    padding: '12px 14px', display: 'flex',
                    alignItems: 'center', gap: 8,
                    cursor: 'pointer',
                  }}
                  onClick={() =>
                    setExpandedId(isExpanded ? null : c.connector_id)
                  }
                >
                  <span style={{ fontSize: 20 }}>{iconMap[c.connector_id] || '\uD83D\uDD17'}</span>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 14, fontWeight: 600,
                      color: 'var(--color-text-secondary)' }}>
                      {c.display_name}
                    </div>
                    <div style={{ fontSize: 12,
                      color: 'var(--color-text-secondary)' }}>
                      Not connected
                    </div>
                  </div>
                  <span style={{
                    color: 'var(--color-accent-purple)', fontSize: 11, fontWeight: 500,
                  }}>
                    {isExpanded ? '\u2715 Close' : '+ Add'}
                  </span>
                </div>

                {/* Inline setup panel */}
                {isExpanded && meta?.steps && (
                  <div style={{
                    borderTop: '1px solid var(--color-border)',
                    padding: 12,
                  }}>
                    {meta.steps.map((step, i) => (
                      <div
                        key={i}
                        style={{
                          background: 'var(--color-bg)',
                          border: '1px solid var(--color-border)',
                          borderRadius: 6, padding: 10,
                          marginBottom: 8,
                        }}
                      >
                        <div style={{
                          color: 'var(--color-accent-purple)', fontSize: 10,
                          fontWeight: 600, marginBottom: 3,
                        }}>
                          STEP {i + 1}
                        </div>
                        <div style={{
                          fontSize: 12, marginBottom: step.url ? 4 : 0,
                        }}>
                          {step.label}
                        </div>
                        {step.url && (
                          <a
                            href={step.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{
                              color: 'var(--color-accent)', fontSize: 11,
                              textDecoration: 'underline',
                            }}
                          >
                            {step.urlLabel || 'Open'} {'\u2192'}
                          </a>
                        )}
                      </div>
                    ))}
                    {meta.inputFields && (
                      <InlineConnectForm
                        fields={meta.inputFields}
                        loading={loading}
                        onSubmit={(req) =>
                          handleConnect(c.connector_id, req)
                        }
                      />
                    )}
                    <div style={{
                      fontSize: 10, color: 'var(--color-text-secondary)',
                      textAlign: 'center', marginTop: 8,
                    }}>
                      {'\uD83D\uDD12'} Read-only access {'\u00B7'} No data leaves your device
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function InlineConnectForm({
  fields,
  loading,
  onSubmit,
}: {
  fields: Array<{ name: string; placeholder: string; type?: string }>;
  loading: boolean;
  onSubmit: (req: ConnectRequest) => void;
}) {
  const [inputs, setInputs] = useState<Record<string, string>>({});

  const update = (name: string, value: string) =>
    setInputs((p) => ({ ...p, [name]: value }));

  const allFilled = fields.every((f) => inputs[f.name]?.trim());

  const submit = () => {
    const req: ConnectRequest = {};
    for (const f of fields) {
      if (f.name === 'email') req.email = inputs.email;
      else if (f.name === 'password') req.password = inputs.password;
      else if (f.name === 'token') req.token = inputs.token;
      else if (f.name === 'path') req.path = inputs.path;
    }
    if (req.email && req.password) {
      req.token = `${req.email}:${req.password}`;
      req.code = req.token;
    }
    if (req.token && !req.code) req.code = req.token;
    onSubmit(req);
  };

  return (
    <div>
      {fields.map((f) => (
        <input
          key={f.name}
          value={inputs[f.name] || ''}
          onChange={(e) => update(f.name, e.target.value)}
          placeholder={f.placeholder}
          type={f.type || 'text'}
          style={{
            width: '100%', padding: '7px 10px',
            background: 'var(--color-bg)',
            border: '1px solid var(--color-border)',
            borderRadius: 4, color: 'var(--color-text)',
            fontSize: 12, marginBottom: 6,
            boxSizing: 'border-box',
          }}
        />
      ))}
      <button
        onClick={submit}
        disabled={loading || !allFilled}
        style={{
          width: '100%', padding: 8,
          background: loading || !allFilled ? 'var(--color-disabled-bg)' : 'var(--color-accent-purple)',
          color: 'var(--color-on-accent)', border: 'none',
          borderRadius: 6, fontSize: 12, cursor: 'pointer',
        }}
      >
        {loading ? 'Connecting...' : 'Connect'}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Messaging tab component
// ---------------------------------------------------------------------------

interface ChannelField {
  key: string;
  label: string;
  placeholder: string;
  type?: 'text' | 'password';
  required?: boolean;
}

interface MessagingChannelConfig {
  type: string;
  name: string;
  icon: string;
  description: string;
  setupSteps: string[];
  fields: ChannelField[];
  activeLabel: (cfg: Record<string, unknown>) => string;
  howToUse: (cfg: Record<string, unknown>) => string;
}

const MESSAGING_CHANNELS: MessagingChannelConfig[] = [
  // SendBlue (iMessage + SMS) is handled by the dedicated SendBlueWizard above.
  // These are the other supported channels.
  {
    type: 'slack',
    name: 'Slack',
    icon: '#',
    description: 'DM your agent in any Slack workspace',
    setupSteps: [
      '1. Go to api.slack.com/apps → click "Create New App" → choose "From an app manifest"',
      '2. Select your workspace. When asked for the manifest format, choose JSON. Then paste the manifest below (click "Copy" to copy it):',
      'COPYABLE:{"display_information":{"name":"OpenJarvis"},"features":{"app_home":{"home_tab_enabled":true,"messages_tab_enabled":true,"messages_tab_read_only_enabled":false},"bot_user":{"display_name":"OpenJarvis","always_online":true}},"oauth_config":{"scopes":{"bot":["chat:write","im:write","im:read","im:history","mpim:read","mpim:history","users:read","channels:read","channels:history","channels:join","groups:read","groups:history","app_mentions:read"]}},"settings":{"event_subscriptions":{"bot_events":["message.im"]},"socket_mode_enabled":true}}',
      '3. Click "Next" → review the summary → click "Create". Then go to "Install App" in the left sidebar → click "Install to Workspace" → click "Allow"',
      '4. In the left sidebar, click "OAuth & Permissions". Copy the "Bot User OAuth Token" (starts with xoxb-...)',
      '5. In the left sidebar, click "Basic Information" → scroll to "App-Level Tokens" → click "Generate Token and Scopes" → name it "socket" → click "Add Scope" → select "connections:write" → click "Generate" → copy the token (starts with xapp-...)',
      '6. (Optional) Still in "Basic Information", scroll to "Display Information" → upload the OpenJarvis icon as the app icon',
      '7. Paste both tokens below and click Connect',
    ],
    fields: [
      { key: 'bot_token', label: 'Bot Token', placeholder: 'xoxb-...', type: 'password', required: true },
      { key: 'app_token', label: 'App Token', placeholder: 'xapp-...', type: 'password', required: true },
    ],
    activeLabel: () => 'Connected to Slack',
    howToUse: () => 'Open Slack and DM @OpenJarvis to talk to your agent.',
  },
  {
    type: 'telegram',
    name: 'Telegram',
    icon: '✈',
    description: 'DM this agent on Telegram via a shared bot',
    setupSteps: [
      '1. Create one Telegram bot via @BotFather (use the same bot for every agent).',
      '2. Put its token in ~/.openjarvis/config.toml under [channels.telegram] bot_token = "..." and restart the server.',
      '3. Open Telegram, talk to your bot once (any message), then visit @userinfobot or @getmyid_bot to read your numeric chat ID.',
      '4. Paste that chat ID below. You can dedicate that chat to this agent, or reuse the same chat for multiple agents and target one explicitly with /agent <id> <message>.',
    ],
    fields: [
      { key: 'channel', label: 'Telegram Chat ID', placeholder: '123456789', type: 'text', required: true },
    ],
    activeLabel: (cfg) =>
      cfg.channel ? `Chat ID ${String(cfg.channel)}` : 'Telegram connected',
    howToUse: (cfg) =>
      cfg.channel
        ? `Message your bot from chat ${String(cfg.channel)}. If this chat is shared across agents, use /agent <id> <message> to route to a specific one.`
        : 'Message your bot from the bound chat. If that chat is shared across agents, use /agent <id> <message> to target one.',
  },
];

// ---------------------------------------------------------------------------
// SendBlue webhook step — ngrok tunnel + registration
// ---------------------------------------------------------------------------

function SendBlueWebhookStep({
  apiKey, apiSecret, selectedNumber,
}: {
  apiKey: string; apiSecret: string; selectedNumber: string;
}) {
  const [webhookUrl, setWebhookUrl] = useState('');
  const [webhookStatus, setWebhookStatus] = useState<'idle' | 'registering' | 'done' | 'error'>('idle');

  const registerWebhook = async () => {
    if (!webhookUrl.trim()) return;
    setWebhookStatus('registering');
    try {
      const url = webhookUrl.trim().replace(/\/+$/, '') + '/v1/channels/sendblue/webhook';
      await sendblueRegisterWebhook(apiKey, apiSecret, url);
      setWebhookStatus('done');
    } catch {
      setWebhookStatus('error');
    }
  };

  return (
    <div style={{ borderTop: '1px solid var(--color-border)', padding: 14, background: 'var(--color-bg)' }}>
      <div style={{
        background: 'color-mix(in srgb, var(--color-success) 10%, var(--color-bg))', border: '1px solid color-mix(in srgb, var(--color-success) 22%, transparent)',
        borderRadius: 6, padding: 12, marginBottom: 12, textAlign: 'center',
      }}>
        <div style={{ fontSize: 11, color: 'var(--color-success)', fontWeight: 600, marginBottom: 4 }}>
          {'\u2713'} Your agent is now reachable via iMessage / SMS
        </div>
        <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--color-success)' }}>{selectedNumber}</div>
      </div>

      {/* Webhook / ngrok step */}
      <div style={{ marginTop: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
          <span style={{ background: 'var(--color-accent-purple)', color: 'var(--color-on-accent)', borderRadius: '50%', width: 20, height: 20, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700, flexShrink: 0 }}>4</span>
          <span style={{ fontSize: 12, fontWeight: 600 }}>Set up webhook to receive texts</span>
        </div>
        <div style={{
          fontSize: 11, lineHeight: 1.6,
          color: 'var(--color-text-secondary)',
          padding: '8px 10px', marginBottom: 10,
          background: 'var(--color-bg-secondary)',
          borderRadius: 6,
          borderLeft: '3px solid var(--color-accent, var(--color-accent-purple))',
        }}>
          <div><strong>1.</strong> Open a terminal and run: <code style={{ color: 'var(--color-accent)', background: 'var(--color-bg)', padding: '1px 4px', borderRadius: 3 }}>ngrok http 8000</code></div>
          <div style={{ marginTop: 4 }}><strong>2.</strong> Copy the <code style={{ color: 'var(--color-accent)', background: 'var(--color-bg)', padding: '1px 4px', borderRadius: 3 }}>https://</code> forwarding URL</div>
          <div style={{ marginTop: 4 }}><strong>3.</strong> Paste it below and click "Register Webhook"</div>
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <input
            value={webhookUrl}
            onChange={(e) => { setWebhookUrl(e.target.value); setWebhookStatus('idle'); }}
            placeholder="https://abc123.ngrok-free.app"
            style={{
              flex: 1, padding: '7px 10px', background: 'var(--color-bg-secondary)',
              border: '1px solid var(--color-border)', borderRadius: 4,
              color: 'var(--color-text)', fontSize: 12, boxSizing: 'border-box' as const,
            }}
          />
          <button
            onClick={registerWebhook}
            disabled={!webhookUrl.trim() || webhookStatus === 'registering'}
            style={{
              fontSize: 11, padding: '7px 14px', whiteSpace: 'nowrap' as const,
              background: webhookStatus === 'done' ? 'var(--color-success)' : 'var(--color-accent-purple)',
              color: 'var(--color-on-accent)', border: 'none', borderRadius: 5,
              cursor: 'pointer', fontWeight: 600,
              opacity: !webhookUrl.trim() || webhookStatus === 'registering' ? 0.5 : 1,
            }}
          >
            {webhookStatus === 'registering' ? 'Registering...'
              : webhookStatus === 'done' ? 'Registered!'
              : webhookStatus === 'error' ? 'Retry'
              : 'Register Webhook'}
          </button>
        </div>
        {webhookStatus === 'done' && (
          <div style={{ fontSize: 11, color: 'var(--color-success)', marginTop: 6 }}>
            Webhook registered! Incoming texts will be forwarded to your agent.
          </div>
        )}
        {webhookStatus === 'error' && (
          <div style={{ fontSize: 11, color: 'var(--color-error)', marginTop: 6 }}>
            Failed to register. Check your ngrok URL and try again.
          </div>
        )}
        <div style={{ fontSize: 10, color: 'var(--color-text-tertiary)', marginTop: 8 }}>
          Don't have ngrok? <a href="https://ngrok.com/download" target="_blank" rel="noopener noreferrer" style={{ color: 'var(--color-accent)', textDecoration: 'underline' }}>Download it free</a>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// SendBlue setup wizard — guided multi-step flow
// ---------------------------------------------------------------------------

function SendBlueWizard({
  agentId,
  binding,
  onDone,
  onRemove,
}: {
  agentId: string;
  binding: ChannelBinding | undefined;
  onDone: () => void;
  onRemove: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [step, setStep] = useState<'idle' | 'creds' | 'verifying' | 'verified' | 'connecting' | 'done' | 'test'>('idle');
  const [apiKey, setApiKey] = useState('');
  const [apiSecret, setApiSecret] = useState('');
  const [numbers, setNumbers] = useState<string[]>([]);
  const [selectedNumber, setSelectedNumber] = useState('');
  const [error, setError] = useState('');
  const [testNumber, setTestNumber] = useState('');
  const [testSent, setTestSent] = useState(false);

  const [healthy, setHealthy] = useState(true);
  const [reconnecting, setReconnecting] = useState(false);

  const isActive = !!binding;
  const activeNumber = (binding?.config?.from_number as string) || '';

  // Check health on mount when active
  useEffect(() => {
    if (!isActive) return;
    sendblueHealth().then((h) => setHealthy(h.ready)).catch(() => setHealthy(false));
  }, [isActive]);

  const handleReconnect = async () => {
    if (!binding) return;
    setReconnecting(true);
    try {
      // Re-bind to re-create the bridge
      const cfg = binding.config || {};
      await unbindAgentChannel(agentId, binding.id);
      await bindAgentChannel(agentId, 'sendblue', cfg as Record<string, unknown>);
      setHealthy(true);
      onDone();
    } catch { /* */ } finally { setReconnecting(false); }
  };

  const cardStyle: React.CSSProperties = {
    background: 'var(--color-bg-secondary)',
    border: isActive ? '1px solid color-mix(in srgb, var(--color-success) 22%, transparent)' : '1px dashed var(--color-border)',
    borderRadius: 8, marginBottom: 10, overflow: 'hidden',
  };

  const btnPrimary: React.CSSProperties = {
    fontSize: 12, padding: '7px 18px', background: 'var(--color-accent-purple)', color: 'var(--color-on-accent)',
    border: 'none', borderRadius: 5, cursor: 'pointer', fontWeight: 600,
  };

  const btnSecondary: React.CSSProperties = {
    fontSize: 11, padding: '5px 14px', background: 'transparent',
    color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)',
    borderRadius: 4, cursor: 'pointer',
  };

  const inputStyle: React.CSSProperties = {
    width: '100%', padding: '7px 10px', background: 'var(--color-bg-secondary)',
    border: '1px solid var(--color-border)', borderRadius: 4,
    color: 'var(--color-text)', fontSize: 12, boxSizing: 'border-box',
  };

  const handleVerify = async () => {
    setError('');
    setStep('verifying');
    try {
      const result = await sendblueVerify(apiKey, apiSecret);
      if (result.valid && result.numbers.length > 0) {
        setNumbers(result.numbers);
        setSelectedNumber(result.numbers[0]);
        setStep('verified');
      } else if (result.valid) {
        // Free tier / shared line — no dedicated number returned
        // Move to verified step so user can enter the number manually
        setNumbers([]);
        setSelectedNumber('');
        setStep('verified');
      } else {
        setError('Invalid credentials. Check your API key and secret.');
        setStep('creds');
      }
    } catch (e) {
      setError((e as Error).message);
      setStep('creds');
    }
  };

  const handleConnect = async () => {
    setError('');
    setStep('connecting');
    try {
      // 1. Bind the channel
      await bindAgentChannel(agentId, 'sendblue', {
        api_key_id: apiKey,
        api_secret_key: apiSecret,
        from_number: selectedNumber,
      });
      // 2. Try to auto-register webhook (best effort)
      try {
        const webhookUrl = `${window.location.origin}/webhooks/sendblue`;
        await sendblueRegisterWebhook(apiKey, apiSecret, webhookUrl);
      } catch {
        // Non-fatal — user may need to set up ngrok manually
      }
      setStep('done');
      onDone();
    } catch (e) {
      setError((e as Error).message);
      setStep('verified');
    }
  };

  const handleTest = async () => {
    if (!testNumber.trim()) return;
    setError('');
    try {
      const cfg = binding?.config || {};
      await sendblueTest(
        (cfg.api_key_id as string) || apiKey,
        (cfg.api_secret_key as string) || apiSecret,
        activeNumber || selectedNumber,
        testNumber.trim(),
      );
      setTestSent(true);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  // Active state
  if (isActive && !expanded) {
    return (
      <div style={cardStyle}>
        <div style={{ display: 'flex', alignItems: 'center', padding: '12px 14px' }}>
          <span style={{ fontSize: 18, marginRight: 10 }}>{'\uD83D\uDCAC'}</span>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 600, fontSize: 13 }}>iMessage / SMS</div>
            <div style={{ fontSize: 11, color: healthy ? 'var(--color-success)' : 'var(--color-warning)' }}>
              {healthy ? `Active on ${activeNumber}` : `Disconnected — ${activeNumber}`}
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {!healthy && (
              <button
                onClick={handleReconnect}
                disabled={reconnecting}
                style={{ ...btnPrimary, fontSize: 10, padding: '3px 10px' }}
              >
                {reconnecting ? '...' : 'Reconnect'}
              </button>
            )}
            <span style={{
              background: healthy ? 'color-mix(in srgb, var(--color-success) 22%, transparent)' : 'color-mix(in srgb, var(--color-warning) 18%, var(--color-bg))',
              color: healthy ? 'var(--color-success)' : 'var(--color-warning)',
              padding: '2px 8px', borderRadius: 10, fontSize: 10, fontWeight: 600,
            }}>{healthy ? 'Active' : 'Disconnected'}</span>
            <button onClick={() => setExpanded(true)} style={btnSecondary}>
              Details
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Active + expanded (show how to use + test)
  if (isActive && expanded) {
    return (
      <div style={cardStyle}>
        <div style={{ display: 'flex', alignItems: 'center', padding: '12px 14px' }}>
          <span style={{ fontSize: 18, marginRight: 10 }}>{'\uD83D\uDCAC'}</span>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 600, fontSize: 13 }}>iMessage / SMS</div>
            <div style={{ fontSize: 11, color: 'var(--color-success)' }}>Active on {activeNumber}</div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => setExpanded(false)} style={btnSecondary}>Collapse</button>
            <button onClick={() => onRemove(binding!.id)} style={{ ...btnSecondary, color: 'var(--color-error)' }}>Remove</button>
          </div>
        </div>
        <div style={{ borderTop: '1px solid var(--color-border)', padding: 14, background: 'var(--color-bg)' }}>
          <div style={{ fontSize: 12, marginBottom: 10, lineHeight: 1.6 }}>
            {'\u2192'} Text <strong>{activeNumber}</strong> from any phone to talk to your agent.
            Responses arrive as iMessage (blue bubbles) when possible, SMS otherwise.
          </div>

          <div style={{ fontSize: 11, color: 'var(--color-text-secondary)', marginBottom: 8, fontWeight: 600 }}>
            Send a test message
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <input
              value={testNumber}
              onChange={(e) => { setTestNumber(e.target.value); setTestSent(false); }}
              placeholder="Your phone number (+1...)"
              style={{ ...inputStyle, flex: 1 }}
            />
            <button
              onClick={handleTest}
              disabled={!testNumber.trim() || testSent}
              style={{ ...btnPrimary, opacity: !testNumber.trim() ? 0.5 : 1 }}
            >
              {testSent ? 'Sent!' : 'Send Test'}
            </button>
          </div>
          {error && <div style={{ color: 'var(--color-error)', fontSize: 11, marginTop: 6 }}>{error}</div>}
        </div>
      </div>
    );
  }

  // Not active — setup wizard
  return (
    <div style={cardStyle}>
      {/* Header */}
      <div
        style={{ display: 'flex', alignItems: 'center', padding: '12px 14px', cursor: 'pointer' }}
        onClick={() => setStep(step === 'idle' ? 'creds' : 'idle')}
      >
        <span style={{ fontSize: 18, marginRight: 10 }}>{'\uD83D\uDCAC'}</span>
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 600, fontSize: 13 }}>iMessage / SMS</div>
          <div style={{ fontSize: 11, color: 'var(--color-text-secondary)' }}>
            Your agent gets its own phone number — text it via iMessage or SMS
          </div>
        </div>
        <button
          onClick={(e) => { e.stopPropagation(); setStep(step === 'idle' ? 'creds' : 'idle'); }}
          style={{ fontSize: 10, padding: '3px 12px', background: 'var(--color-accent-purple)', color: 'var(--color-on-accent)', border: 'none', borderRadius: 5, cursor: 'pointer', fontWeight: 600 }}
        >
          {step === 'idle' ? 'Set Up' : 'Cancel'}
        </button>
      </div>

      {/* Step 1: Sign up + enter credentials */}
      {(step === 'creds' || step === 'verifying') && (
        <div style={{ borderTop: '1px solid var(--color-border)', padding: 14, background: 'var(--color-bg)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
            <span style={{ background: 'var(--color-accent-purple)', color: 'var(--color-on-accent)', borderRadius: '50%', width: 20, height: 20, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700, flexShrink: 0 }}>1</span>
            <span style={{ fontSize: 12, fontWeight: 600 }}>Create a SendBlue account</span>
          </div>
          <button
            onClick={() => window.open('https://dashboard.sendblue.com/company-signup', '_blank')}
            style={{ ...btnPrimary, marginBottom: 14, display: 'flex', alignItems: 'center', gap: 6 }}
          >
            Open SendBlue signup {'\u2192'}
          </button>

          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
            <span style={{ background: 'var(--color-accent-purple)', color: 'var(--color-on-accent)', borderRadius: '50%', width: 20, height: 20, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700, flexShrink: 0 }}>2</span>
            <span style={{ fontSize: 12, fontWeight: 600 }}>Paste your API credentials</span>
          </div>
          <div style={{ fontSize: 11, color: 'var(--color-text-secondary)', marginBottom: 8 }}>
            Go to your{' '}
            <a href="https://dashboard.sendblue.co/api-credentials" target="_blank" rel="noopener noreferrer" style={{ color: 'var(--color-accent)', textDecoration: 'underline' }}>
              SendBlue API Credentials page
            </a>{' '}
            and copy the API Key and API Secret.
          </div>

          <div style={{ marginBottom: 8 }}>
            <label style={{ display: 'block', fontSize: 11, color: 'var(--color-text-secondary)', marginBottom: 3, fontWeight: 500 }}>
              API Key ID *
            </label>
            <input value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="Your API key ID" style={inputStyle} />
          </div>
          <div style={{ marginBottom: 12 }}>
            <label style={{ display: 'block', fontSize: 11, color: 'var(--color-text-secondary)', marginBottom: 3, fontWeight: 500 }}>
              API Secret Key *
            </label>
            <input value={apiSecret} onChange={(e) => setApiSecret(e.target.value)} placeholder="Your API secret key" type="password" style={inputStyle} />
          </div>

          {error && <div style={{ color: 'var(--color-error)', fontSize: 11, marginBottom: 8 }}>{error}</div>}

          <button
            onClick={handleVerify}
            disabled={!apiKey.trim() || !apiSecret.trim() || step === 'verifying'}
            style={{ ...btnPrimary, opacity: !apiKey.trim() || !apiSecret.trim() ? 0.5 : 1 }}
          >
            {step === 'verifying' ? 'Verifying...' : 'Verify & Find Number'}
          </button>
        </div>
      )}

      {/* Step 2: Number found — confirm + connect */}
      {(step === 'verified' || step === 'connecting') && (
        <div style={{ borderTop: '1px solid var(--color-border)', padding: 14, background: 'var(--color-bg)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
            <span style={{ background: 'var(--color-success)', color: 'var(--color-on-accent)', borderRadius: '50%', width: 20, height: 20, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700, flexShrink: 0 }}>{'\u2713'}</span>
            <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-success)' }}>Credentials verified</span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
            <span style={{ background: 'var(--color-accent-purple)', color: 'var(--color-on-accent)', borderRadius: '50%', width: 20, height: 20, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700, flexShrink: 0 }}>3</span>
            <span style={{ fontSize: 12, fontWeight: 600 }}>Your agent's phone number</span>
          </div>

          {numbers.length > 1 ? (
            <div style={{ marginBottom: 12 }}>
              <label style={{ display: 'block', fontSize: 11, color: 'var(--color-text-secondary)', marginBottom: 3, fontWeight: 500 }}>
                Select a number for your agent
              </label>
              <select
                value={selectedNumber}
                onChange={(e) => setSelectedNumber(e.target.value)}
                style={{ ...inputStyle, padding: '8px 10px' }}
              >
                {numbers.map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </div>
          ) : numbers.length === 1 ? (
            <div style={{
              background: 'var(--color-bg-secondary)', border: '1px solid color-mix(in srgb, var(--color-success) 22%, transparent)',
              borderRadius: 6, padding: '10px 12px', marginBottom: 12,
              display: 'flex', alignItems: 'center', gap: 8,
            }}>
              <span style={{ fontSize: 20 }}>{'\uD83D\uDCF1'}</span>
              <div>
                <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--color-success)' }}>{selectedNumber}</div>
                <div style={{ fontSize: 11, color: 'var(--color-text-secondary)' }}>This will be your agent's phone number</div>
              </div>
            </div>
          ) : (
            <div style={{ marginBottom: 12 }}>
              <div style={{
                fontSize: 11, color: 'var(--color-text-secondary)',
                marginBottom: 8, lineHeight: 1.5,
                padding: '8px 10px', background: 'var(--color-bg-secondary)',
                borderRadius: 6, borderLeft: '3px solid var(--color-accent-purple)',
              }}>
                Copy the phone number shown under <strong>"Send from"</strong> in your SendBlue dashboard
                and paste it below. On the free tier this is a shared number.
              </div>
              <label style={{ display: 'block', fontSize: 11, color: 'var(--color-text-secondary)', marginBottom: 3, fontWeight: 500 }}>
                SendBlue phone number *
              </label>
              <input
                value={selectedNumber}
                onChange={(e) => setSelectedNumber(e.target.value)}
                placeholder="+16452468235"
                style={inputStyle}
              />
            </div>
          )}

          {error && <div style={{ color: 'var(--color-error)', fontSize: 11, marginBottom: 8 }}>{error}</div>}

          <button
            onClick={handleConnect}
            disabled={step === 'connecting' || !selectedNumber.trim()}
            style={{ ...btnPrimary, opacity: !selectedNumber.trim() ? 0.5 : 1 }}
          >
            {step === 'connecting' ? 'Connecting...' : 'Activate Phone Number'}
          </button>
        </div>
      )}

      {/* Step 3: Done — success + webhook setup */}
      {step === 'done' && (
        <SendBlueWebhookStep
          apiKey={apiKey}
          apiSecret={apiSecret}
          selectedNumber={selectedNumber}
        />
      )}
    </div>
  );
}

function MessagingTab({ agentId }: { agentId: string }) {
  const [bindings, setBindings] = useState<ChannelBinding[]>([]);
  const [setupType, setSetupType] = useState<string | null>(null);
  const [formValues, setFormValues] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);

  const loadBindings = useCallback(() => {
    fetchAgentChannels(agentId).then(setBindings).catch(() => setBindings([]));
  }, [agentId]);

  useEffect(() => { loadBindings(); }, [loadBindings]);

  const setField = (key: string, value: string) => {
    setFormValues((prev) => ({ ...prev, [key]: value }));
  };

  const handleSetup = async (ch: MessagingChannelConfig) => {
    // Check required fields
    const missing = ch.fields.filter(
      (f) => f.required && !formValues[f.key]?.trim(),
    );
    if (missing.length > 0) return;

    setLoading(true);
    try {
      const config: Record<string, string> = {};
      for (const f of ch.fields) {
        const v = formValues[f.key]?.trim();
        if (v) config[f.key] = v;
      }
      await bindAgentChannel(agentId, ch.type, config);
      setSetupType(null);
      setFormValues({});
      loadBindings();
    } catch { /* */ } finally { setLoading(false); }
  };

  const handleRemove = async (bindingId: string) => {
    try {
      await unbindAgentChannel(agentId, bindingId);
      loadBindings();
    } catch { /* */ }
  };

  const inputStyle: React.CSSProperties = {
    width: '100%', padding: '6px 10px',
    background: 'var(--color-bg-secondary)',
    border: '1px solid var(--color-border)',
    borderRadius: 4, color: 'var(--color-text)',
    fontSize: 12, boxSizing: 'border-box',
  };

  return (
    <div style={{ padding: 16 }}>
      <div style={{
        color: 'var(--color-text-secondary)',
        fontSize: 12, marginBottom: 14,
      }}>
        Connect a messaging channel so you can talk to your agent from your phone or other devices.
      </div>

      {/* SendBlue wizard — primary option */}
      <SendBlueWizard
        agentId={agentId}
        binding={bindings.find((b) => b.channel_type === 'sendblue')}
        onDone={loadBindings}
        onRemove={(id) => { unbindAgentChannel(agentId, id).then(loadBindings).catch(() => {}); }}
      />

      {/* Divider */}
      <div style={{
        fontSize: 10, color: 'var(--color-text-secondary)',
        textTransform: 'uppercase', letterSpacing: 1,
        margin: '14px 0 8px', fontWeight: 600,
      }}>
        Other messaging channels
      </div>

      {MESSAGING_CHANNELS.map((ch) => {
        const binding = bindings.find((b) => b.channel_type === ch.type);
        const cfg = (binding?.config || {}) as Record<string, unknown>;
        const isSetup = setupType === ch.type;

        // Check if required fields are filled
        const canConnect = ch.fields.every(
          (f) => !f.required || formValues[f.key]?.trim(),
        );

        return (
          <div
            key={ch.type}
            style={{
              background: 'var(--color-bg-secondary)',
              border: binding
                ? '1px solid color-mix(in srgb, var(--color-success) 22%, transparent)'
                : '1px dashed var(--color-border)',
              borderRadius: 8, marginBottom: 10,
              overflow: 'hidden',
            }}
          >
            {/* Header row */}
            <div style={{
              display: 'flex', alignItems: 'center',
              padding: '12px 14px',
            }}>
              <span style={{ fontSize: 18, marginRight: 10 }}>{ch.icon}</span>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600, fontSize: 13 }}>{ch.name}</div>
                <div style={{
                  fontSize: 11,
                  color: binding ? 'var(--color-success)' : 'var(--color-text-secondary)',
                }}>
                  {binding ? ch.activeLabel(cfg) : ch.description}
                </div>
              </div>
              {binding ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{
                    background: 'color-mix(in srgb, var(--color-success) 22%, transparent)', color: 'var(--color-success)',
                    padding: '2px 8px', borderRadius: 10,
                    fontSize: 10, fontWeight: 600,
                  }}>Active</span>
                  <button
                    onClick={() => handleRemove(binding.id)}
                    style={{
                      fontSize: 10, padding: '2px 8px',
                      background: 'transparent',
                      color: 'var(--color-text-secondary)',
                      border: '1px solid var(--color-border)',
                      borderRadius: 4, cursor: 'pointer',
                    }}
                  >Remove</button>
                </div>
              ) : (
                <button
                  onClick={() => {
                    setSetupType(isSetup ? null : ch.type);
                    setFormValues({});
                  }}
                  style={{
                    fontSize: 10, padding: '3px 12px',
                    background: 'var(--color-accent-purple)', color: 'var(--color-on-accent)',
                    border: 'none', borderRadius: 5,
                    cursor: 'pointer', fontWeight: 600,
                  }}
                >
                  {isSetup ? 'Cancel' : 'Set Up'}
                </button>
              )}
            </div>

            {/* Active state: how to use */}
            {binding && (
              <div style={{
                borderTop: '1px solid var(--color-border)',
                padding: '10px 14px',
                background: 'var(--color-bg)',
              }}>
                <div style={{
                  fontSize: 11, color: 'var(--color-text-secondary)',
                  display: 'flex', alignItems: 'flex-start', gap: 6,
                }}>
                  <span style={{ flexShrink: 0 }}>{'\u2192'}</span>
                  <span>{ch.howToUse(cfg)}</span>
                </div>
              </div>
            )}

            {/* Setup form */}
            {isSetup && (
              <div style={{
                borderTop: '1px solid var(--color-border)',
                padding: '14px',
                background: 'var(--color-bg)',
              }}>
                {/* Setup instructions */}
                <div style={{
                  fontSize: 11, lineHeight: 1.5,
                  color: 'var(--color-text-secondary)',
                  marginBottom: 12,
                  padding: '8px 10px',
                  background: 'var(--color-bg-secondary)',
                  borderRadius: 6,
                  borderLeft: '3px solid var(--color-accent, var(--color-accent-purple))',
                }}>
                  {ch.setupSteps.map((step, i) => {
                    if (step.startsWith('COPYABLE:')) {
                      const text = step.slice(9);
                      return (
                        <div key={i} style={{ marginBottom: 6, marginTop: 4 }}>
                          <div style={{
                            position: 'relative',
                            background: 'var(--color-bg)',
                            border: '1px solid var(--color-border)',
                            borderRadius: 4, padding: '8px 10px',
                            fontSize: 10, fontFamily: 'monospace',
                            wordBreak: 'break-all', lineHeight: 1.4,
                            maxHeight: 80, overflowY: 'auto',
                          }}>
                            {text}
                            <button
                              onClick={() => { navigator.clipboard.writeText(text); }}
                              style={{
                                position: 'sticky', float: 'right', top: 0,
                                fontSize: 10, padding: '2px 8px',
                                background: 'var(--color-accent-purple)', color: 'var(--color-on-accent)',
                                border: 'none', borderRadius: 3,
                                cursor: 'pointer', fontWeight: 600,
                              }}
                            >Copy</button>
                          </div>
                        </div>
                      );
                    }
                    return (
                      <div key={i} style={{ marginBottom: i < ch.setupSteps.length - 1 ? 4 : 0 }}>
                        {step}
                      </div>
                    );
                  })}
                </div>

                {/* Form fields */}
                {ch.fields.map((field) => (
                  <div key={field.key} style={{ marginBottom: 8 }}>
                    <label style={{
                      display: 'block', fontSize: 11,
                      color: 'var(--color-text-secondary)',
                      marginBottom: 3, fontWeight: 500,
                    }}>
                      {field.label}{field.required ? ' *' : ''}
                    </label>
                    <input
                      type={field.type || 'text'}
                      value={formValues[field.key] || ''}
                      onChange={(e) => setField(field.key, e.target.value)}
                      placeholder={field.placeholder}
                      style={inputStyle}
                    />
                  </div>
                ))}

                {/* Connect button */}
                <button
                  onClick={() => handleSetup(ch)}
                  disabled={loading || !canConnect}
                  style={{
                    fontSize: 12, padding: '7px 20px',
                    background: 'var(--color-accent-purple)', color: 'var(--color-on-accent)',
                    border: 'none', borderRadius: 5,
                    cursor: 'pointer', fontWeight: 600,
                    opacity: loading || !canConnect ? 0.5 : 1,
                    marginTop: 4,
                  }}
                >
                  {loading ? 'Connecting...' : 'Connect'}
                </button>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Learning tab component
// ---------------------------------------------------------------------------

function LearningTab({ agentId, learningEnabled }: { agentId: string; learningEnabled: boolean }) {
  const [logs, setLogs] = useState<LearningLogEntry[]>([]);
  const [triggering, setTriggering] = useState(false);

  useEffect(() => {
    fetchLearningLog(agentId).then(setLogs).catch(() => {});
  }, [agentId]);

  async function handleTrigger() {
    setTriggering(true);
    try {
      await triggerLearning(agentId);
      // Refresh after a short delay
      setTimeout(() => fetchLearningLog(agentId).then(setLogs).catch(() => {}), 1000);
    } catch {
      // ignore
    } finally {
      setTriggering(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>Learning</span>
          <span
            className="text-xs px-2 py-0.5 rounded-full"
            style={{
              background: learningEnabled ? 'var(--color-success)20' : 'var(--color-bg-secondary)',
              color: learningEnabled ? 'var(--color-success)' : 'var(--color-text-tertiary)',
            }}
          >
            {learningEnabled ? 'Enabled' : 'Disabled'}
          </span>
        </div>
        <button
          onClick={handleTrigger}
          disabled={triggering}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs cursor-pointer font-medium"
          style={{
            background: 'var(--color-accent)',
            color: 'var(--color-on-accent)',
            opacity: triggering ? 0.6 : 1,
          }}
        >
          <RefreshCw size={12} className={triggering ? 'animate-spin' : ''} />
          Run Learning
        </button>
      </div>
      {logs.length === 0 ? (
        <div className="text-sm text-center py-8" style={{ color: 'var(--color-text-tertiary)' }}>
          No learning events yet. Run the agent or trigger learning manually.
        </div>
      ) : (
        <div className="space-y-2">
          {logs.map((entry) => (
            <div
              key={entry.id}
              className="rounded-lg p-3 text-sm"
              style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
            >
              <div className="flex items-center justify-between mb-1">
                <span
                  className="text-xs px-2 py-0.5 rounded"
                  style={{ background: 'var(--color-accent)' + '20', color: 'var(--color-accent)' }}
                >
                  {entry.event_type}
                </span>
                <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                  {formatRelativeTime(entry.created_at)}
                </span>
              </div>
              {entry.description && (
                <p style={{ color: 'var(--color-text-secondary)' }}>{entry.description}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Logs tab component
// ---------------------------------------------------------------------------

function TraceTreeView({
  node,
  depth,
  agentNames,
}: {
  node: TraceTreeNode;
  depth: number;
  agentNames: Record<string, string>;
}) {
  const friendly = agentNames[node.agent] || node.agent;
  const outcomeColor =
    node.outcome === 'success'
      ? 'var(--color-success)'
      : node.outcome === 'error'
        ? 'var(--color-error)'
        : 'var(--color-text-tertiary)';
  return (
    <div style={{ marginLeft: depth * 16 }} className="text-xs">
      <div className="flex items-center gap-2 py-0.5">
        <span
          className="w-1.5 h-1.5 rounded-full inline-block"
          style={{ background: outcomeColor }}
        />
        <span style={{ color: 'var(--color-text)' }}>{friendly}</span>
        <span style={{ color: 'var(--color-text-tertiary)' }}>
          ({(node.outcome ?? '?')}, {node.duration.toFixed(2)}s)
        </span>
        <span
          className="text-[10px] font-mono"
          style={{ color: 'var(--color-text-tertiary)' }}
        >
          {node.id.slice(0, 8)}
        </span>
      </div>
      {node.result_preview && (
        <div
          className="ml-4 mb-0.5"
          style={{ color: 'var(--color-text-tertiary)' }}
        >
          {node.result_preview}
        </div>
      )}
      {node.children.map((child) => (
        <TraceTreeView
          key={child.id}
          node={child}
          depth={depth + 1}
          agentNames={agentNames}
        />
      ))}
    </div>
  );
}

function LogsTab({ agentId }: { agentId: string }) {
  const managedAgents = useAppStore((s) => s.managedAgents);
  const agentNames = useMemo(() => {
    const out: Record<string, string> = {};
    for (const a of managedAgents) out[a.id] = a.name;
    return out;
  }, [managedAgents]);
  const [traces, setTraces] = useState<AgentTrace[]>([]);
  const [learningEntries, setLearningEntries] = useState<LearningLogEntry[]>([]);
  const [expandedTrace, setExpandedTrace] = useState<string | null>(null);
  const [trees, setTrees] = useState<Record<string, TraceTreeNode>>({});
  const [treeLoading, setTreeLoading] = useState<string | null>(null);
  const [treeError, setTreeError] = useState<Record<string, string>>({});

  const toggleTree = useCallback(
    async (traceId: string) => {
      if (trees[traceId]) {
        setTrees((current) => {
          const next = { ...current };
          delete next[traceId];
          return next;
        });
        return;
      }
      setTreeLoading(traceId);
      try {
        const tree = await fetchTraceTree(agentId, traceId);
        setTrees((current) => ({ ...current, [traceId]: tree }));
        setTreeError((current) => {
          const next = { ...current };
          delete next[traceId];
          return next;
        });
      } catch (err: any) {
        setTreeError((current) => ({
          ...current,
          [traceId]: err?.message || 'Failed to load tree',
        }));
      } finally {
        setTreeLoading(null);
      }
    },
    [agentId, trees],
  );

  const loadData = useCallback(async () => {
    try {
      const [t, l] = await Promise.all([
        fetchAgentTraces(agentId),
        fetchLearningLog(agentId),
      ]);
      setTraces(t);
      setLearningEntries(l);
    } catch {
      // ignore
    }
  }, [agentId]);

  useEffect(() => {
    loadData();
    // Fallback slow poll — WS is primary, this catches missed events
    const interval = setInterval(loadData, 30000);
    return () => clearInterval(interval);
  }, [loadData]);

  // Event-driven refresh — trace/learning entries are created by tick + tool events
  useAgentEvents(agentId, loadData, [
    'agent_tick_end',
    'agent_tick_error',
    'tool_call_end',
    'inference_end',
    'agent_learning_completed',
  ]);

  // Merge traces and learning entries into a unified timeline
  type TimelineEntry =
    | { kind: 'trace'; data: AgentTrace; ts: number }
    | { kind: 'learning'; data: LearningLogEntry; ts: number };

  const timeline: TimelineEntry[] = [
    ...traces.map((t): TimelineEntry => ({ kind: 'trace', data: t, ts: t.started_at })),
    ...learningEntries.map((e): TimelineEntry => ({ kind: 'learning', data: e, ts: e.created_at })),
  ].sort((a, b) => b.ts - a.ts);

  const learningEventColor = (eventType: string) => {
    if (eventType === 'query_start') return 'var(--color-accent)';
    if (eventType === 'query_complete') return 'var(--color-success)';
    if (eventType === 'tool_call') return 'var(--color-warning)';
    if (eventType === 'tool_result') return 'var(--color-accent-purple)';
    if (eventType === 'query_error') return 'var(--color-error)';
    return 'var(--color-text-secondary)';
  };

  const learningEventLabel = (eventType: string) => {
    if (eventType === 'query_start') return 'Query';
    if (eventType === 'query_complete') return 'Complete';
    if (eventType === 'tool_call') return 'Tool Call';
    if (eventType === 'tool_result') return 'Tool Result';
    if (eventType === 'query_error') return 'Error';
    return eventType;
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
          Activity Log
        </span>
        <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
          {timeline.length} entr{timeline.length !== 1 ? 'ies' : 'y'} (auto-refreshing)
        </span>
      </div>
      {timeline.length === 0 ? (
        <div className="text-sm text-center py-8" style={{ color: 'var(--color-text-tertiary)' }}>
          No activity yet. Send a message or run the agent to generate logs.
        </div>
      ) : (
        <div className="space-y-2">
          {timeline.map((entry) => {
            if (entry.kind === 'learning') {
              const e = entry.data;
              return (
                <div
                  key={`learn-${e.id}`}
                  className="rounded-lg p-3 text-sm"
                  style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span
                        className="w-2 h-2 rounded-full inline-block"
                        style={{ background: learningEventColor(e.event_type) }}
                      />
                      <span
                        className="text-[10px] px-1.5 py-0.5 rounded font-medium"
                        style={{
                          background: `${learningEventColor(e.event_type)}20`,
                          color: learningEventColor(e.event_type),
                        }}
                      >
                        {learningEventLabel(e.event_type)}
                      </span>
                    </div>
                    <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                      {formatRelativeTime(e.created_at)}
                    </span>
                  </div>
                  <div className="mt-1 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                    {e.description}
                  </div>
                </div>
              );
            }

            // Trace entry
            const t = entry.data;
            const errorDetail = t.metadata?.error_detail as
              | { error_type: string; error_message: string; suggested_action: string }
              | undefined;
            const isError = t.outcome !== 'success';
            const isExpanded = expandedTrace === t.id;

            return (
              <div
                key={`trace-${t.id}`}
                className="rounded-lg p-3 text-sm cursor-pointer"
                style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
                onClick={() => isError && errorDetail && setExpandedTrace(isExpanded ? null : t.id)}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span
                      className="w-2 h-2 rounded-full inline-block"
                      style={{ background: t.outcome === 'success' ? 'var(--color-success)' : 'var(--color-error)' }}
                    />
                    <span style={{ color: 'var(--color-text)' }}>{t.outcome}</span>
                    <span
                      className="text-[10px] px-1.5 py-0.5 rounded font-medium"
                      style={{ background: 'var(--color-bg)', color: 'var(--color-text-secondary)' }}
                    >
                      Trace
                    </span>
                    {errorDetail && (
                      <span
                        className="text-[10px] px-1.5 py-0.5 rounded font-medium"
                        style={{
                          background: errorDetail.error_type === 'fatal' ? 'var(--color-error)20' :
                            errorDetail.error_type === 'escalate' ? 'var(--color-warning)20' : 'var(--color-accent)20',
                          color: errorDetail.error_type === 'fatal' ? 'var(--color-error)' :
                            errorDetail.error_type === 'escalate' ? 'var(--color-warning)' : 'var(--color-accent)',
                        }}
                      >
                        {errorDetail.error_type}
                      </span>
                    )}
                  </div>
                  <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                    {formatRelativeTime(t.started_at)}
                  </span>
                </div>
                <div className="flex items-center gap-3 mt-1 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                  <span>{t.duration.toFixed(1)}s</span>
                  <span>{t.steps} step{t.steps !== 1 ? 's' : ''}</span>
                  <button
                    type="button"
                    onClick={(ev) => {
                      ev.stopPropagation();
                      toggleTree(t.id);
                    }}
                    className="ml-auto cursor-pointer"
                    style={{ color: 'var(--color-accent)' }}
                  >
                    {trees[t.id]
                      ? 'Hide call tree'
                      : treeLoading === t.id
                        ? 'Loading...'
                        : 'Show call tree'}
                  </button>
                </div>
                {isExpanded && errorDetail && (
                  <div className="mt-2 pt-2 space-y-1.5 text-xs" style={{ borderTop: '1px solid var(--color-border)' }}>
                    <div>
                      <span className="font-medium" style={{ color: 'var(--color-text-secondary)' }}>Error: </span>
                      <span style={{ color: 'var(--color-text)' }}>{errorDetail.error_message}</span>
                    </div>
                    <div>
                      <span className="font-medium" style={{ color: 'var(--color-text-secondary)' }}>Action: </span>
                      <span style={{ color: 'var(--color-text)' }}>{errorDetail.suggested_action}</span>
                    </div>
                  </div>
                )}
                {trees[t.id] && (
                  <div
                    className="mt-2 pt-2"
                    style={{ borderTop: '1px solid var(--color-border)' }}
                    onClick={(ev) => ev.stopPropagation()}
                  >
                    <TraceTreeView
                      node={trees[t.id]}
                      depth={0}
                      agentNames={agentNames}
                    />
                  </div>
                )}
                {treeError[t.id] && (
                  <div
                    className="mt-2 text-xs"
                    style={{ color: 'var(--color-error)' }}
                  >
                    {treeError[t.id]}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page component
// ---------------------------------------------------------------------------

export function AgentsPage() {
  const navigate = useNavigate();
  const managedAgents = useAppStore((s) => s.managedAgents);
  const setManagedAgents = useAppStore((s) => s.setManagedAgents);
  const selectedAgentId = useAppStore((s) => s.selectedAgentId);
  const setSelectedAgentId = useAppStore((s) => s.setSelectedAgentId);
  const savings = useAppStore((s) => s.savings);
  const [loading, setLoading] = useState(true);
  const [agentManagerAvailable, setAgentManagerAvailable] = useState<boolean | null>(null);
  const [tasks, setTasks] = useState<AgentTask[]>([]);
  const [taskStatusFilter, setTaskStatusFilter] = useState<AgentTaskStatusFilter>('all');
  const [taskProjectFilter, setTaskProjectFilter] = useState('all');
  const [missionControlData, setMissionControlData] = useState<MissionControlData | null>(null);
  const [channels, setChannels] = useState<ChannelBinding[]>([]);
  const [templates, setTemplates] = useState<AgentTemplate[]>([]);
  const [skills, setSkills] = useState<InstalledSkill[]>([]);
  const [showWizard, setShowWizard] = useState(false);
  const [detailTab, setDetailTab] = useState<'overview' | 'interact' | 'channels' | 'messaging' | 'tasks' | 'memory' | 'learning' | 'logs'>('interact');

  const refreshLibrary = useCallback(() => {
    fetchTemplates().then(setTemplates).catch(() => {});
    fetchSkills().then(setSkills).catch(() => setSkills([]));
  }, []);

  const refresh = useCallback(async () => {
    try {
      const agents = await fetchManagedAgents();
      setManagedAgents(agents);
      setAgentManagerAvailable(true);
    } catch (err: any) {
      if (err.message?.includes('404')) {
        setAgentManagerAvailable(false);
      }
      setManagedAgents([]);
    } finally {
      setLoading(false);
    }
  }, [setManagedAgents]);

  useEffect(() => {
    refresh();
    refreshLibrary();
  }, [refresh, refreshLibrary]);

  const selectedAgent = managedAgents.find((a) => a.id === selectedAgentId);
  const taskProjectContext = useMemo(
    () => collectProjectTaskContext(missionControlData),
    [missionControlData],
  );
  const taskProjectOptions = useMemo(() => {
    const ids = new Set(tasks.map((task) => task.project_id).filter(Boolean) as string[]);
    return [...ids].map((id) => ({
      id,
      name: taskProjectContext.projectById.get(id)?.name || `Project ${id}`,
    })).sort((a, b) => a.name.localeCompare(b.name));
  }, [tasks, taskProjectContext]);
  const filteredTasks = useMemo(() => {
    return tasks.filter((task) => {
      if (taskStatusFilter !== 'all' && task.status !== taskStatusFilter) {
        return false;
      }
      if (taskProjectFilter !== 'all' && task.project_id !== taskProjectFilter) {
        return false;
      }
      return true;
    });
  }, [tasks, taskProjectFilter, taskStatusFilter]);

  const reloadTasks = useCallback(() => {
    if (!selectedAgentId) return;
    fetchAgentTasks(selectedAgentId, true).then(setTasks).catch(() => setTasks([]));
    fetchMissionControl().then(setMissionControlData).catch(() => setMissionControlData(null));
  }, [selectedAgentId]);

  useEffect(() => {
    if (selectedAgentId) {
      setTaskStatusFilter('all');
      setTaskProjectFilter('all');
      reloadTasks();
      fetchAgentChannels(selectedAgentId).then(setChannels).catch(() => setChannels([]));
    }
  }, [selectedAgentId, reloadTasks]);

  const handlePause = async (id: string) => {
    await pauseManagedAgent(id).catch(() => {});
    await refresh();
  };

  const handleResume = async (id: string) => {
    await resumeManagedAgent(id).catch(() => {});
    await refresh();
  };

  const handleDelete = async (id: string) => {
    await deleteManagedAgent(id).catch(() => {});
    if (selectedAgentId === id) setSelectedAgentId(null);
    await refresh();
  };

  const handleRun = async (id: string) => {
    try {
      await runManagedAgent(id);
    } catch (err: any) {
      toast.error('Failed to start agent', {
        description: err.message || 'Unknown error',
      });
      await refresh();
      return;
    }
    await refresh();
    setTimeout(async () => {
      try {
        const agent = await fetchManagedAgent(id);
        if (agent.status === 'error') {
          toast.error(`Agent "${agent.name}" failed`, {
            description: agent.summary_memory?.replace(/^ERROR: /, '') || 'Unknown error',
          });
          useAppStore.getState().addLogEntry({
            timestamp: Date.now(), level: 'error', category: 'model',
            message: `Agent "${agent.name}" failed: ${agent.summary_memory || 'Unknown error'}`,
          });
        }
      } catch {}
      await refresh();
    }, 3000);
  };

  const handleRecover = async (id: string) => {
    try {
      const result = await recoverManagedAgent(id);
      if (result.checkpoint) {
        toast.success('Agent recovered from checkpoint');
      } else {
        toast.success('Agent reset to idle (no checkpoint available)');
      }
      setDetailTab('overview');
    } catch (err: any) {
      toast.error('Recovery failed', {
        description: err.message || 'Unknown error',
      });
    }
    await refresh();
  };

  const prevStatuses = useRef<Record<string, string>>({});
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const agents = await fetchManagedAgents();
        for (const agent of agents) {
          const prev = prevStatuses.current[agent.id];
          if (prev && prev !== 'error' && agent.status === 'error') {
            toast.error(`Agent "${agent.name}" failed`, {
              description: agent.summary_memory?.replace(/^ERROR: /, '') || 'Unknown error',
            });
          }
          prevStatuses.current[agent.id] = agent.status;
        }
      } catch {}
    }, 30000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center" style={{ color: 'var(--color-text-tertiary)' }}>
        Loading agents...
      </div>
    );
  }

  // ── Detail View ─────────────────────────────────────────────────────────

  if (selectedAgent) {
    const successRate =
      tasks.length > 0
        ? Math.round((tasks.filter((t) => t.status === 'completed').length / tasks.length) * 100)
        : null;

    const DETAIL_TABS = [
      { id: 'interact', label: 'Interact', icon: MessageSquare },
      { id: 'overview', label: 'Overview', icon: Activity },
      { id: 'channels', label: 'Data Sources', icon: Database },
      { id: 'messaging', label: 'Messaging Channels', icon: Wifi },
      { id: 'tasks', label: 'Tasks', icon: ListTodo },
      { id: 'memory', label: 'Memory', icon: Brain },
      { id: 'learning', label: 'Learning', icon: Settings },
      { id: 'logs', label: 'Logs', icon: FileText },
    ] as const;

    return (
      <div className="flex-1 overflow-y-auto px-6 py-10">
        <div className="max-w-[1500px] mx-auto">
        {/* Back button */}
        <button
          onClick={() => setSelectedAgentId(null)}
          className="flex items-center gap-1 mb-4 text-sm cursor-pointer"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          <ChevronLeft size={16} /> Back to agents
        </button>

        {/* Header */}
        <div className="flex items-start justify-between mb-6">
          <div className="flex items-center gap-3">
            <AgentAvatar agent={selectedAgent} size="lg" active={selectedAgent.status === 'running'} />
            <div>
              <AgentNameField agent={selectedAgent} onAgentUpdated={refresh} />
              <div className="flex items-center gap-2 mt-1">
                <StatusBadge status={selectedAgent.status} />
                <span
                  className="text-xs px-2 py-0.5 rounded-full"
                  style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)' }}
                >
                  {roleLabel(selectedAgent)}
                </span>
                <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                  {selectedAgent.agent_type}
                </span>
              </div>
            </div>
          </div>
          {/* Header actions */}
          <div className="flex items-center gap-2">
            {detailTab === 'interact' ? (
              <span
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs"
                style={{ background: 'var(--color-success)20', color: 'var(--color-success)', border: '1px solid var(--color-success)40' }}
              >
                <MessageSquare size={13} /> Chat ready — just type below
              </span>
            ) : (
              <button
                onClick={() => handleRun(selectedAgent.id)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm cursor-pointer font-medium"
                style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}
              >
                <Zap size={13} /> Run Now
              </button>
            )}
            {(selectedAgent.status === 'running' || selectedAgent.status === 'idle') && (
              <button
                onClick={() => handlePause(selectedAgent.id)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm cursor-pointer"
                style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
              >
                <Pause size={13} /> Pause
              </button>
            )}
            {selectedAgent.status === 'paused' && (
              <button
                onClick={() => handleResume(selectedAgent.id)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm cursor-pointer"
                style={{ background: 'var(--color-success)20', color: 'var(--color-success)', border: '1px solid var(--color-success)40' }}
              >
                <Play size={13} /> Resume
              </button>
            )}
            {(selectedAgent.status === 'error' || selectedAgent.status === 'stalled' || selectedAgent.status === 'needs_attention') && (
              <button
                onClick={() => handleRecover(selectedAgent.id)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm cursor-pointer"
                style={{ background: 'var(--color-error)20', color: 'var(--color-error)', border: '1px solid var(--color-error)40' }}
              >
                <AlertTriangle size={13} /> Recover
              </button>
            )}
            <button
              onClick={async () => {
                if (window.confirm(`Delete ${selectedAgent.name}? This cannot be undone.`)) {
                  await deleteManagedAgent(selectedAgent.id);
                  setSelectedAgentId(null);
                  await refresh();
                }
              }}
              className="p-1.5 rounded-lg cursor-pointer transition-colors"
              style={{ color: 'var(--color-error)', background: 'var(--color-error)15' }}
              title="Delete agent"
            >
              <Trash2 size={15} />
            </button>
          </div>
        </div>

        {(selectedAgent.status === 'input_required' ||
          selectedAgent.status === 'auth_required') && (
          <ChiefPendingCard agent={selectedAgent} onResumed={refresh} />
        )}

        <PendingApprovalsList
          agentId={selectedAgent.id}
          agentNameById={{ [selectedAgent.id]: selectedAgent.name }}
          variant="card"
        />

        {/* Tabs */}
        <div className="flex gap-1 mb-6 p-1 rounded-lg overflow-x-auto" style={{ background: 'var(--color-bg-secondary)' }}>
          {DETAIL_TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setDetailTab(id)}
              className="px-3 py-2 rounded-md text-xs flex items-center gap-1.5 whitespace-nowrap cursor-pointer transition-colors"
              style={{
                background: detailTab === id ? 'var(--color-bg)' : 'transparent',
                color: detailTab === id ? 'var(--color-text)' : 'var(--color-text-secondary)',
                fontWeight: detailTab === id ? 500 : 400,
              }}
            >
              <Icon size={13} />
              {label}
            </button>
          ))}
        </div>

        {/* Tab: Overview */}
        {detailTab === 'overview' && (
          <div className="space-y-3">
            <AgentAvatarSection agent={selectedAgent} onAgentUpdated={refresh} />

            {/* Instruction */}
            <AgentInstructionSection agent={selectedAgent} onAgentUpdated={refresh} />

            {/* Personality */}
            <AgentPersonalitySection agent={selectedAgent} onAgentUpdated={refresh} />

            {/* Configuration */}
            <div
              className="p-3 rounded-lg"
              style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
            >
              <h3 className="text-sm font-semibold mb-2" style={{ color: 'var(--color-text)' }}>
                Configuration
              </h3>
              <AgentConfigGrid agent={selectedAgent} onAgentUpdated={refresh} />
              <div className="mt-2 pt-2" style={{ borderTop: '1px solid var(--color-border)' }}>
                <span className="text-xs font-mono" style={{ color: 'var(--color-text-tertiary)' }}>
                  ID: {selectedAgent.id}
                </span>
              </div>
            </div>

            <AgentOrganizationSection
              agent={selectedAgent}
              managedAgents={managedAgents}
              onAgentUpdated={refresh}
            />

            <AgentPresetToolsSection
              agent={selectedAgent}
              managedAgents={managedAgents}
              templates={templates}
              skills={skills}
              onAgentUpdated={refresh}
              onOpenLibrary={() => navigate('/library')}
            />

            {/* Phase 2B — Capability Inspector (additive; complements
                AgentPresetToolsSection above). */}
            <CapabilityInspector agent={selectedAgent} onAgentUpdated={refresh} />

            {/* Hint for deep research agents */}
            {selectedAgent.agent_type === 'deep_research' && (
              <div
                className="flex items-start gap-3 p-3 rounded-lg text-sm"
                style={{
                  background: 'var(--color-accent-subtle)',
                  border: '1px solid var(--color-border)',
                }}
              >
                <Database size={16} style={{ color: 'var(--color-accent)', flexShrink: 0, marginTop: 2 }} />
                <div style={{ color: 'var(--color-text-secondary)' }}>
                  <strong>Tip:</strong> Connect your personal data in the{' '}
                  <button
                    onClick={() => setDetailTab('channels')}
                    className="cursor-pointer underline"
                    style={{ color: 'var(--color-accent)', background: 'none', border: 'none', padding: 0, font: 'inherit' }}
                  >Data Sources</button>{' '}
                  tab, then set up{' '}
                  <button
                    onClick={() => setDetailTab('messaging')}
                    className="cursor-pointer underline"
                    style={{ color: 'var(--color-accent)', background: 'none', border: 'none', padding: 0, font: 'inherit' }}
                  >Messaging Channels</button>{' '}
                  to talk to this agent from your phone.
                </div>
              </div>
            )}

            {/* Usage stats + savings — single compact row */}
            {(() => {
              const inTok = selectedAgent.input_tokens ?? 0;
              const outTok = selectedAgent.output_tokens ?? 0;
              const modelName = (selectedAgent.config?.model as string) || '';
              const paramMatch = modelName.match(/:(\d+(?:\.\d+)?)b/i);
              const paramsB = paramMatch ? parseFloat(paramMatch[1]) : 9;
              const flops = 2 * paramsB * 1e9 * (inTok + outTok);
              const providers = [
                { label: 'GPT-5.3', inPer1M: 2.0, outPer1M: 10.0 },
                { label: 'Claude Opus 4.6', inPer1M: 5.0, outPer1M: 25.0 },
                { label: 'Gemini 3.1 Pro', inPer1M: 2.0, outPer1M: 12.0 },
              ];
              const energyWh = (inTok + outTok) / 1000 * 0.4;
              const energyKj = energyWh * 3.6;
              const fmtFlops = flops >= 1e15 ? `${(flops / 1e15).toFixed(1)} PFLOPs` : `${(flops / 1e12).toFixed(1)} TFLOPs`;
              const hasSavings = inTok + outTok > 0;
              const sectionTitle = { fontSize: 11, fontWeight: 600, color: 'var(--color-text-tertiary)', textTransform: 'uppercase' as const, letterSpacing: '0.05em', marginBottom: 8 };
              return (
                <div className="p-4 rounded-xl" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
                  <div className="flex gap-0 flex-wrap items-stretch">
                    {/* Agent Statistics */}
                    <div className="pr-5">
                      <p style={sectionTitle}>Agent Statistics</p>
                      <div className="flex gap-5">
                        <div>
                          <p className="text-xl font-bold leading-none" style={{ color: 'var(--color-text)' }}>{selectedAgent.total_runs ?? 0}</p>
                          <p className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>Total Queries</p>
                        </div>
                        <div>
                          <p className="text-xl font-bold leading-none" style={{ color: 'var(--color-text)' }}>{inTok.toLocaleString()}</p>
                          <p className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>Input Tokens</p>
                        </div>
                        <div>
                          <p className="text-xl font-bold leading-none" style={{ color: 'var(--color-text)' }}>{outTok.toLocaleString()}</p>
                          <p className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>Output Tokens</p>
                        </div>
                      </div>
                    </div>
                    {hasSavings && (<>
                      <div style={{ width: 1, background: 'var(--color-border)' }} />
                      {/* Local Utilization */}
                      <div className="px-5">
                        <p style={sectionTitle}>Local Utilization</p>
                        <div className="flex gap-5">
                          <div>
                            <p className="text-xl font-bold leading-none" style={{ color: 'var(--color-success)' }}>{fmtFlops}</p>
                            <p className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>Compute</p>
                          </div>
                          <div>
                            <p className="text-xl font-bold leading-none" style={{ color: 'var(--color-success)' }}>{energyKj.toFixed(2)} kJ</p>
                            <p className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>Energy</p>
                          </div>
                        </div>
                      </div>
                      <div style={{ width: 1, background: 'var(--color-border)' }} />
                      {/* Dollars Saved */}
                      <div className="pl-5">
                        <p style={sectionTitle}>Dollars Saved vs.</p>
                        <div className="flex gap-5">
                          {providers.map((p) => {
                            const cost = (inTok / 1e6) * p.inPer1M + (outTok / 1e6) * p.outPer1M;
                            return (
                              <div key={p.label}>
                                <p className="text-xl font-bold leading-none" style={{ color: 'var(--color-success)' }}>${cost.toFixed(4)}</p>
                                <p className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>{p.label}</p>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    </>)}
                  </div>
                </div>);
            })()}

            {/* Channels summary */}
            {channels.length > 0 && (
              <div
                className="p-4 rounded-lg"
                style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
              >
                <h3 className="text-sm font-medium mb-2" style={{ color: 'var(--color-text-secondary)' }}>
                  Messaging Channels
                </h3>
                {channels.map((b) => (
                  <div key={b.id} className="text-sm py-1" style={{ color: 'var(--color-text)' }}>
                    {b.channel_type}: {b.routing_mode}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Tab: Interact */}
        {detailTab === 'interact' && <InteractTab agentId={selectedAgent.id} agentStatus={selectedAgent.status} />}

        {/* Tab: Channels */}
        {detailTab === 'channels' && (
          <ChannelsTab agentId={selectedAgent.id} />
        )}

        {/* Tab: Messaging */}
        {detailTab === 'messaging' && (
          <MessagingTab agentId={selectedAgent.id} />
        )}

        {/* Tab: Tasks */}
        {detailTab === 'tasks' && (
          <div className="space-y-3">
            <div
              className="p-3 rounded-lg grid grid-cols-1 md:grid-cols-[1fr_180px_220px] gap-3 items-end"
              style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
            >
              <div>
                <div className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
                  Agent task ledger
                </div>
                <div className="text-xs mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>
                  Shows work this agent performed and work it passed to subordinate agents.
                </div>
              </div>
              <label className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                Status
                <select
                  value={taskStatusFilter}
                  onChange={(e) => setTaskStatusFilter(e.target.value as AgentTaskStatusFilter)}
                  className="mt-1 w-full px-2 py-1.5 rounded outline-none"
                  style={{
                    background: 'var(--color-bg)',
                    border: '1px solid var(--color-border)',
                    color: 'var(--color-text)',
                  }}
                >
                  <option value="all">All statuses</option>
                  {TASK_STATUSES.map((status) => (
                    <option key={status} value={status}>
                      {status}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                Project
                <select
                  value={taskProjectFilter}
                  onChange={(e) => setTaskProjectFilter(e.target.value)}
                  className="mt-1 w-full px-2 py-1.5 rounded outline-none"
                  style={{
                    background: 'var(--color-bg)',
                    border: '1px solid var(--color-border)',
                    color: 'var(--color-text)',
                  }}
                >
                  <option value="all">All projects</option>
                  {taskProjectOptions.map((project) => (
                    <option key={project.id} value={project.id}>
                      {project.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
              Showing {filteredTasks.length} of {tasks.length} task{tasks.length === 1 ? '' : 's'}
            </div>

            {filteredTasks.map((t) => {
              const projectTask = t.project_task_id
                ? taskProjectContext.taskById.get(t.project_task_id)
                : undefined;
              const projectId = t.project_id || projectTask?.projectId || '';
              const project = projectId
                ? taskProjectContext.projectById.get(projectId)
                : undefined;
              return (
                <TaskItem
                  key={t.id}
                  task={t}
                  agentId={selectedAgent.id}
                  managedAgents={managedAgents}
                  projectContext={{
                    projectName: project?.name || (projectId ? `Project ${projectId}` : ''),
                    projectTaskTitle: projectTask?.title || '',
                  }}
                  onChanged={reloadTasks}
                />
              );
            })}
            {filteredTasks.length === 0 && (
              <div className="text-sm py-8 text-center" style={{ color: 'var(--color-text-tertiary)' }}>
                No tasks match these filters.
              </div>
            )}
          </div>
        )}

        {/* Tab: Memory */}
        {detailTab === 'memory' && (
          <div
            className="p-4 rounded-lg"
            style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
          >
            <h3 className="text-sm font-medium mb-3 flex items-center gap-2" style={{ color: 'var(--color-text-secondary)' }}>
              <Brain size={14} /> Summary Memory
            </h3>
            <p className="whitespace-pre-wrap text-sm" style={{ color: 'var(--color-text)' }}>
              {selectedAgent.summary_memory || 'Agent has no stored memory yet.'}
            </p>
          </div>
        )}

        {/* Tab: Learning */}
        {detailTab === 'learning' && (
          <LearningTab agentId={selectedAgent.id} learningEnabled={!!selectedAgent.learning_enabled} />
        )}

        {/* Tab: Logs */}
        {detailTab === 'logs' && (
          <LogsTab agentId={selectedAgent.id} />
        )}
        </div>
      </div>
    );
  }

  // ── List View ───────────────────────────────────────────────────────────

  return (
    <div data-agents-page-pane className="relative flex-1 overflow-y-auto px-6 py-8">
      <div className="mx-auto max-w-[1480px]">
      {/* Launch wizard modal */}
      {showWizard && (
        <LaunchWizard
          templates={templates}
          managedAgents={managedAgents}
          onClose={() => setShowWizard(false)}
          onLaunched={() => {
            setShowWizard(false);
            refresh();
          }}
        />
      )}

      <header className="mb-5">
        <div className="flex justify-between items-start gap-4">
          <div>
            <h1 className="text-3xl font-semibold" style={{ color: 'var(--color-text)' }}>
              Agents
            </h1>
            <p className="text-sm mt-1 max-w-3xl" style={{ color: 'var(--color-text-secondary)' }}>
              Manage your autonomous agents and their hierarchy. Monitor status, performance, and inter-agent collaboration.
            </p>
          </div>
          <button
            onClick={() => agentManagerAvailable && setShowWizard(true)}
            disabled={agentManagerAvailable === false}
            className="flex items-center gap-2 px-5 py-3 rounded-xl text-sm font-semibold cursor-pointer transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            style={{
              background: agentManagerAvailable === false ? 'var(--color-bg-tertiary)' : 'var(--color-accent)',
              color: agentManagerAvailable === false ? 'var(--color-text-tertiary)' : 'var(--color-on-accent)',
              boxShadow: agentManagerAvailable === false ? 'none' : '0 0 22px color-mix(in srgb, var(--color-accent) 34%, transparent)',
            }}
          >
            <Plus size={15} /> New Agent
          </button>
        </div>
      </header>

      {agentManagerAvailable === false && (
        <div
          className="mx-4 mt-2 px-4 py-3 rounded-lg flex items-center gap-3 text-sm"
          style={{
            background: 'var(--color-accent-amber-subtle)',
            border: '1px solid color-mix(in srgb, var(--color-warning) 20%, transparent)',
            color: 'var(--color-accent-amber)',
          }}
        >
          <AlertTriangle size={16} />
          <span>Agent manager is not enabled. Set <code className="font-mono text-xs">agent_manager.enabled = true</code> in your config.</span>
        </div>
      )}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px] 2xl:grid-cols-[minmax(0,1fr)_420px]">
        <main className="min-w-0 space-y-5">
          {managedAgents.length > 0 && (
            <AgentOrgChart
              managedAgents={managedAgents}
              selectedAgentId={selectedAgentId}
              onSelect={(agentId) => {
                setSelectedAgentId(agentId);
                setDetailTab('overview');
              }}
            />
          )}

          {managedAgents.length > 0 && (
            <section
              className="rounded-2xl p-4"
              style={{
                background: 'var(--color-bg-secondary)',
                border: '1px solid color-mix(in srgb, var(--color-accent) 22%, var(--color-border))',
              }}
            >
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-sm font-semibold uppercase tracking-normal" style={{ color: 'var(--color-text)' }}>
                    All Agents
                  </h2>
                  <p className="mt-1 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                    {managedAgents.length} agent{managedAgents.length === 1 ? '' : 's'}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <div
                    className="hidden sm:flex h-9 min-w-[180px] items-center gap-2 rounded-lg px-3 text-xs"
                    style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text-tertiary)' }}
                  >
                    <Search size={14} />
                    <span>Search agents...</span>
                  </div>
                  <button
                    type="button"
                    className="grid h-9 w-9 place-items-center rounded-lg"
                    title="Grid view"
                    style={{ background: 'color-mix(in srgb, var(--color-accent) 14%, transparent)', border: '1px solid var(--color-accent)', color: 'var(--color-accent)' }}
                  >
                    <Boxes size={15} />
                  </button>
                  <button
                    type="button"
                    className="grid h-9 w-9 place-items-center rounded-lg"
                    title="List view"
                    style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
                  >
                    <ListTodo size={15} />
                  </button>
                </div>
              </div>

              <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))' }}>
                {managedAgents.map((a) => (
                  <AgentCard
                    key={a.id}
                    agent={a}
                    onClick={() => {
                      setSelectedAgentId(a.id);
                      setDetailTab('overview');
                    }}
                    onPause={handlePause}
                    onResume={handleResume}
                    onRun={handleRun}
                    onRecover={handleRecover}
                    onDelete={handleDelete}
                    onChat={(id) => {
                      setSelectedAgentId(id);
                      setDetailTab('interact');
                    }}
                    onEdit={(id) => {
                      setSelectedAgentId(id);
                      setDetailTab('overview');
                    }}
                  />
                ))}
              </div>
            </section>
          )}

          {managedAgents.length === 0 && (
            <div className="text-center py-16" style={{ color: 'var(--color-text-tertiary)' }}>
              <Bot size={48} className="mx-auto mb-4 opacity-30" />
              <p className="mb-2 font-medium" style={{ color: 'var(--color-text-secondary)' }}>
                No agents yet
              </p>
              <p className="text-sm mb-6">Create your first agent to get started with autonomous task management.</p>
              <button
                onClick={() => agentManagerAvailable && setShowWizard(true)}
                disabled={agentManagerAvailable === false}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
                style={{
                  background: agentManagerAvailable === false ? 'var(--color-bg-tertiary)' : 'var(--color-accent)',
                  color: agentManagerAvailable === false ? 'var(--color-text-tertiary)' : 'var(--color-on-accent)',
                }}
              >
                <Plus size={15} /> Launch your first agent
              </button>
            </div>
          )}
        </main>

        {managedAgents.length > 0 && (
          <InterAgentActivityPanel
            managedAgents={managedAgents}
            onSelectAgent={(agentId) => {
              setSelectedAgentId(agentId);
              setDetailTab('interact');
            }}
          />
        )}
      </div>
      </div>
    </div>
  );
}
