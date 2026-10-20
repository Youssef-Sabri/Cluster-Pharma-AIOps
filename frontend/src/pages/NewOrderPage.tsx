import { useCallback, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, PartyPopper } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Button, Card, Toast } from '@/components/ui';
import { OrderInput } from '@/components/orders/OrderInput';
import { InvoiceTable } from '@/components/orders/InvoiceTable';
import { useMatchOrderMutation } from '@/api/endpoints/matchOrder';
import { useResolveReview } from '@/api/endpoints/reviewQueue';
import { describeApiError } from '@/api/axios';
import { DEFAULT_PHARMACY_ID, findProduct } from '@/data/catalogue';
import { formatEgpPrecise, sumEgp } from '@/lib/money';
import type { MatchedItem, MatchOrderResponse } from '@/types/matchOrder';
import './NewOrderPage.css';

/**
 * Recorded against every decision.
 *
 * The review endpoint requires a `reviewed_by` and there is no authentication
 * layer behind the demo deployment, so this is a fixed, honest label rather than
 * an invented person's name.
 */
const REVIEWED_BY = 'pharmacy-operator';

/** What the page shows after a successful submit. */
interface SubmittedOrder {
  orderId: string;
  lineCount: number;
  unitCount: number;
  totalEgp: number;
  /** Lines still awaiting a pharmacist after corrections were applied. */
  reviewCount: number;
  /** Corrections applied at submit time. */
  correctedCount: number;
}

/**
 * Pair up corrections with the persisted lines they apply to.
 *
 * The preview is a dry run and the submitted order is a second, real call, so
 * the two responses are separate. They are matched on `raw_token` rather than on
 * position: the LLM re-ranker can order its output differently between two runs,
 * and a correction silently landing on the wrong line is worse than one that
 * does not land at all.
 */
function pairCorrections(
  preview: readonly MatchedItem[],
  persisted: readonly MatchedItem[],
  corrections: Record<number, string>,
): Array<{ itemId: string; catalogueId: string }> {
  const byToken = new Map<string, string[]>();
  for (const item of persisted) {
    if (!item.item_id) continue;
    const queue = byToken.get(item.raw_token) ?? [];
    queue.push(item.item_id);
    byToken.set(item.raw_token, queue);
  }

  const pairs: Array<{ itemId: string; catalogueId: string }> = [];
  preview.forEach((item, index) => {
    const catalogueId = corrections[index];
    if (!catalogueId) return;
    const itemId = byToken.get(item.raw_token)?.shift();
    if (itemId) pairs.push({ itemId, catalogueId });
  });
  return pairs;
}

/**
 * New order.
 *
 * Two deliberate steps rather than one:
 *
 * 1. **Process Order** runs a dry match. Nothing is written, so an order the
 *    operator abandons leaves no rows behind, and the invoice can be corrected
 *    freely while it is still a preview.
 * 2. **Confirm & Submit** writes the order, then applies any corrections as
 *    pharmacist decisions on the persisted lines.
 *
 * Step 2 has to be two API calls because a correction can only be recorded
 * against a line that exists in the database, and only lines the matcher
 * flagged can be corrected at all — the backend returns 404 for a line it
 * already considers settled.
 */
