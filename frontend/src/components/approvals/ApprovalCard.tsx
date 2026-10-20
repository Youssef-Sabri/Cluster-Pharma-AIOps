import { Check, Pencil, X } from 'lucide-react';
import { Button } from '@/components/ui';
import { findProduct } from '@/data/catalogue';
import type { ReviewQueueItem } from '@/types/reviewQueue';
import './ApprovalCard.css';

export interface ApprovalCardProps {
  item: ReviewQueueItem;
  /** True when this card is the keyboard target. */
  focused?: boolean;
  /** True while a decision on this card is in flight. */
  busy?: boolean;
  onApprove: (item: ReviewQueueItem) => void;
  onCorrect: (item: ReviewQueueItem) => void;
  onReject: (item: ReviewQueueItem) => void;
}

/**
 * One order line awaiting a decision.
 *
 * Shows what the customer actually wrote, what we think it means, and where it
 * came from — with three ways to resolve it. The matcher's confidence is
 * represented by a coloured dot and a word, never as a number: a pharmacist
 * needs to know *whether* to trust a suggestion, not how the score was computed.
 */
export function ApprovalCard({
  item,
  focused = false,
  busy = false,
  onApprove,
  onCorrect,
  onReject,
}: ApprovalCardProps) {
  const proposed = findProduct(item.proposed_catalogue_id);
  const proposedName = item.proposed_catalogue_name ?? proposed?.label ?? null;
  const proposedGeneric = proposed?.generic ?? null;

  // A proposal the catalogue cannot resolve is shown as an unknown suggestion
  // rather than a confident guess.
  const hasProposal = Boolean(proposedName);

  return (
    <article
      className={`acard${focused ? ' acard--focused' : ''}`}
      aria-current={focused ? 'true' : undefined}
    >
      <div className="acard__main">
        <div className="acard__block">
          <span className="acard__label">Customer's order</span>
          <p className="acard__raw">{item.raw_token}</p>
          {item.quantity !== null ? (
            <p className="acard__qty">{item.quantity} units requested</p>
          ) : null}
        </div>

        <div className="acard__block">
          <span className="acard__label">Suggested match</span>
          {hasProposal ? (
            <>
              <p className="acard__suggestion">
                <span
                  className={`acard__dot${proposed ? ' acard__dot--known' : ' acard__dot--unknown'}`}
                  aria-hidden="true"
                />
                {proposedName}
              </p>
              {proposedGeneric ? <p className="acard__generic">{proposedGeneric}</p> : null}
            </>
          ) : (
            <p className="acard__suggestion acard__suggestion--none">
              <span className="acard__dot acard__dot--unknown" aria-hidden="true" />
              No close match found
            </p>
          )}
        </div>

        <div className="acard__block acard__block--source">
          <span className="acard__label">From</span>
          <p className="acard__source">
            Order #{item.order_id.slice(0, 8)} · {item.pharmacy_id}
          </p>
          {item.order_created_at ? (
            <p className="acard__time">
              {new Date(item.order_created_at).toLocaleString()}
            </p>
          ) : null}
        </div>
      </div>

      <div className="acard__actions">
        <Button
          variant="success"
          size="sm"
          onClick={() => onApprove(item)}
          loading={busy}
          icon={<Check size={14} />}
        >
          Approve
        </Button>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => onCorrect(item)}
          disabled={busy}
          icon={<Pencil size={14} />}
        >
          Correct
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onReject(item)}
          disabled={busy}
          icon={<X size={14} />}
        >
          Reject
        </Button>
      </div>

      {focused ? (
        <span className="acard__keys" aria-hidden="true">
          A approve · C correct · D reject
        </span>
      ) : null}
    </article>
  );
}

export default ApprovalCard;
