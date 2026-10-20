/**
 * The ClusterOps product catalogue.
 *
 * ## Provenance
 *
 * Every entry is a row of `drug_catalogue`, read from the live database on
 * 2026-10-18: `catalogue_id`, `brand_name`, `generic_name`, `form`, `strength`,
 * `unit_price_egp`, `category` and `therapeutic_class`. Nothing here is
 * hand-maintained and nothing is invented — the prices are what the invoice
 * screen charges and the drug-search modal offers.
 *
 * There is no `GET /api/v1/products` endpoint, so the catalogue is read straight
 * from the table. Adding one would let this file disappear.
 *
 * ## A note on ids
 *
 * The ids encode the catalogue's deliberate Egyptian transliteration variants —
 * `broughen-400` is Brufen 400, `congistal-500` is Congestal, `kattaflam-50` is
 * Cataflam 50, `amoksil-500` is Amoxil 500. Earlier documents listed the
 * "obvious" spellings (`brufen-400`, `congestal-tablet`, `cataflam-50`,
 * `amoxil-500`); none of those exist, and the backend silently drops ids it
 * cannot resolve, so the wrong spelling produces a missing product rather than
 * an error.
 */

export type CatalogueCategory = 'OTC' | 'PRESCRIPTION' | 'COSMETIC';

/** Business-facing category names. The raw codes never reach the UI. */
export const CATEGORY_LABELS: Record<CatalogueCategory, string> = {
  OTC: 'Over the counter',
  PRESCRIPTION: 'Prescription',
  COSMETIC: 'Personal care',
};

