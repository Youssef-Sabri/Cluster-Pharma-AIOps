import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { ClipboardList, Info } from 'lucide-react';
import { Button, Card, LoadingSpinner } from '@/components/ui';
import {
  OrderHistoryTable,
  type HistoryLine,
  type HistoryOrder,
} from '@/components/orders/OrderHistoryTable';
import { useReviewQueue } from '@/api/endpoints/reviewQueue';
import { describeApiError } from '@/api/axios';
import { PHARMACY_IDS, findProduct } from '@/data/catalogue';
import { formatEgpPrecise } from '@/lib/money';
import { useReviewLog } from '@/hooks/useReviewLog';
import './OrderHistoryPage.css';

/**
 * How many pending lines to pull.
 *
 * The review queue accepts at most 500 items per request, and orders are
 * reconstructed by grouping those lines — so this is the most history one page
 * of requests can produce.
 */
const HISTORY_LIMIT = 500;

/**
 * Order history.
 *
 * ## What this screen can and cannot show
 *
 * There is no `GET /api/v1/orders`. The only record of past orders the API
 * exposes is the review queue, which lists *pending* lines and nothing else, so
 * this screen is built by grouping those lines into the orders they belong to.
 *
 * Two consequences, both stated on the page rather than hidden:
 *
 * - An order appears here only if it has at least one line still awaiting a
 *   decision. Orders matched in full never enter the queue and so never appear.
 *   Presenting this as the complete order ledger would overstate the data.
 * - The queue is ordered oldest-first on purpose — it is a work queue meant to
 *   be drained in arrival order — and offers no sort parameter. The first page
 *   is therefore the oldest backlog, not the most recent orders. The list is
 *   sorted newest-first *within* that page, and the pager moves through the
 *   backlog.
 */
