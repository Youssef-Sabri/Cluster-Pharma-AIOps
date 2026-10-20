# Phase 3: Two-Stage Order Matching Engine (*Clara*-Style)

> **Objective**: Build a high-performance, two-stage pharmaceutical order parsing and matching engine capable of resolving messy text containing Egyptian drug brand names, generics, Arabic script, Franco-Arabic transliterations, and typos into structured catalogue records.

---

## 1. Deliverables Checklist

- [x] `backend/app/ml/order_matcher.py`:
  - Token extraction engine to parse quantities, units (e.g., "boxes", "strips", "علب"), and drug names from raw inputs.
  - **Stage 1 (rapidfuzz)**: In-memory fuzzy matcher utilizing `token_set_ratio` against multi-field catalogue representations (`brand_name`, `generic_name`, `arabic_name`, `franco_arabic`).
  - **Stage 2 (Gemini API Re-ranker)**: LLM re-ranker using `gemini-2.0-flash` invoked exclusively when Stage 1 confidence is $< 0.70$.
  - Safe offline fallback when `GEMINI_API_KEY` is not configured or rate limits are reached.
  - **Review Queue Classifier**: Items with final confidence $< 0.50$ tagged with `needs_review = True`.
- [x] Golden Benchmark Dataset (`backend/tests/golden_orders.json`):
  - 100+ realistic Egyptian order snippets with ground truth mappings covering:
    - Standard English ("10 Panadol Extra 500mg")
    - Typographical errors ("5 augmentn 625", "3 brufn 400")
    - Arabic script ("عشرة علب بنادول اكسترا وخمسة اوجمنتين")
    - Franco-Arabic ("2 banadol azra2 w 1 cataflam")
    - Generic vs Brand requests ("amoxicillin clavulanate" $\rightarrow$ "Augmentin")
- [x] Evaluation benchmark script reporting accuracy, p95 latency, and estimated LLM API cost per 1,000 orders.
- [x] Unit & benchmark tests in `backend/tests/test_match_order.py`.

---

## 2. Technical Specifications

### 2.1 Multi-Stage Pipeline Architecture
```
Raw Order Text: "10 panadol and 5 augmentn 625, 2 boxes brufen"
                         │
                         ▼
             Token Extraction Regex / Parser
             ├── Token 1: (qty=10, name="panadol")
             ├── Token 2: (qty=5,  name="augmentn 625")
             └── Token 3: (qty=2,  name="brufen")
                         │
                         ▼
        Stage 1: rapidfuzz token_set_ratio (<1ms)
        ├── Token 1 ──> Panadol 500mg (score: 95%) ──> ACCEPT (fuzzy)
        ├── Token 2 ──> Augmentin 625mg (score: 64%) ──> AMBIGUOUS (<70%)
        └── Token 3 ──> Brufen 400mg (score: 92%) ──> ACCEPT (fuzzy)
                         │
                         ▼
        Stage 2: Gemini 2.0 Flash Re-ranker
        (passes candidate list from Stage 1 to LLM)
        └── Token 2 ──> Augmentin 625mg (LLM confidence: 0.88) ──> ACCEPT (llm)
                         │
         Final Confidence Check (<0.50)
         └── If any item < 0.50 ──> Flag `needs_review = True`
```

### 2.2 Gemini API Re-Ranker Prompt
```python
PROMPT_TEMPLATE = """You are an expert Egyptian pharmaceutical inventory matcher.
Match the following raw pharmacy order token to the single most accurate item from the candidate catalogue list.

Raw token: "{token}"

Top candidates from catalogue:
{candidates_formatted}

Respond ONLY with valid JSON in this exact structure:
{{
  "catalogue_id": "<exact_id_from_candidates_or_null>",
  "confidence": <float_between_0.0_and_1.0>,
  "rationale": "<brief_explanation>"
}}
"""
```

### 2.3 Confidence Categorization
| Confidence Range | Match Method | Review Status | Action |
|---|---|---|---|
| $\ge 0.70$ | `fuzzy` | `needs_review = False` | Auto-accepted via rapidfuzz |
| $0.50 \le \text{conf} < 0.70$ | `llm` (or fuzzy fallback) | `needs_review = False` | Accepted via Gemini re-ranking |
| $< 0.50$ | `fuzzy` / `llm` | `needs_review = True` | Queued in database for pharmacist review |

---

## 3. Step-by-Step Implementation Instructions

1. **Implement Catalogue Cache**:
   In `backend/app/ml/order_matcher.py`, create a singleton `CatalogueMatcher` that loads the `drug_catalogue` records into memory for high-speed indexing.

2. **Build Tokenizer & Fuzzy Matcher**:
   Implement `extract_tokens(raw_text: str)` supporting both English digits and Arabic-Indic numerals ("١, ٢, ٣"). Implement `match_fuzzy(token: str)` returning the top 5 candidates scored via `rapidfuzz.fuzz.token_set_ratio`.

3. **Integrate Gemini Re-ranker**:
   Using `google.genai` SDK, initialize the client using `GEMINI_API_KEY`. If the key is absent or raises an API exception, log a warning and fall back to the top fuzzy candidate with confidence penalized by 20%.

4. **Construct Golden Test Set**:
   Create `backend/tests/golden_orders.json` with at least 100 diverse Egyptian test cases and expected outputs.

5. **Implement Comprehensive Tests**:
   Write `backend/tests/test_match_order.py` verifying:
   - Clean orders match with confidence $\ge 0.90$.
   - Common typos ("augmentn", "brufn", "banadol") match correctly.
   - Ambiguous queries flag `needs_review = True`.
   - Execution finishes well below the 500ms p95 latency ceiling.

---

## 4. Verification & Acceptance Criteria

```bash
# Run the order matcher test suite
pytest tests/test_match_order.py -v

# Run golden set evaluation benchmark
python -m app.ml.order_matcher --benchmark
```

**Success criteria**:
- Golden set accuracy achieves $\ge 85\%$ exact catalogue item resolution.
- Rapidfuzz stage resolves $\ge 70\%$ of standard orders in $< 5\text{ ms}$.
- Ambiguous items correctly invoke Gemini re-ranking when configured.
- Zero uncaught exceptions on malformed strings, emojis, or foreign inputs.
