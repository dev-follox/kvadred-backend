from ..constants import PLATFORM_FEE_RATE


def compute_sale_amounts(quantity: int, price_per_item: float, bonus_percent: float) -> tuple[float, float, float]:
    """Returns (line_revenue, designer_bonus, platform_fee)."""
    line = round(float(quantity) * float(price_per_item), 2)
    designer_bonus = round(line * float(bonus_percent) / 100.0, 2)
    platform_fee = round(line * PLATFORM_FEE_RATE, 2)
    return line, designer_bonus, platform_fee
