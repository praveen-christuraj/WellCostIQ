"""Shared decimal entry and storage contract; round derived values at their result boundary."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from pydantic import Field, PlainSerializer

DECIMAL_PLACES = 3
DECIMAL_QUANT = Decimal('0.001')


def rounded(value: Decimal) -> Decimal:
    return value.quantize(DECIMAL_QUANT, rounding=ROUND_HALF_UP)


def plain_decimal(value: Decimal) -> str:
    return format(value, 'f')


# Preserve the existing integral limits (16 digits for common inputs, 10 for days).
Decimal3 = Annotated[
    Decimal, Field(max_digits=16 + DECIMAL_PLACES, decimal_places=DECIMAL_PLACES),
    PlainSerializer(plain_decimal, return_type=str, when_used='json'),
]
Decimal3Days = Annotated[
    Decimal, Field(max_digits=10 + DECIMAL_PLACES, decimal_places=DECIMAL_PLACES),
    PlainSerializer(plain_decimal, return_type=str, when_used='json'),
]
