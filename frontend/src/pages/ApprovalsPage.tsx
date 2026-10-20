import { useCallback, useEffect, useMemo, useState } from 'react';
import { CheckCircle2, Keyboard } from 'lucide-react';
import { Badge, Button, Card, LoadingSpinner, Toast } from '@/components/ui';
import { ApprovalCard } from '@/components/approvals/ApprovalCard';
import { ApprovalHistory } from '@/components/approvals/ApprovalHistory';
import { DrugSearchModal } from '@/components/approvals/DrugSearchModal';
import { useReviewQueue, useResolveReview } from '@/api/endpoints/reviewQueue';
import { describeApiError } from '@/api/axios';
import { PHARMACY_IDS, displayName, findProduct } from '@/data/catalogue';
import { useReviewLog } from '@/hooks/useReviewLog';
import type { ReviewAction, ReviewQueueItem } from '@/types/reviewQueue';
import './ApprovalsPage.css';

/**
 * Recorded against every decision.
 *
 * The review endpoint requires a `reviewed_by` and the demo deployment has no
 * authentication, so this is a fixed, honest label rather than a made-up name.
 */
const REVIEWED_BY = 'pharmacy-operator';

/** Rows fetched per page of the workbench. */
const PAGE_SIZE = 50;

/**
 * Pharmacist approvals.
 *
 * ## Keyboard model
 *
 * `A` / `C` / `D` act on the focused card; `↑` / `↓` move the focus. Shortcuts are
 * disabled whenever the operator is typing — the correction modal has a search
 * box, and an `A` typed into it must not approve a line behind the modal.
 */
