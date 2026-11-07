"""Decimal-only Invoice Processing calculations.

Workbook equivalents:
* line invoice/verified total = quantity × number of days × unit price, where
  the day count is 1 unless the IDVS shows the "No. of days" column;
* line and sheet difference = invoice − actual/contract;
* tax = subtotal × configured rate, with additions and deductions signed;
* adjusted verified amount = verified total − disallowed − advance;
* each payment split = adjusted verified amount × percentage × explicit FX rate.

Different output currencies stay on separate payment-split rows and are never
added together. Values retain the application's ten-decimal storage precision;
presentation layers may show two decimals without changing these calculations.
"""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Protocol

ZERO = Decimal("0")
HUNDRED = Decimal("100")
QUANT = Decimal("0.0000000001")


def decimal(value: Decimal | str | int | None) -> Decimal:
    if value in (None, ""):
        return ZERO
    return value if isinstance(value, Decimal) else Decimal(str(value))


def money(value: Decimal | str | int) -> Decimal:
    return decimal(value).quantize(QUANT, rounding=ROUND_HALF_UP)


def signed_tax(subtotal: Decimal, rate_percent: Decimal, direction: str) -> Decimal:
    amount = money(subtotal * rate_percent / HUNDRED)
    return amount if direction == "addition" else -amount


def payment_due_date(invoice_date: date, tenure_days: int) -> date:
    """The user's invoice-term rule: Invoice Date + payment tenure days."""
    return invoice_date + timedelta(days=tenure_days)


class LineLike(Protocol):
    invoice_quantity: Decimal
    invoice_days: Decimal
    invoice_unit_price: Decimal
    verified_quantity: Decimal
    verified_days: Decimal
    verified_unit_price: Decimal
    invoice_total: Decimal
    verified_total: Decimal
    difference_amount: Decimal


class TaxLike(Protocol):
    rate_percent: Decimal
    direction: str
    invoice_amount: Decimal
    verified_amount: Decimal


class SplitLike(Protocol):
    percentage: Decimal
    exchange_rate: Decimal
    amount: Decimal


def calculate_idvs(
    lines: Iterable[LineLike],
    taxes: Iterable[TaxLike],
    splits: Iterable[SplitLike],
    disallowed_amount: Decimal,
    advance_amount: Decimal,
) -> dict[str, Decimal]:
    """Populate row calculations and return the header's calculated columns."""
    invoice_subtotal = ZERO
    verified_subtotal = ZERO
    for line in lines:
        line.invoice_total = money(line.invoice_quantity * line.invoice_days * line.invoice_unit_price)
        line.verified_total = money(line.verified_quantity * line.verified_days * line.verified_unit_price)
        line.difference_amount = money(line.invoice_total - line.verified_total)
        invoice_subtotal += line.invoice_total
        verified_subtotal += line.verified_total
    invoice_subtotal = money(invoice_subtotal)
    verified_subtotal = money(verified_subtotal)

    invoice_tax_total = ZERO
    verified_tax_total = ZERO
    for tax in taxes:
        # The persisted tax amounts are unsigned; direction supplies the sign in totals.
        tax.invoice_amount = money(invoice_subtotal * tax.rate_percent / HUNDRED)
        tax.verified_amount = money(verified_subtotal * tax.rate_percent / HUNDRED)
        invoice_tax_total += signed_tax(invoice_subtotal, tax.rate_percent, tax.direction)
        verified_tax_total += signed_tax(verified_subtotal, tax.rate_percent, tax.direction)
    invoice_tax_total = money(invoice_tax_total)
    verified_tax_total = money(verified_tax_total)
    invoice_total = money(invoice_subtotal + invoice_tax_total)
    verified_total = money(verified_subtotal + verified_tax_total)
    adjusted = money(verified_total - disallowed_amount - advance_amount)
    for split in splits:
        split.amount = money(adjusted * split.percentage / HUNDRED * split.exchange_rate)
    return {
        "invoice_subtotal": invoice_subtotal,
        "verified_subtotal": verified_subtotal,
        "invoice_tax_total": invoice_tax_total,
        "verified_tax_total": verified_tax_total,
        "invoice_total": invoice_total,
        "verified_total": verified_total,
        "adjusted_verified_amount": adjusted,
        "difference_amount": money(invoice_total - verified_total),
    }
