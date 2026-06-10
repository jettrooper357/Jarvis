import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { MessageBubble } from './MessageBubble';
import type { ChatMessage } from '../../types';

function msg(over: Partial<ChatMessage> = {}): ChatMessage {
  return { id: '1', role: 'assistant', content: 'hi', timestamp: 0, ...over };
}

describe('MessageBubble interrupted marker', () => {
  it('shows an interrupted marker when message.interrupted is true', () => {
    render(<MessageBubble message={msg({ interrupted: true })} />);
    expect(screen.getByText(/interrupted/i)).toBeInTheDocument();
  });

  it('does not show the marker otherwise', () => {
    render(<MessageBubble message={msg()} />);
    expect(screen.queryByText(/interrupted/i)).toBeNull();
  });
});
