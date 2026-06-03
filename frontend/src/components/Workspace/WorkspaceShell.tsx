import type { ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router';
import type { WorkspaceTab } from '../../navigation/workspaces';

type WorkspaceShellProps = {
  title: string;
  tabs: WorkspaceTab[];
  children: ReactNode;
};

export function WorkspaceShell({ title, tabs, children }: WorkspaceShellProps) {
  const location = useLocation();
  const navigate = useNavigate();

  return (
    <section className="flex-1 flex flex-col min-h-0 overflow-hidden">
      <header
        className="shrink-0 px-6 pt-4 pb-3"
        style={{ borderBottom: '1px solid var(--color-border)' }}
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h1
            className="text-sm font-semibold"
            style={{ color: 'var(--color-text)' }}
          >
            {title}
          </h1>
          {tabs.length > 0 && (
            <nav
              aria-label={`${title} tabs`}
              className="flex flex-wrap items-center gap-1"
            >
              {tabs.map((tab) => {
                const active =
                  location.pathname === tab.path ||
                  (tab.path !== '/' && location.pathname.startsWith(`${tab.path}/`));
                return (
                  <button
                    key={`${tab.label}:${tab.path}`}
                    type="button"
                    onClick={() => navigate(tab.path)}
                    className="px-3 py-1.5 rounded-md text-xs font-medium transition-colors cursor-pointer"
                    style={{
                      background: active
                        ? 'var(--color-accent-subtle)'
                        : 'transparent',
                      color: active
                        ? 'var(--color-text)'
                        : 'var(--color-text-secondary)',
                      border: active
                        ? '1px solid var(--color-border)'
                        : '1px solid transparent',
                    }}
                  >
                    {tab.label}
                  </button>
                );
              })}
            </nav>
          )}
        </div>
      </header>
      <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
        {children}
      </div>
    </section>
  );
}