export function OrderHistoryPage() {
  const { entries } = useReviewLog();
  const [pharmacyFilter, setPharmacyFilter] = useState<string>('ALL');
  const [offset, setOffset] = useState(0);

  const { data, isPending, isFetching, isError, error, refetch } = useReviewQueue({
    ...(pharmacyFilter === 'ALL' ? {} : { pharmacyId: pharmacyFilter }),
    limit: HISTORY_LIMIT,
    offset,
  });

  /**
   * Pending lines grouped into orders.
   *
   * Priced from the proposed product on each line. A line whose suggestion the
   * catalogue cannot resolve contributes nothing rather than a guessed price.
   */
  const orders = useMemo<HistoryOrder[]>(() => {
    if (!data) return [];

    const byOrder = new Map<string, HistoryOrder>();

    for (const item of data.items) {
      // A rejected line from this browser folds into its order below, so it is
      // skipped here to avoid listing it twice.
      if (entries.some((entry) => entry.itemId === item.item_id)) continue;

      let order = byOrder.get(item.order_id);
      if (!order) {
        order = {
          orderId: item.order_id,
          pharmacyId: item.pharmacy_id,
          createdAt: item.order_created_at,
          lines: [],
          pendingCount: 0,
          totalEgp: 0,
        };
        byOrder.set(item.order_id, order);
      }

      const product = findProduct(item.proposed_catalogue_id);
      const line: HistoryLine = {
        rawToken: item.raw_token,
        quantity: item.quantity,
        productName: product ? `${product.label} ${product.strength}`.trim() : null,
        rejected: false,
      };

      order.lines.push(line);
      order.pendingCount += 1;
      order.totalEgp += (product?.unitPriceEgp ?? 0) * (item.quantity ?? 0);
    }

    return [...byOrder.values()].sort((a, b) => {
      const left = a.createdAt ? new Date(a.createdAt).getTime() : 0;
      const right = b.createdAt ? new Date(b.createdAt).getTime() : 0;
      return right - left;
    });
  }, [data, entries]);

  /**
   * Orders that only appear because of decisions made in this browser.
   *
   * Resolving the last pending line of an order removes it from the queue, and
   * with it from the grouping above — which would make a reviewed order vanish
   * instead of turning Completed. Rebuilding those from the local log keeps the
   * order visible and lets it carry the Flagged status.
   */
  const reviewedOrders = useMemo<HistoryOrder[]>(() => {
    const byOrder = new Map<string, HistoryOrder>();

    for (const entry of entries) {
      let order = byOrder.get(entry.orderId);
      if (!order) {
        order = {
          orderId: entry.orderId,
          pharmacyId: entry.pharmacyId,
          createdAt: entry.orderCreatedAt,
          lines: [],
          pendingCount: 0,
          totalEgp: 0,
        };
        byOrder.set(entry.orderId, order);
      }

      const product = findProduct(entry.catalogueId);
      order.lines.push({
        rawToken: entry.rawToken,
        quantity: entry.quantity,
        productName: entry.catalogueName ?? (product ? product.label : null),
        rejected: entry.action === 'dismiss',
      });
      order.totalEgp += (product?.unitPriceEgp ?? 0) * (entry.quantity ?? 0);
    }

    // Merge into the matching pending order where there still is one.
    const merged = orders.map((order) => {
      const extra = byOrder.get(order.orderId);
      if (!extra) return order;
      byOrder.delete(order.orderId);
      return {
        ...order,
        lines: [...order.lines, ...extra.lines],
        pendingCount: order.pendingCount,
        totalEgp: order.totalEgp + extra.totalEgp,
      };
    });

    return [...merged, ...byOrder.values()];
  }, [entries, orders]);

  const visible = useMemo(
    () =>
      pharmacyFilter === 'ALL'
        ? reviewedOrders
        : reviewedOrders.filter((order) => order.pharmacyId === pharmacyFilter),
    [pharmacyFilter, reviewedOrders],
  );

  /** Pharmacies with an order on screen, plus the registry for the filter. */
  const pharmacyOptions = useMemo(() => {
    const present = new Set(reviewedOrders.map((order) => order.pharmacyId));
    return [...PHARMACY_IDS].filter((id) => present.has(id));
  }, [reviewedOrders]);

  const totalValue = useMemo(
    () => reviewedOrders.reduce((sum, order) => sum + order.totalEgp, 0),
    [reviewedOrders],
  );

  const pendingTotal = data?.pending_total ?? 0;

  return (
    <div className="ohist-page">
      <header className="ohist-page__header">
        <div>
          <h1 className="page-title">Order history</h1>
          <p className="page-subtitle">
            Every order we can see, with the lines that are still being checked.
          </p>
        </div>
        <Button variant="secondary" onClick={() => void refetch()}>
          Refresh
        </Button>
      </header>

      <Card tone="info">
        <p className="ohist-page__scope">
          <Info size={15} aria-hidden="true" />
          <span>
            This list shows orders with at least one line still waiting to be confirmed —{' '}
            <strong>{reviewedOrders.length}</strong> of them. Orders matched in full are settled
            automatically and never reach this list, so it is not the complete order ledger.
            Lines are listed oldest first, so this page is the start of the backlog rather than
            the most recent activity.
          </span>
        </p>
      </Card>

      {isPending ? (
        <Card>
          <LoadingSpinner label="Loading orders" />
        </Card>
      ) : isError ? (
        <Card tone="danger">
          <p className="ohist-page__error">{describeApiError(error)}</p>
          <div className="mt-4">
            <Button variant="secondary" onClick={() => void refetch()}>
              Try again
            </Button>
          </div>
        </Card>
      ) : (
        <>
          <div className="ohist-page__stats">
            <div className="ohist-page__stat">
              <span className="ohist-page__stat-value">{reviewedOrders.length}</span>
              <span className="ohist-page__stat-label">Orders</span>
            </div>
            <div className="ohist-page__stat">
              <span className="ohist-page__stat-value">
                {reviewedOrders.reduce((sum, order) => sum + order.pendingCount, 0)}
              </span>
              <span className="ohist-page__stat-label">Lines awaiting a decision</span>
            </div>
            <div className="ohist-page__stat">
              {/*
                Rounded to whole pounds: this tile aggregates hundreds of lines,
                and a piastre on a six-figure figure reads as an error rather
                than as precision. Line totals in the table stay exact.
              */}
              <span className="ohist-page__stat-value">
                {formatEgpPrecise(Math.round(totalValue))}
              </span>
              <span className="ohist-page__stat-label">Value of listed lines</span>
            </div>
          </div>

          <Card>
            <div className="ohist-page__toolbar">
              <label className="ohist-page__filter-label" htmlFor="history-page-pharmacy">
                Pharmacy
              </label>
              <select
                id="history-page-pharmacy"
                className="ohist-page__select"
                value={pharmacyFilter}
                onChange={(event) => {
                  setPharmacyFilter(event.target.value);
                  setOffset(0);
                }}
              >
                <option value="ALL">All pharmacies</option>
                {pharmacyOptions.map((id) => (
                  <option key={id} value={id}>
                    {id}
                  </option>
                ))}
              </select>

              <Link className="ohist-page__cta" to="/orders/new">
                <ClipboardList size={15} aria-hidden="true" />
                New order
              </Link>

              {isFetching ? (
                <span className="ohist-page__updating">updating…</span>
              ) : null}
            </div>

            <OrderHistoryTable orders={visible} />

            {pendingTotal > HISTORY_LIMIT ? (
              <nav className="ohist-page__pager" aria-label="Older orders">
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - HISTORY_LIMIT))}
                >
                  Newer
                </Button>
                <span className="ohist-page__page">
                  Showing {offset + 1}–{offset + (data?.items.length ?? 0)} of {pendingTotal}{' '}
                  unresolved lines
                </span>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={offset + HISTORY_LIMIT >= pendingTotal}
                  onClick={() => setOffset(offset + HISTORY_LIMIT)}
                >
                  Older
                </Button>
              </nav>
            ) : null}
          </Card>
        </>
      )}
    </div>
  );
}

export default OrderHistoryPage;
