"""Two-stage pharmaceutical order matcher (Clara-style).

Stage 1 resolves most order lines with **rapidfuzz** in microseconds.  Stage 2
re-ranks only the ambiguous remainder with the Gemini API, which keeps the LLM
cost per order low and the hot path dependency-free.

    raw text ──▶ extract_tokens ──▶ Stage 1 rapidfuzz ──▶ ≥0.70 ? accept : Stage 2 Gemini
                                                    │                                    │
                                                    └──────── <0.70 ────────────────────┘
                                                                                      │
                                                              final confidence <0.50 ──▶ needs_review

Confidence policy:

=========================  ==============  ==============  ==========================
Confidence                 match_method    needs_review   Outcome
=========================  ==============  ==============  ==========================
≥ 0.70                     ``fuzzy``       ``False``      auto-accepted by rapidfuzz
0.50 – 0.70                 ``llm`` / fuzzy ``False``      re-ranked, or degraded
< 0.50                      ``llm`` / fuzzy ``True``       queued for pharmacist review
=========================  ==============  ==============  ==========================

The human-in-the-loop rule is enforced in exactly one place
(:meth:`OrderMatcher._result`), so no caller can ship an unflagged low-confidence
item.

Synthetic data only.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Iterable, Sequence

from rapidfuzz import fuzz, process

from app.config import Settings, settings
from app.logging_config import configure_logging, get_logger
from app.ml.text_processing import OrderToken, extract_tokens, normalize, strip_stop_words

logger: Final[logging.Logger] = get_logger("ml.order_matcher")

# --- Thresholds (engineering rules) ---------------------------------------

#: Stage 1 auto-accept threshold.
FUZZY_ACCEPT_THRESHOLD: Final[float] = 0.70
#: Below this final confidence an item must be reviewed by a human.
REVIEW_CONFIDENCE_THRESHOLD: Final[float] = 0.50
#: Penalty applied when Stage 2 is unavailable (missing key, error, timeout).
FALLBACK_PENALTY: Final[float] = 0.20
#: Number of Stage 1 candidates handed to the re-ranker.
CANDIDATE_LIMIT: Final[int] = 5

#: Match methods written to ``order_items.match_method``.
METHOD_FUZZY: Final[str] = "fuzzy"
METHOD_LLM: Final[str] = "llm"

#: Stage that produced the accepted answer.
STAGE_FUZZY: Final[str] = "fuzzy"
STAGE_LLM: Final[str] = "llm"
STAGE_FALLBACK: Final[str] = "fallback"

# --- Gemini re-ranker ------------------------------------------------------

GEMINI_MODEL: Final[str] = settings.gemini_model

#: Prompt sent to Gemini.  The JSON contract is stated explicitly because the
#: response is parsed, not merely read.
PROMPT_TEMPLATE: Final[str] = """You are an expert Egyptian pharmaceutical inventory matcher.
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

#: Conservative Flash-class pricing for the benchmark's cost estimate.  The free
#: tier is $0; these are what a paid key would cost.
GEMINI_INPUT_COST_PER_MILLION_TOKENS: Final[float] = 0.075
GEMINI_OUTPUT_COST_PER_MILLION_TOKENS: Final[float] = 0.30
GEMINI_INPUT_TOKENS_PER_CALL: Final[int] = 250
GEMINI_OUTPUT_TOKENS_PER_CALL: Final[int] = 40

_JSON_BLOCK: Final[re.Pattern[str]] = re.compile(r"\{.*\}", re.DOTALL)


class CatalogueUnavailableError(RuntimeError):
    """Raised when the matcher has no catalogue to match against."""


