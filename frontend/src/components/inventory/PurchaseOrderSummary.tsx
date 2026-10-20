import { useMemo } from 'react';
import { Trash2, FileDown } from 'lucide-react';
import { Button, Card } from '@/components/ui';
import { formatEgp, round1 } from '@/lib/procurement';
import './PurchaseOrderSummary.css';

export interface OrderLine {
  productId: string;
  /** Display name at the moment it was added. */
  label: string;
  quantity: number;
  unitPriceEgp: number;
}

export interface PurchaseOrderSummaryProps {
  lines: OrderLine[];
  onRemove: (productId: string) => void;
  onClear: () => void;
  pharmacyId: string;
}

/**
 * CSV cell escaping.
 *
 * A product name containing a comma or quote would otherwise produce a file
 * whose columns silently shift — the sort of thing that is only noticed when a
 * purchase order is wrong. Doubling quotes is the RFC 4180 rule.
 */
function csvCell(value: string | number): string {
  const text = String(value);
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/**
 * Purchase order summary.
 *
 * Export writes a real CSV file to the user's device using the browser's Blob
 * and object-URL APIs — no server round trip and no extra dependency. The URL is
 * revoked immediately after the click, which matters: a leaked object URL keeps
 * the generated file alive in memory for the life of the tab.
 */
export function PurchaseOrderSummary({
  lines,
  onRemove,
  onClear,
  pharmacyId,
}: PurchaseOrderSummaryProps) {
  const total = useMemo(
    () => lines.reduce((sum, line) => sum + line.quantity * line.unitPriceEgp, 0),
    [lines],
  );

  const exportCsv = () => {
    const header = ['Drug', 'Quantity', 'Unit Price (EGP)', 'Subtotal (EGP)'];
    const rows = lines.map((line) => [
      line.label,
      String(line.quantity),
      round1(line.unitPriceEgp).toFixed(2),
      round1(line.quantity * line.unitPriceEgp).toFixed(2),
    ]);

    const csv = [header, ...rows]
      .map((row) => row.map((cell) => csvCell(cell)).join(','))
      .join('\r\n');

    // A BOM makes Excel read the file as UTF-8 rather than the local codepage.
    const blob = new Blob(['﻿', csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);

    const link = document.createElement('a');
    link.href = url;
    link.download = `clusterops-purchase-order-${pharmacyId}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  return (
    <Card
      title="Purchase order"
      action={
        lines.length > 0 ? (
          <Button variant="ghost" size="sm" icon={<Trash2 size={14} />} onClick={onClear}>
            Clear all
          </Button>
        ) : undefined
      }
    >
      {lines.length === 0 ? (
        <p className="pos__empty">
          Your purchase order is empty. Add a product from the list to get started.
        </p>
      ) : (
        <>
          <div className="pos__wrap">
            <table className="pos">
              <caption className="visually-hidden">
                Items in the current purchase order
              </caption>
              <thead>
                <tr>
                  <th scope="col">Drug</th>
                  <th scope="col" className="pos__num">
                    Quantity
                  </th>
                  <th scope="col" className="pos__num">
                    Unit price
                  </th>
                  <th scope="col" className="pos__num">
                    Subtotal
                  </th>
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {lines.map((line) => (
                  <tr key={line.productId}>
                    <th scope="row" className="pos__drug">
                      {line.label}
                    </th>
                    <td className="pos__num numeric">
                      {line.quantity.toLocaleString('en-EG')}
                    </td>
                    <td className="pos__num numeric">{formatEgp(line.unitPriceEgp)}</td>
                    <td className="pos__num numeric">
                      {formatEgp(round1(line.quantity * line.unitPriceEgp))}
                    </td>
                    <td className="pos__actions">
                      <button
                        type="button"
                        className="pos__remove"
                        onClick={() => onRemove(line.productId)}
                        aria-label={`Remove ${line.label} from the purchase order`}
                      >
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <th scope="row">
                    Total
                    <span className="pos__count">
                      {lines.length} {lines.length === 1 ? 'product' : 'products'}
                    </span>
                  </th>
                  <td className="pos__num numeric">
                    {lines.reduce((sum, line) => sum + line.quantity, 0).toLocaleString('en-EG')}
                  </td>
                  <td />
                  <td className="pos__num numeric pos__total">{formatEgp(round1(total))}</td>
                  <td />
                </tr>
              </tfoot>
            </table>
          </div>

          <div className="pos__actions-bar">
            <span className="pos__grand">
              Grand total <strong>{formatEgp(round1(total))}</strong>
            </span>
            <Button variant="primary" icon={<FileDown size={16} />} onClick={exportCsv}>
              Export Purchase Order
            </Button>
          </div>
        </>
      )}
    </Card>
  );
}

export default PurchaseOrderSummary;
