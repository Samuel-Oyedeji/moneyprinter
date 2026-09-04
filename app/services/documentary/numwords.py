"""Deterministic digits-to-speech expansion for narration text.

TTS voices mispronounce bare digits, currency symbols and ordinals, so the
narration copy is expanded to spoken words before synthesis ("$2,000,000" →
"two million dollars", "844" → "eight hundred and forty-four", "24th" →
"twenty-fourth", "1915" → "nineteen fifteen"). This is done in Python, not
by an LLM: numbers are exactly the facts that must never drift.

Only the TTS text is expanded — the reviewed script and subtitles keep
digits for readability.
"""

import re

_ONES = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen",
]
_TENS = [
    "", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
    "eighty", "ninety",
]
_SCALES = [(10**9, "billion"), (10**6, "million"), (10**3, "thousand")]

_ORDINAL_ONES = {
    "one": "first", "two": "second", "three": "third", "five": "fifth",
    "eight": "eighth", "nine": "ninth", "twelve": "twelfth",
}

_CURRENCIES = {
    "$": ("dollar", "dollars"),
    "£": ("pound", "pounds"),
    "€": ("euro", "euros"),
    "₦": ("naira", "naira"),
}


def _under_thousand(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        word = _TENS[n // 10]
        return f"{word}-{_ONES[n % 10]}" if n % 10 else word
    word = f"{_ONES[n // 100]} hundred"
    if n % 100:
        word += f" and {_under_thousand(n % 100)}"
    return word


def int_to_words(n: int) -> str:
    if n < 0:
        return f"minus {int_to_words(-n)}"
    if n < 1000:
        return _under_thousand(n)
    parts = []
    remainder = n
    for scale, scale_word in _SCALES:
        if remainder >= scale:
            parts.append(f"{_under_thousand(remainder // scale)} {scale_word}")
            remainder %= scale
    if remainder:
        joiner = "and " if remainder < 100 else ""
        parts.append(f"{joiner}{_under_thousand(remainder)}")
    result = parts[0]
    for part in parts[1:]:
        result += (" " if part.startswith("and ") else ", ") + part
    return result


def ordinal_to_words(n: int) -> str:
    words = int_to_words(n)
    head, _, last = words.rpartition(" ")
    hyphen_head, _, hyphen_last = last.rpartition("-")
    target = hyphen_last
    if target in _ORDINAL_ONES:
        ordinal = _ORDINAL_ONES[target]
    elif target.endswith("y"):
        ordinal = target[:-1] + "ieth"
    else:
        ordinal = target + "th"
    rebuilt = f"{hyphen_head}-{ordinal}" if hyphen_head else ordinal
    return f"{head} {rebuilt}".strip()


def year_to_words(n: int) -> str:
    """Read a year the way a narrator would."""
    if 2000 <= n < 2010:
        return int_to_words(n)  # "two thousand and two"
    if 1000 <= n < 10000:
        high, low = divmod(n, 100)
        if low == 0:
            return f"{_under_thousand(high)} hundred"
        if low < 10:
            return f"{_under_thousand(high)} oh {_ONES[low]}"
        return f"{_under_thousand(high)} {_under_thousand(low)}"
    return int_to_words(n)


def _parse_int(text: str) -> int:
    return int(text.replace(",", ""))


def _scaled_amount(number_text: str, scale_word: str | None) -> tuple[str, bool]:
    """('two million', plural?) for an amount with an optional scale word."""
    if "." in number_text:
        whole, frac = number_text.split(".", 1)
        words = int_to_words(_parse_int(whole)) + " point " + " ".join(
            _ONES[int(d)] for d in frac if d.isdigit()
        )
        plural = True
    else:
        value = _parse_int(number_text)
        words = int_to_words(value)
        plural = value != 1
    if scale_word:
        words += f" {scale_word.lower()}"
        plural = True
    return words, plural


def _expand_currency(match: re.Match) -> str:
    singular, plural_form = _CURRENCIES[match.group("symbol")]
    words, plural = _scaled_amount(match.group("amount"), match.group("scale"))
    return f"{words} {plural_form if plural else singular}"


def _expand_ordinal(match: re.Match) -> str:
    return ordinal_to_words(_parse_int(match.group(1)))


def _expand_percent(match: re.Match) -> str:
    words, _ = _scaled_amount(match.group(1), None)
    return f"{words} per cent"


def _expand_decimal(match: re.Match) -> str:
    words, _ = _scaled_amount(match.group(0), None)
    return words


def _expand_decade(match: re.Match) -> str:
    words = year_to_words(int(match.group(1)))
    return words[:-1] + "ies" if words.endswith("y") else words + "s"


def _expand_integer(match: re.Match) -> str:
    text = match.group(0)
    value = _parse_int(text)
    # A bare four-digit number in period narration is almost always a year.
    if "," not in text and 1500 <= value <= 2099:
        return year_to_words(value)
    return int_to_words(value)


_CURRENCY_RE = re.compile(
    r"(?P<symbol>[$£€₦])\s?(?P<amount>\d[\d,]*(?:\.\d+)?)"
    r"(?:\s?(?P<scale>million|billion|thousand))?",
    re.IGNORECASE,
)
_ORDINAL_RE = re.compile(r"\b(\d[\d,]*)(?:st|nd|rd|th)\b")
_PERCENT_RE = re.compile(r"\b(\d[\d,]*(?:\.\d+)?)\s?(?:%|percent|per cent)")
_DECIMAL_RE = re.compile(r"\b\d[\d,]*\.\d+\b")
_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\b")
_DECADE_RE = re.compile(r"\b(\d{3}0)s\b")
_INTEGER_RE = re.compile(r"\b\d[\d,]*\b")


def expand_numbers(text: str) -> str:
    """Expand digits into spoken words, leaving clock times untouched."""
    # Protect times ("7:30") — TTS reads those correctly already.
    protected: list[str] = []

    def _protect(match: re.Match) -> str:
        # Letter-based token so the digit regexes below can't touch it.
        protected.append(match.group(0))
        return "\x00" + chr(ord("A") + len(protected) - 1) + "\x00"

    text = _TIME_RE.sub(_protect, text)
    text = _CURRENCY_RE.sub(_expand_currency, text)
    text = _ORDINAL_RE.sub(_expand_ordinal, text)
    text = _PERCENT_RE.sub(_expand_percent, text)
    text = _DECIMAL_RE.sub(_expand_decimal, text)
    text = _DECADE_RE.sub(_expand_decade, text)
    text = _INTEGER_RE.sub(_expand_integer, text)
    return re.sub(
        r"\x00([A-Za-z])\x00",
        lambda m: protected[ord(m.group(1)) - ord("A")],
        text,
    )
