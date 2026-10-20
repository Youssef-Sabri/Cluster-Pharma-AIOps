/**
 * Order matching types, mirroring the backend Pydantic schemas.
 *
 * ## Field names
 *
 * These mirror `backend/app/schemas/match_order.py` exactly. Note that the
 * request field is `raw_text` (not `text`), the response fields are
 * `catalogue_id` / `catalogue_name` (not `matched_product_id` / `product_name`),
 * and the flags are `needs_review` (not `requires_review`).
 */

/** `POST /api/v1/match-order` request body. */
export interface MatchOrderRequest {
  /**
   * The order as the customer wrote it.
   *
   * Mixing scripts and separators is expected and supported — that is the point
   * of the matcher.
   */
  raw_text: string;
  /** Pharmacy placing the order. */
  pharmacy_id: string;
  /**
   * Write the order and its items to PostgreSQL.
   *
   * `false` performs a dry run: the order is matched and priced but nothing is
   * stored, which is what the invoice preview uses.
   */
  persist?: boolean;
}

/**
 * One matched line of an order.
 *
 * `match_method`, `stage` and `rationale` describe the matching engine and are
 * deliberately **never rendered** — they name internal techniques and, in the
 * case of `rationale`, contain implementation detail. They are typed here
 * because the API returns them, and the UI simply does not use them.
 */
export interface MatchedItem {
  /** The fragment of the order that produced this line. */
  raw_token: string;
  /** Resolved catalogue id, or null when unmatched. */
  catalogue_id: string | null;
  /** Display name of the resolved product. */
  catalogue_name: string | null;
  /** Units requested on this line. */
  quantity: number;
  /** Pack unit when the text named one (boxes, strips, sachets). */
  unit: string | null;
  /** Matcher confidence. Below 0.50 the line is queued for review. */
  confidence: number;
  /** Matching technique used. Internal — not displayed. */
  match_method: 'fuzzy' | 'llm';
  /** Pipeline stage that decided the line. Internal — not displayed. */
  stage: string;
  /** True when the line needs a pharmacist's decision. */
  needs_review: boolean;
  /** Why the matcher chose this product. Internal — not displayed. */
  rationale: string;
  /** Database id of the persisted `order_items` row, when persisted. */
  item_id: string | null;
}

/** `POST /api/v1/match-order` response body. */
export interface MatchOrderResponse {
  /** Database id of the persisted order, or null for a dry run. */
  order_id: string | null;
  pharmacy_id: string;
  items: MatchedItem[];
  /** Quantity-weighted mean confidence across the matched lines. */
  overall_confidence: number;
  /** Count of lines flagged for review. */
  items_needing_review: number;
  /** Total units across all matched lines. */
  total_units: number;
  /** Whether the order was written to PostgreSQL. */
  persisted: boolean;
  matched_at: string;
}
