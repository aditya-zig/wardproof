"""Conservative demographic generalisation for research releases."""
from decimal import Decimal, InvalidOperation
import re


def age_band(value):
    """Return a five-year age range; never emit an exact age."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        age = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not age.is_finite() or age < 0 or age > 125:
        return None
    lower = (int(age) // 5) * 5
    return f"{lower}-{lower + 4}"


_GENDERS = {"m": "M", "male": "Male", "f": "F", "female": "Female",
            "other": "Other", "unknown": "Unknown", "पुरुष": "पुरुष",
            "महिला": "महिला", "अन्य": "अन्य"}


def gender_category(value):
    if not isinstance(value, str):
        return ""
    return _GENDERS.get(value.strip().casefold(), "")


def district_label(value):
    """Retain only a short administrative label, never a free-form address."""
    if not isinstance(value, str):
        return ""
    value = " ".join(value.split())
    if 2 <= len(value) <= 64 and not any(ch.isdigit() for ch in value) and re.fullmatch(r"[\w .'-]+", value, re.UNICODE):
        return value
    return ""