export function ApprovalsPage() {
  const [pharmacyFilter, setPharmacyFilter] = useState<string>('ALL');
  const [offset, setOffset] = useState(0);
  const [focusIndex, setFocusIndex] = useState(0);
  const [correcting, setCorrecting] = useState<ReviewQueueItem | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [toast, setToast] = useState<{ title: string; message: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { entries, record } = useReviewLog();
  const resolveReview = useResolveReview();

  const { data, isPending, isFetching, isError, error: loadError, refetch } = useReviewQueue({
    ...(pharmacyFilter === 'ALL' ? {} : { pharmacyId: pharmacyFilter }),
    limit: PAGE_SIZE,
    offset,
  });

  const items = useMemo(() => data?.items ?? [], [data]);

  /** Decision on one line, then refresh the queue and the sidebar badge. */
  const decide = useCallback(
    (item: ReviewQueueItem, action: ReviewAction, correctedCatalogueId?: string) => {
      setBusyId(item.item_id);
      setError(null);

      resolveReview.mutate(
        {
          itemId: item.item_id,
          payload: {
            action,
            ...(correctedCatalogueId ? { corrected_catalogue_id: correctedCatalogueId } : {}),
            reviewed_by: REVIEWED_BY,
          },
        },
        {
          onSuccess: (result) => {
            const product = findProduct(result.catalogue_id);

            record({
              itemId: item.item_id,
              orderId: item.order_id,
              pharmacyId: item.pharmacy_id,
              rawToken: item.raw_token,
              quantity: item.quantity,
              orderCreatedAt: item.order_created_at,
              action,
              catalogueId: result.catalogue_id,
              catalogueName: result.catalogue_name ?? (product ? displayName(product) : null),
              decidedAt: result.reviewed_at,
            });

            setToast(
              action === 'accept'
                ? { title: 'Match approved', message: `“${item.raw_token}” confirmed.` }
                : action === 'correct'
                  ? {
                      title: 'Match corrected',
                      message: `“${item.raw_token}” is now ${result.catalogue_name ?? 'the selected product'}.`,
                    }
                  : {
                      title: 'Line rejected',
                      message: `“${item.raw_token}” was removed from order #${item.order_id.slice(0, 8)}.`,
                    },
            );
          },
          onError: (cause) => setError(describeApiError(cause)),
          onSettled: () => setBusyId(null),
        },
      );
    },
    [record, resolveReview],
  );

  const handleApprove = useCallback(
    (item: ReviewQueueItem) => decide(item, 'accept'),
    [decide],
  );

  const handleReject = useCallback(
    (item: ReviewQueueItem) => decide(item, 'dismiss'),
    [decide],
  );

  const handleCorrection = useCallback(
    (item: ReviewQueueItem, catalogueId: string) => decide(item, 'correct', catalogueId),
    [decide],
  );

  // Keep the focused card inside the list as it shrinks under decisions.
  useEffect(() => {
    setFocusIndex((current) => Math.min(current, Math.max(items.length - 1, 0)));
  }, [items.length]);

  // Page changes start at the top again.
  useEffect(() => {
    setFocusIndex(0);
  }, [offset, pharmacyFilter]);

  /** True while the operator is typing, where shortcuts must not fire. */
  const isTyping = useCallback((target: EventTarget | null): boolean => {
    if (!(target instanceof HTMLElement)) return false;
    if (target.isContentEditable) return true;
    return ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName);
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;

      // Typing anywhere — including inside the correction modal — wins.
      if (isTyping(event.target) || correcting !== null) return;

      const focused = items[focusIndex];
      if (!focused) return;

      switch (event.key.toLowerCase()) {
        case 'a':
          event.preventDefault();
          handleApprove(focused);
          break;
        case 'c':
          event.preventDefault();
          setCorrecting(focused);
          break;
        case 'd':
          event.preventDefault();
          handleReject(focused);
          break;
        case 'arrowdown':
          event.preventDefault();
          setFocusIndex((current) => Math.min(current + 1, items.length - 1));
          break;
        case 'arrowup':
          event.preventDefault();
          setFocusIndex((current) => Math.max(current - 1, 0));
          break;
        default:
          break;
      }
    };

    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [correcting, focusIndex, handleApprove, handleReject, isTyping, items]);

  const pendingTotal = data?.pending_total ?? 0;
  const pageCount = Math.max(1, Math.ceil(pendingTotal / PAGE_SIZE));
  const page = Math.floor(offset / PAGE_SIZE) + 1;

  return (
    <div className="approvals">
      <header className="approvals__header">
        <div>
          <h1 className="page-title">Approvals</h1>
          <p className="page-subtitle">
            {pendingTotal > 0 ? (
              <>
                <strong>
                  {pendingTotal} order {pendingTotal === 1 ? 'line needs' : 'lines need'} your
                  confirmation
                </strong>
              </>
            ) : (
              'Nothing is waiting for you right now.'
            )}
          </p>
        </div>

        <div className="approvals__controls">
          <label className="approvals__filter-label" htmlFor="approvals-pharmacy">
            Pharmacy
          </label>
          <select
            id="approvals-pharmacy"
            className="approvals__select"
            value={pharmacyFilter}
            onChange={(event) => {
              setPharmacyFilter(event.target.value);
              setOffset(0);
            }}
          >
            <option value="ALL">All pharmacies</option>
            {PHARMACY_IDS.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        </div>
      </header>

      <div className="approvals__legend">
        <span className="approvals__legend-item">
          <Keyboard size={14} aria-hidden="true" />
          <kbd>A</kbd> approve · <kbd>C</kbd> correct · <kbd>D</kbd> reject ·{' '}
          <kbd>&uarr;</kbd>
          <kbd>&darr;</kbd> move
        </span>
        {isFetching && !isPending ? (
          <span className="approvals__updating">updating…</span>
        ) : null}
      </div>

      {error ? (
        <Card tone="danger">
          <p style={{ fontSize: 'var(--font-size-sm)', color: 'var(--color-danger)' }}>{error}</p>
        </Card>
      ) : null}

      {isPending ? (
        <Card>
          <LoadingSpinner label="Loading review queue" />
        </Card>
      ) : isError ? (
        <Card tone="danger">
          <p style={{ fontSize: 'var(--font-size-sm)', color: 'var(--color-danger)' }}>
            {describeApiError(loadError)}
          </p>
          <div style={{ marginTop: 'var(--space-4)' }}>
            <Button variant="secondary" onClick={() => void refetch()}>
              Try again
            </Button>
          </div>
        </Card>
      ) : items.length === 0 ? (
        <Card tone="success">
          <div className="approvals__empty">
            <CheckCircle2 size={28} aria-hidden="true" />
            <h2 className="approvals__empty-title">All caught up</h2>
            <p className="approvals__empty-text">
              Every order line has been confirmed. New orders that need checking will appear here.
            </p>
            {offset > 0 ? (
              <Button variant="secondary" onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
                Back to earlier items
              </Button>
            ) : null}
          </div>
        </Card>
      ) : (
        <>
          <div className="approvals__list">
            {items.map((item, index) => (
              <ApprovalCard
                key={item.item_id}
                item={item}
                focused={index === focusIndex}
                busy={busyId === item.item_id}
                onApprove={handleApprove}
                onCorrect={setCorrecting}
                onReject={handleReject}
              />
            ))}
          </div>

          <nav className="approvals__pager" aria-label="Review queue pages">
            <Button
              variant="secondary"
              size="sm"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              Previous
            </Button>
            <Badge tone="neutral" size="sm">
              Page {page} of {pageCount}
            </Badge>
            <Button
              variant="secondary"
              size="sm"
              disabled={offset + PAGE_SIZE >= pendingTotal}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              Next
            </Button>
          </nav>
        </>
      )}

      <Card title="Recently reviewed">
        <ApprovalHistory entries={entries} />
      </Card>

      <DrugSearchModal
        open={correcting !== null}
        rawToken={correcting?.raw_token}
        initialQuery={correcting?.proposed_catalogue_name ?? ''}
        onClose={() => setCorrecting(null)}
        onSelect={(product) => {
          if (correcting) handleCorrection(correcting, product.id);
        }}
      />

      <Toast
        open={toast !== null}
        tone="success"
        title={toast?.title ?? ''}
        message={toast?.message}
        onClose={() => setToast(null)}
      />
    </div>
  );
}

export default ApprovalsPage;
