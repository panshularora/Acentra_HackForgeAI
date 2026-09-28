import { useEffect, useState, useSyncExternalStore, type RefObject } from 'react';

function subscribeVisibility(onChange: () => void) {
  document.addEventListener('visibilitychange', onChange);
  return () => document.removeEventListener('visibilitychange', onChange);
}

/**
 * True while `ref` is on screen and the tab is visible. The 3D view stops
 * rendering otherwise, so a background tab or a scrolled-away canvas costs
 * no GPU time.
 */
export function useRenderGate(ref: RefObject<Element | null>): boolean {
  const pageVisible = useSyncExternalStore(
    subscribeVisibility,
    () => document.visibilityState !== 'hidden',
    () => true,
  );
  const [onScreen, setOnScreen] = useState(true);

  useEffect(() => {
    const element = ref.current;
    if (!element || typeof IntersectionObserver === 'undefined') return;
    const observer = new IntersectionObserver(
      (entries) => {
        const entry = entries[entries.length - 1];
        if (entry) setOnScreen(entry.isIntersecting);
      },
      { rootMargin: '64px' },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);

  return pageVisible && onScreen;
}
