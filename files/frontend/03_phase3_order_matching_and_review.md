# Phase 3: Order Processing & Pharmacist Approvals

> **Objective**: Build the New Order page (`/orders/new`) with a friendly chat-style order entry and instant digital invoice generation, the Order History page (`/orders`), and the Pharmacist Approvals workbench (`/approvals`) with fast keyboard-driven verification. The AI matching engine works invisibly — the user sees clean invoices and simple "Please verify" flags.

---

## 1. Deliverables

### 1.1 New Order Page (`/orders/new`)

- [x] **Order Input Area** (`src/components/orders/OrderInput.tsx`):
  - Large, welcoming text area with placeholder: *"Type or paste a pharmacy order in Arabic or English..."*
  - **Preset Demo Buttons** (`src/components/orders/PresetButtons.tsx`):
    - "Clean English" → `"10 Panadol Extra 500mg, 5 Augmentin 625mg, 3 Brufen 400mg"`
    - "Arabic" → `"١٠ بانادول اكسترا و ٥ كونجستال اقراص و ٣ كتافلام"`
    - "Messy typing" → `"10 panadul xtra, 5 ogmentin 625, 2 catflam 50"`
    - "Mixed" → `"10 panadol extra w 5 congestal 3alashan el-bard"`
  - Blue **"Process Order"** button.

- [x] **Digital Invoice** (`src/components/orders/InvoiceTable.tsx`):
  - Appears after processing. Clean, professional invoice layout:
    | # | Item | Qty | Unit Price | Total | Status |
    |---|---|---|---|---|---|
    | 1 | Panadol Extra 500mg | 10 | 12.50 EGP | 125.00 EGP | ✅ Matched |
    | 2 | Augmentin 625mg | 5 | 45.00 EGP | 225.00 EGP | ✅ Matched |
    | 3 | "catflam 50" | 2 | — | — | 🟡 Please verify |
  - **Status column logic** (translated from backend confidence):
    - Confidence ≥ 0.70 → ✅ **Matched** (green).
    - Confidence 0.50–0.70 → ✅ Matched but shown subtly (no yellow unless truly ambiguous).
    - Confidence < 0.50 → 🟡 **Please verify** — shows a dropdown to select the correct drug.
  - **Order Total** row at bottom.
  - Green **"Confirm & Submit Order"** button.

- [x] **What the user does NOT see on this page**:
  - ❌ No "RapidFuzz" or "Gemini 2.0 Flash" badges.
  - ❌ No "Stage 1 / Stage 2" pipeline stepper.
  - ❌ No "Confidence: 0.73" decimal numbers.
  - ❌ No "Token set ratio" or "semantic re-ranking rationale".
  - The AI just works. Items are either matched or flagged for verification.

### 1.2 Order History Page (`/orders`)

- [x] **Orders Table** (`src/components/orders/OrderHistoryTable.tsx`):
  | Date | Order # | Pharmacy | Items | Total (EGP) | Status |
  |---|---|---|---|---|---|
  | Oct 18, 2026 | #1042 | PH-001 El-Ezaby | 5 items | 1,250 EGP | ✅ Completed |
  | Oct 18, 2026 | #1041 | PH-003 19011 | 3 items | 680 EGP | 🟡 1 pending review |
  - Click any row → full invoice detail view.
  - Filter by pharmacy, date range, or status.

### 1.3 Approvals Page (`/approvals`)

- [x] **Pending Counter**: "3 items need your review" (synced with sidebar badge).
- [x] **Approval Card** (`src/components/approvals/ApprovalCard.tsx`):
  - Clean card showing:
    - **What was ordered**: The raw text (e.g., *"catflam 50"*).
    - **AI's best guess**: "Cataflam 50mg — Diclofenac Potassium" with a small colored status dot (🟢🟡🔴) — no decimal confidence shown.
    - **From**: Order #, Pharmacy name, timestamp.
  - **3 Action Buttons**:
    - ✅ **Approve** (green) — confirms the suggestion → `PATCH /api/v1/orders/review-queue/{id}` with `action: 'accepted'`.
    - ✏️ **Correct** (blue) — opens drug search modal → records `action: 'corrected'`.
    - ❌ **Reject** (red) — dismisses the item → records `action: 'dismissed'`.
  - **Keyboard Shortcuts**: `A` (Approve), `C` (Correct), `D` (Reject), `↑/↓` (Navigate between items).

- [x] **Drug Search Modal** (`src/components/approvals/DrugSearchModal.tsx`):
  - Type-ahead search across the pharmaceutical catalogue.
  - Shows drug name, generic name, strength, and form.
  - Selecting a drug and confirming sends the correction to the backend.

- [x] **Approval History Tab** (`src/components/approvals/ApprovalHistory.tsx`):
  - Table of past reviewed items with the pharmacist's decision, timestamp, and audit trail.

---

## 2. Backend API Mapping

| User Action | API Call | What User Sees |
|---|---|---|
| Click "Process Order" | `POST /api/v1/match-order` | Digital invoice with ✅/🟡 status |
| Click "Confirm & Submit" | Order persisted in PostgreSQL | Success toast, redirect to history |
| Open Approvals page | `GET /api/v1/orders/review-queue` | List of pending items |
| Click Approve | `PATCH /api/v1/orders/review-queue/{id}` with `accepted` | Item removed, counter decrements |
| Click Correct | `PATCH /api/v1/orders/review-queue/{id}` with `corrected` | Item resolved with correct drug |
| Click Reject | `PATCH /api/v1/orders/review-queue/{id}` with `dismissed` | Item removed |

---

## 3. Implementation Steps

1. Build `OrderInput.tsx` with text area and preset buttons.
2. Build `InvoiceTable.tsx` translating backend confidence into ✅/🟡 status.
3. Build `PresetButtons.tsx` with 4 demo scenarios.
4. Assemble `NewOrderPage.tsx`.
5. Build `OrderHistoryTable.tsx` with filters.
6. Assemble `OrderHistoryPage.tsx`.
7. Build `ApprovalCard.tsx` with 3 action buttons and keyboard shortcut bindings.
8. Build `DrugSearchModal.tsx` with type-ahead catalogue search.
9. Build `ApprovalHistory.tsx` audit log.
10. Assemble `ApprovalsPage.tsx`.
11. Wire sidebar pending count badge to live review queue count.

---

## 4. Verification

**Success criteria**:
- Submitting an order shows a clean digital invoice within < 250ms.
- Items are labeled ✅ Matched or 🟡 Please verify — no confidence numbers or method badges visible.
- Approvals page allows rapid review with keyboard shortcuts (A/C/D).
- Sidebar badge decrements immediately when an item is approved.
- No mention of "RapidFuzz", "Gemini", "confidence score", or "match method" anywhere on screen.
