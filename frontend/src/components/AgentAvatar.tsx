import { useEffect, useMemo, useRef, useState } from 'react';
import { BarChart3, Bot, Crown, Database, Terminal, Workflow } from 'lucide-react';
import type { ManagedAgent } from '../lib/api';
import { getBase } from '../lib/api';

type AgentAvatarSize = 'sm' | 'md' | 'lg' | 'orgChart';

interface AgentAvatarProps {
  agent?: Pick<ManagedAgent, 'avatar_url' | 'avatar_mime_type' | 'org_role' | 'agent_type' | 'is_chief' | 'status'> | null;
  avatarUrl?: string | null;
  avatarMimeType?: string | null;
  size?: AgentAvatarSize;
  active?: boolean;
  className?: string;
}

const SIZE_PX: Record<AgentAvatarSize, number> = {
  sm: 28,
  md: 40,
  lg: 64,
  orgChart: 42,
};

function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return;
    const query = window.matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => setReduced(query.matches);
    update();
    query.addEventListener?.('change', update);
    return () => query.removeEventListener?.('change', update);
  }, []);

  return reduced;
}

function resolveAvatarUrl(url?: string | null): string {
  if (!url) return '';
  if (/^(https?:|data:|blob:)/i.test(url)) return url;
  if (url.startsWith('/')) return `${getBase()}${url}`;
  return url;
}

function roleKey(agent?: AgentAvatarProps['agent']): string {
  const role = `${agent?.org_role || ''} ${agent?.agent_type || ''}`.toLowerCase();
  if (agent?.is_chief || role.includes('chief')) return 'chief';
  if (role.includes('sql') || role.includes('database')) return 'sql';
  if (role.includes('powershell') || role.includes('terminal') || role.includes('admin')) return 'terminal';
  if (role.includes('business') || role.includes('analyst')) return 'analyst';
  if (role.includes('workflow') || role.includes('manager') || role.includes('coordinator')) return 'workflow';
  return 'default';
}

function FallbackIcon({ kind, size }: { kind: string; size: number }) {
  const iconSize = Math.max(14, Math.floor(size * 0.46));
  const props = { size: iconSize, style: { color: 'var(--color-accent)' } };
  if (kind === 'chief') return <Crown {...props} />;
  if (kind === 'sql') return <Database {...props} />;
  if (kind === 'terminal') return <Terminal {...props} />;
  if (kind === 'analyst') return <BarChart3 {...props} />;
  if (kind === 'workflow') return <Workflow {...props} />;
  return <Bot {...props} />;
}

export function AgentAvatar({
  agent,
  avatarUrl,
  avatarMimeType,
  size = 'md',
  active = false,
  className = '',
}: AgentAvatarProps) {
  const reducedMotion = useReducedMotion();
  const [failed, setFailed] = useState(false);
  const [inView, setInView] = useState(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const px = SIZE_PX[size];
  const rawUrl = avatarUrl ?? agent?.avatar_url ?? null;
  const mimeType = avatarMimeType ?? agent?.avatar_mime_type ?? '';
  const src = useMemo(() => resolveAvatarUrl(rawUrl), [rawUrl]);
  const isVideo = mimeType === 'video/mp4';
  const animated = mimeType === 'image/gif' || mimeType === 'image/webp' || isVideo;
  const showMedia = Boolean(src) && !failed && !(reducedMotion && animated);
  const fallbackKind = roleKey(agent);

  useEffect(() => setFailed(false), [src]);

  useEffect(() => {
    const node = videoRef.current;
    if (!node || !isVideo || !showMedia || typeof IntersectionObserver === 'undefined') {
      setInView(!isVideo);
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        const visible = entry.isIntersecting;
        setInView(visible);
        if (!visible) node.pause();
      },
      { rootMargin: '80px' },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [isVideo, showMedia, src]);

  const style = {
    width: px,
    height: px,
    borderRadius: 9999,
    border: '1px solid rgba(34, 211, 238, 0.45)',
    boxShadow: active ? '0 0 18px rgba(34, 211, 238, 0.38)' : '0 0 0 rgba(0,0,0,0)',
    background: 'radial-gradient(circle at 35% 25%, rgba(34, 211, 238, 0.22), rgba(15, 23, 42, 0.88))',
    flexShrink: 0,
  };

  if (showMedia && isVideo) {
    return (
      <video
        ref={videoRef}
        src={inView ? src : undefined}
        aria-hidden="true"
        muted
        loop
        playsInline
        autoPlay={inView}
        preload="metadata"
        onError={() => setFailed(true)}
        className={`inline-block object-cover ${className}`}
        style={style}
      />
    );
  }

  if (showMedia) {
    return (
      <img
        src={src}
        alt=""
        loading="lazy"
        decoding="async"
        onError={() => setFailed(true)}
        className={`inline-block object-cover ${className}`}
        style={style}
      />
    );
  }

  return (
    <span
      aria-hidden="true"
      className={`inline-grid place-items-center ${className}`}
      style={style}
      title={reducedMotion && animated ? 'Animated avatar paused for reduced motion' : undefined}
    >
      <FallbackIcon kind={fallbackKind} size={px} />
    </span>
  );
}

export default AgentAvatar;
