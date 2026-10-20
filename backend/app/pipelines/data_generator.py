"""Synthetic Egyptian pharmaceutical dataset generator (ClusterOps, Phase 1).

**All data produced by this module is 100% synthetic and exists purely for
demonstration purposes.** Prices, pharmacy identities, order volumes, customer
behaviour and every timestamp are invented by this script. The only real-world
inputs are the *public* trade names of medicines commonly listed in the Egyptian
market (Panadol, Augmentin, Brufen, ...) and the names of Egyptian governorates,
which are used so that fuzzy order matching and seasonal modelling are exercised
against realistic text. No real pharmacy, order, prescriber, or commercial data
is stored, hardcoded, or claimed anywhere in this project.

What it generates
-----------------
1. **Catalogue** — 50+ SKUs with brand / generic / Arabic / Franco-Arabic
   (transliterated) names, dosage form, strength and EGP unit price.
2. **Pharmacies** — 50 synthetic pharmacies distributed across Egyptian
   governorates and segmented into ``SMALL`` / ``MEDIUM`` / ``LARGE`` tiers.
3. **Orders** — ``--days`` of restock history (default 180) built from a
   Negative-Binomial demand process modulated by:
   * day-of-week seasonality (Egyptian weekend: Friday ``0.45``, Saturday ``0.70``),
   * seasonal flu pressure in winter,
   * Egyptian public holidays, Ramadan / Eid patterns (Hijri calendar computed
     in-process, no extra dependency),
   * a slow growth trend,
   * per-pharmacy **standing baskets** — a stable set of staples restocked
     nearly every day, which is what gives the panel continuous series,
   * an optional **demand shock** that multiplies antibiotic + antipyretic
     volume by ``3x-4x`` for drift-detection testing.
4. **Baseline** — the naive *same day last week* forecaster, evaluated on a
   strictly chronological holdout (last 20% of days) and printed to the console
   so that later phases can prove LightGBM beats it.

CLI
---
::

    python -m app.pipelines.data_generator --seed --days 180
    python -m app.pipelines.data_generator --demand-shock --seed
    python -m app.pipelines.data_generator --days 30            # dry run, no DB
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import sys
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
from sqlalchemy import delete, func as sa_func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database import async_session_factory
from app.logging_config import configure_logging, get_logger
from app.models import DrugCatalogue, DriftLog, Order, OrderItem, Prediction
from app.models.drug_catalogue import CATEGORY_COSMETIC, CATEGORY_OTC, CATEGORY_PRESCRIPTION

logger = get_logger("pipelines.data_generator")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Egypt observes EET (UTC+2). A fixed offset is used instead of a tz database
#: so the generator behaves identically on Windows, slim containers and CI,
#: and so it stays deterministic regardless of the host tzdata version.
EGYPT_TZ: Final[timezone] = timezone(timedelta(hours=2), name="EET")

#: Stable namespace so re-seeding with the same seed yields identical UUIDs.
ID_NAMESPACE: Final[uuid.UUID] = uuid.UUID("6f1c9e2a-0f8b-5d3e-9a41-2b7c5d8e1a90")

#: Business hours in which synthetic orders are placed (Egyptian local time).
ORDER_WINDOW_START_HOUR: Final[int] = 8
ORDER_WINDOW_END_HOUR: Final[int] = 21

# --- Day-of-week demand multipliers ---------------------------------------
# Egypt's working week runs Sunday..Thursday; Friday and Saturday are the
# weekend, when wholesale distribution and pharmacy restocking largely stop.
FRIDAY_MULTIPLIER: Final[float] = 0.45
SATURDAY_MULTIPLIER: Final[float] = 0.70
MIDWEEK_MULTIPLIER: Final[float] = 1.15
#: Sunday opens the working week and carries the largest catch-up restock.
SUNDAY_MULTIPLIER: Final[float] = 1.20
DAY_OF_WEEK_MULTIPLIER: Final[dict[int, float]] = {
    0: MIDWEEK_MULTIPLIER,  # Monday
    1: MIDWEEK_MULTIPLIER,  # Tuesday
    2: MIDWEEK_MULTIPLIER,  # Wednesday
    3: MIDWEEK_MULTIPLIER,  # Thursday
    4: FRIDAY_MULTIPLIER,  # Friday  — Egyptian weekend
    5: SATURDAY_MULTIPLIER,  # Saturday — Egyptian weekend
    6: SUNDAY_MULTIPLIER,  # Sunday
}
DAY_NAMES: Final[tuple[str, ...]] = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)

# --- Growth trend ----------------------------------------------------------
#: Compounding daily growth of the synthetic market (≈ +45% over 180 days).
DAILY_GROWTH_RATE: Final[float] = 0.0025

# --- Order process ---------------------------------------------------------
#: Mean number of restock orders a pharmacy places on a normal weekday, before
#: the day-of-week / seasonal / holiday / shock multipliers.
BASE_ORDERS_PER_PHARMACY_DAY: Final[float] = 2.0
#: Extra, non-standing lines per pharmacy-day: ``Poisson(BASKET_POISSON_LAMBDA)``,
#: inflated by the mean shock magnitude when a demand shock is active.
BASKET_POISSON_LAMBDA: Final[float] = 3.4
#: Upper bound for ad-hoc top-up lines once a demand shock inflates the pool.
MAX_ADHOC_ITEMS: Final[int] = 24
#: Zipf exponent applied to the static demand weights. Real pharmacy baskets
#: are dominated by fast movers (analgesics, antibiotics, antihistamines) with a
#: long tail of slow movers, which a uniform draw over 60 SKUs does not reproduce.
ZIPF_EXPONENT: Final[float] = 2.2
#: Negative-Binomial dispersion (number of failures). Lower => heavier tail.
NB_DISPERSION: Final[float] = 4.0
# --- Standing ("core") baskets ---------------------------------------------
#: Each pharmacy keeps a stable set of staples it restocks nearly every day:
#: ``CORE_BASKET_MIN + Poisson(CORE_BASKET_LAMBDA)`` SKUs.
CORE_BASKET_MIN: Final[int] = 5
CORE_BASKET_LAMBDA: Final[float] = 3.5
CORE_BASKET_SEED_SALT: Final[int] = 0x5F3759DF
#: Probability that a given staple appears on a given day.
CORE_INCLUSION_PROBABILITY: Final[float] = 0.88
#: Standing orders cover a week of cover, so quantities are larger.
CORE_QUANTITY_SCALE: Final[float] = 1.6
MAX_CORE_QUANTITY: Final[int] = 120

# --- Quantities ------------------------------------------------------------
QUANTITY_RANGES: Final[dict[str, tuple[int, int]]] = {
    CATEGORY_OTC: (4, 25),
    CATEGORY_PRESCRIPTION: (2, 13),
    CATEGORY_COSMETIC: (1, 7),
}

# --- Demand shock ----------------------------------------------------------
#: Classes multiplied by 3x-4x when ``--demand-shock`` is enabled.
PRIMARY_SHOCK_CLASSES: Final[frozenset[str]] = frozenset({"ANTIBIOTIC", "ANTIPYRETIC"})
#: Classes that typically move along with an epidemic (secondary contagion).
SECONDARY_SHOCK_CLASSES: Final[frozenset[str]] = frozenset({"COUGH", "ALLERGY", "COLD_FLU", "RESPIRATORY"})
PRIMARY_SHOCK_RANGE: Final[tuple[float, float]] = (3.0, 4.0)
SECONDARY_SHOCK_RANGE: Final[tuple[float, float]] = (1.4, 2.0)
#: Number of days over which the shock ramps to full magnitude (epidemic onset).
SHOCK_RAMP_DAYS: Final[int] = 3
DEFAULT_SHOCK_DAYS: Final[int] = 21
#: Order count grows while the shock is active (more frequent restocking).
SHOCK_ORDER_RATE_MULTIPLIER: Final[float] = 1.25

# --- Baseline --------------------------------------------------------------
#: Fraction of the timeline held out for baseline evaluation (chronological).
BASELINE_HOLDOUT_FRACTION: Final[float] = 0.20
#: Naive seasonality period in days (same day last week).
NAIVE_PERIOD_DAYS: Final[int] = 7
#: A (pharmacy, product) series must reach this many units over the window to
#: be scored by the baseline — the same active population the model trains on.
MIN_ACTIVE_SERIES_UNITS: Final[int] = 30
MAPE_EPSILON: Final[float] = 1e-6


class TherapeuticClass(StrEnum):
    """Coarse ATC-like grouping driving seasonality, shelves and the shock."""

    ANTIBIOTIC = "ANTIBIOTIC"
    ANTIPYRETIC = "ANTIPYRETIC"
    ANALGESIC = "ANALGESIC"
    TOPICAL_ANALGESIC = "TOPICAL_ANALGESIC"
    COLD_FLU = "COLD_FLU"
    ALLERGY = "ALLERGY"
    COUGH = "COUGH"
    RESPIRATORY = "RESPIRATORY"
    GI = "GI"
    CARDIO = "CARDIO"
    CHOLESTEROL = "CHOLESTEROL"
    DIURETIC = "DIURETIC"
    DIABETES = "DIABETES"
    VITAMIN = "VITAMIN"
    SUPPLEMENT = "SUPPLEMENT"
    DERM = "DERM"
    DERM_COSMETIC = "DERM_COSMETIC"
    ORAL_CARE = "ORAL_CARE"


#: Seasonal archetypes — how each group reacts to Egyptian seasons.
SEASONAL_ARCHETYPE: Final[dict[TherapeuticClass, str]] = {
    TherapeuticClass.ANTIBIOTIC: "RESPIRATORY_SET",
    TherapeuticClass.ANTIPYRETIC: "RESPIRATORY_SET",
    TherapeuticClass.ANALGESIC: "RESPIRATORY_SET",
    TherapeuticClass.TOPICAL_ANALGESIC: "RESPIRATORY_SET",
    TherapeuticClass.COLD_FLU: "RESPIRATORY_SET",
    TherapeuticClass.ALLERGY: "RESPIRATORY_SET",
    TherapeuticClass.COUGH: "RESPIRATORY_SET",
    TherapeuticClass.RESPIRATORY: "RESPIRATORY_SET",
    TherapeuticClass.CARDIO: "CHRONIC",
    TherapeuticClass.CHOLESTEROL: "CHRONIC",
    TherapeuticClass.DIURETIC: "CHRONIC",
    TherapeuticClass.DIABETES: "CHRONIC",
    TherapeuticClass.VITAMIN: "SUPPLEMENT",
    TherapeuticClass.SUPPLEMENT: "SUPPLEMENT",
    TherapeuticClass.DERM: "SKIN",
    TherapeuticClass.DERM_COSMETIC: "SKIN",
    TherapeuticClass.ORAL_CARE: "ORAL_CARE",
    TherapeuticClass.GI: "FLAT",
}


@dataclass(frozen=True, slots=True)
class SeasonalPhase:
    """A calendar window with a fixed seasonal label."""

    name: str
    start: tuple[int, int]
    end: tuple[int, int]


#: Winter in Egypt = the influenza season, hence the demand spike.
SEASONAL_PHASES: Final[tuple[SeasonalPhase, ...]] = (
    SeasonalPhase("WINTER_PEAK", (11, 15), (2, 28)),
    SeasonalPhase("SHOULDER", (3, 1), (5, 31)),
    SeasonalPhase("SUMMER", (6, 1), (8, 31)),
    SeasonalPhase("AUTUMN", (9, 1), (11, 14)),
)
SEASONAL_MULTIPLIER: Final[dict[str, dict[str, float]]] = {
    "RESPIRATORY_SET": {"WINTER_PEAK": 1.40, "SHOULDER": 1.12, "SUMMER": 0.82, "AUTUMN": 1.08},
    "CHRONIC": {"WINTER_PEAK": 1.08, "SHOULDER": 1.00, "SUMMER": 0.98, "AUTUMN": 1.02},
    "SUPPLEMENT": {"WINTER_PEAK": 1.15, "SHOULDER": 1.00, "SUMMER": 0.92, "AUTUMN": 1.00},
    "SKIN": {"WINTER_PEAK": 0.95, "SHOULDER": 1.08, "SUMMER": 1.28, "AUTUMN": 1.02},
    "ORAL_CARE": {"WINTER_PEAK": 1.00, "SHOULDER": 1.00, "SUMMER": 1.05, "AUTUMN": 1.00},
    "FLAT": {"WINTER_PEAK": 1.00, "SHOULDER": 1.00, "SUMMER": 1.00, "AUTUMN": 1.00},
}

# --- Ramadan / Eid ---------------------------------------------------------
RAMADAN_VOLUME_MULTIPLIER: Final[float] = 0.80
PRE_RAMADAN_DAYS: Final[int] = 5
PRE_RAMADAN_STOCKUP_MULTIPLIER: Final[float] = 1.15
EID_ALFITR_MULTIPLIER: Final[float] = 1.25
EID_ALFITR_DAYS: Final[int] = 3
EID_ALADHA_MULTIPLIER: Final[float] = 1.15
EID_ALADHA_DAYS: Final[int] = 4


@dataclass(frozen=True, slots=True)
class HolidayProfile:
    """An Egyptian public holiday and its effect on wholesale order volume."""

    name: str
    multiplier: float


#: Fixed-date Egyptian public holidays. Movable feasts (Eid, Sham el-Nessim)
#: are handled separately from the Hijri / computus helpers below.
EGYPTIAN_HOLIDAYS: Final[tuple[tuple[int, int, HolidayProfile], ...]] = (
    (1, 6, HolidayProfile("Armenian Christmas Eve", 1.00)),
    (1, 7, HolidayProfile("Coptic Christmas", 0.95)),
    (1, 25, HolidayProfile("Revolution Day 2011", 1.05)),
    (2, 1, HolidayProfile("Student Day / Police Day", 0.95)),
    (3, 19, HolidayProfile("Sham el-Nessim (Coptic Easter)", 1.15)),
    (4, 25, HolidayProfile("Sinai Liberation Day", 1.00)),
    (5, 1, HolidayProfile("Labour Day", 1.00)),
    (6, 30, HolidayProfile("June 30 Revolution Day", 1.00)),
    (7, 23, HolidayProfile("Revolution Day 2012 (national holiday)", 1.10)),
    (10, 6, HolidayProfile("Armed Forces Day", 1.10)),
)

# --- Pharmacies ------------------------------------------------------------
#: Real Egyptian governorate names (public geography, not commercial data).
GOVERNORATES: Final[tuple[tuple[str, float, float], ...]] = (
    ("Cairo", 30.0444, 31.2357),
    ("Giza", 30.0626, 31.2497),
    ("Alexandria", 31.2001, 29.9187),
    ("Qalyubia", 30.1798, 31.1122),
    ("Port Said", 31.2653, 32.3019),
    ("Suez", 29.9668, 32.5498),
    ("Dakahlia", 31.0340, 31.3800),
    ("Sharqia", 30.5965, 31.5075),
    ("Gharbia", 30.8683, 31.0195),
    ("Monufia", 30.4668, 30.9315),
    ("Beheira", 31.1000, 30.0500),
    ("Kafr El Sheikh", 31.1000, 30.8000),
    ("Damietta", 31.4165, 31.8133),
    ("Ismailia", 30.5965, 32.2715),
    ("Faiyum", 29.3084, 30.8428),
    ("Beni Suef", 29.0661, 31.0994),
    ("Minya", 28.1099, 30.7503),
    ("Asyut", 27.1783, 31.1859),
    ("Sohag", 26.5569, 31.6948),
    ("Qena", 26.1642, 32.7267),
    ("Luxor", 25.6872, 32.6396),
    ("Aswan", 24.0889, 32.8998),
    ("Red Sea", 27.2578, 33.8116),
    ("New Valley", 25.3448, 30.4779),
    ("Matrouh", 31.3543, 27.2372),
    ("North Sinai", 31.1367, 33.3850),
    ("South Sinai", 28.1096, 33.3711),
)

#: Populous governorates receive proportionally more synthetic pharmacies.
GOVERNORATE_WEIGHTS: Final[dict[str, float]] = {
    "Cairo": 6.0,
    "Giza": 5.0,
    "Alexandria": 4.0,
    "Qalyubia": 2.0,
    "Sharqia": 2.0,
    "Dakahlia": 1.8,
    "Gharbia": 1.6,
    "Beheira": 1.6,
    "Monufia": 1.4,
    "Asyut": 1.2,
    "Minya": 1.2,
    "Sohag": 1.1,
    "Faiyum": 1.0,
    "Port Said": 1.0,
    "Suez": 1.0,
    "Damietta": 0.9,
    "Ismailia": 0.9,
    "Beni Suef": 0.9,
    "Qena": 0.8,
    "Kafr El Sheikh": 0.8,
    "Luxor": 0.7,
    "Aswan": 0.7,
    "Red Sea": 0.6,
    "Matrouh": 0.5,
    "New Valley": 0.3,
    "North Sinai": 0.3,
    "South Sinai": 0.3,
}

#: Invented tokens — no real pharmacy brand is referenced anywhere.
SYNTHETIC_PHARMACY_TOKENS: Final[tuple[str, ...]] = (
    "Aster",
    "Blue Nile",
    "Delta",
    "Horizon",
    "Green Valley",
    "Kasr",
    "Lotus",
    "Marina",
    "Orchid",
    "Palm",
    "Qamar",
    "Ramses",
    "Sahara",
    "Sina",
    "Star",
    "Sunrise",
    "Violet",
    "Waha",
    "Nile Crown",
    "Citrus",
)

PHARMACY_COUNT: Final[int] = 50

#: Tier ordering and the demand multiplier applied to the pharmacy's volume.
PHARMACY_TIER_MULTIPLIER: Final[dict[str, float]] = {"SMALL": 0.68, "MEDIUM": 1.00, "LARGE": 1.55}
PHARMACY_TIER_WEIGHTS: Final[dict[str, float]] = {"SMALL": 0.45, "MEDIUM": 0.40, "LARGE": 0.15}

# --- Matcher simulation ----------------------------------------------------
#: Probability mix of the synthetic two-stage matcher (exact / fuzzy / LLM).
MATCH_QUALITY_WEIGHTS: Final[dict[str, float]] = {"exact": 0.62, "fuzzy": 0.26, "ambiguous": 0.12}
EXACT_CONFIDENCE_RANGE: Final[tuple[float, float]] = (0.90, 0.99)
FUZZY_CONFIDENCE_RANGE: Final[tuple[float, float]] = (0.55, 0.89)
AMBIGUOUS_CONFIDENCE_RANGE: Final[tuple[float, float]] = (0.28, 0.49)
#: Safety valve from the engineering rules: anything below this is human-reviewed.
REVIEW_CONFIDENCE_THRESHOLD: Final[float] = 0.50

ORDER_SEPARATORS: Final[tuple[str, ...]] = (" + ", " , ", " و ", " ; ", ", ")
ORDER_NOTES: Final[tuple[str, ...]] = ("", "", "", "urgent", "استعجال", "no substitute", "بدون بديل", "credit terms")


# ---------------------------------------------------------------------------
# Curated catalogue
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DrugSpec:
    """One catalogue entry with its synthetic demand characteristics."""

    catalogue_id: str
    brand_name: str
    generic_name: str
    arabic_name: str
    franco_arabic: str
    form: str
    strength: str
    unit_price_egp: float
    category: str
    therapeutic_class: TherapeuticClass
    demand_weight: float
    """Relative share of basket volume (fast movers carry a larger weight)."""

    @property
    def display_name(self) -> str:
        """Customer-facing name, e.g. ``Panadol Extra 500mg tablet``."""
        return f"{self.brand_name} {self.strength}"


#: 60 SKUs widely listed in the Egyptian market. Brand names are public
#: trade names; prices and demand weights are invented for this demo.
CURATED_DRUGS: Final[tuple[DrugSpec, ...]] = (
    DrugSpec("panadol-extra-500", "Panadol Extra", "Paracetamol 500mg", "بانادول إكسترا", "panadol", "tablet", "500mg", 18.00, CATEGORY_OTC, TherapeuticClass.ANTIPYRETIC, 10.0),
    DrugSpec("panadol-caffrine-500", "Panadol Caffrine", "Paracetamol + Caffeine", "بانادول كافرين", "panadol caffrine", "tablet", "500mg", 22.00, CATEGORY_OTC, TherapeuticClass.ANTIPYRETIC, 5.6),
    DrugSpec("augmentin-1g", "Augmentin 1g", "Amoxicillin + Clavulanic Acid", "أوجمنتين", "augmentyn", "tablet", "1g", 245.00, CATEGORY_PRESCRIPTION, TherapeuticClass.ANTIBIOTIC, 5.0),
    DrugSpec("augmentin-625", "Augmentin 625", "Amoxicillin + Clavulanic Acid", "أوجمنتين ٦٢٥", "augmentyn 625", "tablet", "625mg", 195.00, CATEGORY_PRESCRIPTION, TherapeuticClass.ANTIBIOTIC, 6.2),
    DrugSpec("augmentin-susp-457", "Augmentin Suspension", "Amoxicillin + Clavulanic Acid", "أوجمنتين شراب", "augmentyn susp", "suspension", "457mg/5ml", 168.00, CATEGORY_PRESCRIPTION, TherapeuticClass.ANTIBIOTIC, 3.2),
    DrugSpec("bactrim-800-160", "Septran Forte", "Sulfamethoxazole + Trimethoprim", "سبتران فورت", "siptan forte", "tablet", "800/160mg", 40.00, CATEGORY_PRESCRIPTION, TherapeuticClass.ANTIBIOTIC, 4.4),
    DrugSpec("cipronil-500", "Cipronil 500", "Ciprofloxacin", "سيبرونيل", "sipronil", "tablet", "500mg", 78.00, CATEGORY_PRESCRIPTION, TherapeuticClass.ANTIBIOTIC, 2.4),
    DrugSpec("rovamycine-250", "Rovamycine", "Spiramycin", "روفاميسين", "rovamysin", "tablet", "250mg", 95.00, CATEGORY_PRESCRIPTION, TherapeuticClass.ANTIBIOTIC, 1.8),
    DrugSpec("zithromax-500", "Zithromax", "Azithromycin", "زيثروماكس", "zethromaks", "tablet", "500mg", 210.00, CATEGORY_PRESCRIPTION, TherapeuticClass.ANTIBIOTIC, 1.5),
    DrugSpec("klacid-500", "Klacid", "Clarithromycin", "كلاسيد", "klassid", "tablet", "500mg", 225.00, CATEGORY_PRESCRIPTION, TherapeuticClass.ANTIBIOTIC, 1.2),
    DrugSpec("amoksil-500", "Amoxil 500", "Amoxicillin", "أموكسيل", "amoksil", "capsule", "500mg", 62.00, CATEGORY_PRESCRIPTION, TherapeuticClass.ANTIBIOTIC, 4.0),
    DrugSpec("broughen-400", "Brufen 400", "Ibuprofen", "بروفين", "broughen", "tablet", "400mg", 25.00, CATEGORY_OTC, TherapeuticClass.ANTIPYRETIC, 9.0),
    DrugSpec("broughen-syrup-100", "Brufen Syrup", "Ibuprofen", "بروفين شراب", "broughen syrup", "syrup", "100mg/5ml", 38.00, CATEGORY_OTC, TherapeuticClass.ANTIPYRETIC, 4.8),
    DrugSpec("congistal-500", "Congestal", "Paracetamol + Chlorphenamine + Pseudoephedrine", "كونجستال", "congistal", "tablet", "500mg", 34.00, CATEGORY_OTC, TherapeuticClass.COLD_FLU, 7.4),
    DrugSpec("antinal-200", "Antinal 200", "Nifuroxazide", "أنتينال", "antinall", "capsule", "200mg", 45.00, CATEGORY_OTC, TherapeuticClass.GI, 4.0),
    DrugSpec("kattaflam-50", "Cataflam 50", "Diclofenac Potassium", "كتافلام", "kattaflam", "tablet", "50mg", 68.00, CATEGORY_OTC, TherapeuticClass.ANALGESIC, 6.4),
    DrugSpec("kattaflam-gel-1", "Cataflam Gel", "Diclofenac Diethylamine", "كتافلام جل", "kattaflam gel", "gel", "1%", 72.00, CATEGORY_OTC, TherapeuticClass.TOPICAL_ANALGESIC, 3.0),
    DrugSpec("tramadol-50", "Tramadol 50", "Tramadol", "ترامادول", "tramadol", "capsule", "50mg", 45.00, CATEGORY_PRESCRIPTION, TherapeuticClass.ANALGESIC, 2.8),
    DrugSpec("clarityne-10", "Clarityne", "Loratadine", "كلاريتين", "clarityne", "tablet", "10mg", 28.00, CATEGORY_OTC, TherapeuticClass.ALLERGY, 6.0),
    DrugSpec("clarityne-syrup-5", "Clarityne Syrup", "Loratadine", "كلاريتين شراب", "clarityne syrup", "syrup", "5mg/5ml", 32.00, CATEGORY_OTC, TherapeuticClass.ALLERGY, 3.9),
    DrugSpec("zyrtec-10", "Zyrtec", "Cetirizine", "زيرتك", "zyrtek", "tablet", "10mg", 35.00, CATEGORY_OTC, TherapeuticClass.ALLERGY, 4.9),
    DrugSpec("bessolvon-syrup-5", "Bisolvon", "Bromhexine", "بيسولفون", "bessolvon", "syrup", "5mg/5ml", 42.00, CATEGORY_OTC, TherapeuticClass.COUGH, 5.1),
    DrugSpec("otkol-syrup-100", "Otcol", "Guaifenesin + Menthol", "أوتوكول", "otkol", "syrup", "100mg/5ml", 36.00, CATEGORY_OTC, TherapeuticClass.COUGH, 5.9),
    DrugSpec("ventolin-inhaler-100", "Ventolin Inhaler", "Salbutamol", "فنتولين", "ventolin", "inhaler", "100mcg", 145.00, CATEGORY_PRESCRIPTION, TherapeuticClass.RESPIRATORY, 2.2),
    DrugSpec("aerolayd-inhaler", "Aerolide Inhaler", "Salbutamol + Fluticasone", "إيرولايد", "aerolayd", "inhaler", "50/500mcg", 320.00, CATEGORY_PRESCRIPTION, TherapeuticClass.RESPIRATORY, 1.1),
    DrugSpec("montelast-10", "Montelast 10", "Montelukast", "مونتلاست", "montelast", "tablet", "10mg", 165.00, CATEGORY_PRESCRIPTION, TherapeuticClass.RESPIRATORY, 1.4),
    DrugSpec("otrivin-drops", "Otrivin Nasal", "Xylometazoline", "أوتريفين", "otrivin", "nasal drops", "0.1%", 28.00, CATEGORY_OTC, TherapeuticClass.COLD_FLU, 3.5),
    DrugSpec("nazo-clair-spray", "Naso Clear", "Xylometazoline", "نازو كلير", "nazo clair", "nasal spray", "0.1%", 24.00, CATEGORY_OTC, TherapeuticClass.COLD_FLU, 3.1),
    DrugSpec("fevadol-500", "Fevadol 500", "Paracetamol 500mg", "فيفادول", "fevadol", "tablet", "500mg", 15.00, CATEGORY_OTC, TherapeuticClass.ANTIPYRETIC, 6.9),
    DrugSpec("adol-500", "Adol 500", "Paracetamol 500mg", "أدول", "adol", "tablet", "500mg", 12.50, CATEGORY_OTC, TherapeuticClass.ANTIPYRETIC, 5.4),
    DrugSpec("paramol-500", "Paramol", "Paracetamol 500mg", "بارامول", "paramol", "tablet", "500mg", 14.00, CATEGORY_OTC, TherapeuticClass.ANTIPYRETIC, 5.9),
    DrugSpec("ceevit-1000", "Ceevit", "Ascorbic Acid", "سيفيت", "seevit", "effervescent tablet", "1000mg", 26.00, CATEGORY_OTC, TherapeuticClass.VITAMIN, 5.4),
    DrugSpec("vitamin-c-500", "Vitamin C 500", "Ascorbic Acid", "فيتامين سي", "vitamin c", "effervescent tablet", "500mg", 18.00, CATEGORY_OTC, TherapeuticClass.VITAMIN, 5.9),
    DrugSpec("cal-d-600", "Cal-D", "Calcium + Vitamin D3", "كال د", "cal-d", "effervescent tablet", "600mg", 55.00, CATEGORY_OTC, TherapeuticClass.SUPPLEMENT, 3.9),
    DrugSpec("newro-b-500", "Neuro-B", "B-Complex Vitamins", "نيورو ب", "newro b", "capsule", "500mg", 60.00, CATEGORY_OTC, TherapeuticClass.SUPPLEMENT, 2.9),
    DrugSpec("feroglobin-150", "Feroglobin", "Iron + Vitamins", "فيروجلوبين", "feroglobin", "capsule", "150mg", 88.00, CATEGORY_OTC, TherapeuticClass.SUPPLEMENT, 2.7),
    DrugSpec("inzhor-plus-400", "Ensure Plus", "Nutritional Supplement", "إنشور بلاس", "inzhor plas", "powder sachet", "400g", 520.00, CATEGORY_OTC, TherapeuticClass.SUPPLEMENT, 0.9),
    DrugSpec("glucophage-850", "Glucophage 850", "Metformin", "جلوكوفاج", "glucophage", "tablet", "850mg", 72.00, CATEGORY_PRESCRIPTION, TherapeuticClass.DIABETES, 4.9),
    DrugSpec("diamicron-80", "Diamicron 80", "Gliclazide", "دياميكرون", "diamicron", "tablet", "80mg", 65.00, CATEGORY_PRESCRIPTION, TherapeuticClass.DIABETES, 3.5),
    DrugSpec("amaryl-3", "Amaryl 3", "Glimepiride", "أماريل", "amaryl", "tablet", "3mg", 90.00, CATEGORY_PRESCRIPTION, TherapeuticClass.DIABETES, 2.0),
    DrugSpec("concor-5", "Concor 5", "Bisoprolol", "كونكور", "concor", "tablet", "5mg", 58.00, CATEGORY_PRESCRIPTION, TherapeuticClass.CARDIO, 3.3),
    DrugSpec("tritass-2-5", "Tritace 2.5", "Ramipril", "تريتس", "tritass", "tablet", "2.5mg", 85.00, CATEGORY_PRESCRIPTION, TherapeuticClass.CARDIO, 2.5),
    DrugSpec("norvask-5", "Norvasc 5", "Amlodipine", "نورفاسك", "norvask", "tablet", "5mg", 96.00, CATEGORY_PRESCRIPTION, TherapeuticClass.CARDIO, 2.9),
    DrugSpec("lepetor-20", "Lipitor 20", "Atorvastatin", "ليبيتور", "lepetor", "tablet", "20mg", 175.00, CATEGORY_PRESCRIPTION, TherapeuticClass.CHOLESTEROL, 1.6),
    DrugSpec("cristor-20", "Crestor 20", "Rosuvastatin", "كريستور", "cristor", "tablet", "20mg", 265.00, CATEGORY_PRESCRIPTION, TherapeuticClass.CHOLESTEROL, 0.9),
    DrugSpec("lassik-40", "Lasix 40", "Furosemide", "لازكس", "lassik", "tablet", "40mg", 30.00, CATEGORY_PRESCRIPTION, TherapeuticClass.DIURETIC, 2.9),
    DrugSpec("aldacton-25", "Aldactone 25", "Spironolactone", "ألداكتون", "aldacton", "tablet", "25mg", 38.00, CATEGORY_PRESCRIPTION, TherapeuticClass.DIURETIC, 2.0),
    DrugSpec("milanta-susp", "Mylanta", "Aluminium + Magnesium Hydroxide", "ميلانتا", "milanta", "suspension", "400mg/10ml", 55.00, CATEGORY_OTC, TherapeuticClass.GI, 4.1),
    DrugSpec("javiskon-sachet", "Gaviscon Advance", "Sodium Alginate", "جافيسكون", "javiskon", "sachet", "10ml", 98.00, CATEGORY_OTC, TherapeuticClass.GI, 2.2),
    DrugSpec("renni-1000", "Rennie", "Calcium Carbonate", "ريني", "renni", "chewable tablet", "1000mg", 30.00, CATEGORY_OTC, TherapeuticClass.GI, 2.9),
    DrugSpec("neksiom-40", "Nexium 40", "Esomeprazole", "نيكسيوم", "neksiom", "tablet", "40mg", 235.00, CATEGORY_PRESCRIPTION, TherapeuticClass.GI, 1.8),
    DrugSpec("omez-20", "Omez 20", "Omeprazole", "أوميز", "omez", "capsule", "20mg", 85.00, CATEGORY_PRESCRIPTION, TherapeuticClass.GI, 2.5),
    DrugSpec("nizoral-cream-20", "Nizoral 2%", "Ketoconazole", "نيزورال", "nizoral", "cream", "20mg/g", 130.00, CATEGORY_OTC, TherapeuticClass.DERM, 1.5),
    DrugSpec("ketoderm-cream-2", "Ketoderm 2%", "Ketoconazole", "كيتودرم", "ketoderm", "cream", "2%", 145.00, CATEGORY_OTC, TherapeuticClass.DERM, 1.4),
    DrugSpec("beta-sol-cream-1", "Betamethasone Valerate", "Betamethasone Valerate", "بيتاميثازون", "beta sol", "cream", "1mg/g", 95.00, CATEGORY_PRESCRIPTION, TherapeuticClass.DERM, 1.3),
    DrugSpec("hydrocort-cream-1", "Hydrocortisone Cream", "Hydrocortisone", "هيدروكورتيزون", "hydrocort", "cream", "1%", 48.00, CATEGORY_OTC, TherapeuticClass.DERM, 2.4),
    DrugSpec("thermaqua-cream", "Thermaqua Sensitive", "Centella + Niacinamide", "ثيرماكوا", "thermaqua", "facial cream", "40ml", 380.00, CATEGORY_COSMETIC, TherapeuticClass.DERM_COSMETIC, 0.6),
    DrugSpec("melanogen-cream-20", "Melanogen Cream", "Azelaic Acid 20%", "ميلانوجين", "melanogen", "cream", "20%", 210.00, CATEGORY_COSMETIC, TherapeuticClass.DERM_COSMETIC, 0.8),
    DrugSpec("sensodain-toothpaste", "Sensodyne Repair", "Sodium Fluoride + Potassium Nitrate", "سنسوداين", "sensodain", "toothpaste", "75ml", 165.00, CATEGORY_COSMETIC, TherapeuticClass.ORAL_CARE, 1.6),
    DrugSpec("signal-toothpaste-100", "Signal 2", "Fluoride Toothpaste", "سيجنال", "signal", "toothpaste", "100g", 42.00, CATEGORY_COSMETIC, TherapeuticClass.ORAL_CARE, 3.3),
)

#: Fast lookup used by the generator and by future matcher phases.
CATALOGUE_BY_ID: Final[dict[str, DrugSpec]] = {spec.catalogue_id: spec for spec in CURATED_DRUGS}


# ---------------------------------------------------------------------------
# Pharmacies
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Pharmacy:
    """A synthetic pharmacy (identity invented; no real pharmacy is described)."""

    pharmacy_id: str
    name: str
    governorate: str
    tier: str
    latitude: float
    longitude: float
    is_chain: bool
    volume_factor: float
    """Persistent multiplicative idiosyncrasy of this pharmacy's demand."""