/** Title-cased therapeutic class, e.g. `COLD_FLU` -> `Cold Flu`. */
export function therapeuticLabel(value: string): string {
  return value
    .toLowerCase()
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

export interface CatalogueProduct {
  /** Exact `drug_catalogue.catalogue_id`. Case-sensitive. */
  id: string;
  /** `brand_name` — the trade name, e.g. "Panadol Extra". */
  label: string;
  /** `generic_name` — the molecule, e.g. "Paracetamol 500mg". */
  generic: string;
  /** `form` — tablet, capsule, syrup, cream… */
  form: string;
  /** `strength` — e.g. "500mg". */
  strength: string;
  /** `unit_price_egp`. */
  unitPriceEgp: number;
  category: CatalogueCategory;
  therapeuticClass: string;
}

/**
 * Display name, matching what the backend returns as `catalogue_name`.
 *
 * The backend composes brand + strength ("Panadol Extra 500mg"), so the client
 * does the same and the invoice line and the picker agree with the API.
 */
export function displayName(product: CatalogueProduct): string {
  return `${product.label} ${product.strength}`.trim();
}

/** The full catalogue, ordered by trade name. */
export const CATALOGUE: readonly CatalogueProduct[] = [
  { id: 'adol-500', label: 'Adol 500', generic: 'Paracetamol 500mg', form: 'tablet', strength: '500mg', unitPriceEgp: 12.5, category: 'OTC', therapeuticClass: 'ANTIPYRETIC' },
  { id: 'aerolayd-inhaler', label: 'Aerolide Inhaler', generic: 'Salbutamol + Fluticasone', form: 'inhaler', strength: '50/500mcg', unitPriceEgp: 320, category: 'PRESCRIPTION', therapeuticClass: 'RESPIRATORY' },
  { id: 'aldacton-25', label: 'Aldactone 25', generic: 'Spironolactone', form: 'tablet', strength: '25mg', unitPriceEgp: 38, category: 'PRESCRIPTION', therapeuticClass: 'DIURETIC' },
  { id: 'amaryl-3', label: 'Amaryl 3', generic: 'Glimepiride', form: 'tablet', strength: '3mg', unitPriceEgp: 90, category: 'PRESCRIPTION', therapeuticClass: 'DIABETES' },
  { id: 'amoksil-500', label: 'Amoxil 500', generic: 'Amoxicillin', form: 'capsule', strength: '500mg', unitPriceEgp: 62, category: 'PRESCRIPTION', therapeuticClass: 'ANTIBIOTIC' },
  { id: 'antinal-200', label: 'Antinal 200', generic: 'Nifuroxazide', form: 'capsule', strength: '200mg', unitPriceEgp: 45, category: 'OTC', therapeuticClass: 'GI' },
  { id: 'augmentin-1g', label: 'Augmentin 1g', generic: 'Amoxicillin + Clavulanic Acid', form: 'tablet', strength: '1g', unitPriceEgp: 245, category: 'PRESCRIPTION', therapeuticClass: 'ANTIBIOTIC' },
  { id: 'augmentin-625', label: 'Augmentin 625', generic: 'Amoxicillin + Clavulanic Acid', form: 'tablet', strength: '625mg', unitPriceEgp: 195, category: 'PRESCRIPTION', therapeuticClass: 'ANTIBIOTIC' },
  { id: 'augmentin-susp-457', label: 'Augmentin Suspension', generic: 'Amoxicillin + Clavulanic Acid', form: 'suspension', strength: '457mg/5ml', unitPriceEgp: 168, category: 'PRESCRIPTION', therapeuticClass: 'ANTIBIOTIC' },
  { id: 'beta-sol-cream-1', label: 'Betamethasone Valerate', generic: 'Betamethasone Valerate', form: 'cream', strength: '1mg/g', unitPriceEgp: 95, category: 'PRESCRIPTION', therapeuticClass: 'DERM' },
  { id: 'bessolvon-syrup-5', label: 'Bisolvon', generic: 'Bromhexine', form: 'syrup', strength: '5mg/5ml', unitPriceEgp: 42, category: 'OTC', therapeuticClass: 'COUGH' },
  { id: 'broughen-400', label: 'Brufen 400', generic: 'Ibuprofen', form: 'tablet', strength: '400mg', unitPriceEgp: 25, category: 'OTC', therapeuticClass: 'ANTIPYRETIC' },
  { id: 'broughen-syrup-100', label: 'Brufen Syrup', generic: 'Ibuprofen', form: 'syrup', strength: '100mg/5ml', unitPriceEgp: 38, category: 'OTC', therapeuticClass: 'ANTIPYRETIC' },
  { id: 'cal-d-600', label: 'Cal-D', generic: 'Calcium + Vitamin D3', form: 'effervescent tablet', strength: '600mg', unitPriceEgp: 55, category: 'OTC', therapeuticClass: 'SUPPLEMENT' },
  { id: 'kattaflam-50', label: 'Cataflam 50', generic: 'Diclofenac Potassium', form: 'tablet', strength: '50mg', unitPriceEgp: 68, category: 'OTC', therapeuticClass: 'ANALGESIC' },
  { id: 'kattaflam-gel-1', label: 'Cataflam Gel', generic: 'Diclofenac Diethylamine', form: 'gel', strength: '1%', unitPriceEgp: 72, category: 'OTC', therapeuticClass: 'TOPICAL_ANALGESIC' },
  { id: 'ceevit-1000', label: 'Ceevit', generic: 'Ascorbic Acid', form: 'effervescent tablet', strength: '1000mg', unitPriceEgp: 26, category: 'OTC', therapeuticClass: 'VITAMIN' },
  { id: 'cipronil-500', label: 'Cipronil 500', generic: 'Ciprofloxacin', form: 'tablet', strength: '500mg', unitPriceEgp: 78, category: 'PRESCRIPTION', therapeuticClass: 'ANTIBIOTIC' },
  { id: 'clarityne-10', label: 'Clarityne', generic: 'Loratadine', form: 'tablet', strength: '10mg', unitPriceEgp: 28, category: 'OTC', therapeuticClass: 'ALLERGY' },
  { id: 'clarityne-syrup-5', label: 'Clarityne Syrup', generic: 'Loratadine', form: 'syrup', strength: '5mg/5ml', unitPriceEgp: 32, category: 'OTC', therapeuticClass: 'ALLERGY' },
  { id: 'concor-5', label: 'Concor 5', generic: 'Bisoprolol', form: 'tablet', strength: '5mg', unitPriceEgp: 58, category: 'PRESCRIPTION', therapeuticClass: 'CARDIO' },
  { id: 'congistal-500', label: 'Congestal', generic: 'Paracetamol + Chlorphenamine + Pseudoephedrine', form: 'tablet', strength: '500mg', unitPriceEgp: 34, category: 'OTC', therapeuticClass: 'COLD_FLU' },
  { id: 'cristor-20', label: 'Crestor 20', generic: 'Rosuvastatin', form: 'tablet', strength: '20mg', unitPriceEgp: 265, category: 'PRESCRIPTION', therapeuticClass: 'CHOLESTEROL' },
  { id: 'diamicron-80', label: 'Diamicron 80', generic: 'Gliclazide', form: 'tablet', strength: '80mg', unitPriceEgp: 65, category: 'PRESCRIPTION', therapeuticClass: 'DIABETES' },
  { id: 'inzhor-plus-400', label: 'Ensure Plus', generic: 'Nutritional Supplement', form: 'powder sachet', strength: '400g', unitPriceEgp: 520, category: 'OTC', therapeuticClass: 'SUPPLEMENT' },
  { id: 'feroglobin-150', label: 'Feroglobin', generic: 'Iron + Vitamins', form: 'capsule', strength: '150mg', unitPriceEgp: 88, category: 'OTC', therapeuticClass: 'SUPPLEMENT' },
  { id: 'fevadol-500', label: 'Fevadol 500', generic: 'Paracetamol 500mg', form: 'tablet', strength: '500mg', unitPriceEgp: 15, category: 'OTC', therapeuticClass: 'ANTIPYRETIC' },
  { id: 'javiskon-sachet', label: 'Gaviscon Advance', generic: 'Sodium Alginate', form: 'sachet', strength: '10ml', unitPriceEgp: 98, category: 'OTC', therapeuticClass: 'GI' },
  { id: 'glucophage-850', label: 'Glucophage 850', generic: 'Metformin', form: 'tablet', strength: '850mg', unitPriceEgp: 72, category: 'PRESCRIPTION', therapeuticClass: 'DIABETES' },
  { id: 'hydrocort-cream-1', label: 'Hydrocortisone Cream', generic: 'Hydrocortisone', form: 'cream', strength: '1%', unitPriceEgp: 48, category: 'OTC', therapeuticClass: 'DERM' },
  { id: 'ketoderm-cream-2', label: 'Ketoderm 2%', generic: 'Ketoconazole', form: 'cream', strength: '2%', unitPriceEgp: 145, category: 'OTC', therapeuticClass: 'DERM' },
  { id: 'klacid-500', label: 'Klacid', generic: 'Clarithromycin', form: 'tablet', strength: '500mg', unitPriceEgp: 225, category: 'PRESCRIPTION', therapeuticClass: 'ANTIBIOTIC' },
  { id: 'lassik-40', label: 'Lasix 40', generic: 'Furosemide', form: 'tablet', strength: '40mg', unitPriceEgp: 30, category: 'PRESCRIPTION', therapeuticClass: 'DIURETIC' },
  { id: 'lepetor-20', label: 'Lipitor 20', generic: 'Atorvastatin', form: 'tablet', strength: '20mg', unitPriceEgp: 175, category: 'PRESCRIPTION', therapeuticClass: 'CHOLESTEROL' },
  { id: 'melanogen-cream-20', label: 'Melanogen Cream', generic: 'Azelaic Acid 20%', form: 'cream', strength: '20%', unitPriceEgp: 210, category: 'COSMETIC', therapeuticClass: 'DERM_COSMETIC' },
  { id: 'montelast-10', label: 'Montelast 10', generic: 'Montelukast', form: 'tablet', strength: '10mg', unitPriceEgp: 165, category: 'PRESCRIPTION', therapeuticClass: 'RESPIRATORY' },
  { id: 'milanta-susp', label: 'Mylanta', generic: 'Aluminium + Magnesium Hydroxide', form: 'suspension', strength: '400mg/10ml', unitPriceEgp: 55, category: 'OTC', therapeuticClass: 'GI' },
  { id: 'nazo-clair-spray', label: 'Naso Clear', generic: 'Xylometazoline', form: 'nasal spray', strength: '0.1%', unitPriceEgp: 24, category: 'OTC', therapeuticClass: 'COLD_FLU' },
  { id: 'newro-b-500', label: 'Neuro-B', generic: 'B-Complex Vitamins', form: 'capsule', strength: '500mg', unitPriceEgp: 60, category: 'OTC', therapeuticClass: 'SUPPLEMENT' },
  { id: 'neksiom-40', label: 'Nexium 40', generic: 'Esomeprazole', form: 'tablet', strength: '40mg', unitPriceEgp: 235, category: 'PRESCRIPTION', therapeuticClass: 'GI' },
  { id: 'nizoral-cream-20', label: 'Nizoral 2%', generic: 'Ketoconazole', form: 'cream', strength: '20mg/g', unitPriceEgp: 130, category: 'OTC', therapeuticClass: 'DERM' },
  { id: 'norvask-5', label: 'Norvasc 5', generic: 'Amlodipine', form: 'tablet', strength: '5mg', unitPriceEgp: 96, category: 'PRESCRIPTION', therapeuticClass: 'CARDIO' },
  { id: 'omez-20', label: 'Omez 20', generic: 'Omeprazole', form: 'capsule', strength: '20mg', unitPriceEgp: 85, category: 'PRESCRIPTION', therapeuticClass: 'GI' },
  { id: 'otkol-syrup-100', label: 'Otcol', generic: 'Guaifenesin + Menthol', form: 'syrup', strength: '100mg/5ml', unitPriceEgp: 36, category: 'OTC', therapeuticClass: 'COUGH' },
  { id: 'otrivin-drops', label: 'Otrivin Nasal', generic: 'Xylometazoline', form: 'nasal drops', strength: '0.1%', unitPriceEgp: 28, category: 'OTC', therapeuticClass: 'COLD_FLU' },
  { id: 'panadol-caffrine-500', label: 'Panadol Caffrine', generic: 'Paracetamol + Caffeine', form: 'tablet', strength: '500mg', unitPriceEgp: 22, category: 'OTC', therapeuticClass: 'ANTIPYRETIC' },
  { id: 'panadol-extra-500', label: 'Panadol Extra', generic: 'Paracetamol 500mg', form: 'tablet', strength: '500mg', unitPriceEgp: 18, category: 'OTC', therapeuticClass: 'ANTIPYRETIC' },
  { id: 'paramol-500', label: 'Paramol', generic: 'Paracetamol 500mg', form: 'tablet', strength: '500mg', unitPriceEgp: 14, category: 'OTC', therapeuticClass: 'ANTIPYRETIC' },
  { id: 'renni-1000', label: 'Rennie', generic: 'Calcium Carbonate', form: 'chewable tablet', strength: '1000mg', unitPriceEgp: 30, category: 'OTC', therapeuticClass: 'GI' },
  { id: 'rovamycine-250', label: 'Rovamycine', generic: 'Spiramycin', form: 'tablet', strength: '250mg', unitPriceEgp: 95, category: 'PRESCRIPTION', therapeuticClass: 'ANTIBIOTIC' },
  { id: 'sensodain-toothpaste', label: 'Sensodyne Repair', generic: 'Sodium Fluoride + Potassium Nitrate', form: 'toothpaste', strength: '75ml', unitPriceEgp: 165, category: 'COSMETIC', therapeuticClass: 'ORAL_CARE' },
  { id: 'bactrim-800-160', label: 'Septran Forte', generic: 'Sulfamethoxazole + Trimethoprim', form: 'tablet', strength: '800/160mg', unitPriceEgp: 40, category: 'PRESCRIPTION', therapeuticClass: 'ANTIBIOTIC' },
  { id: 'signal-toothpaste-100', label: 'Signal 2', generic: 'Fluoride Toothpaste', form: 'toothpaste', strength: '100g', unitPriceEgp: 42, category: 'COSMETIC', therapeuticClass: 'ORAL_CARE' },
  { id: 'thermaqua-cream', label: 'Thermaqua Sensitive', generic: 'Centella + Niacinamide', form: 'facial cream', strength: '40ml', unitPriceEgp: 380, category: 'COSMETIC', therapeuticClass: 'DERM_COSMETIC' },
  { id: 'tramadol-50', label: 'Tramadol 50', generic: 'Tramadol', form: 'capsule', strength: '50mg', unitPriceEgp: 45, category: 'PRESCRIPTION', therapeuticClass: 'ANALGESIC' },
  { id: 'tritass-2-5', label: 'Tritace 2.5', generic: 'Ramipril', form: 'tablet', strength: '2.5mg', unitPriceEgp: 85, category: 'PRESCRIPTION', therapeuticClass: 'CARDIO' },
  { id: 'ventolin-inhaler-100', label: 'Ventolin Inhaler', generic: 'Salbutamol', form: 'inhaler', strength: '100mcg', unitPriceEgp: 145, category: 'PRESCRIPTION', therapeuticClass: 'RESPIRATORY' },
  { id: 'vitamin-c-500', label: 'Vitamin C 500', generic: 'Ascorbic Acid', form: 'effervescent tablet', strength: '500mg', unitPriceEgp: 18, category: 'OTC', therapeuticClass: 'VITAMIN' },
  { id: 'zithromax-500', label: 'Zithromax', generic: 'Azithromycin', form: 'tablet', strength: '500mg', unitPriceEgp: 210, category: 'PRESCRIPTION', therapeuticClass: 'ANTIBIOTIC' },
  { id: 'zyrtec-10', label: 'Zyrtec', generic: 'Cetirizine', form: 'tablet', strength: '10mg', unitPriceEgp: 35, category: 'OTC', therapeuticClass: 'ALLERGY' },

] as const;

/**
 * Synthetic pharmacy ids, `PH-001` through `PH-050`.
 *
 * These match the generator's registry exactly (verified against `orders`:
 * 50 pharmacies, ~198–752 orders each). The table also holds two one-row
 * fixtures, `PH-CAI-001` and `PHARM-001`, left over from the golden-set
 * matching tests — deliberately excluded, they have no history to plan from.
 */
export const PHARMACY_IDS: readonly string[] = Array.from(
  { length: 50 },
  (_, index) => `PH-${String(index + 1).padStart(3, '0')}`,
);

export const DEFAULT_PHARMACY_ID = PHARMACY_IDS[0] ?? 'PH-001';

/** Every catalogue id. */
export const ALL_PRODUCT_IDS: readonly string[] = CATALOGUE.map((product) => product.id);

/**
 * How many product ids one forecast request may carry.
 *
 * The backend validates `product_ids` with `max_length=50` and rejects anything
 * longer with a 422 — not a truncation, so asking for all 60 fails outright.
 */
export const MAX_PRODUCTS_PER_FORECAST = 50;

/**
 * The ids the inventory studio asks about.
 *
 * The studio therefore covers 50 of the 60 catalogue products per request.
 * `INVENTORY_UNREQUESTED_IDS` holds the remainder so the page can name them
 * rather than presenting a silently shortened catalogue as the whole one.
 */
export const FORECAST_REQUEST_IDS: readonly string[] = ALL_PRODUCT_IDS.slice(
  0,
  MAX_PRODUCTS_PER_FORECAST,
);

/** Catalogue products no forecast request covers. See `FORECAST_REQUEST_IDS`. */
export const INVENTORY_UNREQUESTED_IDS: readonly string[] = ALL_PRODUCT_IDS.slice(
  MAX_PRODUCTS_PER_FORECAST,
);

/** Product ids the studio opens on. */
export const DEFAULT_PRODUCT_IDS: readonly string[] = FORECAST_REQUEST_IDS.slice(0, 8);

/**
 * Look up a catalogue product by id.
 *
 * Used by the invoice to price a matched line, and by the correction picker to
 * resolve a catalogue id back to a product.
 */
export function findProduct(id: string | null | undefined): CatalogueProduct | undefined {
  if (!id) return undefined;
  return CATALOGUE.find((product) => product.id === id);
}

/**
 * Search the catalogue by any way a product might be named.
 *
 * Searches the trade name, the composed display name (`label` + `strength`),
 * the molecule, the form, the therapeutic class and the category. The composed
 * name is what the backend returns as `catalogue_name`, and the correction
 * picker pre-fills with it — so if that string is not searched, the modal opens
 * on "nothing matches" against the very product it is proposing.
 */
export function searchCatalogue(query: string): CatalogueProduct[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [...CATALOGUE];

  return CATALOGUE.filter((product) =>
    [
      product.label,
      displayName(product),
      product.generic,
      product.form,
      product.therapeuticClass,
      therapeuticLabel(product.therapeuticClass),
      CATEGORY_LABELS[product.category],
    ].some((field) => field.toLowerCase().includes(needle)),
  );
}