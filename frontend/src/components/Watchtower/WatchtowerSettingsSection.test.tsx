import { render, screen, fireEvent } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useAppStore } from '../../lib/store';
import { WatchtowerSettingsSection } from './WatchtowerSettingsSection';

// Keep backend settings perpetually "loading" so the only control on screen is
// the device-local proactive toggle (rendered above the loading guard). This
// lets us target it with a bare getByRole('button') without ambiguity.
vi.mock('../../lib/api', () => ({
  fetchWatchtowerSettings: vi.fn(() => new Promise(() => {})),
  patchWatchtowerSettings: vi.fn(),
}));

describe('WatchtowerSettingsSection — proactive toggle', () => {
  beforeEach(() => {
    localStorage.clear();
    useAppStore.setState((s) => ({
      settings: { ...s.settings, watchtowerProactive: true },
    }));
  });

  it('renders the proactive row even while backend settings are loading', () => {
    render(<WatchtowerSettingsSection />);
    expect(screen.getByText('Proactive voice & toasts')).toBeInTheDocument();
  });

  it('flips the watchtowerProactive store setting when toggled', () => {
    render(<WatchtowerSettingsSection />);
    expect(useAppStore.getState().settings.watchtowerProactive).toBe(true);

    fireEvent.click(screen.getByRole('button'));
    expect(useAppStore.getState().settings.watchtowerProactive).toBe(false);

    fireEvent.click(screen.getByRole('button'));
    expect(useAppStore.getState().settings.watchtowerProactive).toBe(true);
  });
});
