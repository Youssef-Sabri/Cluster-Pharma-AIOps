import { useEffect, useMemo, useRef, useState } from 'react';
import { Search } from 'lucide-react';
import { Button, Modal } from '@/components/ui';
import { CATALOGUE, CATEGORY_LABELS, displayName, searchCatalogue, therapeuticLabel } from '@/data/catalogue';
import type { CatalogueProduct } from '@/data/catalogue';
import './DrugSearchModal.css';

export interface DrugSearchModalProps {
  open: boolean;
  onClose: () => void;
  onSelect: (product: CatalogueProduct) => void;
  /** The text the pharmacist is trying to correct, shown as context. */
  rawToken?: string;
  /** Pre-fill the search box with this, e.g. the suggested product. */
  initialQuery?: string;
}

/**
 * Catalogue picker.
 *
 * Restricted to real catalogue ids — the backend rejects anything else with a
 * 409, so offering a free-text field would only produce failed corrections.
 * Search covers trade name, molecule, form and therapeutic class, because a
 * pharmacist may know a product by any of them.
 */
export function DrugSearchModal({
  open,
  onClose,
  onSelect,
  rawToken,
  initialQuery = '',
}: DrugSearchModalProps) {
  const [query, setQuery] = useState(initialQuery);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!open) return;
    setQuery(initialQuery);
    // Focus the field and select whatever is in it. The box is pre-filled with
    // the product we are trying to *replace*, so the pharmacist's first
    // keystroke should overwrite it rather than append to it — otherwise they
    // end up searching for "Cataflam 50 50mgamox".
    const timer = window.setTimeout(() => {
      const input = inputRef.current;
      if (!input) return;
      input.focus();
      input.select();
    }, 30);
    return () => window.clearTimeout(timer);
  }, [open, initialQuery]);

  const results = useMemo(() => searchCatalogue(query), [query]);

  return (
    <Modal
      open={open}
      title="Select the correct product"
      subtitle={
        rawToken ? `Replacing "${rawToken}"` : 'Search the product catalogue'
      }
      onClose={onClose}
      wide
    >
      <div className="dsearch__field">
        <Search size={16} aria-hidden="true" />
        <input
          ref={inputRef}
          className="dsearch__input"
          type="search"
          value={query}
          placeholder="Search by brand, ingredient, or category…"
          onChange={(event) => setQuery(event.target.value)}
          aria-label="Search the product catalogue"
        />
      </div>

      {results.length === 0 ? (
        <p className="dsearch__empty">
          Nothing matches &ldquo;{query}&rdquo;. Try a shorter word, or the ingredient name.
        </p>
      ) : (
        <ul className="dsearch__list">
          {results.slice(0, 60).map((product) => (
            <li key={product.id}>
              <button
                type="button"
                className="dsearch__item"
                onClick={() => {
                  onSelect(product);
                  onClose();
                }}
              >
                <span className="dsearch__name">{displayName(product)}</span>
                <span className="dsearch__generic">{product.generic}</span>
                <span className="dsearch__meta">
                  {CATEGORY_LABELS[product.category]} · {therapeuticLabel(product.therapeuticClass)}{' '}
                  · {product.form}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="dsearch__foot">
        <span className="dsearch__count">
          {results.length} of {CATALOGUE.length} products
        </span>
        <Button variant="secondary" size="sm" onClick={onClose}>
          Cancel
        </Button>
      </div>
    </Modal>
  );
}

export default DrugSearchModal;
