import { useMemo } from 'react';
import { AlertTriangle, Check, Package } from 'lucide-react';
import { Badge } from '@/components/ui';
import type { BadgeTone } from '@/components/ui';
import { CATALOGUE, displayName, findProduct } from '@/data/catalogue';
import { formatAmountEgp, sumEgp } from '@/lib/money';
import type { MatchedItem } from '@/types/matchOrder';
import './InvoiceTable.css';

export interface InvoiceTableProps {
  items: MatchedItem[];
  /**
   * Catalogue id chosen by the operator for a line that needs checking,
   * keyed by the line's index in `items`.
   */
  corrections: Record<number, string>;
  onCorrect: (index: number, catalogueId: string) => void;
  /** Called when a line's correction is applied. */
  onCommit?: () => void;
}

/** Above this, a match is considered settled and shows a plain green badge. */
const SETTLED_THRESHOLD = 0.7;

/**
 * Line status.
 *
 * The backend already decides which lines need a human (`needs_review`), so
 * that flag is authoritative. The confidence value is used only to tell a
 * settled match apart from a softer one — it is never shown as a number.
 */
function lineStatus(
  item: MatchedItem,
  corrected: string | undefined,
): { tone: BadgeTone; label: string; needsAttention: boolean } {
  if (corrected) {
    return { tone: 'success', label: 'Matched', needsAttention: false };
  }
  if (item.needs_review) {
    return { tone: 'warning', label: 'Please verify', needsAttention: true };
  }
  if (item.confidence >= SETTLED_THRESHOLD) {
    return { tone: 'success', label: 'Matched', needsAttention: false };
  }
  // A softer match, still accepted — shown neutrally rather than alarmed.
  return { tone: 'info', label: 'Matched', needsAttention: false };
}

/**
 * The digital invoice.
 *
 * A commercial document, not a model output: every line has a product, a
 * quantity, a unit price and a total in EGP, plus a plain-language status. The
 * matching engine's technique names, confidence values and rationales are
 * deliberately absent.
 */
export function InvoiceTable({ items, corrections, onCorrect, onCommit }: InvoiceTableProps) {
  const lines = useMemo(
    () =>
      items.map((item, index) => {
        const correctedId = corrections[index];
        const product = findProduct(correctedId) ?? findProduct(item.catalogue_id);
        const status = lineStatus(item, correctedId);

        const unitPrice = product?.unitPriceEgp ?? null;
        const total = unitPrice === null ? null : unitPrice * item.quantity;

        return { item, index, product, status, unitPrice, total, correctedId };
      }),
    [items, corrections],
  );

  const subtotal = sumEgp(lines.map((line) => line.total ?? 0));
  const pricedCount = lines.filter((line) => line.total !== null).length;
  const needsAttention = lines.filter((line) => line.status.needsAttention).length;

  return (
    <div className="invoice">
      <header className="invoice__head">
        <div className="invoice__title-block">
          <h2 className="invoice__title">Purchase order</h2>
          <p className="invoice__subtitle">
            {lines.length} {lines.length === 1 ? 'line' : 'lines'} ·{' '}
            {lines.reduce((sum, line) => sum + line.item.quantity, 0)} units
          </p>
        </div>

        {needsAttention > 0 ? (
          <Badge tone="warning" size="sm" pulse>
            <AlertTriangle size={11} aria-hidden="true" />
            {needsAttention} {needsAttention === 1 ? 'line needs' : 'lines need'} your attention
          </Badge>
        ) : (
          <Badge tone="success" size="sm">
            <Check size={11} aria-hidden="true" />
            All lines matched
          </Badge>
        )}
      </header>

      <div className="invoice__wrap">
        <table className="invoice__table">
          <caption className="visually-hidden">Purchase order lines</caption>
          <thead>
            <tr>
              <th scope="col" className="invoice__num">
                #
              </th>
              <th scope="col">Item</th>
              <th scope="col" className="invoice__num">
                Quantity
              </th>
              <th scope="col" className="invoice__num">
                Unit Price (EGP)
              </th>
              <th scope="col" className="invoice__num">
                Total (EGP)
              </th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {lines.map((line) => (
              <tr key={`${line.item.raw_token}-${line.index}`} className={line.status.needsAttention ? 'invoice__row--attention' : ''}>
                <td className="invoice__num invoice__index">{line.index + 1}</td>

                <th scope="row" className="invoice__item">
                  {/*
                    A line awaiting checking shows the text that was actually
                    written, because that is what the pharmacist needs to read
                    back — the suggested product is a guess until confirmed.

                    A corrected line shows the *chosen* product, not the one the
                    matcher first guessed: naming "Otrivin Nasal" on a line
                    priced and totalled as Cataflam would make the document
                    contradict itself.
                  */}
                  {line.status.needsAttention ? (
                    <span className="invoice__raw">"{line.item.raw_token}"</span>
                  ) : (
                    <span className="invoice__name">
                      {line.correctedId && line.product
                        ? displayName(line.product)
                        : (line.item.catalogue_name ?? 'Unmatched item')}
                    </span>
                  )}
                  {line.item.unit ? (
                    <span className="invoice__unit">per {line.item.unit}</span>
                  ) : null}

                  {line.status.needsAttention ? (
                    <div className="invoice__fix">
                      <label className="visually-hidden" htmlFor={`fix-${line.index}`}>
                        Correct the product for {line.item.raw_token}
                      </label>
                      <select
                        id={`fix-${line.index}`}
                        className="invoice__select"
                        value={line.correctedId ?? ''}
                        onChange={(event) => {
                          onCorrect(line.index, event.target.value);
                          onCommit?.();
                        }}
                      >
                        <option value="">Select the correct product…</option>
                        {CATALOGUE.map((product) => (
                          <option key={product.id} value={product.id}>
                            {displayName(product)} — {product.generic}
                          </option>
                        ))}
                      </select>
                      {line.correctedId ? (
                        <span className="invoice__fixed">
                          <Check size={12} aria-hidden="true" /> Corrected
                        </span>
                      ) : null}
                    </div>
                  ) : null}
                </th>

                <td className="invoice__num numeric">{line.item.quantity}</td>
                <td className="invoice__num numeric">
                  {line.unitPrice === null ? '—' : formatAmountEgp(line.unitPrice)}
                </td>
                <td className="invoice__num numeric invoice__total">
                  {line.total === null ? '—' : formatAmountEgp(line.total)}
                </td>

                <td>
                  <Badge tone={line.status.tone} size="sm" pulse={line.status.needsAttention}>
                    {line.status.label}
                  </Badge>
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td className="invoice__num" />
              <th scope="row">Subtotal</th>
              <td className="invoice__num" />
              <td className="invoice__num" />
              <td className="invoice__num numeric invoice__grand">{formatAmountEgp(subtotal)}</td>
              <td />
            </tr>
            <tr className="invoice__total-row">
              <td className="invoice__num" />
              <th scope="row">Grand Total</th>
              <td className="invoice__num" />
              <td className="invoice__num" />
              <td className="invoice__num numeric invoice__grand">{formatAmountEgp(subtotal)}</td>
              <td />
            </tr>
          </tfoot>
        </table>
      </div>

      {pricedCount < lines.length ? (
        <p className="invoice__note">
          <Package size={13} aria-hidden="true" />
          {lines.length - pricedCount} {lines.length - pricedCount === 1 ? 'line is' : 'lines are'} not
          priced yet. Pick the right product and the total will complete.
        </p>
      ) : null}
    </div>
  );
}

export default InvoiceTable;