export function NewOrderPage() {
  const [text, setText] = useState('');
  const [pharmacyId, setPharmacyId] = useState(DEFAULT_PHARMACY_ID);
  const [preview, setPreview] = useState<MatchOrderResponse | null>(null);
  const [corrections, setCorrections] = useState<Record<number, string>>({});
  const [submitted, setSubmitted] = useState<SubmittedOrder | null>(null);
  const [toast, setToast] = useState<{ title: string; message: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const matchOrder = useMatchOrderMutation();
  const resolveReview = useResolveReview();

  /**
   * Editing the text invalidates the preview: the invoice on screen would no
   * longer describe what was typed.
   */
  const handleTextChange = useCallback((value: string) => {
    setText(value);
    setPreview(null);
    setCorrections({});
    setSubmitted(null);
    setError(null);
  }, []);

  const handleProcess = useCallback(() => {
    const raw = text.trim();
    if (raw.length === 0) return;

    setSubmitted(null);
    setError(null);
    matchOrder.mutate(
      { raw_text: raw, pharmacy_id: pharmacyId, persist: false },
      {
        onSuccess: (data) => {
          setPreview(data);
          setCorrections({});
        },
        onError: (cause) => setError(describeApiError(cause)),
      },
    );
  }, [matchOrder, pharmacyId, text]);

  const handleCorrect = useCallback((index: number, catalogueId: string) => {
    setCorrections((current) => {
      const next = { ...current };
      if (catalogueId === '') delete next[index];
      else next[index] = catalogueId;
      return next;
    });
  }, []);

  const handleSubmit = useCallback(() => {
    if (!preview) return;

    setSubmitting(true);
    setError(null);

    matchOrder.mutate(
      { raw_text: text.trim(), pharmacy_id: pharmacyId, persist: true },
      {
        onSuccess: async (persisted) => {
          const pairs = pairCorrections(preview.items, persisted.items, corrections);

          try {
            // Sequential on purpose: each correction clears a flag, and firing
            // them in parallel against one order invites write contention.
            for (const pair of pairs) {
              await resolveReview.mutateAsync({
                itemId: pair.itemId,
                payload: {
                  action: 'correct',
                  corrected_catalogue_id: pair.catalogueId,
                  reviewed_by: REVIEWED_BY,
                },
              });
            }

            // Price the order as it was actually written: a corrected line is
            // charged at the corrected product, not the one first suggested.
            const totalEgp = sumEgp(
              persisted.items.map((item, index) => {
                const product =
                  findProduct(corrections[index]) ?? findProduct(item.catalogue_id);
                return (product?.unitPriceEgp ?? 0) * item.quantity;
              }),
            );

            setSubmitted({
              orderId: persisted.order_id ?? '',
              lineCount: persisted.items.length,
              unitCount: persisted.total_units,
              totalEgp,
              reviewCount: persisted.items_needing_review - pairs.length,
              correctedCount: pairs.length,
            });
            setToast({
              title: 'Order submitted',
              message:
                pairs.length > 0
                  ? `The purchase order and ${pairs.length} ${pairs.length === 1 ? 'correction' : 'corrections'} were recorded.`
                  : 'The purchase order has been recorded.',
            });
            setPreview(null);
            setCorrections({});
          } catch (cause) {
            setError(
              `The order was placed, but a correction could not be saved: ${describeApiError(cause)}`,
            );
          } finally {
            setSubmitting(false);
          }
        },
        onError: (cause) => {
          setError(describeApiError(cause));
          setSubmitting(false);
        },
      },
    );
  }, [corrections, matchOrder, pharmacyId, preview, resolveReview, text]);

  const handleReset = useCallback(() => {
    setText('');
    setPreview(null);
    setCorrections({});
    setSubmitted(null);
    setError(null);
  }, []);

  /** Corrections still waiting on a product. */
  const unresolvedCount = useMemo(
    () =>
      preview
        ? preview.items.filter((item, index) => item.needs_review && !corrections[index]).length
        : 0,
    [corrections, preview],
  );

  const correctedCount = Object.keys(corrections).length;

  return (
    <div className="norder">
      <header className="norder__header">
        <div>
          <h1 className="page-title">New order</h1>
          <p className="page-subtitle">
            Write the order in your own words and we will turn it into a clean purchase order.
          </p>
        </div>
        {submitted ? (
          <Link className="norder__link" to="/orders">
            View order history
          </Link>
        ) : null}
      </header>

      {submitted ? (
        <Card tone="success" className="norder__done">
          <div className="norder__done-icon">
            <PartyPopper size={24} aria-hidden="true" />
          </div>
          <h2 className="norder__done-title">Order submitted</h2>
          <p className="norder__done-text">
            {submitted.lineCount} lines · {submitted.unitCount} units ·{' '}
            <strong>{formatEgpPrecise(submitted.totalEgp)}</strong>
          </p>
          <p className="norder__done-ref mono">Order #{submitted.orderId.slice(0, 8)}</p>

          {submitted.reviewCount > 0 ? (
            <p className="norder__done-warn">
              <AlertTriangle size={14} aria-hidden="true" />
              {submitted.reviewCount}{' '}
              {submitted.reviewCount === 1 ? 'line needs' : 'lines need'} a pharmacist to confirm
              before the order goes out.
            </p>
          ) : (
            <p className="norder__done-ok">
              <CheckCircle2 size={14} aria-hidden="true" />
              Every line was matched confidently.
            </p>
          )}

          {submitted.correctedCount > 0 ? (
            <p className="norder__done-fixed">
              <CheckCircle2 size={14} aria-hidden="true" />
              {submitted.correctedCount}{' '}
              {submitted.correctedCount === 1 ? 'correction was' : 'corrections were'} applied from
              this screen.
            </p>
          ) : null}

          <div className="norder__done-actions">
            <Button variant="primary" onClick={handleReset} icon={<CheckCircle2 size={15} />}>
              Start another order
            </Button>
          </div>
        </Card>
      ) : (
        <>
          <Card>
            <OrderInput
              value={text}
              onChange={handleTextChange}
              onSubmit={handleProcess}
              loading={matchOrder.isPending}
              pharmacyId={pharmacyId}
              onPharmacyChange={(value) => {
                setPharmacyId(value);
                setPreview(null);
                setCorrections({});
              }}
            />
          </Card>

          {error ? (
            <Card tone="danger">
              <p className="norder__error">{error}</p>
            </Card>
          ) : null}

          {preview ? (
            <Card
              title="Review before submitting"
              action={
                <Button
                  variant="primary"
                  onClick={handleSubmit}
                  loading={submitting}
                  disabled={unresolvedCount > 0}
                  icon={<CheckCircle2 size={15} />}
                >
                  {submitting ? 'Submitting order' : 'Confirm & Submit Order'}
                </Button>
              }
            >
              {unresolvedCount > 0 ? (
                <p className="norder__blocked">
                  <AlertTriangle size={14} aria-hidden="true" />
                  Choose a product for {unresolvedCount}{' '}
                  {unresolvedCount === 1 ? 'line' : 'lines'} below before submitting.
                </p>
              ) : correctedCount > 0 ? (
                <p className="norder__corrected">
                  <CheckCircle2 size={14} aria-hidden="true" />
                  {correctedCount} {correctedCount === 1 ? 'line' : 'lines'} corrected. The change
                  is recorded against the order when you submit.
                </p>
              ) : (
                <p className="norder__ready">
                  <CheckCircle2 size={14} aria-hidden="true" />
                  Everything is matched. Submitting sends the order to the pharmacy.
                </p>
              )}

              <InvoiceTable
                items={preview.items}
                corrections={corrections}
                onCorrect={handleCorrect}
              />
            </Card>
          ) : null}
        </>
      )}

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

export default NewOrderPage;
