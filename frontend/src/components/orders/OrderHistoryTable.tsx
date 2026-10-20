import { Fragment, useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, PackageSearch } from 'lucide-react';
import { Badge } from '@/components/ui';
import type { BadgeTone } from '@/components/ui';
import { formatEgpPrecise } from '@/lib/money';
import './OrderHistoryTable.css';

export type HistoryStatus = 'completed' | 'pending' | 'flagged';

export interface HistoryLine {
  /** The text as the pharmacist wrote it. */
  rawToken: string;
  quantity: number | null;
  /** Product the line resolved to, when known. */
  productName: string | null;
  /** True when the line was rejected. */
  rejected: boolean;
}

export interface HistoryOrder {
  orderId: string;
  pharmacyId: string;
  /** ISO timestamp of the order, when known. */
  createdAt: string | null;
  lines: HistoryLine[];
  pendingCount: number;
  totalEgp: number;
}

export interface OrderHistoryTableProps {
  orders: HistoryOrder[];
}

const STATUS_LABEL: Record<HistoryStatus, string> = {
  completed: 'Completed',
  pending: 'Pending Verification',
  flagged: 'Flagged',
};

const STATUS_TONE: Record<HistoryStatus, BadgeTone> = {
  completed: 'success',
  pending: 'warning',
  flagged: 'danger',
};

type StatusFilter = HistoryStatus | 'ALL';

const STATUS_OPTIONS: StatusFilter[] = ['ALL', 'pending', 'completed', 'flagged'];

/**
 * Order history.
 *
 * Expands to show the individual lines of an order. The row's status is derived
 * from what is still outstanding: an order with unresolved lines is pending
 * verification, one whose lines were rejected is flagged, and one with nothing
 * left to resolve is complete.
 */
export function OrderHistoryTable({ orders }: OrderHistoryTableProps) {
  const [pharmacyFilter, setPharmacyFilter] = useState<string>('ALL');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('ALL');
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const rows = useMemo(
    () =>
      orders
        .map((order) => {
          const hasRejected = order.lines.some((line) => line.rejected);
          const status: HistoryStatus =
            order.pendingCount > 0 ? 'pending' : hasRejected ? 'flagged' : 'completed';
          return { ...order, status };
        })
        .filter((order) => {
          if (pharmacyFilter !== 'ALL' && order.pharmacyId !== pharmacyFilter) return false;
          if (statusFilter !== 'ALL' && order.status !== statusFilter) return false;
          return true;
        }),
    [orders, pharmacyFilter, statusFilter],
  );

  const pharmacies = useMemo(
    () => [...new Set(orders.map((order) => order.pharmacyId))].sort(),
    [orders],
  );

  if (orders.length === 0) {
    return (
      <div className="ohist__empty">
        <PackageSearch size={26} aria-hidden="true" />
        <p>No orders to show yet.</p>
      </div>
    );
  }

  return (
    <>
      <div className="ohist__filters">
        <div className="ohist__filter">
          <label className="ohist__filter-label" htmlFor="history-pharmacy">
            Pharmacy
          </label>
          <select
            id="history-pharmacy"
            className="ohist__select"
            value={pharmacyFilter}
            onChange={(event) => setPharmacyFilter(event.target.value)}
          >
            <option value="ALL">All pharmacies</option>
            {pharmacies.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        </div>

        <div className="ohist__filter">
          <label className="ohist__filter-label" htmlFor="history-status">
            Status
          </label>
          <select
            id="history-status"
            className="ohist__select"
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}
          >
            {STATUS_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option === 'ALL' ? 'All statuses' : STATUS_LABEL[option]}
              </option>
            ))}
          </select>
        </div>

        <span className="ohist__count">
          {rows.length} {rows.length === 1 ? 'order' : 'orders'}
        </span>
      </div>

      <div className="ohist__wrap">
        <table className="ohist">
          <caption className="visually-hidden">Past orders</caption>
          <thead>
            <tr>
              <th scope="col" className="ohist__chevron-col">
                <span className="visually-hidden">Details</span>
              </th>
              <th scope="col">Date</th>
              <th scope="col">Order #</th>
              <th scope="col">Pharmacy</th>
              <th scope="col" className="ohist__num">
                Items
              </th>
              <th scope="col" className="ohist__num">
                Total (EGP)
              </th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((order) => {
              const expanded = order.orderId === expandedId;
              return (
                <Fragment key={order.orderId}>
                  <tr
                    className={`ohist__row ohist__row--${order.status}`}
                    onClick={() => setExpandedId(expanded ? null : order.orderId)}
                  >
                    <td className="ohist__chevron-col">
                      <span className="ohist__chevron" aria-hidden="true">
                        {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                      </span>
                    </td>
                    <td className="ohist__date">
                      {order.createdAt ? new Date(order.createdAt).toLocaleDateString() : '—'}
                    </td>
                    <td className="ohist__ref mono">#{order.orderId.slice(0, 8)}</td>
                    <td>{order.pharmacyId}</td>
                    <td className="ohist__num">
                      {order.lines.length} {order.lines.length === 1 ? 'item' : 'items'}
                    </td>
                    <td className="ohist__num numeric">{formatEgpPrecise(order.totalEgp)}</td>
                    <td>
                      <Badge tone={STATUS_TONE[order.status]} size="sm">
                        {STATUS_LABEL[order.status]}
                      </Badge>
                    </td>
                  </tr>

                  {expanded ? (
                    <tr className="ohist__detail-row">
                      <td colSpan={7}>
                        <div className="ohist__detail">
                          {order.lines.map((line, index) => (
                            <div key={`${line.rawToken}-${index}`} className="ohist__line">
                              <span className="ohist__line-raw">{line.rawToken}</span>
                              <span className="ohist__line-qty">
                                {line.quantity !== null ? `${line.quantity} units` : '—'}
                              </span>
                              <span className="ohist__line-product">
                                {line.rejected
                                  ? 'Rejected'
                                  : (line.productName ?? 'Awaiting confirmation')}
                              </span>
                            </div>
                          ))}
                        </div>
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

export default OrderHistoryTable;
