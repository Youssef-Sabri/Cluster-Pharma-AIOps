import { useCallback, useEffect, useState } from 'react';

/**
 * Current stock levels, held locally and persisted to this browser only.
 *
 * ## Why this exists at all
 *
 * The ClusterOps data model has **no inventory feed**. Checked against
 * `information_schema` on 2026-10-18: there is no `stock`, `inventory`,
 * `on_hand` or `level` column in any table, and `/metrics` exposes no stock
 * gauge. An order in the ledger is a purchase, not a balance, so on-hand cannot
 * be derived from it either.
 *
 * That matters more here than anywhere else in the product. Stock status is
 * computed as on-hand against expected daily demand, so an invented figure would
 * paint a confident red "Critical" badge that a pharmacist might reorder against.
 * So the number is entered by the operator, stored on their own device, and
 * never presented as if it came from a system of record.
 *
 * A real deployment replaces this with a warehouse/stock feed; the rest of the
 * component tree consumes the same shape.
 */

const STORAGE_KEY = 'clusterops.stock.v1';

/** Read persisted levels, tolerating absent or corrupted storage. */
function load(): Record<string, number> {
  if (typeof window === 'undefined') return {};
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== 'object' || parsed === null) return {};

    // Rebuild rather than cast: storage is untrusted input and could hold
    // anything, including values that are not finite numbers.
    const result: Record<string, number> = {};
    for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof value === 'number' && Number.isFinite(value) && value >= 0) {
        result[key] = Math.floor(value);
      }
    }
    return result;
  } catch {
    // Private-browsing modes and quota errors both land here. Losing persistence
    // is acceptable; breaking the page is not.
    return {};
  }
}

export interface StockLevels {
  /** Entered stock, or `undefined` when the operator has not set it. */
  get: (productId: string) => number | undefined;
  set: (productId: string, units: number) => void;
  clear: (productId: string) => void;
  clearAll: () => void;
  /** How many products currently have a stock figure. */
  count: number;
}

export function useStockLevels(): StockLevels {
  const [levels, setLevels] = useState<Record<string, number>>(load);

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(levels));
    } catch {
      // Non-fatal: the numbers still work for this session in memory.
    }
  }, [levels]);

  const set = useCallback((productId: string, units: number) => {
    setLevels((current) => ({ ...current, [productId]: units }));
  }, []);

  const clear = useCallback((productId: string) => {
    setLevels((current) => {
      const next = { ...current };
      delete next[productId];
      return next;
    });
  }, []);

  const clearAll = useCallback(() => setLevels({}), []);

  const get = useCallback(
    (productId: string) => (productId in levels ? levels[productId] : undefined),
    [levels],
  );

  return { get, set, clear, clearAll, count: Object.keys(levels).length };
}

export default useStockLevels;
