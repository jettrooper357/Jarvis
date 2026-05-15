import { memo, useRef, useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { MessageBubble } from './MessageBubble';
import { InputArea } from './InputArea';
import { StreamingDots } from './StreamingDots';
import { ToolCallCard } from './ToolCallCard';
import { ChatHero, SuggestedPrompts } from './ChatWelcome';
import { useAppStore } from '../../lib/store';
import { PanelRightOpen, PanelRightClose, Database, X } from 'lucide-react';
import { listConnectors } from '../../lib/connectors-api';

const MessageList = memo(function MessageList() {
  const messages = useAppStore((s) => s.messages);
  return (
    <>
      {messages.map((msg) => (
        <MessageBubble key={msg.id} message={msg} />
      ))}
    </>
  );
});

export function ChatArea() {
  const messageCount = useAppStore((s) => s.messages.length);
  const streamState = useAppStore((s) => s.streamState);
  const systemPanelOpen = useAppStore((s) => s.systemPanelOpen);
  const toggleSystemPanel = useAppStore((s) => s.toggleSystemPanel);
  const navigate = useNavigate();
  const listRef = useRef<HTMLDivElement>(null);
  const shouldAutoScroll = useRef(true);

  // Check if any data sources are connected
  const [hasConnectedSources, setHasConnectedSources] = useState<boolean | null>(null);
  const [bannerDismissed, setBannerDismissed] = useState(false);

  useEffect(() => {
    listConnectors()
      .then((list) => setHasConnectedSources(list.some((c) => c.connected)))
      .catch(() => setHasConnectedSources(null));
  }, []);

  useEffect(() => {
    if (!shouldAutoScroll.current || !listRef.current) return;
    const node = listRef.current;
    const rafId = requestAnimationFrame(() => {
      node.scrollTop = node.scrollHeight;
    });
    return () => cancelAnimationFrame(rafId);
  }, [
    messageCount,
    streamState.isStreaming,
    streamState.content,
    streamState.activeToolCalls.length,
  ]);

  const handleScroll = () => {
    if (!listRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = listRef.current;
    shouldAutoScroll.current = scrollHeight - scrollTop - clientHeight < 100;
  };

  const isEmpty = messageCount === 0 && !streamState.isStreaming;

  const PanelIcon = systemPanelOpen ? PanelRightClose : PanelRightOpen;

  return (
    <div className="flex flex-col h-full">
      {/* Toggle bar */}
      <div className="flex items-center justify-end px-3 py-1.5 shrink-0">
        <button
          onClick={toggleSystemPanel}
          className="p-1.5 rounded-md transition-colors cursor-pointer"
          style={{ color: 'var(--color-text-tertiary)' }}
          title={`${systemPanelOpen ? 'Hide' : 'Show'} system panel (${navigator.platform.includes('Mac') ? '⌘' : 'Ctrl'}+I)`}
        >
          <PanelIcon size={16} />
        </button>
      </div>

      {/* Data sources banner */}
      {hasConnectedSources === false && !bannerDismissed && (
        <div
          className="mx-4 mb-2 flex items-center gap-3 px-4 py-3 rounded-lg text-sm shrink-0"
          style={{
            background: 'var(--color-accent-subtle)',
            border: '1px solid var(--color-border)',
          }}
        >
          <Database size={16} style={{ color: 'var(--color-accent)', flexShrink: 0 }} />
          <span style={{ color: 'var(--color-text-secondary)', flex: 1 }}>
            Connect your data sources (Gmail, iMessage, Slack, etc.) to get personalized answers.
          </span>
          <button
            onClick={() => navigate('/data-sources')}
            className="px-3 py-1 rounded text-xs font-medium cursor-pointer"
            style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)', border: 'none' }}
          >
            Connect
          </button>
          <button
            onClick={() => setBannerDismissed(true)}
            className="p-1 rounded cursor-pointer"
            style={{ color: 'var(--color-text-tertiary)', background: 'transparent', border: 'none' }}
          >
            <X size={14} />
          </button>
        </div>
      )}
      {/* Frozen hero — stays put while the conversation scrolls beneath it */}
      <ChatHero />

      <div
        ref={listRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto min-h-0"
      >
        {isEmpty ? (
          <SuggestedPrompts />
        ) : (
          <div className="max-w-[var(--chat-max-width)] mx-auto px-4 py-6">
            <MessageList />
            {streamState.isStreaming && (
              <div className="mb-6">
                {streamState.activeToolCalls.length > 0 && (
                  <div className="mb-3 flex flex-col gap-2">
                    {streamState.activeToolCalls.map((tc) => (
                      <ToolCallCard key={tc.id} toolCall={tc} />
                    ))}
                  </div>
                )}
                {streamState.content ? (
                  <div
                    className="text-sm leading-relaxed whitespace-pre-wrap break-words"
                    style={{ color: 'var(--color-text)' }}
                  >
                    {streamState.content}
                  </div>
                ) : (
                  <div className="flex justify-start mb-4">
                    <StreamingDots phase={streamState.phase} />
                  </div>
                )}
                {streamState.content && (
                  <div
                    className="mt-2 text-xs"
                    style={{ color: 'var(--color-text-tertiary)' }}
                  >
                    {streamState.phase || 'Generating...'}
                    {streamState.elapsedMs > 0
                      ? ` · ${(streamState.elapsedMs / 1000).toFixed(1)}s`
                      : ''}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
      <InputArea />
    </div>
  );
}
