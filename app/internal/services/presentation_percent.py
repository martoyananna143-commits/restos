"""Presentation-only percentage formatting shared by API/PDF projections.

Stored scoring values remain untouched.  This module is deliberately small and
strict: unsupported or non-finite values fail instead of being stringified.
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


class PresentationPercentInvalid(ValueError):
    pass


def rounded_percent(value: Decimal | str | int | float) -> int:
    """Return a display integer using the product ROUND_HALF_UP contract."""

    try:
        decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise PresentationPercentInvalid("percentage is invalid") from error
    if not decimal_value.is_finite():
        raise PresentationPercentInvalid("percentage must be finite")
    return int(decimal_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def format_percent(value: Decimal | str | int | float) -> str:
    return f"{rounded_percent(value)}%"


def format_percentage_points(value: Decimal | str | int | float) -> str:
    rounded = rounded_percent(value)
    sign = "+" if rounded > 0 else ""
    return f"{sign}{rounded} п.п."