#: Sentinel distinguishing "no reranker supplied" from "reranker=None" (offline).
_UNSET: Final[Any] = object()


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CatalogueEntry:
    """One searchable catalogue SKU."""

    catalogue_id: str
    brand_name: str
    generic_name: str | None
    arabic_name: str | None
    franco_arabic: str | None
    form: str | None
    strength: str | None
    category: str | None = None
    unit_price_egp: float | None = None

    @property
    def display_name(self) -> str:
        """Customer-facing name, e.g. ``Panadol Extra 500mg``."""
        return " ".join(part for part in (self.brand_name, self.strength) if part)

    @property
    def search_fields(self) -> tuple[str, ...]:
        """Normalised representations Stage 1 scores against.

        One entry per name the Egyptian market uses for the product: brand,
        brand+strength, generic, Arabic script and Franco-Arabic.
        """
        candidates = (
            self.brand_name,
            " ".join(part for part in (self.brand_name, self.strength) if part),
            self.generic_name or "",
            self.arabic_name or "",
            self.franco_arabic or "",
        )
        fields: list[str] = []
        for candidate in candidates:
            value = normalize(candidate)
            if value and value not in fields:
                fields.append(value)
        return tuple(fields)


@dataclass(frozen=True, slots=True)
class CatalogueCandidate:
    """A scored Stage 1 proposal."""

    catalogue_id: str
    display_name: str
    score: float
    """Similarity in ``[0, 1]`` (rapidfuzz score divided by 100)."""
    matched_field: str

    @property
    def is_confident(self) -> bool:
        """``True`` when Stage 1 clears the auto-accept threshold."""
        return self.score >= FUZZY_ACCEPT_THRESHOLD


class CatalogueMatcher:
    """In-memory catalogue index shared by every request.

    Every SKU's name fields are pre-loaded once, so Stage 1 is a pure in-memory
    lookup with no database round-trip on the hot path.
    """

    __slots__ = ("_entries", "_by_id", "_choices", "_owner")

    def __init__(self, entries: Iterable[CatalogueEntry]) -> None:
        entry_list = tuple(entries)
        if not entry_list:
            raise CatalogueUnavailableError("catalogue is empty; seed the database first")
        self._entries: Final[tuple[CatalogueEntry, ...]] = entry_list
        self._by_id: Final[dict[str, CatalogueEntry]] = {entry.catalogue_id: entry for entry in entry_list}
        # One searchable string per (SKU, name field), with a parallel owner
        # index so a hit can be attributed back to its SKU.
        self._choices: Final[tuple[str, ...]] = tuple(
            search_field for entry in entry_list for search_field in entry.search_fields
        )
        self._owner: Final[tuple[str, ...]] = tuple(
            entry.catalogue_id for entry in entry_list for _ in entry.search_fields
        )

    # -- construction ------------------------------------------------------
    @classmethod
    def from_drug_specs(cls, specs: Iterable[Any]) -> "CatalogueMatcher":
        """Build from the Phase 1 curated catalogue (no database required)."""
        return cls(
            CatalogueEntry(
                catalogue_id=spec.catalogue_id,
                brand_name=spec.brand_name,
                generic_name=spec.generic_name,
                arabic_name=spec.arabic_name,
                franco_arabic=spec.franco_arabic,
                form=spec.form,
                strength=spec.strength,
                category=spec.category,
                unit_price_egp=spec.unit_price_egp,
            )
            for spec in specs
        )

    @classmethod
    async def from_database(cls, session: Any) -> "CatalogueMatcher":
        """Load every row of ``drug_catalogue`` (production serving path)."""
        from sqlalchemy import select

        from app.models import DrugCatalogue

        rows = (
            await session.execute(
                select(
                    DrugCatalogue.catalogue_id,
                    DrugCatalogue.brand_name,
                    DrugCatalogue.generic_name,
                    DrugCatalogue.arabic_name,
                    DrugCatalogue.franco_arabic,
                    DrugCatalogue.form,
                    DrugCatalogue.strength,
                    DrugCatalogue.category,
                    DrugCatalogue.unit_price_egp,
                )
            )
        ).all()
        logger.info("Catalogue loaded", extra={"entries": len(rows)})
        return cls(CatalogueEntry(*row) for row in rows)

    # -- accessors ---------------------------------------------------------
    @property
    def entries(self) -> tuple[CatalogueEntry, ...]:
        """Every catalogue entry."""
        return self._entries

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, catalogue_id: str) -> CatalogueEntry | None:
        """Look an entry up by id."""
        return self._by_id.get(catalogue_id)

    def display_name(self, catalogue_id: str) -> str:
        """Human-readable name for an id (falls back to the id itself)."""
        entry = self._by_id.get(catalogue_id)
        return entry.display_name if entry else catalogue_id

    # -- Stage 1 -----------------------------------------------------------
    def score(self, token: str, limit: int = CANDIDATE_LIMIT) -> tuple[CatalogueCandidate, ...]:
        """Return the ``limit`` best candidates for ``token``.

        Uses ``fuzz.token_set_ratio`` over every name field; the best field per
        SKU wins, so a product mentioned by any of its spellings can surface.
        """
        query = self._normalize_query(token)
        if not query:
            return ()

        # Over-fetch, then aggregate by SKU: one SKU can hit several of its own
        # fields, which would otherwise crowd out the candidate list.
        hits = process.extract(
            query,
            self._choices,
            scorer=fuzz.token_set_ratio,
            limit=limit * 4,
            score_cutoff=0,
        )
        best: dict[str, CatalogueCandidate] = {}
        for choice, score, index in hits:
            catalogue_id = self._owner[index]
            ratio = score / 100.0
            current = best.get(catalogue_id)
            if current is None or ratio > current.score:
                best[catalogue_id] = CatalogueCandidate(
                    catalogue_id=catalogue_id,
                    display_name=self.display_name(catalogue_id),
                    score=ratio,
                    matched_field=choice,
                )
        return tuple(sorted(best.values(), key=lambda candidate: candidate.score, reverse=True)[:limit])

    @staticmethod
    def _normalize_query(token: str) -> str:
        """Normalise a raw token into the query form used for scoring."""
        if not token:
            return ""
        return strip_stop_words(token) or normalize(token)


