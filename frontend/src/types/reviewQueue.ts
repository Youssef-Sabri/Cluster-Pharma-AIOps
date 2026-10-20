/**
 * Pharmacist review queue types, mirroring the backend Pydantic schemas.
 *
 * ## Action names
 *
 * The backend's enum is `accept` / `correct` / `dismiss` — not
 * `accepted` / `corrected` / `dismissed`. The correction field is
 * `corrected_catalogue_id`, and `reviewed_by` is **required**.
 */

/**
 * A pharmacist's decision on one flagged line.
 *
 * `match_method` and `confidence` describe the matching engine and are never
 * rendered; they are typed because the API returns them.
 */
export interface ReviewQueueItem {
  /** Database id of the flagged order line. */
  item_id: string;
  /** Order the line belongs to. */
  order_id: string;
  /** Pharmacy that placed the order. */
  pharmacy_id: string;
  /** The original text fragment the matcher could not resolve confidently. */
  raw_token: string;
  /** Best candidate, which the matcher was not confident about. */
  proposed_catalogue_id: string | null;
  /** Display name of that candidate. */
  proposed_catalogue_name: string | null;
  /** Units requested on the line. */
  quantity: number | null;
  /** Matcher confidence, below the review threshold. Internal — not displayed. */
  confidence: number | null;
  /** Matching technique used. Internal — not displayed. */
  match_method: string | null;
  /** When the order was submitted. */
  order_created_at: string | null;
  /** When the line was flagged for review. */
  flagged_at: string | null;
  /** When a pharmacist resolved it. */
  reviewed_at: string | null;
  /** Who resolved it. */
  reviewed_by: string | null;
}

/** `GET /api/v1/orders/review-queue` response body. */
export interface ReviewQueueResponse {
  /** Flagged lines, oldest first. */
  items: ReviewQueueItem[];
  /** Number of items returned. */
  total: number;
  /** Total unresolved items, including any beyond `limit`. */
  pending_total: number;
}

/** The three decisions a pharmacist can make on a flagged line. */
export type ReviewAction = 'accept' | 'correct' | 'dismiss';

/** `PATCH /api/v1/orders/review-queue/{item_id}` request body. */
export interface ReviewActionRequest {
  action: ReviewAction;
  /** Required when `action` is `correct`; must be a known catalogue id. */
  corrected_catalogue_id?: string;
  /** Pharmacist or operator resolving the item. Recorded for the audit trail. */
  reviewed_by: string;
  /** Optional free-text rationale retained for the audit trail. */
  note?: string;
}

/** `PATCH /api/v1/orders/review-queue/{item_id}` response body. */
export interface ReviewActionResponse {
  item_id: string;
  action: ReviewAction;
  /** Final catalogue id, or null when dismissed. */
  catalogue_id: string | null;
  /** Display name of the final product. */
  catalogue_name: string | null;
  /** Always false after a successful review. */
  needs_review: boolean;
  reviewed_at: string;
  reviewed_by: string;
  note: string | null;
}
