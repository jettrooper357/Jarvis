import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import { Sidebar } from './Sidebar';

vi.mock('./ConversationList', () => ({
  ConversationList: () => <div>No conversations yet</div>,
}));

describe('Sidebar workspace navigation', () => {
  it('renders only the five main workspace groups', () => {
    render(
      <MemoryRouter initialEntries={['/command/today']}>
        <Sidebar />
      </MemoryRouter>,
    );

    const nav = screen.getByRole('navigation', {
      name: 'Workspace navigation',
    });

    expect(nav).toHaveTextContent('Command Center');
    expect(nav).toHaveTextContent('Projects');
    expect(nav).toHaveTextContent('Agents');
    expect(nav).toHaveTextContent('Knowledge');
    expect(nav).toHaveTextContent('System');
    expect(nav.querySelectorAll('button')).toHaveLength(5);
    expect(screen.queryByRole('button', { name: 'Data Sources' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Mission Control' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Get Started' })).toBeNull();
  });
});
