/**
 * Money formatting for commercial documents.
 *
 * ## Why this exists alongside `procurement.formatEgp`
 *
 * The inventory studio quotes an *estimate* and rounds it to whole pounds — a
 * "you are about to spend roughly 5,382 EGP" figure reads fine and does not
 * need piastres. An invoice is different: it is a document whose line totals
 * must add up to its total, and half the catalogue is priced in piastres (Adol
 * 500 is 12.50 EGP). Rounding each line independently would make the arithmetic
 * on the printed document wrong, so invoice amounts are shown exactly and the
 * grand total is summed from unrounded values.
 */

/** Egyptian pounds, "EGP". */
export const EGP = 'EGP';

/**
 * Format an amount with up to two decimals, dropping trailing zeros.
 *
 * `12.5` renders as `12.50` on an invoice line — a price is conventionally shown
 * to two places — but `195` renders as `195`, because adding `.00` to a whole
 * number is noise.
 */
export function formatAmountEgp(value: number): string {
  return formatAmount(value);
}

/** Format an amount with no currency label. */
export function formatAmount(value: number): string {
  return value.toLocaleString('en-EG', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });
}

/** Format an amount with the currency, e.g. `12.50 EGP`. */
export function formatEgpPrecise(value: number): string {
  return `${formatAmount(value)} ${EGP}`;
}

/**
 * Sum amounts without intermediate rounding.
 *
 * Summing the *formatted* values would reintroduce the drift this module
 * exists to avoid, so the total is computed on the numbers themselves.
 */
export function sumEgp(values: readonly number[]): number {
  return values.reduce((total, value) => total + value, 0);
}
