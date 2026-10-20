import { Loader2, Send } from 'lucide-react';
import { Button } from '@/components/ui';
import { PresetButtons } from './PresetButtons';
import './OrderInput.css';

export interface OrderInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  /** True while the order is being matched. */
  loading: boolean;
  /** Pharmacy the order is for. */
  pharmacyId: string;
  onPharmacyChange: (pharmacyId: string) => void;
}

/**
 * Order entry.
 *
 * A single large text area rather than a form: a pharmacist restocking writes
 * the order the way they would on paper, and the whole point of the product is
 * that it does not need a structured form.
 */
export function OrderInput({
  value,
  onChange,
  onSubmit,
  loading,
  pharmacyId,
  onPharmacyChange,
}: OrderInputProps) {
  const canSubmit = value.trim().length > 0 && !loading;

  return (
    <div className="oinput">
      <div className="oinput__head">
        <div>
          <h2 className="oinput__title">Type your order</h2>
          <p className="oinput__subtitle">
            Write it the way you would on paper — Arabic, English, or a mix. We will turn it into a
            clean purchase order.
          </p>
        </div>
        <label className="oinput__pharmacy">
          <span>Pharmacy</span>
          <select
            value={pharmacyId}
            onChange={(event) => onPharmacyChange(event.target.value)}
            aria-label="Pharmacy placing this order"
          >
            {PHARMACY_OPTIONS.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        </label>
      </div>

      <textarea
        className="oinput__area"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="Type or paste a pharmacy order in Arabic or English..."
        rows={6}
        spellCheck={false}
        aria-label="Order text"
        onKeyDown={(event) => {
          // Ctrl/Cmd+Enter submits, matching the usual expectation for a
          // multi-line composer.
          if ((event.ctrlKey || event.metaKey) && event.key === 'Enter' && canSubmit) {
            event.preventDefault();
            onSubmit();
          }
        }}
      />

      <div className="oinput__actions">
        <PresetButtons
          onPick={(preset) => onChange(preset)}
          disabled={loading}
          current={value}
        />

        <Button
          variant="primary"
          size="lg"
          onClick={onSubmit}
          loading={loading}
          disabled={!canSubmit}
          icon={loading ? <Loader2 size={16} className="oinput__spin" /> : <Send size={16} />}
        >
          {loading ? 'Processing order' : 'Process Order'}
        </Button>
      </div>

      <p className="oinput__hint">Tip: press Ctrl + Enter to process the order.</p>
    </div>
  );
}

/**
 * Pharmacy options.
 *
 * Kept local to the component so the list of synthetic pharmacies lives in one
 * place. The full registry is in `data/catalogue`.
 */
const PHARMACY_OPTIONS: readonly string[] = Array.from(
  { length: 50 },
  (_, index) => `PH-${String(index + 1).padStart(3, '0')}`,
);

export default OrderInput;
