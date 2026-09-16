# tests/unit/test_customer_lookup.py
# ============================================================================
# Customer Identifier Normalization Tests
#
# Covers exact identifier boundaries and rejected ambiguous or malicious input.
# ============================================================================

from __future__ import annotations

import pytest

from app.domain.errors import QueryValidationError
from app.services.customer_lookup_service import normalize_phone, normalize_plate, normalize_vin


@pytest.mark.parametrize(
    "value",
    [
        "+998 (90) 123-45-67",
        "00998901234567",
        "90 123 45 67",
        "998901234567",
    ],
)
def test_uzbek_phone_formats_have_one_identity(value: str) -> None:
    assert normalize_phone(value) == "998901234567"


def test_international_phone_keeps_country_code() -> None:
    assert normalize_phone("+44 20 7946 0958") == "442079460958"


def test_vehicle_identifiers_normalize_case_and_formatting() -> None:
    assert normalize_plate("01 a-123 bc") == "01A123BC"
    assert normalize_vin("1hgc-m82633a004352") == "1HGCM82633A004352"


@pytest.mark.parametrize("value", ["", "%", "123", "abc998901234567", "0" * 12, "1" * 65])
def test_phone_rejects_partial_and_non_phone_input(value: str) -> None:
    with pytest.raises(QueryValidationError, match="invalid_phone"):
        normalize_phone(value)


@pytest.mark.parametrize("value", ["", "01%", "01_A_123_BC", "01А123ВС", "x';DROP TABLE users--"])
def test_plate_rejects_wildcards_and_ambiguous_alphabets(value: str) -> None:
    with pytest.raises(QueryValidationError, match="invalid_plate_number"):
        normalize_plate(value)


@pytest.mark.parametrize(
    "value", ["", "1HGCM82633A00435", "1HGCM82633A0043520", "I" * 17, "Q" * 17]
)
def test_vin_requires_complete_standard_identifier(value: str) -> None:
    with pytest.raises(QueryValidationError, match="invalid_vin"):
        normalize_vin(value)
