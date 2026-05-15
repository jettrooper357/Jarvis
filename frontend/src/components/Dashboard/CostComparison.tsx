import { DollarSign, Cloud, HardDrive, TrendingDown } from 'lucide-react';
import { useAppStore } from '../../lib/store';

const CLOUD_PRICING = [
  { name: 'GPT-5.3', input: 2.0, output: 10.0 },
  { name: 'Claude Opus 4.6', input: 5.0, output: 25.0 },
  { name: 'Gemini 3.1 Pro', input: 2.0, output: 12.0 },
];

function Gauge({ fillPct }: { fillPct: number }) {
  const pct = Math.max(0, Math.min(100, fillPct));
  return (
    <div
      className="jarvis-gauge shrink-0"
      style={{ width: 132, height: 132, ['--jv-fill' as string]: `${pct}%` }}
    >
      <div className="flex flex-col items-center">
        <DollarSign size={26} style={{ color: 'var(--color-success)' }} />
        <span className="hud-mono text-[11px] mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>
          {pct > 0 ? `${pct.toFixed(0)}% saved` : 'USD'}
        </span>
      </div>
    </div>
  );
}

function Row({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className="flex items-center justify-between py-2" style={{ borderBottom: '1px solid var(--color-border-subtle)' }}>
      <span className="hud-label flex items-center gap-2" style={{ fontSize: '0.6875rem', letterSpacing: '0.14em' }}>
        <span className="w-1 h-1 rounded-full" style={{ background: accent ?? 'var(--color-text-tertiary)' }} />
        {label}
      </span>
      <span className="hud-mono text-sm" style={{ color: accent ?? 'var(--color-text)' }}>
        {value}
      </span>
    </div>
  );
}

export function CostComparison() {
  const savings = useAppStore((s) => s.savings);
  const hasData = !!savings && savings.total_tokens > 0;

  const promptK = (savings?.total_prompt_tokens ?? 0) / 1000;
  const completionK = (savings?.total_completion_tokens ?? 0) / 1000;
  const local = savings?.local_cost ?? 0;

  // Headline cloud cost = the priciest provider, so "savings" is the
  // conservative upper bound the user would have paid.
  const cloudCosts = CLOUD_PRICING.map(
    (p) => (promptK * p.input) / 1000 + (completionK * p.output) / 1000,
  );
  const cloudCost = hasData ? Math.max(...cloudCosts) : 0;
  const saved = Math.max(0, cloudCost - local);
  const fillPct = cloudCost > 0 ? (saved / cloudCost) * 100 : 0;

  return (
    <div className="hud-panel p-6">
      <h3 className="hud-label flex items-center gap-2 mb-5">
        <DollarSign size={12} style={{ color: 'var(--color-success)' }} />
        Cost Comparison
      </h3>

      <div className="flex items-center gap-6">
        <Gauge fillPct={fillPct} />

        <div className="flex-1 min-w-0">
          {!hasData && (
            <p className="hud-mono text-xs mb-3" style={{ color: 'var(--color-text-tertiary)' }}>
              awaiting first inference…
            </p>
          )}
          <Row
            label="Cloud API Cost"
            value={hasData ? `$${cloudCost.toFixed(4)}` : '———'}
            accent="var(--color-text-tertiary)"
          />
          <Row
            label="Local Inference Cost"
            value={hasData ? `$${local.toFixed(4)}` : '———'}
            accent="var(--color-accent)"
          />
          <Row
            label="Savings"
            value={hasData ? `$${saved.toFixed(4)}` : '———'}
            accent="var(--color-success)"
          />
        </div>
      </div>

      {hasData && (
        <div className="mt-4 pt-3 flex flex-col gap-1.5" style={{ borderTop: '1px solid var(--color-border)' }}>
          {CLOUD_PRICING.map((p, i) => {
            const c = cloudCosts[i];
            const s = Math.max(0, c - local);
            return (
              <div key={p.name} className="flex items-center gap-2 text-xs">
                <Cloud size={12} style={{ color: 'var(--color-text-tertiary)' }} />
                <span className="flex-1 truncate" style={{ color: 'var(--color-text-secondary)' }}>
                  {p.name}
                </span>
                <span className="hud-mono" style={{ color: 'var(--color-text)' }}>
                  ${c.toFixed(4)}
                </span>
                {s > 0.0001 && (
                  <span className="flex items-center gap-0.5 hud-mono" style={{ color: 'var(--color-success)' }}>
                    <TrendingDown size={10} />${s.toFixed(4)}
                  </span>
                )}
              </div>
            );
          })}
          <div className="flex items-center gap-2 text-xs mt-1">
            <HardDrive size={12} style={{ color: 'var(--color-accent)' }} />
            <span className="flex-1" style={{ color: 'var(--color-text-secondary)' }}>
              Local · {savings!.total_calls} req · {savings!.total_tokens.toLocaleString()} tok
            </span>
          </div>
        </div>
      )}

      <p className="text-[10px] leading-relaxed mt-3" style={{ color: 'var(--color-text-tertiary)' }}>
        *Estimates assume local models produce roughly the same tokens per request, on average, as cloud models.
      </p>
    </div>
  );
}