def build_pharmacies(count: int = PHARMACY_COUNT, random_seed: int = 42) -> list[Pharmacy]:
    """Create ``count`` deterministic synthetic pharmacies across Egypt.

    Pharmacies are assigned to governorates proportionally to synthetic
    population weights, segmented into tiers, and given a stable per-pharmacy
    volume factor so that no two pharmacies follow the same curve.
    """
    if count <= 0:
        raise ValueError("count must be positive")
    rng = np.random.default_rng(random_seed)
    governorate_names = [name for name, _lat, _lon in GOVERNORATES]
    coords = {name: (lat, lon) for name, lat, lon in GOVERNORATES}
    weights = np.array([GOVERNORATE_WEIGHTS.get(name, 1.0) for name in governorate_names], dtype=float)
    weights = weights / weights.sum()
    tier_names = list(PHARMACY_TIER_WEIGHTS)
    tier_probs = np.array([PHARMACY_TIER_WEIGHTS[tier] for tier in tier_names], dtype=float)
    tier_probs = tier_probs / tier_probs.sum()

    assignments = rng.choice(governorate_names, size=count, p=weights)
    tiers = rng.choice(tier_names, size=count, p=tier_probs)
    pharmacy_list: list[Pharmacy] = []
    for index in range(count):
        governorate = str(assignments[index])
        tier = str(tiers[index])
        lat, lon = coords[governorate]
        branch = index + 1
        token = SYNTHETIC_PHARMACY_TOKENS[index % len(SYNTHETIC_PHARMACY_TOKENS)]
        pharmacy_list.append(
            Pharmacy(
                pharmacy_id=f"PH-{branch:03d}",
                name=f"{token} Pharmacy — {governorate} Branch {branch:03d}",
                governorate=governorate,
                tier=tier,
                latitude=round(float(lat) + float(rng.normal(0.0, 0.06)), 6),
                longitude=round(float(lon) + float(rng.normal(0.0, 0.06)), 6),
                is_chain=bool(tier in {"MEDIUM", "LARGE"} and rng.random() < 0.45),
                volume_factor=float(
                    PHARMACY_TIER_MULTIPLIER[tier] * np.clip(rng.lognormal(mean=0.0, sigma=0.18), 0.55, 1.9)
                ),
            )
        )
    return pharmacy_list