# ---------------------------------------------------------------------------
# Catalogue singleton
# ---------------------------------------------------------------------------

_CATALOGUE_MATCHER: CatalogueMatcher | None = None


def get_catalogue_matcher() -> CatalogueMatcher:
    """Return the process-wide catalogue index, building it on first use.

    Defaults to the curated Phase 1 catalogue so the matcher works without a
    database; :func:`load_catalogue_from_database` refreshes it in production.
    """
    global _CATALOGUE_MATCHER
    if _CATALOGUE_MATCHER is None:
        from app.pipelines.data_generator import CURATED_DRUGS

        _CATALOGUE_MATCHER = CatalogueMatcher.from_drug_specs(CURATED_DRUGS)
        logger.info("Catalogue matcher initialised", extra={"entries": len(_CATALOGUE_MATCHER)})
    return _CATALOGUE_MATCHER


def set_catalogue_matcher(matcher: CatalogueMatcher | None) -> None:
    """Override (or clear, with ``None``) the process-wide catalogue index."""
    global _CATALOGUE_MATCHER
    _CATALOGUE_MATCHER = matcher


async def load_catalogue_from_database(session: Any) -> CatalogueMatcher:
    """Reload the catalogue index from PostgreSQL and install it."""
    matcher = await CatalogueMatcher.from_database(session)
    set_catalogue_matcher(matcher)
    return matcher


# ---------------------------------------------------------------------------
# Stage 2 — Gemini re-ranker
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LlmVerdict:
    """A parsed, validated re-ranking decision from the LLM."""

    catalogue_id: str | None
    confidence: float
    rationale: str


