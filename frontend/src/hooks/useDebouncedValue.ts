import { useEffect, useState } from 'react';

/**
 * Delay a rapidly-changing value.
 *
 * Used for the horizon slider so dragging it settles into one request instead of
 * firing a POST per pixel. The delay is deliberately shorter than the phase
 * document's 300 ms interaction budget, so the final request still lands inside
 * it once the user stops moving.
 *
 * @param value   value to debounce
 * @param delayMs quiet period before the value is committed
 */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState<T>(value);

  useEffect(() => {
    // A zero/negative delay would schedule a pointless extra render.
    if (delayMs <= 0) {
      setDebounced(value);
      return;
    }

    const timer = window.setTimeout(() => setDebounced(value), delayMs);
    // Clearing on every change is what makes this a debounce rather than a
    // throttle — and it is also what guarantees no timer outlives the component.
    return () => window.clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}

export default useDebouncedValue;
