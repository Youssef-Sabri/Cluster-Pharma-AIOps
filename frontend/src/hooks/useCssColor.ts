import { useEffect, useState } from 'react';

/**
 * Resolve a `:root` design token to a concrete colour string.
 *
 * Recharts writes colours into SVG **presentation attributes** (`stroke="…"`),
 * not into a stylesheet. `var(--color-primary)` is only substituted in real CSS
 * declarations, so handing Recharts a raw token risks the attribute reaching the
 * DOM unresolved and painting nothing. Reading the token once and passing the
 * literal value keeps every colour sourced from `:root` — single source of truth
 * — while staying in a form SVG actually honours.
 *
 * The token is read from `document.documentElement`, where `:root` lives, so
 * a theme override applied to `html` is picked up too.
 *
 * @param varName  token name including the leading dashes
 * @param fallback used before the stylesheet is parsed, and if the token is absent
 */
export function useCssColor(varName: string, fallback: string): string {
  const [color, setColor] = useState<string>(fallback);

  useEffect(() => {
    const read = () => {
      const value = getComputedStyle(document.documentElement).getPropertyValue(varName).trim();
      if (value) setColor(value);
    };

    read();

    // Theme switches at runtime (a future appearance toggle) should repaint the
    // chart without a reload.
    const observer = new MutationObserver(read);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'style'] });

    return () => observer.disconnect();
  }, [varName]);

  return color;
}

export default useCssColor;