class GeminiReRanker:
    """Thin, defensive wrapper around the Gemini re-ranking call.

    The matcher never has to care whether the API is available: every failure
    mode — missing key, network error, rate limit, malformed JSON, hallucinated
    id — resolves to ``None``, which sends the caller to the fuzzy fallback.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = GEMINI_MODEL,
        db_settings: Settings | None = None,
    ) -> None:
        db_settings = db_settings or settings
        self.model = model
        self._api_key = api_key if api_key is not None else db_settings.gemini_api_key
        self._client: Any | None = None
        self.call_count = 0
        self.failure_count = 0

    @property
    def available(self) -> bool:
        """``True`` when an API key is configured (the client is lazy)."""
        return bool(self._api_key)

    def _get_client(self) -> Any | None:
        if self._client is not None:
            return self._client
        if not self.available:
            return None
        try:
            from google import genai

            self._client = genai.Client(api_key=self._api_key)
        except Exception as exc:  # noqa: BLE001 - SDK import/config must never propagate
            logger.warning("Gemini client unavailable; using fuzzy fallback", extra={"error": str(exc)})
            self._client = None
        return self._client

    def rerank(self, token: str, candidates: Sequence[CatalogueCandidate]) -> LlmVerdict | None:
        """Ask Gemini to choose between ``candidates``.

        Returns ``None`` on any problem.  The LLM may only return an id that was
        offered to it — a hallucinated id is discarded and the confidence capped
        into the review band.
        """
        client = self._get_client()
        if client is None or not candidates:
            return None

        prompt = PROMPT_TEMPLATE.format(
            token=token.strip(),
            candidates_formatted=self._format_candidates(candidates),
        )
        self.call_count += 1
        try:
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config={"response_mime_type": "application/json", "temperature": 0.0},
            )
            verdict = self._parse_verdict(getattr(response, "text", "") or "", candidates)
        except Exception as exc:  # noqa: BLE001 - degraded mode is the contract
            self.failure_count += 1
            logger.warning(
                "Gemini re-ranking failed; falling back to rapidfuzz",
                extra={"error": str(exc), "token": token[:60]},
            )
            return None

        if verdict is None:
            self.failure_count += 1
        return verdict

    @staticmethod
    def _format_candidates(candidates: Sequence[CatalogueCandidate]) -> str:
        return "\n".join(
            f"- catalogue_id={candidate.catalogue_id} | name={candidate.display_name} "
            f"| fuzzy_score={candidate.score:.2f}"
            for candidate in candidates
        )

    @staticmethod
    def _parse_verdict(
        raw_text: str, candidates: Sequence[CatalogueCandidate]
    ) -> LlmVerdict | None:
        """Parse the model's JSON reply defensively."""
        block = _JSON_BLOCK.search(raw_text or "")
        if block is None:
            return None
        try:
            payload = json.loads(block.group(0))
        except json.JSONDecodeError:
            logger.warning("Gemini returned unparseable JSON", extra={"response": raw_text[:120]})
            return None
        if not isinstance(payload, dict):
            return None

        catalogue_id = payload.get("catalogue_id")
        try:
            confidence = float(payload.get("confidence"))
        except (TypeError, ValueError):
            return None
        if not 0.0 <= confidence <= 1.0:
            return None

        if catalogue_id is not None and catalogue_id not in {c.catalogue_id for c in candidates}:
            # The model invented an id — refuse it rather than matching a product
            # that was never offered.
            logger.warning(
                "Gemini returned a candidate outside the offered list",
                extra={"catalogue_id": catalogue_id},
            )
            catalogue_id = None
            confidence = min(confidence, REVIEW_CONFIDENCE_THRESHOLD)

        return LlmVerdict(
            catalogue_id=catalogue_id,
            confidence=confidence,
            rationale=str(payload.get("rationale", ""))[:200],
        )


