import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router';
import { toast } from 'sonner';
import { fetchWatchtowerBrief } from '../../lib/api';

const ALERT_PRIORITIES = new Set(['high', 'urgent', 'emergency']);

function briefStorageKey(findingIds: string[]) {
  return `watchtower-brief:${findingIds.sort().join(',')}`;
}

export function WatchtowerNotifier() {
  const navigate = useNavigate();
  const lastShownRef = useRef<string>('');

  useEffect(() => {
    let cancelled = false;

    const showBrief = async () => {
      try {
        const brief = await fetchWatchtowerBrief();
        if (cancelled || brief.actionable_count === 0) return;
        const actionable = brief.items.filter((item) =>
          ALERT_PRIORITIES.has(item.priority)
          || item.finding_type.includes('approval')
          || item.finding_type.includes('user_input'),
        );
        if (actionable.length === 0) return;

        const key = briefStorageKey(actionable.map((item) => item.finding_id));
        if (lastShownRef.current === key) return;
        lastShownRef.current = key;

        let alreadyShown = false;
        try {
          alreadyShown = sessionStorage.getItem(key) === 'shown';
          sessionStorage.setItem(key, 'shown');
        } catch {
          alreadyShown = false;
        }
        if (alreadyShown) return;

        const top = actionable[0];
        const title = actionable.length === 1
          ? `Watchtower: ${top.finding_type.replace(/_/g, ' ')}`
          : `Watchtower: ${actionable.length} items need attention`;
        const description = actionable.length === 1
          ? top.reason
          : `${top.reason} and ${actionable.length - 1} more active item${actionable.length === 2 ? '' : 's'}.`;

        toast.warning(title, {
          description,
          duration: 15000,
          action: {
            label: 'Open',
            onClick: () => navigate('/command/mission-control'),
          },
        });
      } catch {
        // Non-blocking: the Watchtower panel itself shows API errors.
      }
    };

    showBrief();
    const onFocus = () => showBrief();
    window.addEventListener('focus', onFocus);
    return () => {
      cancelled = true;
      window.removeEventListener('focus', onFocus);
    };
  }, [navigate]);

  return null;
}
