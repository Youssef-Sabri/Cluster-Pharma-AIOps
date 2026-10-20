import { ChevronDown, ChevronRight, PackageSearch } from 'lucide-react';
import { Badge } from '@/components/ui';
import type { BadgeTone } from '@/components/ui';
import { STOCK_BAND_LABELS, round1, type StockBand } from '@/lib/procurement';
import './ProductTable.css';

export interface CatalogRow {
  productId: string;
  label: string;
  /** Category display name, e.g. "Over the counter". */
  category: string;
  /** Entered stock, or undefined when the operator has not set it. */
  stock: number | undefined;
  /** Scenario-adjusted expected demand over the window. */
  expectedDemand: number;
  band: StockBand;
  daysOfCover: number | null;
  inOrder: boolean;
}

export interface ProductTableProps {
  rows: CatalogRow[];
  expandedId: string | null;
  onToggleExpand: (productId: string) => void;
  /** Currently highlighted row, tied to the detail panel. */
  selectedId: string | null;
  onSelect: (productId: string) => void;
  onStockChange: (productId: string, units: number) => void;
}

/** Green / amber / red, plus a neutral for "not entered". */
const BAND_TONE: Record<StockBand, BadgeTone> = {
  adequate: 'success',
  low: 'warning',
  critical: 'danger',
  unknown: 'neutral',
};

/**
 * Product catalog.
 *
 * Rows are ordered by urgency — critical first — so the products that need a
 * decision are at the top without the operator sorting anything.
 *
 * "Current stock" is an editable field rather than a read-only figure because
 * there is no inventory feed in the backend (see `hooks/useStockLevels`). An
 * invented number here would paint a confident red "Critical" that a pharmacist
 * might reorder against, so the cell prompts instead of guessing.
 */
export function ProductTable({
  rows,
  expandedId,
  onToggleExpand,
  selectedId,
  onSelect,
  onStockChange,
}: ProductTableProps) {
  if (rows.length === 0) {
    return (
      <div className="ptable-empty">
        <PackageSearch size={26} aria-hidden="true" />
        <p>No products match these filters.</p>
      </div>
    );
  }

  return (
    <div className="ptable-wrap">
      <table className="ptable">
        <caption className="visually-hidden">
          Product catalog with stock status and expected demand
        </caption>
        <thead>
          <tr>
            <th scope="col" className="ptable__expand-col">
              <span className="visually-hidden">Details</span>
            </th>
            <th scope="col">Drug name</th>
            <th scope="col">Category</th>
            <th scope="col" className="ptable__num">
              Current stock
            </th>
            <th scope="col" className="ptable__num">
              7-day forecast
            </th>
            <th scope="col">Stock status</th>
            <th scope="col">Action</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const expanded = row.productId === expandedId;
            const selected = row.productId === selectedId;

            return (
              <tr
                key={row.productId}
                className={[
                  'ptable__row',
                  `ptable__row--${row.band}`,
                  expanded ? 'ptable__row--expanded' : '',
                  selected ? 'ptable__row--selected' : '',
                ]
                  .filter(Boolean)
                  .join(' ')}
              >
                <td className="ptable__expand-col">
                  <button
                    type="button"
                    className="ptable__chevron"
                    onClick={() => onToggleExpand(row.productId)}
                    aria-expanded={expanded}
                    aria-label={`${expanded ? 'Hide' : 'Show'} demand chart for ${row.label}`}
                  >
                    {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                  </button>
                </td>

                <th scope="row" className="ptable__drug">
                  <button
                    type="button"
                    className="ptable__name-btn"
                    onClick={() => onSelect(row.productId)}
                  >
                    {row.label}
                  </button>
                </th>

                <td className="ptable__category">{row.category}</td>

                {/* Stock is operator-entered; an empty cell means "not set",
                    never zero. */}
                <td className="ptable__num">
                  <input
                    className="ptable__stock"
                    type="number"
                    min={0}
                    step={1}
                    inputMode="numeric"
                    placeholder="Enter"
                    value={row.stock ?? ''}
                    onChange={(event) => {
                      const parsed = Number(event.target.value);
                      const units =
                        Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : 0;
                      onStockChange(row.productId, units);
                    }}
                    aria-label={`Current stock for ${row.label}`}
                  />
                </td>

                <td className="ptable__num numeric">
                  {round1(row.expectedDemand)} units
                </td>

                <td>
                  <Badge tone={BAND_TONE[row.band]} size="sm" pulse={row.band === 'critical'}>
                    {STOCK_BAND_LABELS[row.band]}
                  </Badge>
                  {row.daysOfCover !== null ? (
                    <span className="ptable__cover">{row.daysOfCover}d cover</span>
                  ) : null}
                </td>

                <td>
                  <button
                    type="button"
                    className="ptable__view"
                    onClick={() => onSelect(row.productId)}
                  >
                    {selected ? 'Viewing' : 'View'}
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}


export default ProductTable;
