import { useGSAP } from '@gsap/react';
import gsap from 'gsap';
import { useRef, type RefObject } from 'react';

gsap.registerPlugin(useGSAP);

/**
 * One entry reveal for the dashboard shell. Targets `.reveal` descendants,
 * opacity + a short rise, staggered. Honours prefers-reduced-motion.
 */
export function useReveal<T extends HTMLElement>(): RefObject<T | null> {
  const root = useRef<T>(null);

  useGSAP(
    () => {
      const items = root.current?.querySelectorAll('.reveal');
      if (!items || items.length === 0) return;
      const reduce =
        typeof window.matchMedia === 'function' &&
        window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      gsap.from(items, {
        opacity: reduce ? 1 : 0,
        y: reduce ? 0 : 10,
        duration: reduce ? 0.01 : 0.45,
        stagger: reduce ? 0 : 0.07,
        ease: 'power3.out',
        immediateRender: !reduce,
      });
    },
    { scope: root },
  );

  return root;
}
