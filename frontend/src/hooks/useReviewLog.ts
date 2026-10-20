import { useCallback, useEffect, useState } from 'react';
import type { ReviewAction } from '@/types/reviewQueue';

/**
 * The operator's own record of review decisions.
 *
 * ## Why this exists
 *
 * `GET /api/v1/orders/review-queue` lists only lines still awaiting a decision,
 * and there is no endpoint returning lines that have already been resolved. A
 * decision is therefore invisible to the rest of the app the moment it is made:
 * the line drops out of the queue and the order it belonged to loses its
 * "pending" marker.
 *
 * Two screens need that missing information — the approvals audit trail and the
 * "Flagged" status in order history — so decisions are kept here, in the
 * operator's browser, and read back by both.
 *
 * This is explicitly *not* the pharmacy's compliance record. It covers this
 * browser only and says so wherever it is displayed.
 */

/** One decision, as the operator made it. */
export interface ReviewLogEntry {
  /** The flagged line that was decided. */
  itemId: string;
  orderId: string;
  pharmacyId: string;
  /** The text as the customer wrote it. */
  rawToken: string;
  quantity: number | null;
  /**
   * When the order was placed.
   *
   * Captured at decision time because the review queue drops the line as soon as
   * it is resolved — without this, an order whose only flagged line was rejected
   * would appear in order history with no date at all.
   */
  orderCreatedAt: string | null;
  action: ReviewAction;
  /** Final catalogue id, or null when the line was rejected. */
  catalogueId: string | null;
  catalogueName: string | null;
  decidedAt: string;
}

const STORAGE_KEY = 'clusterops.review-log.v1';

/** Keeps the log bounded; older entries fall off the end. */
const MAX_ENTRIES = 200;

/** Tolerant read — a corrupt or absent entry must not break the page. */
function readStored(): ReviewLogEntry[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];

    return parsed.filter((entry): entry is ReviewLogEntry => {
      if (typeof entry !== 'object' || entry === null) return false;
      const candidate = entry as Partial<ReviewLogEntry>;
      return (
        typeof candidate.itemId === 'string' &&
        typeof candidate.orderId === 'string' &&
        typeof candidate.rawToken === 'string' &&
        typeof candidate.action === 'string'
      );
    });
  } catch {
    return [];
  }
}

function writeStored(entries: ReviewLogEntry[]): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(entries.slice(0, MAX_ENTRIES)));
  } catch {
    // A full or blocked storage quota is not worth failing an order over; the
    // decision itself has already been saved on the server.
  }
}

export interface ReviewLog {
  entries: ReviewLogEntry[];
  /** Prepend a decision. Re-deciding a line replaces its earlier entry. */
  record: (entry: ReviewLogEntry) => void;
  clear: () => void;
}

/** Review decisions made in this browser. */
export function useReviewLog(): ReviewLog {
  const [entries, setEntries] = useState<ReviewLogEntry[]>(() => readStored());

  // Another tab recording a decision should update this one.
  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === STORAGE_KEY) setEntries(readStored());
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  const record = useCallback((entry: ReviewLogEntry) => {
    setEntries((current) => {
      // A line should appear once. Re-deciding it replaces the old entry so the
      // log cannot hold two contradictory outcomes for the same line.
      const next = [entry, ...current.filter((existing) => existing.itemId !== entry.itemId)];
      writeStored(next);
      return next;
    });
  }, []);

  const clear = useCallback(() => {
    setEntries([]);
    writeStored([]);
  }, []);

  return { entries, record, clear };
}
