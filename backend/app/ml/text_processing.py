"""Text normalisation and token extraction for Egyptian pharmacy orders.

Pharmacy orders arrive as free text written by pharmacists and customers::

    "10 panadol and 5 augmentn 625, 2 boxes brufen 400"
    "عشرة علب بنادول وخمسة اوجمنتين ٦٢٥"
    "2 banadol azra2 w 1 cataflam 50"

Before any string similarity is computed, that text has to be reduced to the
parts that actually identify a product: a **quantity**, an optional **unit**,
and the **drug token** itself.  This module owns that step and nothing else —
matching lives in :mod:`app.ml.order_matcher`.

Design notes
------------
* **Both numeral systems.** Western digits (0-9) *and* Arabic-Indic digits are
  understood, in the quantity or embedded in the token (``٦٢٥`` is the strength
  of Augmentin 625).
* **Arabic number words** (``عشرة`` = 10, ``خمسة`` = 5 …) are converted, because
  that is how orders are actually dictated over the phone.
* **Egyptian Arabizi pack modifiers** (``ازرا2`` / ``azra2`` / ``ahmar``)
  describe the pack variant, not the medicine, so they are stripped from the
  token and kept as metadata for auditability.
* Every vocabulary below is stored **already normalised**, because membership is
  tested against normalised input.  Keeping the literals human-readable while
  comparing normalised forms is the whole point of :func:`normalize`.

Synthetic data only — this module operates on generated or customer-supplied
free text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final

# ---------------------------------------------------------------------------
# Normalisation
#
# Defined before the vocabulary: the word lists are normalised *with* it, so
# membership tests can never disagree with the strings being tested.
# ---------------------------------------------------------------------------

#: Arabic-Indic (٠-٩) and Eastern Arabic-Indic (۰-۹) digits -> Western.
ARABIC_INDIC_DIGITS: Final[dict[str, str]] = {
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
    "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
    "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
}

#: Arabic vowel marks and tatweel: typed by customers, absent from catalogues.
_ARABIC_DIACRITICS: Final[frozenset[str]] = frozenset(
    {"ـ", "ً", "ٌ", "ٍ", "َ", "ُ", "ِ", "ّ", "ْ", "ٰ"}
)

#: Letter variants Egyptians interchange when typing.
_ARABIC_LETTER_FOLD: Final[dict[int, str]] = str.maketrans(
    {
        "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ٲ": "ا",
        "ة": "ه", "ى": "ي", "ئ": "ي", "ؤ": "و", "ء": "",
    }
)


def convert_arabic_numerals(text: str) -> str:
    """Replace Arabic-Indic digits with Western ones (``٦٢٥`` -> ``625``)."""
    return "".join(ARABIC_INDIC_DIGITS.get(character, character) for character in text)


def strip_diacritics(text: str) -> str:
    """Remove Arabic vowel marks and tatweel, keeping the base letters."""
    return "".join(character for character in text if character not in _ARABIC_DIACRITICS)


def normalize_arabic_letters(text: str) -> str:
    """Fold interchangeable Arabic letter variants.

    ``أ/إ/آ`` -> ``ا``, ``ة`` -> ``ه``, ``ى`` -> ``ي``.  This is the single
    highest-value normalisation for Arabizi input: it lets ``اوجمنتين`` match
    the catalogue's ``أوجمنتين``.
    """
    return text.translate(_ARABIC_LETTER_FOLD)


def normalize(text: str) -> str:
    """Canonical form used for every string comparison in the matcher.

    Lowercase, diacritic-free, letter-folded, Western numerals, punctuation
    reduced to single spaces.  Applied identically to catalogue fields and to
    incoming tokens.
    """
    if not text:
        return ""
    folded = convert_arabic_numerals(str(text)).lower()
    folded = strip_diacritics(folded)
    folded = normalize_arabic_letters(folded)
    folded = folded.replace("-", " ").replace("/", " ").replace(".", " ")
    folded = re.sub(r"[^\w\s؀-ۿ]+", " ", folded, flags=re.UNICODE)
    return re.sub(r"\s+", " ", folded).strip()


def tokenize(text: str) -> list[str]:
    """Split normalised text into comparison tokens."""
    return [token for token in normalize(text).split(" ") if token]


def _normalized_set(words: object) -> frozenset[str]:
    """Normalise a literal vocabulary so membership matches normalised input."""
    return frozenset(normalize(word) for word in words)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Vocabulary (stored normalised)
# ---------------------------------------------------------------------------

#: Arabic number words used when an order is dictated rather than typed.
_RAW_ARABIC_NUMBER_WORDS: Final[dict[str, int]] = {
    "صفر": 0, "واحد": 1, "اثنان": 2, "اثنين": 2, "ثلاثة": 3, "تلاتة": 3,
    "اربعه": 4, "اربعاء": 4, "خمسة": 5, "خمسه": 5, "سته": 6, "ستة": 6,
    "سبعه": 7, "سبعة": 7, "ثمانيه": 8, "ثمانية": 8, "تسعه": 9, "تسعة": 9,
    "عشره": 10, "عشرة": 10, "عشر": 10, "خمسه عشر": 15, "عشرين": 20,
    "ثلاثين": 30, "اربعين": 40, "خمسين": 50, "ستين": 60, "سبعين": 70,
    "ثمانين": 80, "تسعين": 90, "مائه": 100, "مئة": 100,
}

#: Public, normalised view of the number words.
ARABIC_NUMBER_WORDS: Final[dict[str, int]] = {
    normalize(word): value for word, value in _RAW_ARABIC_NUMBER_WORDS.items()
}

#: Lookup used against raw segment text: diacritics stripped, **longest match
#: first** so "خمسه عشر" (15) wins over "خمسه" (5).
_ARABIC_NUMBER_LOOKUP: Final[tuple[tuple[str, int], ...]] = tuple(
    sorted(
        ((strip_diacritics(word), value) for word, value in _RAW_ARABIC_NUMBER_WORDS.items()),
        key=lambda item: len(item[0]),
        reverse=True,
    )
)

#: Unit words, bilingual — "boxes" and "علب" are the same instruction.
UNIT_WORDS: Final[frozenset[str]] = _normalized_set(
    {
        # English
        "box", "boxes", "bx", "strip", "strips", "pack", "packs", "packet",
        "packets", "tab", "tabs", "tablet", "tablets", "cap", "caps", "capsule",
        "capsules", "bottle", "bottles", "btl", "tube", "tubes", "sachet",
        "sachets", "vial", "vials", "amp", "amps", "ampoule", "ampoules",
        "carton", "cartons", "pcs", "piece", "pieces", "unit", "units", "dose",
        "doses", "can", "cans", "jar", "kit", "set", "sets", "sheet", "sheets",
        # Arabic
        "علب", "علبة", "علبتان", "علبتين", "علبه", "قلم", "اقراص", "أقراص",
        "كبسولات", "كبسولة", "كبسوله", "زجاجة", "زجاجات", "انبوب", "أنبوب",
        "انابيب", "أنابيب", "حقن", "امبول", "أمبول", "امبولات", "أمبولات",
        "خرطوشة", "خرطوشات", "شريط", "شرائط", "شرايط", "فلوس", "ظروف",
        "كيس", "كرتون",
    }
)

#: Egyptian pack modifiers — they describe the *variant*, not the medicine.
PACK_MODIFIERS: Final[frozenset[str]] = _normalized_set(
    {
        # colours, Arabic script
        "ازرا2", "ازرق", "ازرقاء", "الازرق", "الازرقاء", "احمر", "الاحمر",
        "اخضر", "الاخضر", "اصفر", "الاصفر", "ابيض", "الابيض", "وردي",
        "بني", "بنفسجي", "اسود", "الاسود",
        # colours, Arabizi (how Egyptians actually type them)
        "azra2", "azrak", "azraa", "ahmar", "akhadar", "akhdar", "asfar",
        "abyad", "aboyad", "ward", "wardi", "bani", "aswad",
        # sizes
        "كبير", "كبيره", "akbar", "kbir", "صغير", "صغيره", "sghir", "saghir", "وسط",
        # pack counts / formats
        "6", "60", "10", "20", "30", "12", "24", "pack", "علبة",
        "الاصلي", "اصلي", "original", "اورجinal", "genuine",
    }
)

#: Filler words that must never become part of a drug token.
STOP_WORDS: Final[frozenset[str]] = _normalized_set(
    {
        "and", "or", "with", "plus", "w", "of", "the", "a", "an", "for", "to",
        "from", "please", "urgent", "need", "want", "send", "order", "orderly",
        "qty", "quantity", "x", "total", "each", "per", "stock", "available",
        "credit", "terms", "delivery", "deliver", "same", "am", "pm", "urs",
        "من", "الى", "الي", "على", "في", "مع", "و", "يا", "لو", "سمحت",
        "برجاء", "محتاج", "عايز", "ابعت", "بدون", "بديل", "صباحا", "مساء",
        "بد", "او", "كم", "كام", "الكمية", "العدد", "علي", "عندنا", "متوفر",
    }
)

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

#: Separators between order lines.
#:
#: ``/`` only separates when *surrounded by whitespace*, because a dose written
#: as ``100mg/5ml`` or a strength like ``800/160mg`` must stay on one line.
#: The Arabic conjunction is split on even without surrounding spaces:
#: "بنادول وخمسة" (Panadol and five) is how that line break is written.
SEPARATOR_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:\s*[,;+\n\r]\s*|\s+/\s+|\s+(?:and|or|with|plus|ثم|بعدها)\s+|(?:^|\s)و\s*)",
    re.IGNORECASE | re.UNICODE,
)

#: Leading quantity.  Only the number (plus trailing whitespace) is consumed —
#: the unit is resolved separately against :data:`UNIT_WORDS`, because a greedy
#: "optional word" group swallows the drug name ("10 panadol" would become "").
_QUANTITY_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(?P<number>\d{1,5}(?:[.,]\d{1,4})?)\s*", re.UNICODE
)

#: Arabic-script word at the start of a segment, behind an optional "و".
_ARABIC_WORD_PATTERN: Final[re.Pattern[str]] = re.compile(r"^(?:و\s+)?(?P<word>[؀-ۿ]+)")

_LEADING_PUNCTUATION: Final[str] = ".:!?،-—"

_WHITESPACE: Final[re.Pattern[str]] = re.compile(r"\s+")
_WORD_AT_START: Final[re.Pattern[str]] = re.compile(r"^(\S+)\s+")
_NON_WORD: Final[re.Pattern[str]] = re.compile(r"[^\w\s؀-ۿ]+", re.UNICODE)


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OrderToken:
    """One parsed order line: how many, of what unit, of which product.

    Attributes
    ----------
    quantity:
        Parsed quantity, or ``1`` when the line carried none.
    unit:
        Normalised unit word (``box``, ``strip``, …) when present.
    raw_token:
        Drug text with quantity, unit and pack modifiers removed — what the
        matcher scores against the catalogue.
    original:
        The original slice of ``raw_text`` this token came from.
    modifiers:
        Pack modifiers that were stripped, kept for auditability.
    """

    quantity: int
    unit: str | None
    raw_token: str
    original: str
    modifiers: tuple[str, ...] = ()
    source_span: tuple[int, int] = field(default=(0, 0), compare=False)

    def __str__(self) -> str:
        unit = f"{self.unit} " if self.unit else ""
        return f"{self.quantity} {unit}{self.raw_token}".strip()


def strip_stop_words(text: str) -> str:
    """Remove filler words that would otherwise dilute the similarity score."""
    return " ".join(
        word for word in tokenize(text) if word not in STOP_WORDS and word not in UNIT_WORDS
    )


def _arabic_number_at(text: str, position: int) -> tuple[int, int]:
    """Return ``(value, end_index)`` for an Arabic number word at ``position``.

    Longest match wins, so ``خمسه عشر`` is read as 15 rather than 5.
    """
    for word, value in _ARABIC_NUMBER_LOOKUP:
        if text.startswith(word, position):
            return value, position + len(word)
    return 0, position


def _strip_leading_filler(segment: str) -> str:
    """Drop leading politeness/urgency words so the quantity can be found.

    ``"urgent: 4 Ventolin inhaler"`` and ``"محتاج ٣ بنادول"`` both hide the
    number behind a filler word.
    """
    working = segment.strip()
    changed = True
    while changed:
        changed = False
        stripped = working.lstrip(_LEADING_PUNCTUATION)
        if stripped != working:
            working, changed = stripped, True
        match = _WORD_AT_START.match(working)
        if match and normalize(match.group(1)) in STOP_WORDS:
            working, changed = working[match.end() :].strip(), True
    return working


def extract_tokens(raw_text: str) -> list[OrderToken]:
    """Split a raw order into parsed lines.

    Handles Western and Arabic-Indic numerals, Arabic number words, bilingual
    unit words, and ``و`` / ``and`` / ``+`` / ``,`` separators.  Text with no
    separator is treated as a single line.

    Parameters
    ----------
    raw_text:
        Free-form order text.  ``None``, empty or whitespace is accepted and
        yields an empty list rather than raising.

    Returns
    -------
    list[OrderToken]
        One token per order line, in the order they appear.  Lines that contain
        no product (e.g. a bare "please") are dropped; lines that are made
        *entirely* of units ("3 boxes") are kept so the matcher can flag them
        for review instead of silently losing the line.
    """
    if raw_text is None or not str(raw_text).strip():
        return []

    text = strip_diacritics(convert_arabic_numerals(str(raw_text)))
    segments = [segment for segment in SEPARATOR_PATTERN.split(text) if segment and segment.strip()]
    if not segments:
        return []

    tokens: list[OrderToken] = []
    offset = 0
    for segment in segments:
        start = text.find(segment, offset)
        offset = start + len(segment) if start >= 0 else offset
        token = _parse_segment(segment)
        if token is None:
            continue
        tokens.append(
            OrderToken(
                quantity=token.quantity,
                unit=token.unit,
                raw_token=token.raw_token,
                original=token.original,
                modifiers=token.modifiers,
                source_span=(start, start + len(segment)),
            )
        )
    return tokens


def _parse_segment(segment: str) -> OrderToken | None:
    """Parse one separator-delimited line into an :class:`OrderToken`."""
    working = _strip_leading_filler(segment)
    if not working:
        return None

    quantity = 1
    unit: str | None = None

    # 1. Arabic number word, optionally behind the "و" conjunction.
    arabic_match = _ARABIC_WORD_PATTERN.match(working)
    if arabic_match:
        value, end = _arabic_number_at(working, arabic_match.start("word"))
        if value:
            quantity = value
            # Everything up to `end` was "و" plus the number word.
            working = working[end:].strip()

    # 2. Western / Arabic-Indic digits.
    if quantity == 1:
        quantity_match = _QUANTITY_PATTERN.match(working)
        if quantity_match:
            digits = quantity_match.group("number").replace(",", "")
            if digits.isdigit():
                quantity = int(digits)
                working = working[quantity_match.end() :].strip()

    # 3. Unit word, at either end of the line.
    words = working.split()
    while words and normalize(words[0]) in UNIT_WORDS:
        unit = normalize(words[0])
        words = words[1:]
    while words and normalize(words[-1]) in UNIT_WORDS:
        unit = unit or normalize(words[-1])
        words = words[:-1]

    # 4. Split off pack modifiers ("banadol azra2" -> "banadol" + modifier).
    modifiers: list[str] = []
    kept: list[str] = []
    for word in words:
        normalized_word = normalize(word)
        if normalized_word in PACK_MODIFIERS:
            modifiers.append(normalized_word)
        else:
            kept.append(word)

    drug_token = " ".join(kept).strip()
    if not drug_token:
        # Everything was a unit or modifier (e.g. "3 boxes"): keep the raw words
        # so the matcher's low-confidence path can flag the line for review
        # instead of silently dropping it.
        drug_token = " ".join(words).strip()
    if not drug_token:
        return None
    if not strip_stop_words(drug_token):
        # Nothing but filler ("please") — there is no product to match.
        return None

    return OrderToken(
        quantity=quantity,
        unit=unit,
        raw_token=drug_token,
        original=segment.strip(),
        modifiers=tuple(modifiers),
    )


__all__ = [
    "ARABIC_INDIC_DIGITS",
    "ARABIC_NUMBER_WORDS",
    "PACK_MODIFIERS",
    "STOP_WORDS",
    "UNIT_WORDS",
    "OrderToken",
    "convert_arabic_numerals",
    "extract_tokens",
    "normalize",
    "normalize_arabic_letters",
    "strip_diacritics",
    "strip_stop_words",
    "tokenize",
]