# ---------------------------------------------------------------------------
# Matcher
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MatchResult:
    """The outcome of matching one order line."""

    raw_token: str
    catalogue_id: str | None
    catalogue_name: str | None
    quantity: int
    confidence: float
    match_method: str
    needs_review: bool
    stage: str
    rationale: str = ""
    unit: str | None = None
    modifiers: tuple[str, ...] = ()
    fuzzy_score: float = 0.0
    fuzzy_candidates: tuple[CatalogueCandidate, ...] = ()
    latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialisable summary for logs, benchmarks and API responses."""
        return {
            "raw_token": self.raw_token,
            "catalogue_id": self.catalogue_id,
            "catalogue_name": self.catalogue_name,
            "quantity": self.quantity,
            "unit": self.unit,
            "confidence": round(self.confidence, 4),
            "match_method": self.match_method,
            "needs_review": self.needs_review,
            "stage": self.stage,
            "rationale": self.rationale,
            "fuzzy_score": round(self.fuzzy_score, 4),
            "latency_ms": round(self.latency_ms, 4),
        }


class OrderMatcher:
    """Two-stage matcher: rapidfuzz first, Gemini only for the ambiguous tail.

    Parameters
    ----------
    catalogue:
        Index to match against; defaults to the process-wide singleton.
    reranker:
        Stage 2 implementation.  Defaults to a :class:`GeminiReRanker`; pass
        ``None`` to disable Stage 2 entirely (fully offline operation).
    """

    def __init__(
        self,
        catalogue: CatalogueMatcher | None = None,
        reranker: Any = _UNSET,
    ) -> None:
        self.catalogue = catalogue or get_catalogue_matcher()
        # ``reranker=None`` disables Stage 2; omitting it enables the default
        # Gemini re-ranker (which self-disables when no API key is configured).
        self.reranker: Any = GeminiReRanker() if reranker is _UNSET else reranker
        self.llm_call_count = 0
        self.llm_failure_count = 0

    # -- public API --------------------------------------------------------
    def match_text(self, raw_text: str) -> list[MatchResult]:
        """Parse and match every line of a raw order.

        Never raises: malformed, empty or emoji-only input yields an empty list,
        because one bad line must not take down the request.
        """
        try:
            tokens = extract_tokens(raw_text)
        except Exception as exc:  # noqa: BLE001 - parsing must never break an order
            logger.warning("Token extraction failed", exc_info=True, extra={"error": str(exc)})
            return []
        return [self.match_token(token) for token in tokens]

    def match_token(self, token: OrderToken | str, quantity: int = 1) -> MatchResult:
        """Match one order line: Stage 1, then Stage 2 only if Stage 1 is unsure."""
        started = time.perf_counter()
        parsed = (
            OrderToken(quantity=quantity, unit=None, raw_token=token, original=token)
            if isinstance(token, str)
            else token
        )

        candidates = self.catalogue.score(parsed.raw_token)
        if not candidates:
            return MatchResult(
                raw_token=parsed.raw_token,
                catalogue_id=None,
                catalogue_name=None,
                quantity=parsed.quantity,
                confidence=0.0,
                match_method=METHOD_FUZZY,
                needs_review=True,
                stage=STAGE_FALLBACK,
                rationale="no catalogue candidate could be scored",
                unit=parsed.unit,
                modifiers=parsed.modifiers,
                latency_ms=round((time.perf_counter() - started) * 1000.0, 4),
            )

        best = candidates[0]
        rationale = f"rapidfuzz token_set_ratio={best.score:.2f} on '{best.matched_field}'"

        # ---- Stage 1: confident match ------------------------------------
        if best.score >= FUZZY_ACCEPT_THRESHOLD:
            return self._result(
                parsed,
                best.catalogue_id,
                confidence=best.score,
                method=METHOD_FUZZY,
                stage=STAGE_FUZZY,
                rationale=rationale,
                candidates=candidates,
                fuzzy_score=best.score,
                started=started,
            )

        # ---- Stage 2: LLM re-rank ----------------------------------------
        verdict = self._rerank(parsed.raw_token, candidates)
        if verdict is not None and verdict.catalogue_id is not None:
            return self._result(
                parsed,
                verdict.catalogue_id,
                confidence=verdict.confidence,
                method=METHOD_LLM,
                stage=STAGE_LLM,
                rationale=verdict.rationale or "accepted by Gemini re-ranking",
                candidates=candidates,
                fuzzy_score=best.score,
                started=started,
            )

        # ---- Degraded / offline fallback ---------------------------------
        # Stage 2 could not improve on a line rapidfuzz found weak, so the fuzzy
        # answer is used with a 20% penalty rather than trusted.
        penalised = max(0.0, best.score * (1.0 - FALLBACK_PENALTY))
        logger.info(
            "Fuzzy fallback applied",
            extra={"token": parsed.raw_token[:60], "score": round(best.score, 3)},
        )
        return self._result(
            parsed,
            best.catalogue_id,
            confidence=penalised,
            method=METHOD_FUZZY,
            stage=STAGE_FALLBACK,
            rationale=f"{rationale}; Stage 2 unavailable, {FALLBACK_PENALTY:.0%} penalty applied",
            candidates=candidates,
            fuzzy_score=best.score,
            started=started,
        )

    # -- internals ---------------------------------------------------------
    def _rerank(self, token: str, candidates: Sequence[CatalogueCandidate]) -> LlmVerdict | None:
        """Invoke Stage 2 when configured, counting the outcome."""
        if self.reranker is None or not getattr(self.reranker, "available", False):
            return None
        try:
            verdict = self.reranker.rerank(token, candidates)
        except Exception as exc:  # noqa: BLE001 - a bad API call must not fail the order
            self.llm_failure_count += 1
            logger.warning("Re-ranker raised; using fuzzy fallback", extra={"error": str(exc)})
            return None
        if verdict is None:
            self.llm_failure_count += 1
            return None
        self.llm_call_count += 1
        return verdict

    def _result(
        self,
        token: OrderToken,
        catalogue_id: str,
        *,
        confidence: float,
        method: str,
        stage: str,
        rationale: str,
        candidates: Sequence[CatalogueCandidate],
        fuzzy_score: float,
        started: float,
    ) -> MatchResult:
        """Build the result and apply the human-in-the-loop rule.

        Single place where the safety rule lives: anything below
        :data:`REVIEW_CONFIDENCE_THRESHOLD` is flagged for a pharmacist.
        """
        return MatchResult(
            raw_token=token.raw_token,
            catalogue_id=catalogue_id,
            catalogue_name=self.catalogue.display_name(catalogue_id),
            quantity=token.quantity,
            confidence=round(float(confidence), 4),
            match_method=method,
            needs_review=confidence < REVIEW_CONFIDENCE_THRESHOLD,
            stage=stage,
            rationale=rationale,
            unit=token.unit,
            modifiers=token.modifiers,
            fuzzy_score=round(fuzzy_score, 4),
            fuzzy_candidates=tuple(candidates),
            latency_ms=round((time.perf_counter() - started) * 1000.0, 4),
        )


# ---------------------------------------------------------------------------
# Golden-set benchmark
# ---------------------------------------------------------------------------

DEFAULT_GOLDEN_PATH: Final[Path] = Path(__file__).resolve().parents[2] / "tests" / "golden_orders.json"

#: Acceptance target from the phase specification.
MINIMUM_GOLDEN_ACCURACY: Final[float] = 0.85


@dataclass(frozen=True, slots=True)
class GoldenCase:
    """One benchmark case: raw text and the expected catalogue ids."""

    raw_text: str
    expected_catalogue_id: str
    category: str = "unspecified"
    notes: str = ""
    expected_catalogue_ids: tuple[str, ...] = ()

    @property
    def expected_ids(self) -> list[str]:
        """Every catalogue id this case is expected to resolve to."""
        return list(self.expected_catalogue_ids) or [self.expected_catalogue_id]


@dataclass(slots=True)
class BenchmarkReport:
    """Outcome of evaluating the matcher against the golden set."""

    total_cases: int
    correct: int
    accuracy: float
    resolved_by_fuzzy: int
    fuzzy_share: float
    needing_llm: int
    needing_review: int
    latency_ms_p50: float
    latency_ms_p95: float
    latency_ms_max: float
    per_category: dict[str, dict[str, Any]] = field(default_factory=dict)
    llm_calls: int = 0
    estimated_cost_per_1000_orders: float = 0.0
    failures: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_cases": self.total_cases,
            "correct": self.correct,
            "accuracy": round(self.accuracy, 4),
            "resolved_by_fuzzy": self.resolved_by_fuzzy,
            "fuzzy_share": round(self.fuzzy_share, 4),
            "needing_llm": self.needing_llm,
            "needing_review": self.needing_review,
            "latency_ms": {
                "p50": round(self.latency_ms_p50, 4),
                "p95": round(self.latency_ms_p95, 4),
                "max": round(self.latency_ms_max, 4),
            },
            "llm_calls": self.llm_calls,
            "estimated_cost_per_1000_orders_usd": round(self.estimated_cost_per_1000_orders, 6),
            "per_category": self.per_category,
            "failures": self.failures[:20],
        }


def load_golden_cases(path: Path | str = DEFAULT_GOLDEN_PATH) -> list[GoldenCase]:
    """Load the golden benchmark set from JSON."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    raw_cases = payload["cases"] if isinstance(payload, dict) else payload
    return [
        GoldenCase(
            raw_text=case["raw_text"],
            expected_catalogue_id=case["expected_catalogue_id"],
            category=case.get("category", "unspecified"),
            notes=case.get("notes", ""),
            expected_catalogue_ids=tuple(case.get("expected_catalogue_ids", ())),
        )
        for case in raw_cases
    ]