# ---------------------------------------------------------------------------
# Calendar helpers (weekend, seasons, holidays, Ramadan)
# ---------------------------------------------------------------------------


def gregorian_to_jdn(year: int, month: int, day: int) -> int:
    """Convert a Gregorian date to a Julian Day Number (proleptic)."""
    a = (14 - month) // 12
    y = year + 4800 - a
    m = month + 12 * a - 3
    return (
        day
        + (153 * m + 2) // 5
        + 365 * y
        + y // 4
        - y // 100
        + y // 400
        - 32045
    )


def gregorian_to_hijri(year: int, month: int, day: int) -> tuple[int, int, int]:
    """Convert a Gregorian date to the tabular (Kuwaiti) Islamic calendar.

    Returns ``(hijri_year, hijri_month, hijri_day)`` where ``9`` is Ramadan and
    ``10`` / ``12`` are Eid al-Fitr / Eid al-Adha.  The tabular calendar can
    differ from moon-sighting dates by a day, which is immaterial for seasonal
    volume simulation.
    """
    jdn = gregorian_to_jdn(year, month, day)
    l0 = jdn - 1948440 + 10632
    n = (l0 - 1) // 10631
    l_value = l0 - 10631 * n + 354
    j = (
        ((10985 - l_value) // 5316) * ((50 * l_value) // 17719)
        + (l_value // 5670) * ((43 * l_value) // 15238)
    )
    l_value = (
        l_value
        - ((30 - j) // 15) * ((17719 * j) // 50)
        - (j // 16) * ((15238 * j) // 43)
        + 29
    )
    hijri_month = (24 * l_value) // 709
    hijri_day = l_value - (709 * hijri_month) // 24
    hijri_year = 30 * n + j - 30
    return hijri_year, hijri_month, hijri_day


def is_ramadan(day: date) -> bool:
    """``True`` when ``day`` falls in the Hijri month of Ramadan."""
    _year, hijri_month, _hijri_day = gregorian_to_hijri(day.year, day.month, day.day)
    return hijri_month == 9


def is_eid_al_fitr(day: date) -> bool:
    """``True`` during the first three days of Eid al-Fitr (stock-up + celebration)."""
    _year, hijri_month, hijri_day = gregorian_to_hijri(day.year, day.month, day.day)
    return hijri_month == 10 and hijri_day <= EID_ALFITR_DAYS


def is_eid_al_adha(day: date) -> bool:
    """``True`` during the first four days of Eid al-Adha."""
    _year, hijri_month, hijri_day = gregorian_to_hijri(day.year, day.month, day.day)
    return hijri_month == 12 and hijri_day <= EID_ALADHA_DAYS


def seasonal_phase(day: date) -> str:
    """Return the seasonal phase label (``WINTER_PEAK``, ``SUMMER``, ...)."""
    month_day = (day.month, day.day)
    for phase in SEASONAL_PHASES:
        (start_month, start_day) = phase.start
        (end_month, end_day) = phase.end
        if start_month <= end_month:  # window inside a single calendar year
            if (start_month, start_day) <= month_day <= (end_month, end_day):
                return phase.name
        elif month_day >= (start_month, start_day) or month_day <= (end_month, end_day):
            return phase.name
    return "AUTUMN"


def seasonal_multiplier(day: date, therapeutic_class: TherapeuticClass) -> float:
    """Seasonal demand multiplier for a therapeutic class on a given date."""
    archetype = SEASONAL_ARCHETYPE.get(therapeutic_class, "FLAT")
    return SEASONAL_MULTIPLIER[archetype].get(seasonal_phase(day), 1.0)


def day_of_week_multiplier(day: date) -> float:
    """Egyptian weekly ordering pattern (Friday/Saturday weekend dip)."""
    return DAY_OF_WEEK_MULTIPLIER[day.weekday()]


def holiday_for(day: date) -> HolidayProfile | None:
    """Return the Egyptian public holiday falling on ``day``, if any."""
    for month, day_of_month, profile in EGYPTIAN_HOLIDAYS:
        if day.month == month and day.day == day_of_month:
            return profile
    return None


def calendar_multiplier(day: date) -> float:
    """Combined holiday / Ramadan / Eid multiplier for ``day``."""
    profile = holiday_for(day)
    multiplier = profile.multiplier if profile else 1.0
    if is_ramadan(day):
        # Working hours shift to late evening: fewer daytime deliveries.
        multiplier *= RAMADAN_VOLUME_MULTIPLIER
    if is_eid_al_fitr(day):
        multiplier *= EID_ALFITR_MULTIPLIER
    elif is_eid_al_adha(day):
        multiplier *= EID_ALADHA_MULTIPLIER
    return multiplier


def day_multiplier(day: date, index: int, therapeutic_class: TherapeuticClass | None = None) -> float:
    """Full multiplicative demand factor for ``day``.

    Composed of the weekday pattern, seasonality (class-specific when supplied),
    the holiday/Ramadan calendar, the growth trend and the shock multiplier.
    """
    multiplier = day_of_week_multiplier(day) * calendar_multiplier(day)
    if therapeutic_class is not None:
        multiplier *= seasonal_multiplier(day, therapeutic_class)
    multiplier *= 1.0 + DAILY_GROWTH_RATE * index
    return multiplier


# ---------------------------------------------------------------------------
# Shock helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ShockPlan:
    """Configuration of the synthetic demand shock.

    The shock is applied to the final ``days`` of the generated window so that
    a reference window (pre-shock) always remains available for PSI comparison.
    """

    enabled: bool
    start_index: int
    end_index: int
    ramp_days: int = SHOCK_RAMP_DAYS

    @property
    def length(self) -> int:
        return max(0, self.end_index - self.start_index + 1)


def build_shock_plan(days: int, enabled: bool, shock_days: int) -> ShockPlan:
    """Validate shock parameters and return the resolved :class:`ShockPlan`."""
    if not enabled:
        return ShockPlan(enabled=False, start_index=days, end_index=days - 1)
    if shock_days <= 0:
        raise ValueError("shock_days must be positive")
    if shock_days >= days:
        raise ValueError(
            f"shock_days ({shock_days}) must be smaller than the generation window ({days}) "
            "so that a clean reference window remains available for drift comparison"
        )
    return ShockPlan(enabled=True, start_index=days - shock_days, end_index=days - 1)


def shock_multiplier(plan: ShockPlan, index: int, therapeutic_class: TherapeuticClass) -> float:
    """Return the shock multiplier (>= 1.0) for a class on a given day index.

    The epidemic ramps linearly over :attr:`ShockPlan.ramp_days` days, then
    plateaus at a per-day target drawn from the documented ranges.
    """
    if not plan.enabled or index < plan.start_index:
        return 1.0
    class_value = str(therapeutic_class)
    if class_value in PRIMARY_SHOCK_CLASSES:
        target = PRIMARY_SHOCK_RANGE[0] + (PRIMARY_SHOCK_RANGE[1] - PRIMARY_SHOCK_RANGE[0]) * _hash_unit(
            plan.start_index, index, class_value
        )
    elif class_value in SECONDARY_SHOCK_CLASSES:
        low, high = SECONDARY_SHOCK_RANGE
        target = low + (high - low) * _hash_unit(plan.start_index, index, class_value)
    else:
        return 1.0
    ramp = min(1.0, (index - plan.start_index + 1) / plan.ramp_days)
    return 1.0 + ramp * (target - 1.0)


def _hash_unit(shock_start: int, day_index: int, key: str) -> float:
    """Deterministic pseudo-random float in ``[0, 1)`` from the given keys.

    Using a hash instead of the shared RNG stream keeps the shock multiplier a
    pure function of the calendar, so PSI comparisons stay reproducible even if
    unrelated generation order changes.
    """
    digest = uuid.uuid5(ID_NAMESPACE, f"shock:{shock_start}:{day_index}:{key}").int
    return (digest % 1_000_003) / 1_000_003


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OrderItemRecord:
    """One synthetic order line, already matched with a confidence score."""

    item_id: uuid.UUID
    order_id: uuid.UUID
    raw_token: str
    catalogue_id: str
    catalogue_name: str
    quantity: int
    confidence: float
    match_method: str
    needs_review: bool


@dataclass(frozen=True, slots=True)
class OrderRecord:
    """One synthetic restock order."""

    order_id: uuid.UUID
    pharmacy_id: str
    raw_text: str
    created_at: datetime
    items: tuple[OrderItemRecord, ...]


@dataclass(slots=True)
class GeneratedData:
    """Everything produced by :func:`generate_dataset`."""

    catalogue: tuple[DrugSpec, ...]
    pharmacies: tuple[Pharmacy, ...]
    orders: list[OrderRecord]
    items: list[OrderItemRecord]
    panel: "DemandPanel"
    start_date: date
    end_date: date
    random_seed: int
    shock: ShockPlan
    baseline: "BaselineReport"


# ---------------------------------------------------------------------------
# Demand panel + naive baseline
# ---------------------------------------------------------------------------


class DemandPanel:
    """Dense ``(pharmacy_id, catalogue_id, date) -> units_sold`` aggregation.

    This is the exact panel the forecasting phase consumes: one row per
    pharmacy × product × day, including zero-volume days, so that lag and
    rolling features never silently shift the timeline.
    """

    __slots__ = ("_units", "_catalogue", "start_date", "end_date", "_days")

    def __init__(
        self,
        catalogue: Sequence[DrugSpec],
        pharmacies: Sequence[Pharmacy],
        start_date: date,
        end_date: date,
    ) -> None:
        self._catalogue: Final[dict[str, DrugSpec]] = {spec.catalogue_id: spec for spec in catalogue}
        self.start_date: Final[date] = start_date
        self.end_date: Final[date] = end_date
        self._days: Final[list[date]] = [
            start_date + timedelta(days=offset) for offset in range((end_date - start_date).days + 1)
        ]
        # {(pharmacy_id, catalogue_id): {date: units}}
        self._units: dict[tuple[str, str], dict[date, int]] = {
            (pharmacy.pharmacy_id, spec.catalogue_id): {} for pharmacy in pharmacies for spec in catalogue
        }

    # -- population --------------------------------------------------------
    @property
    def days(self) -> list[date]:
        """Every calendar day in the panel (no gaps)."""
        return self._days

    @property
    def series_count(self) -> int:
        """Number of ``(pharmacy, product)`` series tracked."""
        return len(self._units)

    def add_units(self, pharmacy_id: str, catalogue_id: str, day: date, units: int) -> None:
        """Accumulate ``units`` for one pharmacy/product/day cell."""
        series = self._units.get((pharmacy_id, catalogue_id))
        if series is None:  # pragma: no cover - defensive
            series = self._units[(pharmacy_id, catalogue_id)] = {}
        series[day] = series.get(day, 0) + units

    def series(self, pharmacy_id: str, catalogue_id: str) -> dict[date, int]:
        """Units-per-day mapping for one series (empty when never ordered)."""
        return self._units.get((pharmacy_id, catalogue_id), {})

    def units_on(self, pharmacy_id: str, catalogue_id: str, day: date) -> int:
        """Units sold on ``day`` (0 when the product was not ordered)."""
        return self._units.get((pharmacy_id, catalogue_id), {}).get(day, 0)

    def therapeutic_class_of(self, catalogue_id: str) -> str:
        spec = self._catalogue.get(catalogue_id)
        return str(spec.therapeutic_class) if spec else "UNKNOWN"

    def daily_totals(self, start: date | None = None, end: date | None = None) -> dict[date, int]:
        """Total units sold per day across all products and pharmacies."""
        window_start = start or self.start_date
        window_end = end or self.end_date
        totals: dict[date, int] = {day: 0 for day in self._days if window_start <= day <= window_end}
        for series in self._units.values():
            for day, units in series.items():
                if day in totals:
                    totals[day] += units
        return dict(sorted(totals.items()))

    def class_totals(self, start: date | None = None, end: date | None = None) -> dict[str, int]:
        """Total units per therapeutic class within an optional window."""
        window_start = start or self.start_date
        window_end = end or self.end_date
        totals: dict[str, int] = defaultdict(int)
        for (_pharmacy_id, catalogue_id), series in self._units.items():
            bucket = self.therapeutic_class_of(catalogue_id)
            for day, units in series.items():
                if window_start <= day <= window_end:
                    totals[bucket] += units
        return dict(sorted(totals.items()))

    def to_frame(self) -> pd.DataFrame:
        """Return the panel as a :class:`pandas.DataFrame` (Phase 2 entry point)."""
        records: list[dict[str, Any]] = []
        for (pharmacy_id, catalogue_id), series in self._units.items():
            spec = self._catalogue.get(catalogue_id)
            for day, units in series.items():
                records.append(
                    {
                        "pharmacy_id": pharmacy_id,
                        "catalogue_id": catalogue_id,
                        "brand_name": spec.brand_name if spec else None,
                        "therapeutic_class": str(spec.therapeutic_class) if spec else "UNKNOWN",
                        "category": spec.category if spec else None,
                        "ds": day,
                        "units_sold": units,
                    }
                )
        frame = pd.DataFrame.from_records(records)
        if frame.empty:  # pragma: no cover - defensive
            frame = pd.DataFrame(
                columns=["pharmacy_id", "catalogue_id", "brand_name", "therapeutic_class", "category", "ds", "units_sold"]
            )
        return frame.sort_values(["pharmacy_id", "catalogue_id", "ds"], ignore_index=True)

    # -- naive baseline ----------------------------------------------------
    def naive_week_forecast(self, pharmacy_id: str, catalogue_id: str, target_day: date) -> float | None:
        """Naive seasonal forecast: units sold on the **same day last week**.

        Returns ``None`` when the lagged day is outside the generated window,
        so callers can exclude warm-up observations instead of treating a
        missing history as zero demand.
        """
        lagged_day = target_day - timedelta(days=NAIVE_PERIOD_DAYS)
        if lagged_day < self.start_date or lagged_day > self.end_date:
            return None
        return float(self.units_on(pharmacy_id, catalogue_id, lagged_day))

    def evaluate_naive_baseline(
        self,
        evaluation_days: int | None = None,
        *,
        min_series_units: int = MIN_ACTIVE_SERIES_UNITS,
    ) -> "BaselineReport":
        """Score the naive week-ahead forecaster on a chronological holdout.

        The split is strictly temporal: the final ``evaluation_days`` (default
        ``20%``) are scored against observations from the reference period —
        never a random split (rules: *Time-Series Integrity*).

        Only **active series** are scored (those with at least
        ``min_series_units`` units over the whole window).  This is
        deliberately the same population the forecasting model will be trained
        on; scoring the long tail of one-off SKUs as well would make the
        baseline artificially easy and the comparison with a challenger
        meaningless.
        """
        total_days = len(self._days)
        if total_days <= NAIVE_PERIOD_DAYS + 1:
            raise ValueError(
                f"panel of {total_days} days is too short for a {NAIVE_PERIOD_DAYS}-day naive baseline"
            )
        holdout = evaluation_days or max(NAIVE_PERIOD_DAYS, int(round(total_days * BASELINE_HOLDOUT_FRACTION)))
        holdout = max(1, min(holdout, total_days - NAIVE_PERIOD_DAYS))
        evaluation_dates = self._days[-holdout:]

        active_series = [
            (pharmacy_id, catalogue_id)
            for (pharmacy_id, catalogue_id), series in self._units.items()
            if sum(series.values()) >= min_series_units
        ]

        errors: list[float] = []
        absolute_errors: list[float] = []
        absolute_pct_errors: list[float] = []
        actual_values: list[float] = []
        predicted_values: list[float] = []
        per_class_abs_error: dict[str, list[float]] = defaultdict(list)
        per_weekday_abs_error: dict[int, list[float]] = defaultdict(list)
        skipped = 0

        for day in evaluation_dates:
            for pharmacy_id, catalogue_id in active_series:
                actual = float(self._units[(pharmacy_id, catalogue_id)].get(day, 0))
                predicted = self.naive_week_forecast(pharmacy_id, catalogue_id, day)
                if predicted is None:
                    skipped += 1
                    continue
                error = predicted - actual
                errors.append(error)
                absolute_errors.append(abs(error))
                actual_values.append(actual)
                predicted_values.append(predicted)
                if actual > MAPE_EPSILON:
                    absolute_pct_errors.append(abs(error) / actual)
                per_class_abs_error[self.therapeutic_class_of(catalogue_id)].append(abs(error))
                per_weekday_abs_error[day.weekday()].append(abs(error))

        if not errors:  # pragma: no cover - defensive
            raise RuntimeError("naive baseline produced no comparable observations")

        mae = float(statistics.fmean(absolute_errors))
        rmse = float(math.sqrt(statistics.fmean([error * error for error in errors])))
        mape = float(statistics.fmean(absolute_pct_errors)) if absolute_pct_errors else float("nan")
        class_mae = {
            class_name: float(statistics.fmean(values)) for class_name, values in sorted(per_class_abs_error.items())
        }
        weekday_mae = {
            DAY_NAMES[weekday]: float(statistics.fmean(values)) for weekday, values in sorted(per_weekday_abs_error.items())
        }
        return BaselineReport(
            strategy="naive_same_day_last_week",
            horizon_days=NAIVE_PERIOD_DAYS,
            mae=mae,
            rmse=rmse,
            mape=mape,
            bias=float(statistics.fmean(errors)),
            observations=len(errors),
            skipped_observations=skipped,
            series_scored=len(active_series),
            series_total=len(self._units),
            mean_actual=float(statistics.fmean(actual_values)),
            mean_predicted=float(statistics.fmean(predicted_values)),
            evaluation_start=evaluation_dates[0],
            evaluation_end=evaluation_dates[-1],
            evaluation_days=len(evaluation_dates),
            reference_start=self.start_date,
            reference_end=evaluation_dates[0] - timedelta(days=1),
            by_therapeutic_class=class_mae,
            by_day_of_week=weekday_mae,
        )


@dataclass(frozen=True, slots=True)
class BaselineReport:
    """Naive baseline metrics — the number every challenger model must beat."""

    strategy: str
    horizon_days: int
    mae: float
    rmse: float
    mape: float
    bias: float
    observations: int
    skipped_observations: int
    series_scored: int
    series_total: int
    mean_actual: float
    mean_predicted: float
    evaluation_start: date
    evaluation_end: date
    evaluation_days: int
    reference_start: date
    reference_end: date
    by_therapeutic_class: dict[str, float]
    by_day_of_week: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable representation (used by ``--json-summary``)."""
        return {
            "strategy": self.strategy,
            "horizon_days": self.horizon_days,
            "mae": round(self.mae, 4),
            "rmse": round(self.rmse, 4),
            "mape": round(self.mape, 6),
            "bias": round(self.bias, 4),
            "observations": self.observations,
            "skipped_observations": self.skipped_observations,
            "series_scored": self.series_scored,
            "series_total": self.series_total,
            "mean_actual": round(self.mean_actual, 4),
            "mean_predicted": round(self.mean_predicted, 4),
            "evaluation_start": self.evaluation_start.isoformat(),
            "evaluation_end": self.evaluation_end.isoformat(),
            "evaluation_days": self.evaluation_days,
            "reference_start": self.reference_start.isoformat(),
            "reference_end": self.reference_end.isoformat(),
            "by_therapeutic_class": {key: round(value, 4) for key, value in self.by_therapeutic_class.items()},
            "by_day_of_week": {key: round(value, 4) for key, value in self.by_day_of_week.items()},
        }


# ---------------------------------------------------------------------------
# Order text synthesis
# ---------------------------------------------------------------------------


def corrupt_token(token: str, rng: np.random.Generator) -> str:
    """Introduce a realistic typing error (drop, swap, duplicate or vowel swap)."""
    if len(token) < 4:
        return token
    kind = int(rng.integers(0, 4))
    position = int(rng.integers(1, len(token) - 1))
    if kind == 0:  # drop a character — the classic Arabizi typo
        return token[:position] + token[position + 1 :]
    if kind == 1:  # swap two adjacent characters
        return token[:position] + token[position + 1] + token[position] + token[position + 2 :]
    if kind == 2:  # duplicate a character
        return token[:position] + token[position] + token[position:]
    vowels = "aeiou"
    for index in range(position, len(token)):
        if token[index] in vowels:
            replacement = str(rng.choice([v for v in vowels if v != token[index]]))
            return token[:index] + replacement + token[index + 1 :]
    return token + "e"


def _match_quality(rng: np.random.Generator) -> str:
    """Sample one of ``exact`` / ``fuzzy`` / ``ambiguous`` match outcomes."""
    draw = float(rng.random())
    cumulative = 0.0
    for quality, probability in MATCH_QUALITY_WEIGHTS.items():
        cumulative += probability
        if draw < cumulative:
            return quality
    return "exact"  # pragma: no cover - floating point safety net


def build_raw_token(spec: DrugSpec, quantity: int, quality: str, rng: np.random.Generator) -> str:
    """Compose the customer-facing fragment of text for one order line.

    ``exact`` lines are clean brand names; ``fuzzy`` lines carry typos or a
    wrong strength; ``ambiguous`` lines mix scripts and drop information.
    """
    if quality == "exact":
        style = float(rng.random())
        if style < 0.55:
            return f"{quantity} {spec.brand_name}"
        if style < 0.75:
            return f"{quantity} {spec.brand_name} {spec.strength}"
        if style < 0.90:
            return f"{quantity} {spec.franco_arabic}"
        return f"{quantity} {spec.arabic_name}"
    if quality == "fuzzy":
        style = float(rng.random())
        if style < 0.50:
            return f"{quantity} {corrupt_token(spec.brand_name.split()[0], rng)}"
        if style < 0.75:
            digits = "".join("Oo0" if character.isdigit() else character for character in spec.strength)
            return f"{quantity} {spec.brand_name.split()[0]} {digits}"
        return f"{quantity} {corrupt_token(spec.franco_arabic, rng)} {spec.form}"
    # ambiguous: mixed script, minimal information — exactly what an LLM re-rank
    # and then a human reviewer is needed for.
    style = float(rng.random())
    if style < 0.40:
        return f"{quantity} {spec.franco_arabic.split()[0][:4]} {spec.strength[:3]}"
    if style < 0.70:
        return f"{quantity} {corrupt_token(spec.brand_name.split()[0], rng)[:5]}"
    return f"{quantity} {spec.arabic_name} {spec.form}"


def build_match_outcome(
    spec: DrugSpec, quantity: int, rng: np.random.Generator
) -> tuple[str, float, str, bool]:
    """Return ``(raw_token, confidence, match_method, needs_review)``.

    Enforces the human-in-the-loop rule: ``needs_review`` is ``True`` if and
    only if ``confidence`` falls below the safety threshold.
    """
    quality = _match_quality(rng)
    raw_token = build_raw_token(spec, quantity, quality, rng)
    if quality == "exact":
        low, high = EXACT_CONFIDENCE_RANGE
        method = "exact"
    elif quality == "fuzzy":
        low, high = FUZZY_CONFIDENCE_RANGE
        method = "fuzzy"
    else:
        low, high = AMBIGUOUS_CONFIDENCE_RANGE
        method = "llm"
    confidence = round(float(rng.uniform(low, high)), 3)
    needs_review = confidence < REVIEW_CONFIDENCE_THRESHOLD
    return raw_token, confidence, method, needs_review


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def _basket_weights(
    catalogue: Sequence[DrugSpec], day: date, index: int, plan: ShockPlan
) -> np.ndarray:
    """Per-SKU sampling weights for a basket on ``day``.

    Weights combine the Zipf-sharpened static demand weight with seasonal
    pressure and the active demand shock, then normalise for ``numpy``'s
    ``choice``.  The resulting basket mix reproduces the real-world pattern of
    a handful of fast movers plus a long tail.
    """
    weights = np.array(
        [
            spec.demand_weight**ZIPF_EXPONENT
            * seasonal_multiplier(day, spec.therapeutic_class)
            * shock_multiplier(plan, index, spec.therapeutic_class)
            for spec in catalogue
        ],
        dtype=float,
    )
    total = weights.sum()
    if total <= 0:  # pragma: no cover - defensive
        return np.full(len(catalogue), 1.0 / len(catalogue))
    return weights / total


def _draw_quantity(category: str, rng: np.random.Generator) -> int:
    low, high = QUANTITY_RANGES.get(category, QUANTITY_RANGES[CATEGORY_OTC])
    return int(rng.integers(low, high + 1))


def _draw_order_count(expected: float, rng: np.random.Generator) -> int:
    """Draw the number of restock orders a pharmacy places on one day.

    Wholesale order counts are **overdispersed** (most days 1-2 orders, an
    occasional 5-6 order catch-up day), so a Negative Binomial with mean
    ``expected`` and dispersion :data:`NB_DISPERSION` is used instead of a
    Poisson.  The ``p = r / (r + mean)`` parameterisation is what
    ``numpy.random.Generator.negative_binomial`` expects.
    """
    if expected <= 0:
        return 0
    probability = NB_DISPERSION / (NB_DISPERSION + expected)
    return int(rng.negative_binomial(NB_DISPERSION, probability))


def _build_core_baskets(
    pharmacies: Sequence[Pharmacy], catalogue: Sequence[DrugSpec], random_seed: int
) -> dict[str, tuple[int, ...]]:
    """Assign each pharmacy its standing ("core") basket of regular SKUs.

    Real wholesalers and pharmacies reorder a stable set of staples nearly
    every day; modelling that standing order is what gives the demand panel
    continuous, learnable series instead of sparse salt-and-pepper zeros.
    Returned as ``{pharmacy_id: (catalogue_index, ...)}`` with unique SKUs.
    """
    rng = np.random.default_rng(random_seed ^ CORE_BASKET_SEED_SALT)
    static_weights = np.array([spec.demand_weight**ZIPF_EXPONENT for spec in catalogue], dtype=float)
    probabilities = static_weights / static_weights.sum()

    baskets: dict[str, tuple[int, ...]] = {}
    for pharmacy in pharmacies:
        size = int(min(len(catalogue), rng.poisson(CORE_BASKET_LAMBDA) + CORE_BASKET_MIN))
        picks = rng.choice(len(catalogue), size=size, replace=False, p=probabilities)
        baskets[pharmacy.pharmacy_id] = tuple(int(pick) for pick in picks)
    return baskets


def _draw_day_items(
    *,
    core_skus: Sequence[int],
    weights: np.ndarray,
    mean_shock: float,
    plan: ShockPlan,
    index: int,
    catalogue: Sequence[DrugSpec],
    rng: np.random.Generator,
) -> list[tuple[DrugSpec, int]]:
    """Build one pharmacy-day item list: standing staples + ad-hoc top-ups.

    * **Standing staples** — each core SKU is included with probability
      :data:`CORE_INCLUSION_PROBABILITY`, in a larger, week-supply quantity.
    * **Ad-hoc top-ups** — a Poisson number of extra SKUs drawn from the day's
      demand-weighted pool (seasonality and the active shock included).

    ``mean_shock`` is the mean shock multiplier across the catalogue on this
    day.  It depends only on the day, so the caller computes it once instead of
    once per pharmacy.
    """
    items: list[tuple[DrugSpec, int]] = []
    for sku_index in core_skus:
        if rng.random() >= CORE_INCLUSION_PROBABILITY:
            continue
        spec = catalogue[sku_index]
        # An epidemic makes pharmacies bulk up their standing orders, so the
        # core lines carry the full shock magnitude.
        quantity_scale = CORE_QUANTITY_SCALE * shock_multiplier(plan, index, spec.therapeutic_class)
        quantity = min(MAX_CORE_QUANTITY, int(_draw_quantity(spec.category, rng) * quantity_scale))
        items.append((spec, quantity))

    # Ad-hoc top-ups scale with the average shock, so an epidemic adds *volume*
    # rather than only reshuffling the basket.
    extra_count = int(min(MAX_ADHOC_ITEMS, rng.poisson(BASKET_POISSON_LAMBDA * mean_shock)))
    if extra_count > 0:
        picks = rng.choice(len(catalogue), size=extra_count, replace=False, p=weights)
        for pick in np.atleast_1d(picks):
            spec = catalogue[int(pick)]
            items.append((spec, _draw_quantity(spec.category, rng)))
    return items


def _partition(
    items: Sequence[tuple[DrugSpec, int]], groups: int, rng: np.random.Generator
) -> list[list[tuple[DrugSpec, int]]]:
    """Split one day's items into ``groups`` non-empty order batches.

    Items are shuffled first, so cutting the shuffled sequence into ``groups``
    roughly equal slices spreads the SKUs randomly across the orders the
    pharmacy places that day.
    """
    shuffled = list(items)
    rng.shuffle(shuffled)
    if groups <= 1:
        return [shuffled]
    if groups >= len(shuffled):
        return [[item] for item in shuffled]
    buckets: list[list[tuple[DrugSpec, int]]] = [[] for _ in range(groups)]
    for position, item in enumerate(shuffled):
        buckets[min(groups - 1, position * groups // len(shuffled))].append(item)
    return [bucket for bucket in buckets if bucket]


def _draw_timestamp(day: date, rng: np.random.Generator) -> datetime:
    """Draw a plausible Egyptian business-hour timestamp (stored as UTC)."""
    hour = int(rng.integers(ORDER_WINDOW_START_HOUR, ORDER_WINDOW_END_HOUR + 1))
    minute = int(rng.integers(0, 60))
    second = int(rng.integers(0, 60))
    local = datetime.combine(day, time(hour=hour, minute=minute, second=second), tzinfo=EGYPT_TZ)
    return local.astimezone(timezone.utc)


def generate_dataset(
    days: int = 180,
    random_seed: int = 42,
    *,
    end_date: date | None = None,
    pharmacies: Sequence[Pharmacy] | None = None,
    catalogue: Sequence[DrugSpec] | None = None,
    demand_shock: bool = False,
    shock_days: int = DEFAULT_SHOCK_DAYS,
    baseline_days: int | None = None,
) -> GeneratedData:
    """Generate the complete synthetic dataset in memory.

    The process is fully deterministic for a given ``(days, random_seed,
    demand_shock, shock_days)`` tuple — the same inputs always yield the same
    orders, UUIDs and units, which makes the seed reproducible in CI.

    Parameters
    ----------
    days:
        Length of the generated history, ending on ``end_date`` (inclusive).
    random_seed:
        Seed for the demand process.
    demand_shock:
        Multiply antibiotic and antipyretic volume by 3x-4x over the final
        ``shock_days`` of the window (epidemic scenario for drift testing).
    shock_days:
        Length of the shock window. Must be smaller than ``days``.
    baseline_days:
        Holdout length for the naive baseline (default: 20% of ``days``).
    """
    if days <= 0:
        raise ValueError("days must be positive")

    catalogue_tuple: tuple[DrugSpec, ...] = tuple(catalogue) if catalogue is not None else CURATED_DRUGS
    pharmacy_list: tuple[Pharmacy, ...] = tuple(pharmacies) if pharmacies is not None else tuple(
        build_pharmacies(PHARMACY_COUNT, random_seed)
    )
    if not catalogue_tuple:
        raise ValueError("catalogue must not be empty")
    if not pharmacy_list:
        raise ValueError("pharmacies must not be empty")

    plan = build_shock_plan(days, demand_shock, shock_days)
    final_day = end_date or datetime.now(tz=timezone.utc).date()
    start_day = final_day - timedelta(days=days - 1)
    panel = DemandPanel(catalogue_tuple, pharmacy_list, start_day, final_day)

    rng = np.random.default_rng(random_seed)
    orders: list[OrderRecord] = []
    all_items: list[OrderItemRecord] = []
    order_sequence = 0
    core_baskets = _build_core_baskets(pharmacy_list, catalogue_tuple, random_seed)

    for index, day in enumerate(panel.days):
        weights = _basket_weights(catalogue_tuple, day, index, plan)
        # Mean shock depends only on the day, so it is computed once here.
        mean_shock = float(
            np.mean([shock_multiplier(plan, index, spec.therapeutic_class) for spec in catalogue_tuple])
        )
        shared_day_factor = day_of_week_multiplier(day) * calendar_multiplier(day) * (1.0 + DAILY_GROWTH_RATE * index)
        shock_active = plan.enabled and index >= plan.start_index
        order_rate_factor = SHOCK_ORDER_RATE_MULTIPLIER if shock_active else 1.0

        for pharmacy in pharmacy_list:
            expected_orders = (
                BASE_ORDERS_PER_PHARMACY_DAY * pharmacy.volume_factor * shared_day_factor * order_rate_factor
            )
            order_count = _draw_order_count(expected_orders, rng)
            if order_count == 0:
                continue

            # Standing order (the pharmacy's regular staples) + ad-hoc top-ups.
            day_items = _draw_day_items(
                core_skus=core_baskets[pharmacy.pharmacy_id],
                weights=weights,
                mean_shock=mean_shock,
                plan=plan,
                index=index,
                catalogue=catalogue_tuple,
                rng=rng,
            )
            if not day_items:
                continue

            for batch in _partition(day_items, min(order_count, len(day_items)), rng):
                order_id = uuid.uuid5(
                    ID_NAMESPACE, f"order:{random_seed}:{pharmacy.pharmacy_id}:{day.isoformat()}:{order_sequence}"
                )
                order_sequence += 1
                item_records: list[OrderItemRecord] = []
                tokens: list[str] = []
                for pick_index, (spec, quantity) in enumerate(batch):
                    token, confidence, method, needs_review = build_match_outcome(spec, quantity, rng)
                    item_id = uuid.uuid5(ID_NAMESPACE, f"item:{order_id}:{pick_index}")
                    item_records.append(
                        OrderItemRecord(
                            item_id=item_id,
                            order_id=order_id,
                            raw_token=token,
                            catalogue_id=spec.catalogue_id,
                            catalogue_name=spec.display_name,
                            quantity=quantity,
                            confidence=confidence,
                            match_method=method,
                            needs_review=needs_review,
                        )
                    )
                    tokens.append(token)
                    panel.add_units(pharmacy.pharmacy_id, spec.catalogue_id, day, quantity)

                separator = str(rng.choice(ORDER_SEPARATORS))
                note = str(rng.choice(ORDER_NOTES))
                raw_text = separator.join(tokens)
                if note:
                    raw_text = f"{raw_text} ({note})"

                orders.append(
                    OrderRecord(
                        order_id=order_id,
                        pharmacy_id=pharmacy.pharmacy_id,
                        raw_text=raw_text,
                        created_at=_draw_timestamp(day, rng),
                        items=tuple(item_records),
                    )
                )
                all_items.extend(item_records)

    baseline = panel.evaluate_naive_baseline(baseline_days)
    logger.info(
        "Synthetic dataset generated (in memory)",
        extra={
            "days": days,
            "orders": len(orders),
            "order_items": len(all_items),
            "shock": plan.enabled,
            "naive_mae": round(baseline.mae, 4),
        },
    )
    return GeneratedData(
        catalogue=catalogue_tuple,
        pharmacies=pharmacy_list,
        orders=orders,
        items=all_items,
        panel=panel,
        start_date=start_day,
        end_date=final_day,
        random_seed=random_seed,
        shock=plan,
        baseline=baseline,
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

INSERT_CHUNK_SIZE: Final[int] = 2_000


async def seed_database(
    *,
    days: int = 180,
    random_seed: int = 42,
    end_date: date | None = None,
    demand_shock: bool = False,
    shock_days: int = DEFAULT_SHOCK_DAYS,
    truncate: bool = True,
    baseline_days: int | None = None,
    session: AsyncSession | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> SeedResult:
    """Generate the dataset and persist it to PostgreSQL.

    Uses one transaction for the whole seed so a failure leaves the database
    untouched.  Deterministic UUIDs make re-seeding idempotent when ``truncate``
    is enabled (the default), which is what CI and the test-suite rely on.

    Parameters
    ----------
    session:
        Use this already-open session instead of creating one.
    session_factory:
        Factory used to build the seeding session.  The test-suite passes one
        bound to the disposable ``clusterops_test`` database; when omitted the
        application-wide factory is used.
    """
    generated = generate_dataset(
        days=days,
        random_seed=random_seed,
        end_date=end_date,
        demand_shock=demand_shock,
        shock_days=shock_days,
        baseline_days=baseline_days,
    )

    catalogue_rows = [
        {
            "catalogue_id": spec.catalogue_id,
            "brand_name": spec.brand_name,
            "generic_name": spec.generic_name,
            "arabic_name": spec.arabic_name,
            "franco_arabic": spec.franco_arabic,
            "form": spec.form,
            "strength": spec.strength,
            "unit_price_egp": spec.unit_price_egp,
            "category": spec.category,
            "therapeutic_class": str(spec.therapeutic_class),
        }
        for spec in generated.catalogue
    ]

    if session is not None:
        await _persist(session, generated, catalogue_rows, truncate=truncate)
        return _build_seed_result(generated, persisted=True)

    factory = session_factory or async_session_factory
    async with factory() as owned_session:
        await _persist(owned_session, generated, catalogue_rows, truncate=truncate)
    return _build_seed_result(generated, persisted=True)


async def _persist(
    session: AsyncSession,
    generated: GeneratedData,
    catalogue_rows: Sequence[dict[str, Any]],
    *,
    truncate: bool,
) -> None:
    """Insert catalogue, orders and order items inside a single transaction."""
    if truncate:
        # Order matters only for readability: order_items is emptied through the
        # ON DELETE CASCADE on orders.
        for model in (OrderItem, Order, DrugCatalogue):
            await session.execute(delete(model))
        await session.flush()

    await session.execute(insert(DrugCatalogue), list(catalogue_rows))

    for chunk_start in range(0, len(generated.orders), INSERT_CHUNK_SIZE):
        chunk = generated.orders[chunk_start : chunk_start + INSERT_CHUNK_SIZE]
        await session.execute(
            insert(Order),
            [
                {
                    "id": record.order_id,
                    "pharmacy_id": record.pharmacy_id,
                    "raw_text": record.raw_text,
                    "created_at": record.created_at,
                }
                for record in chunk
            ],
        )
        await session.execute(
            insert(OrderItem),
            [
                {
                    "id": item.item_id,
                    "order_id": item.order_id,
                    "raw_token": item.raw_token,
                    "catalogue_id": item.catalogue_id,
                    "catalogue_name": item.catalogue_name,
                    "quantity": item.quantity,
                    "confidence": item.confidence,
                    "match_method": item.match_method,
                    "needs_review": item.needs_review,
                }
                for record in chunk
                for item in record.items
            ],
        )

    await session.commit()
    logger.info("Synthetic dataset committed", extra={"orders": len(generated.orders), "items": len(generated.items)})


@dataclass(frozen=True, slots=True)
class SeedResult:
    """Outcome of :func:`seed_database`, ready to be logged or serialised."""

    start_date: date
    end_date: date
    days: int
    random_seed: int
    persisted: bool
    catalogue_size: int
    pharmacy_count: int
    orders_created: int
    order_items_created: int
    needs_review_items: int
    total_units: int
    demand_shock: bool
    shock_start_date: date | None
    baseline: BaselineReport
    panel: DemandPanel = field(repr=False)

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable summary (used by ``--json-summary``)."""
        return {
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "days": self.days,
            "random_seed": self.random_seed,
            "persisted": self.persisted,
            "catalogue_size": self.catalogue_size,
            "pharmacy_count": self.pharmacy_count,
            "orders_created": self.orders_created,
            "order_items_created": self.order_items_created,
            "needs_review_items": self.needs_review_items,
            "total_units": self.total_units,
            "demand_shock": self.demand_shock,
            "shock_start_date": self.shock_start_date.isoformat() if self.shock_start_date else None,
            "baseline": self.baseline.to_dict(),
        }


def _build_seed_result(generated: GeneratedData, *, persisted: bool) -> SeedResult:
    shock_start = generated.start_date + timedelta(days=generated.shock.start_index) if generated.shock.enabled else None
    total_units = sum(item.quantity for item in generated.items)
    return SeedResult(
        start_date=generated.start_date,
        end_date=generated.end_date,
        days=len(generated.panel.days),
        random_seed=generated.random_seed,
        persisted=persisted,
        catalogue_size=len(generated.catalogue),
        pharmacy_count=len(generated.pharmacies),
        orders_created=len(generated.orders),
        order_items_created=len(generated.items),
        needs_review_items=sum(1 for item in generated.items if item.needs_review),
        total_units=total_units,
        demand_shock=generated.shock.enabled,
        shock_start_date=shock_start,
        baseline=generated.baseline,
        panel=generated.panel,
    )


# ---------------------------------------------------------------------------
# Console reporting
# ---------------------------------------------------------------------------


def format_summary(result: SeedResult, *, show_class_breakdown: bool = True) -> str:
    """Render a human-readable summary of a generation run."""
    baseline = result.baseline
    if result.demand_shock and result.shock_start_date is not None:
        shock_length = (result.end_date - result.shock_start_date).days + 1
        shock_text = f"enabled from {result.shock_start_date.isoformat()} ({shock_length} days, 3x-4x on antibiotics/antipyretics)"
    else:
        shock_text = "disabled"
    lines = [
        "",
        "=" * 78,
        " ClusterOps — synthetic Egyptian pharmaceutical dataset",
        " Synthetic data generated for demonstration purposes.",
        "=" * 78,
        f" Period                     : {result.start_date.isoformat()} .. {result.end_date.isoformat()} ({result.days} days)",
        f" Random seed                : {result.random_seed}",
        f" Catalogue SKUs             : {result.catalogue_size}",
        f" Synthetic pharmacies       : {result.pharmacy_count}",
        f" Orders generated           : {result.orders_created:,}",
        f" Order items generated      : {result.order_items_created:,}",
        f" Items routed to review     : {result.needs_review_items:,} (confidence < {REVIEW_CONFIDENCE_THRESHOLD})",
        f" Total units (all products) : {result.total_units:,}",
        f" Persisted to PostgreSQL    : {result.persisted}",
        f" Demand shock               : {shock_text}",
        "-" * 78,
        " Naive baseline — same day last week (chronological holdout)",
        f"   Strategy                 : {baseline.strategy}",
        f"   Reference window         : {baseline.reference_start.isoformat()} .. {baseline.reference_end.isoformat()}",
        f"   Evaluation window        : {baseline.evaluation_start.isoformat()} .. {baseline.evaluation_end.isoformat()} ({baseline.evaluation_days} days)",
        f"   Observations             : {baseline.observations:,} (skipped {baseline.skipped_observations:,} warm-up cells)",
        f"   Series scored            : {baseline.series_scored:,} of {baseline.series_total:,} active pharmacy/product series",
        f"   MAE                      : {baseline.mae:.4f} units",
        f"   RMSE                     : {baseline.rmse:.4f} units",
        f"   MAPE                     : {baseline.mape:.4%}",
        f"   Bias (pred - actual)     : {baseline.bias:+.4f} units",
        f"   Mean actual / predicted  : {baseline.mean_actual:.3f} / {baseline.mean_predicted:.3f}",
        f"   Promotion gate (3% rule) : a challenger must reach MAE < {baseline.mae * 0.97:.4f}",
        "-" * 78,
        " Naive MAE by day of week  : "
        + ", ".join(f"{day_name[:3]}={value:.2f}" for day_name, value in baseline.by_day_of_week.items()),
    ]
    if show_class_breakdown:
        class_totals = result.panel.class_totals()
        top = sorted(class_totals.items(), key=lambda item: item[1], reverse=True)[:8]
        lines.append(" Top classes by units       : " + ", ".join(f"{name}={value:,}" for name, value in top))
        worst_classes = sorted(baseline.by_therapeutic_class.items(), key=lambda item: item[1], reverse=True)[:5]
        lines.append(
            " Highest baseline MAE       : "
            + ", ".join(f"{name}={value:.2f}" for name, value in worst_classes)
        )
    lines.append("=" * 78)
    lines.append("")
    return "\n".join(lines)


def summarise_weekday_profile(panel: DemandPanel) -> list[tuple[str, float]]:
    """Average daily units per day-of-week — used to prove the weekend dip."""
    totals = panel.daily_totals()
    buckets: dict[int, list[int]] = defaultdict(list)
    for day, units in totals.items():
        buckets[day.weekday()].append(units)
    return [(DAY_NAMES[weekday], float(statistics.fmean(values))) for weekday, values in sorted(buckets.items())]


async def verify_database_row_counts(session: AsyncSession) -> dict[str, int]:
    """Return live row counts for every ClusterOps table (post-seed sanity check).

    ``predictions`` and ``drift_logs`` are populated by later phases, so zero is
    a valid result for them after Phase 1 seeding.
    """
    counts: dict[str, int] = {}
    for table_name, model in (
        ("drug_catalogue", DrugCatalogue),
        ("orders", Order),
        ("order_items", OrderItem),
        ("predictions", Prediction),
        ("drift_logs", DriftLog),
    ):
        result = await session.execute(sa_func.count().select_from(model))
        counts[table_name] = int(result.scalar_one())
    return counts


async def distinct_pharmacy_count(session: AsyncSession) -> int:
    """Number of distinct pharmacies present in ``orders``."""
    result = await session.execute(select(Order.pharmacy_id).distinct())
    return len({row[0] for row in result.all()})


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the ``python -m app.pipelines.data_generator`` argument parser."""
    parser = argparse.ArgumentParser(
        prog="python -m app.pipelines.data_generator",
        description=(
            "Generate the ClusterOps synthetic Egyptian pharmaceutical dataset. "
            "All output is synthetic and for demonstration purposes only."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Persist the generated dataset into PostgreSQL (default: dry run, database untouched).",
    )
    parser.add_argument("--days", type=int, default=settings.data_generation_days, help="History length in days.")
    parser.add_argument(
        "--random-seed", type=int, default=settings.data_random_seed, help="Seed of the demand process."
    )
    parser.add_argument(
        "--demand-shock",
        action="store_true",
        help="Multiply antibiotic/antipyretic volume by 3x-4x over the final window (drift simulation).",
    )
    parser.add_argument(
        "--shock-days",
        type=int,
        default=DEFAULT_SHOCK_DAYS,
        help="Length of the demand-shock window; must be smaller than --days.",
    )
    parser.add_argument(
        "--baseline-days",
        type=int,
        default=None,
        help="Holdout length for the naive baseline (default: 20%% of --days).",
    )
    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        default=None,
        help="Last calendar day of the generated window (default: today, UTC).",
    )
    parser.add_argument(
        "--truncate",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Delete existing synthetic rows before inserting (keeps re-seeding idempotent).",
    )
    parser.add_argument("--json-summary", type=Path, default=None, help="Write the run summary to this JSON file.")
    parser.add_argument("--log-level", default=settings.log_level, help="Logging level.")
    parser.add_argument("--quiet", action="store_true", help="Suppress the console summary.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point.  Returns a process exit code."""
    args = build_parser().parse_args(argv)
    configure_logging()
    logger.setLevel(args.log_level.upper())

    try:
        if args.seed:
            result = asyncio.run(
                seed_database(
                    days=args.days,
                    random_seed=args.random_seed,
                    end_date=args.end_date,
                    demand_shock=args.demand_shock,
                    shock_days=args.shock_days,
                    truncate=args.truncate,
                    baseline_days=args.baseline_days,
                )
            )
        else:
            generated = generate_dataset(
                days=args.days,
                random_seed=args.random_seed,
                end_date=args.end_date,
                demand_shock=args.demand_shock,
                shock_days=args.shock_days,
                baseline_days=args.baseline_days,
            )
            result = _build_seed_result(generated, persisted=False)
    except (ValueError, OSError) as exc:
        logger.error("Synthetic data generation failed", exc_info=True, extra={"error": str(exc)})
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not args.quiet:
        print(format_summary(result))

    if args.json_summary:
        args.json_summary.parent.mkdir(parents=True, exist_ok=True)
        args.json_summary.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
        logger.info("Summary written", extra={"path": str(args.json_summary)})

    if result.orders_created == 0:
        logger.error("Generator produced no orders", extra={"days": args.days})
        return 1
    return 0


__all__ = [
    "CATALOGUE_BY_ID",
    "CURATED_DRUGS",
    "DEFAULT_SHOCK_DAYS",
    "DAY_NAMES",
    "EGYPTIAN_HOLIDAYS",
    "EGYPT_TZ",
    "GOVERNORATES",
    "ID_NAMESPACE",
    "PHARMACY_COUNT",
    "PRIMARY_SHOCK_CLASSES",
    "PRIMARY_SHOCK_RANGE",
    "REVIEW_CONFIDENCE_THRESHOLD",
    "SECONDARY_SHOCK_CLASSES",
    "SECONDARY_SHOCK_RANGE",
    "SHOCK_RAMP_DAYS",
    "BaselineReport",
    "DemandPanel",
    "DrugSpec",
    "GeneratedData",
    "OrderItemRecord",
    "OrderRecord",
    "Pharmacy",
    "SeasonalPhase",
    "SeedResult",
    "ShockPlan",
    "TherapeuticClass",
    "build_match_outcome",
    "build_parser",
    "build_pharmacies",
    "build_raw_token",
    "build_shock_plan",
    "calendar_multiplier",
    "corrupt_token",
    "day_multiplier",
    "day_of_week_multiplier",
    "distinct_pharmacy_count",
    "format_summary",
    "generate_dataset",
    "gregorian_to_hijri",
    "gregorian_to_jdn",
    "holiday_for",
    "is_eid_al_adha",
    "is_eid_al_fitr",
    "is_ramadan",
    "main",
    "seed_database",
    "seasonal_multiplier",
    "seasonal_phase",
    "shock_multiplier",
    "summarise_weekday_profile",
    "verify_database_row_counts",
]


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())