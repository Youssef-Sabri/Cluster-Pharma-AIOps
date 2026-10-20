import { Check, Pencil, X } from 'lucide-react';
import { Badge } from '@/components/ui';
import type { BadgeTone } from '@/components/ui';
import type { ReviewAction } from '@/types/reviewQueue';
import type { ReviewLogEntry } from '@/hooks/useReviewLog';
import './ApprovalHistory.css';

export interface ApprovalHistoryProps {
  /** Decisions made in this browser. See `useReviewLog` for what this covers. */
  entries: ReviewLogEntry[];
}

const ACTION_LABEL: Record<ReviewAction, string> = {
  accept: 'Approved',
  correct: 'Corrected',
  dismiss: 'Rejected',
};

const ACTION_TONE: Record<ReviewAction, BadgeTone> = {
  accept: 'success',
  correct: 'primary',
  dismiss: 'danger',
};

const ACTION_ICON = {
  accept: Check,
  correct: Pencil,
  dismiss: X,
} as const satisfies Record<ReviewAction, typeof Check>;

/**
 * Audit trail of the decisions made in this browser.
 *
 * The backend only lists *pending* lines — there is no endpoint returning
 * already-resolved ones — so this is a local record, not the pharmacy's
 * compliance history, and the caption says so.
 */
export function ApprovalHistory({ entries }: ApprovalHistoryProps) {
  return (
    <>
      {entries.length === 0 ? (
        <p className="ahist__empty">
          Nothing has been reviewed yet in this browser. Decisions you make will be listed here.
        </p>
      ) : (
        <div className="ahist__wrap">
          <table className="ahist">
            <caption className="visually-hidden">Review decisions made in this browser</caption>
            <thead>
              <tr>
                <th scope="col">Ordered as</th>
                <th scope="col">Decision</th>
                <th scope="col">Final product</th>
                <th scope="col">From</th>
                <th scope="col">When</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => {
                const Icon = ACTION_ICON[entry.action];
                return (
                  <tr key={entry.itemId}>
                    <th scope="row" className="ahist__raw">
                      {entry.rawToken}
                    </th>
                    <td>
                      <Badge tone={ACTION_TONE[entry.action]} size="sm">
                        <Icon size={11} aria-hidden="true" />
                        {ACTION_LABEL[entry.action]}
                      </Badge>
                    </td>
                    <td className="ahist__final">{entry.catalogueName ?? '—'}</td>
                    <td className="ahist__source">
                      {entry.pharmacyId} · #{entry.orderId.slice(0, 8)}
                    </td>
                    <td className="ahist__when">{new Date(entry.decidedAt).toLocaleTimeString()}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <p className="ahist__scope">
        Recorded in this browser only, so it covers the decisions you have made here — not the
        pharmacy&rsquo;s full review history.
      </p>
    </>
  );
}

export default ApprovalHistory;