def percentile(values: Sequence[float], fraction: float) -> float:
    """Nearest-rank percentile, used for the p50/p95 latency figures."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


def run_benchmark(matcher: OrderMatcher, cases: Sequence[GoldenCase]) -> BenchmarkReport:
    """Evaluate ``matcher`` on ``cases``.

    A case counts as correct when every extracted line resolves to the expected
    catalogue id, mirroring how an order is actually fulfilled.
    """
    correct = 0
    resolved_by_fuzzy = 0
    needing_llm = 0
    needing_review = 0
    latencies: list[float] = []
    per_category: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []

    for case in cases:
        results = matcher.match_text(case.raw_text)
        latencies.extend(result.latency_ms for result in results)

        expected_ids = case.expected_ids
        actual_ids = [result.catalogue_id for result in results]
        is_correct = bool(results) and actual_ids == expected_ids

        bucket = per_category.setdefault(
            case.category, {"total": 0, "correct": 0, "fuzzy_resolved": 0, "review_flagged": 0}
        )
        bucket["total"] += 1
        if is_correct:
            correct += 1
            bucket["correct"] += 1

        for result in results:
            if result.stage == STAGE_FUZZY:
                resolved_by_fuzzy += 1
                bucket["fuzzy_resolved"] += 1
            elif result.stage == STAGE_LLM:
                needing_llm += 1
            if result.needs_review:
                needing_review += 1
                bucket["review_flagged"] += 1

        if not is_correct:
            failures.append(
                {
                    "raw_text": case.raw_text,
                    "expected": expected_ids,
                    "actual": actual_ids,
                    "confidences": [result.confidence for result in results],
                    "category": case.category,
                }
            )

    total = len(cases)
    re_rank_rate = needing_llm / max(1, total)
    cost_per_1000 = (
        re_rank_rate
        * 1000.0
        / 1_000_000.0
        * (
            GEMINI_INPUT_TOKENS_PER_CALL * GEMINI_INPUT_COST_PER_MILLION_TOKENS
            + GEMINI_OUTPUT_TOKENS_PER_CALL * GEMINI_OUTPUT_COST_PER_MILLION_TOKENS
        )
    )

    return BenchmarkReport(
        total_cases=total,
        correct=correct,
        accuracy=correct / total if total else 0.0,
        resolved_by_fuzzy=resolved_by_fuzzy,
        fuzzy_share=resolved_by_fuzzy / max(1, resolved_by_fuzzy + needing_llm),
        needing_llm=needing_llm,
        needing_review=needing_review,
        latency_ms_p50=percentile(latencies, 0.50),
        latency_ms_p95=percentile(latencies, 0.95),
        latency_ms_max=max(latencies) if latencies else 0.0,
        per_category=per_category,
        llm_calls=matcher.llm_call_count,
        estimated_cost_per_1000_orders=cost_per_1000,
        failures=failures,
    )


def format_benchmark(report: BenchmarkReport) -> str:
    """Render the benchmark report for the console."""
    lines = [
        "",
        "=" * 74,
        " ClusterOps — order matching benchmark (synthetic data, demonstration only)",
        "=" * 74,
        f" Cases                    : {report.total_cases}",
        f" Exact catalogue accuracy : {report.accuracy:.2%} "
        f"({report.correct}/{report.total_cases}, target >= {MINIMUM_GOLDEN_ACCURACY:.0%})",
        f" Resolved by rapidfuzz    : {report.resolved_by_fuzzy} ({report.fuzzy_share:.1%} of decided lines)",
        f" Sent to Gemini re-ranker: {report.needing_llm}",
        f" Flagged needs_review     : {report.needing_review}",
        f" Latency per line (ms)    : p50 {report.latency_ms_p50:.3f} | p95 {report.latency_ms_p95:.3f} "
        f"| max {report.latency_ms_max:.3f}",
        f" LLM calls made           : {report.llm_calls}",
        f" Est. LLM cost / 1,000    : ${report.estimated_cost_per_1000_orders:.4f} (free tier: $0.00)",
        "-" * 74,
        " Accuracy by category:",
    ]
    for category, stats in sorted(report.per_category.items()):
        accuracy = stats["correct"] / stats["total"] if stats["total"] else 0.0
        lines.append(
            f"   {category:<22} {accuracy:>6.1%}  ({stats['correct']}/{stats['total']}) "
            f"fuzzy={stats['fuzzy_resolved']} review={stats['review_flagged']}"
        )
    if report.failures:
        lines.append("-" * 74)
        lines.append(f" Misses (first {min(10, len(report.failures))}):")
        for failure in report.failures[:10]:
            lines.append(
                f"   {failure['raw_text'][:42]!r:<46} expected={failure['expected']} got={failure['actual']}"
            )
    lines.extend(["=" * 74, ""])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the ``python -m app.ml.order_matcher`` argument parser."""
    parser = argparse.ArgumentParser(
        prog="python -m app.ml.order_matcher",
        description="Match Egyptian pharmacy orders against the catalogue. Synthetic data only.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--benchmark", action="store_true", help="Run the golden-set benchmark and exit.")
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN_PATH, help="Golden-set JSON path.")
    parser.add_argument("--text", default=None, help="Match this raw order text and print the result.")
    parser.add_argument(
        "--no-llm", action="store_true", help="Disable Stage 2 entirely (fully offline fuzzy matching)."
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--quiet", action="store_true", help="Only log warnings and errors.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point.  Returns a process exit code."""
    args = build_parser().parse_args(argv)
    configure_logging()
    logger.setLevel(logging.WARNING if args.quiet else logging.INFO)

    matcher = OrderMatcher(reranker=None if args.no_llm else GeminiReRanker())

    if args.text is not None:
        results = matcher.match_text(args.text)
        if args.json:
            print(json.dumps([result.to_dict() for result in results], indent=2, ensure_ascii=False))
        else:
            print(f"\n{args.text!r} ->")
            for result in results:
                print(
                    f"  {result.quantity:>3} x {str(result.catalogue_name or 'UNMATCHED'):<34} "
                    f"conf={result.confidence:.2f} method={result.match_method:<5} "
                    f"review={result.needs_review} stage={result.stage}"
                )
            if not results:
                print("  (no product lines detected)")
            print()
        return 0

    if not args.benchmark:
        build_parser().print_help()
        return 0

    if not args.golden.exists():
        print(f"error: golden set not found at {args.golden}", file=sys.stderr)
        return 2

    report = run_benchmark(matcher, load_golden_cases(args.golden))
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(format_benchmark(report))
    # Exit 1 below target so CI can gate on it; the report is still printed.
    return 0 if report.accuracy >= MINIMUM_GOLDEN_ACCURACY else 1


__all__ = [
    "CANDIDATE_LIMIT",
    "DEFAULT_GOLDEN_PATH",
    "FALLBACK_PENALTY",
    "FUZZY_ACCEPT_THRESHOLD",
    "GEMINI_MODEL",
    "METHOD_FUZZY",
    "METHOD_LLM",
    "MINIMUM_GOLDEN_ACCURACY",
    "PROMPT_TEMPLATE",
    "REVIEW_CONFIDENCE_THRESHOLD",
    "STAGE_FALLBACK",
    "STAGE_FUZZY",
    "STAGE_LLM",
    "BenchmarkReport",
    "CatalogueCandidate",
    "CatalogueEntry",
    "CatalogueMatcher",
    "CatalogueUnavailableError",
    "GoldenCase",
    "GeminiReRanker",
    "LlmVerdict",
    "MatchResult",
    "OrderMatcher",
    "build_parser",
    "format_benchmark",
    "get_catalogue_matcher",
    "load_catalogue_from_database",
    "load_golden_cases",
    "main",
    "percentile",
    "run_benchmark",
    "set_catalogue_matcher",
]


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())