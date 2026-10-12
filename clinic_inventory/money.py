"""Money storage strategy.

All money is stored as INTEGERS in units of 1/10,000 EGP ("e4"):
    1 EGP = 10_000 units.
This keeps unit costs such as 0.5375 EGP exact (a box of 40 bought for 21.50)
while avoiding floats entirely. Quantities are whole numbers of stock units.
Rounding to 2 decimals (piastres) happens ONLY when displaying, using
ROUND_HALF_UP, never inside stored values.
"""
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

SCALE = 10_000


def to_e4(value) -> int:
    """Convert EGP (str/int/Decimal; floats rejected) to integer e4 units."""
    if isinstance(value, float):
        raise TypeError("floats are not allowed for money")
    try:
        d = Decimal(str(value).strip().replace(",", ""))
    except InvalidOperation:
        raise ValueError("invalid money value")
    return int((d * SCALE).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def to_decimal(e4: int) -> Decimal:
    return Decimal(e4) / SCALE


def fmt_egp(e4: int, arabic_digits: bool = False) -> str:
    d = to_decimal(e4).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    s = f"{d:,.2f} جنيه"
    if arabic_digits:
        s = s.translate(str.maketrans("0123456789,.", "٠١٢٣٤٥٦٧٨٩٬٫"))
    return s
