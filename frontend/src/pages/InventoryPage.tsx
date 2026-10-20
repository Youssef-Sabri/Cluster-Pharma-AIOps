import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, Sparkles, X } from 'lucide-react';
import { Badge, Button, Card } from '@/components/ui';
import { ProductTable, type CatalogRow } from '@/components/inventory/ProductTable';
import { DemandChart } from '@/components/inventory/DemandChart';
import { ReorderCard } from '@/components/inventory/ReorderCard';
import { ScenarioToggle } from '@/components/inventory/ScenarioToggle';
import {
  PurchaseOrderSummary,
  type OrderLine,
} from '@/components/inventory/PurchaseOrderSummary';
import { useForecastQuery } from '@/api/endpoints/forecast';
import { apiErrorStatus, describeApiError } from '@/api/axios';
import { useDebouncedValue } from '@/hooks/useDebouncedValue';
import { useStockLevels } from '@/hooks/useStockLevels';
import {
  CATEGORY_LABELS,
  DEFAULT_PHARMACY_ID,
  DEFAULT_PRODUCT_IDS,
  FORECAST_REQUEST_IDS,
  INVENTORY_UNREQUESTED_IDS,
  PHARMACY_IDS,
  findProduct,
  therapeuticLabel,
  type CatalogueCategory,
} from '@/data/catalogue';
import {
  STOCK_BAND_LABELS,
  assessStockStatus,
  projectDemand,
  recommendReorder,
  round1,
  sortByUrgency,
  type StockBand,
} from '@/lib/procurement';
import { DEFAULT_SCENARIO_ID, findScenario, type ScenarioId } from '@/types/scenario';
import type { ForecastRequest } from '@/types/forecast';
import './InventoryPage.css';

/** Fixed 7-day window — this is the "7-day forecast" column, not a control. */
const HORIZON_DAYS = 7;

/** Debounce for the pharmacy switcher so dragging through 50 options is one request. */
const PHARMACY_DEBOUNCE_MS = 120;

type CategoryFilter = CatalogueCategory | 'ALL';
type StatusFilter = StockBand | 'ALL';

const CATEGORY_OPTIONS: CategoryFilter[] = ['ALL', 'OTC', 'PRESCRIPTION', 'COSMETIC'];
const STATUS_OPTIONS: StatusFilter[] = ['ALL', 'critical', 'low', 'adequate', 'unknown'];

/**
 * Inventory & smart reorder.
 *
 * The forecasting engine is invisible here. Every label is a business outcome:
 * expected demand, possible range, stock status, a quantity and a cost in EGP.
 * The arithmetic that produces them lives in `lib/procurement` and is never
 * rendered.
 */
