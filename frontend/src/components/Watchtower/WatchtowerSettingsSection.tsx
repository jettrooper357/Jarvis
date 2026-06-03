import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import {
  fetchWatchtowerSettings,
  patchWatchtowerSettings,
  type WatchtowerPriority,
  type WatchtowerSettings,
} from '../../lib/api';

const priorities: WatchtowerPriority[] = ['info', 'low', 'normal', 'high', 'urgent', 'emergency'];

function Toggle({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className="relative h-6 w-11 rounded-full transition-colors"
      style={{ background: checked ? 'var(--color-accent)' : 'var(--color-bg-tertiary)' }}
    >
      <span
        className="absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white transition-transform"
        style={{
          transform: checked ? 'translateX(20px)' : 'translateX(0)',
          boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
        }}
      />
    </button>
  );
}

function SelectPriority({
  value,
  onChange,
}: {
  value: WatchtowerPriority;
  onChange: (value: WatchtowerPriority) => void;
}) {
  return (
    <select
      value={value}
      onChange={(event) => onChange(event.target.value as WatchtowerPriority)}
      className="rounded px-2 py-1 text-xs outline-none"
      style={{
        background: 'var(--color-bg-secondary)',
        color: 'var(--color-text)',
        border: '1px solid var(--color-border)',
      }}
    >
      {priorities.map((priority) => (
        <option key={priority} value={priority}>
          {priority}
        </option>
      ))}
    </select>
  );
}

function Row({
  label,
  description,
  children,
}: {
  label: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <div
      className="flex items-center justify-between gap-4 py-3"
      style={{ borderBottom: '1px solid var(--color-border-subtle)' }}
    >
      <div>
        <div className="text-sm" style={{ color: 'var(--color-text)' }}>
          {label}
        </div>
        {description && (
          <div className="mt-0.5 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
            {description}
          </div>
        )}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

export function WatchtowerSettingsSection() {
  const [settings, setSettings] = useState<WatchtowerSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchWatchtowerSettings()
      .then(setSettings)
      .catch((err) => setError((err as Error).message));
  }, []);

  const save = async (patch: Partial<WatchtowerSettings>) => {
    if (!settings) return;
    setSaving(true);
    setError(null);
    const optimistic = { ...settings, ...patch };
    setSettings(optimistic);
    try {
      const saved = await patchWatchtowerSettings(patch);
      setSettings(saved);
    } catch (err) {
      setSettings(settings);
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  if (!settings) {
    return (
      <div className="text-xs" style={{ color: error ? 'var(--color-error)' : 'var(--color-text-tertiary)' }}>
        {error || 'Loading Watchtower settings...'}
      </div>
    );
  }

  return (
    <div data-testid="watchtower-settings">
      <Row label="Watchtower" description="Continuously scan projects, agents, approvals, deadlines, and jobs">
        <Toggle checked={settings.enabled} onChange={(enabled) => save({ enabled })} />
      </Row>
      <Row label="Loop interval" description="Background scan cadence in seconds">
        <input
          type="number"
          min={15}
          value={settings.loop_interval_seconds}
          onChange={(event) => save({ loop_interval_seconds: Number(event.target.value) })}
          className="w-20 rounded px-2 py-1 text-xs outline-none"
          style={{
            background: 'var(--color-bg-secondary)',
            color: 'var(--color-text)',
            border: '1px solid var(--color-border)',
          }}
        />
      </Row>
      <Row label="Local AI only" description="Cloud LLM providers are rejected by the backend guard">
        <Toggle checked={settings.local_ai_only} onChange={(local_ai_only) => save({ local_ai_only })} />
      </Row>
      <Row label="Local AI provider">
        <input
          type="text"
          value={settings.local_ai_provider}
          onChange={(event) => save({ local_ai_provider: event.target.value })}
          className="w-32 rounded px-2 py-1 text-xs outline-none"
          style={{
            background: 'var(--color-bg-secondary)',
            color: 'var(--color-text)',
            border: '1px solid var(--color-border)',
          }}
        />
      </Row>
      <Row label="Do Not Disturb" description={`${settings.quiet_hours_start} to ${settings.quiet_hours_end}`}>
        <Toggle checked={settings.dnd_enabled} onChange={(dnd_enabled) => save({ dnd_enabled })} />
      </Row>
      <Row label="Emergency bypass" description="Emergency user alerts can bypass quiet hours">
        <Toggle
          checked={settings.allow_emergency_bypass}
          onChange={(allow_emergency_bypass) => save({ allow_emergency_bypass })}
        />
      </Row>
      <Row label="Urgent bypass" description="Keep disabled to avoid non-emergency interruptions">
        <Toggle
          checked={settings.allow_urgent_bypass}
          onChange={(allow_urgent_bypass) => save({ allow_urgent_bypass })}
        />
      </Row>
      <Row label="Telegram" description="Uses the existing Jarvis channel integration">
        <Toggle checked={settings.telegram_enabled} onChange={(telegram_enabled) => save({ telegram_enabled })} />
      </Row>
      <Row label="Telegram minimum priority">
        <SelectPriority
          value={settings.telegram_min_priority}
          onChange={(telegram_min_priority) => save({ telegram_min_priority })}
        />
      </Row>
      <Row label="In-app minimum priority">
        <SelectPriority
          value={settings.in_app_min_priority}
          onChange={(in_app_min_priority) => save({ in_app_min_priority })}
        />
      </Row>
      <Row label="Notification cooldown" description="Minutes before repeating the same finding">
        <input
          type="number"
          min={1}
          value={settings.default_cooldown_minutes}
          onChange={(event) => save({ default_cooldown_minutes: Number(event.target.value) })}
          className="w-20 rounded px-2 py-1 text-xs outline-none"
          style={{
            background: 'var(--color-bg-secondary)',
            color: 'var(--color-text)',
            border: '1px solid var(--color-border)',
          }}
        />
      </Row>
      {saving && (
        <div className="mt-2 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
          Saving...
        </div>
      )}
      {error && (
        <div className="mt-2 text-xs" style={{ color: 'var(--color-error)' }}>
          {error}
        </div>
      )}
    </div>
  );
}
