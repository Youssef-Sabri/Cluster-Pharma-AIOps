import { useEffect, useRef, useState } from 'react';
import { Check, ShoppingCart } from 'lucide-react';
import { Button } from '@/components/ui';
import { formatEgp, type ReorderRecommendation } from '@/lib/procurement';
import './ReorderCard.css';

export interface ReorderCardProps {
  recommendation: ReorderRecommendation;
  /** Product display name, used in the accessible label. */
  productLabel: string;
  /** Window length in days, for the coverage sentence. */
  days: number;
  inOrder: boolean;
  onAdd: (productId: string) => void;
  /** How long the confirmation stays visible, in ms. */
  confirmMs?: number;
}

/**
 * Reorder recommendation for one product.
 *
 * The arithmetic is `ceil(high_estimate × 1.15)` and it deliberately uses the
 * high end of the range: running out on an essential line costs a pharmacy more
 * than the 15 % of value it ties up on the shelf. The formula itself is never
 * shown — the operator gets a quantity and a cost, which is what they act on.
 */
export function ReorderCard({
  recommendation,
  productLabel,
  days,
  inOrder,
  onAdd,
  confirmMs = 2600,
}: ReorderCardProps) {
  const [justAdded, setJustAdded] = useState(false);
  const timer = useRef<number | null>(null);

  /* Clear on unmount so the confirmation window can never outlive the component
     or fire a state update after navigation. */
  useEffect(() => {
    return () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    };
  }, []);

  const handleAdd = () => {
    onAdd(productLabel);
    setJustAdded(true);

    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      setJustAdded(false);
      timer.current = null;
    }, confirmMs);
  };

  if (!recommendation.orderable) {
    return (
      <div className="rcard rcard--empty">
        <p className="rcard__none">Nothing to reorder for this product right now.</p>
      </div>
    );
  }

  return (
    <div className="rcard">
      <span className="rcard__label">Recommended reorder</span>

      <p className="rcard__quantity">
        <strong className="numeric">{recommendation.quantity.toLocaleString('en-EG')}</strong>
        <span>units</span>
      </p>

      <p className="rcard__covers">
        Covers {days} {days === 1 ? 'day' : 'days'} of expected demand, with a safety buffer in case
        sales run higher than expected.
      </p>

      <dl className="rcard__rows">
        <div className="rcard__row">
          <dt>Unit price</dt>
          <dd className="numeric">{formatEgp(recommendation.unitPriceEgp)}</dd>
        </div>
        <div className="rcard__row">
          <dt>Expected demand</dt>
          <dd className="numeric">
            {Math.round(recommendation.quantity / recommendation.safetyFactor)} units
          </dd>
        </div>
        <div className="rcard__row rcard__row--total">
          <dt>Estimated cost</dt>
          <dd className="numeric">{formatEgp(recommendation.estimatedCostEgp)}</dd>
        </div>
      </dl>

      <Button
        variant={justAdded || inOrder ? 'success' : 'primary'}
        size="lg"
        fullWidth
        onClick={handleAdd}
        icon={justAdded || inOrder ? <Check size={16} /> : <ShoppingCart size={16} />}
      >
        {justAdded ? 'Added to purchase order' : inOrder ? 'Update purchase order' : 'Add to Purchase Order'}
      </Button>
    </div>
  );
}

export default ReorderCard;