export function InventoryPage() {
  const [pharmacyId, setPharmacyId] = useState<string>(DEFAULT_PHARMACY_ID);
  const [scenarioId, setScenarioId] = useState<ScenarioId>(DEFAULT_SCENARIO_ID);
  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>('ALL');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('ALL');
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string>(DEFAULT_PRODUCT_IDS[0] ?? '');
  const [orderLines, setOrderLines] = useState<OrderLine[]>([]);

  /**
   * The detail panel opens *below* the catalog table.
   *
   * With fourteen rows on screen the panel can land well outside the viewport,
   * so opening a product would look like it did nothing. Scrolling it into view
   * is what makes the click feel connected to its result.
   */
  const detailRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (expandedId) {
      detailRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }, [expandedId]);

  const stock = useStockLevels();
  const settledPharmacy = useDebouncedValue(pharmacyId, PHARMACY_DEBOUNCE_MS);
  const scenario = findScenario(scenarioId);

  const request = useMemo<ForecastRequest>(
    () => ({
      pharmacy_id: settledPharmacy,
      product_ids: [...FORECAST_REQUEST_IDS],
      forecast_horizon_days: HORIZON_DAYS,
    }),
    [settledPharmacy],
  );

  const { data, isPending, isFetching, isError, error, refetch } = useForecastQuery(request);

  /**
   * One derivation feeding the table, the detail panel and the order — so the
   * three can never disagree about a product.
   */
  const rows = useMemo<CatalogRow[]>(() => {
    if (!data) return [];

    const built = data.forecasts.map((item): CatalogRow => {
      const curated = findProduct(item.product_id);
      const projection = projectDemand(item, scenario);
      const status = assessStockStatus(stock.get(item.product_id), projection.meanPerDay);

      return {
        productId: item.product_id,
        label: item.product_name ?? curated?.label ?? item.product_id,
        category: curated ? CATEGORY_LABELS[curated.category] : '—',
        stock: stock.get(item.product_id),
        expectedDemand: projection.totalExpected,
        band: status.band,
        daysOfCover: status.daysOfCover,
        inOrder: orderLines.some((line) => line.productId === item.product_id),
      };
    });

    // Filter before sorting so the visible set is what gets ordered.
    const filtered = built.filter((row) => {
      if (categoryFilter !== 'ALL') {
        const curated = findProduct(row.productId);
        if (!curated || curated.category !== categoryFilter) return false;
      }
      if (statusFilter !== 'ALL' && row.band !== statusFilter) return false;
      return true;
    });

    return sortByUrgency(filtered);
  }, [data, scenario, stock, categoryFilter, statusFilter, orderLines]);

  const selectedRow = useMemo(
    () => rows.find((row) => row.productId === selectedId) ?? null,
    [rows, selectedId],
  );

  const selectedItem = useMemo(
    () => data?.forecasts.find((item) => item.product_id === selectedId) ?? null,
    [data, selectedId],
  );

  const selectedCurated = selectedId ? findProduct(selectedId) : undefined;

  const selectedRecommendation = useMemo(() => {
    if (!selectedItem) return null;
    const projection = projectDemand(selectedItem, scenario);
    return {
      recommendation: recommendReorder(projection, selectedCurated?.unitPriceEgp ?? 0, scenario),
      projection,
    };
  }, [selectedItem, scenario, selectedCurated]);

  /**
   * Products requested but not returned.
   *
   * The backend answers 200 with only the products it had enough purchase
   * history for. Without this note the catalog would silently list fewer
   * products than the catalogue holds.
   */
  const omissions = useMemo(() => {
    if (!data) return [];
    const returned = new Set(data.forecasts.map((item) => item.product_id));
    return FORECAST_REQUEST_IDS.filter((id) => !returned.has(id));
  }, [data]);

  const handleAddToOrder = useCallback(
    (label: string) => {
      if (!selectedCurated || !selectedRecommendation) return;

      setOrderLines((current) => {
        const line: OrderLine = {
          productId: selectedId,
          label,
          quantity: selectedRecommendation.recommendation.quantity,
          unitPriceEgp: selectedCurated.unitPriceEgp,
        };

        const existing = current.findIndex((entry) => entry.productId === selectedId);
        if (existing === -1) return [...current, line];

        const next = [...current];
        next[existing] = line;
        return next;
      });
    },
    [selectedCurated, selectedRecommendation, selectedId],
  );

  const removeFromOrder = useCallback((productId: string) => {
    setOrderLines((current) => current.filter((line) => line.productId !== productId));
  }, []);

  const clearOrder = useCallback(() => setOrderLines([]), []);

  const handleStockChange = useCallback(
    (productId: string, units: number) => {
      stock.set(productId, units);
    },
    [stock],
  );

  /**
   * Selecting a product also opens its detail panel, and vice versa.
   *
   * These must be one action. The panel renders for the product that is both
   * selected and expanded, so the chevron and the View button previously
   * disagreed: the chevron expanded a row without selecting it, and the panel
   * never appeared.
   */
  const handleSelectProduct = useCallback((productId: string) => {
    setSelectedId(productId);
    setExpandedId((current) => (current === productId ? null : productId));
  }, []);

  const showSkeleton = isPending && !data;

  return (
    <div className="inv">
      {/* ---------------------------------------------------------------- */}
      {/* Controls                                                          */}
      {/* ---------------------------------------------------------------- */}
      <Card tone="accent" title="Inventory planning">
        <div className="inv__controls">
          <div className="inv__field">
            <label className="inv__label" htmlFor="pharmacy-select">
              Pharmacy
            </label>
            <select
              id="pharmacy-select"
              className="inv__select"
              value={pharmacyId}
              onChange={(event) => setPharmacyId(event.target.value)}
            >
              {PHARMACY_IDS.map((id) => (
                <option key={id} value={id}>
                  {id}
                </option>
              ))}
            </select>
          </div>

          <div className="inv__field inv__field--scenario">
            <span className="inv__label">Plan for</span>
            <ScenarioToggle activeId={scenarioId} onChange={setScenarioId} />
          </div>
        </div>
      </Card>

      {/* ---------------------------------------------------------------- */}
      {/* Banners                                                           */}
      {/* ---------------------------------------------------------------- */}
      {isError ? (
        <Card tone="danger" title="We could not build your catalog">
          <div className="row" style={{ gap: 'var(--space-3)', alignItems: 'flex-start' }}>
            <AlertTriangle size={18} style={{ color: 'var(--color-danger)', flex: 'none' }} />
            <div>
              {apiErrorStatus(error) === 404 ? (
                <p className="text-sm">
                  We have no purchasing history for <strong>{settledPharmacy}</strong>, so we cannot
                  estimate demand for any product there.
                </p>
              ) : (
                <p className="text-sm">{describeApiError(error)}</p>
              )}
              <Button variant="secondary" size="sm" onClick={() => void refetch()} loading={isFetching}>
                Try again
              </Button>
            </div>
          </div>
        </Card>
      ) : null}

      {/* ---------------------------------------------------------------- */}
      {/* Stock data notice                                                 */}
      {/* ---------------------------------------------------------------- */}
      {!isError ? (
        <div className="inv__notice">
          <AlertTriangle size={15} aria-hidden="true" />
          <span>
            <strong>Stock levels are not connected in this demo.</strong> Enter what you have on
            hand in the Current stock column — saved on this device — and stock status and reorder
            recommendations will fill in. {stock.count > 0 ? `You have set ${stock.count} of ${rows.length} shown.` : ''}
          </span>
          {stock.count > 0 ? (
            <Button variant="ghost" size="sm" onClick={stock.clearAll}>
              Reset
            </Button>
          ) : null}
        </div>
      ) : null}

      {omissions.length > 0 || INVENTORY_UNREQUESTED_IDS.length > 0 ? (
        <Card tone="warning" title="Some products are not listed here">
          {omissions.length > 0 ? (
            <p className="text-sm muted">
              {settledPharmacy} has no purchase history for {omissions.length} of the catalogue
              products, so they are not listed.
            </p>
          ) : null}
          {INVENTORY_UNREQUESTED_IDS.length > 0 ? (
            <p className="text-sm muted">
              The catalog also holds {INVENTORY_UNREQUESTED_IDS.length} products that a single
              forecast request cannot cover, so they are not shown here either.
            </p>
          ) : null}
        </Card>
      ) : null}

      {/* ---------------------------------------------------------------- */}
      {/* Catalog                                                           */}
      {/* ---------------------------------------------------------------- */}
      <Card
        title="Product catalog"
        action={
          isFetching && data ? <span className="inv__updating">updating…</span> : undefined
        }
      >
        <div className="inv__filters">
          <div className="inv__filter">
            <label className="inv__filter-label" htmlFor="category-filter">
              Category
            </label>
            <select
              id="category-filter"
              className="inv__select inv__select--sm"
              value={categoryFilter}
              onChange={(event) => setCategoryFilter(event.target.value as CategoryFilter)}
            >
              {CATEGORY_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option === 'ALL' ? 'All categories' : CATEGORY_LABELS[option]}
                </option>
              ))}
            </select>
          </div>

          <div className="inv__filter">
            <label className="inv__filter-label" htmlFor="status-filter">
              Stock status
            </label>
            <select
              id="status-filter"
              className="inv__select inv__select--sm"
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}
            >
              {STATUS_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option === 'ALL' ? 'All statuses' : STOCK_BAND_LABELS[option]}
                </option>
              ))}
            </select>
          </div>

          <span className="inv__count">
            {rows.length} {rows.length === 1 ? 'product' : 'products'}
          </span>
        </div>

        {showSkeleton ? (
          <div className="inv__skeleton-rows" aria-busy="true" aria-live="polite">
            {[0, 1, 2, 3, 4, 5].map((index) => (
              <div key={index} className="skeleton" style={{ height: 44, marginBottom: 8 }} />
            ))}
            <span className="visually-hidden">Loading your catalog</span>
          </div>
        ) : (
          <ProductTable
            rows={rows}
            expandedId={expandedId}
            onToggleExpand={handleSelectProduct}
            selectedId={selectedId}
            onSelect={handleSelectProduct}
            onStockChange={handleStockChange}
          />
        )}

        {selectedRow && selectedItem && selectedRecommendation && expandedId === selectedRow.productId ? (
          <div className="inv__detail" ref={detailRef}>
            <header className="inv__detail-head">
              <div>
                <h3 className="inv__detail-title">{selectedRow.label}</h3>
                <p className="inv__detail-sub">
                  {selectedCurated
                    ? `${selectedCurated.generic} · ${CATEGORY_LABELS[selectedCurated.category]} · ${therapeuticLabel(selectedCurated.therapeuticClass)}`
                    : ''}
                </p>
              </div>
              <Button
                variant="ghost"
                size="sm"
                icon={<X size={14} />}
                onClick={() => setExpandedId(null)}
                aria-label="Close details"
              >
                Close
              </Button>
            </header>

            <div className="inv__detail-body">
              <div className="inv__chart">
                <p className="inv__legend">
                  <span className="inv__legend-line" /> Expected demand
                  <span className="inv__legend-area" /> Possible range
                </p>
                <DemandChart
                  item={selectedItem}
                  multiplier={scenario.demandMultiplier}
                />

                <dl className="inv__detail-stats">
                  <div>
                    <dt>Expected demand</dt>
                    <dd className="numeric">
                      {round1(selectedRecommendation.projection.totalExpected)} units
                    </dd>
                  </div>
                  <div>
                    <dt>Per day</dt>
                    <dd className="numeric">
                      {round1(selectedRecommendation.projection.meanPerDay)} units
                    </dd>
                  </div>
                  <div>
                    <dt>Days of cover</dt>
                    <dd className="numeric">
                      {selectedRow.daysOfCover !== null
                        ? `${selectedRow.daysOfCover} days`
                        : '—'}
                    </dd>
                  </div>
                  <div>
                    <dt>Status</dt>
                    <dd>
                      <Badge
                        tone={
                          selectedRow.band === 'critical'
                            ? 'danger'
                            : selectedRow.band === 'low'
                              ? 'warning'
                              : selectedRow.band === 'adequate'
                                ? 'success'
                                : 'neutral'
                        }
                        size="sm"
                      >
                        {STOCK_BAND_LABELS[selectedRow.band]}
                      </Badge>
                    </dd>
                  </div>
                </dl>
              </div>

              <ReorderCard
                recommendation={selectedRecommendation.recommendation}
                productLabel={selectedRow.label}
                days={HORIZON_DAYS}
                inOrder={selectedRow.inOrder}
                onAdd={handleAddToOrder}
              />
            </div>
          </div>
        ) : null}
      </Card>

      {/* ---------------------------------------------------------------- */}
      {/* Purchase order                                                    */}
      {/* ---------------------------------------------------------------- */}
      <PurchaseOrderSummary
        lines={orderLines}
        onRemove={removeFromOrder}
        onClear={clearOrder}
        pharmacyId={settledPharmacy}
      />

      {!isError && !showSkeleton && rows.length === 0 && data !== undefined ? (
        <Card tone="default">
          <div className="inv__empty">
            <Sparkles size={26} aria-hidden="true" />
            <p className="muted text-sm">
              We have no products with purchase history for {settledPharmacy}. Try another
              pharmacy.
            </p>
          </div>
        </Card>
      ) : null}
    </div>
  );
}

export default InventoryPage;
