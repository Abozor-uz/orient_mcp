# tests/unit/test_orient_policy.py
# ============================================================================
# Orient Policy Regression Tests
#
# Checks business discovery and rejection of credentials and operational logs.
# ============================================================================

from pathlib import Path

import pytest

from app.infrastructure.policy import CatalogPolicy


@pytest.mark.parametrize("entity", ["users", "carwash_carwashorder", "auction", "car"])
def test_business_entity_is_available(entity: str) -> None:
    policy = CatalogPolicy.load(Path("config/catalog_overrides.yaml"), ["public"])
    assert policy.allows_entity(f"public.{entity}")


@pytest.mark.parametrize(
    "entity", ["django_session", "firebase_token", "pg_stat_statements", "message"]
)
def test_secret_bearing_entities_are_hidden(entity: str) -> None:
    policy = CatalogPolicy.load(Path("config/catalog_overrides.yaml"), ["public"])
    assert not policy.allows_entity(f"public.{entity}")


@pytest.mark.parametrize(
    "field", ["password", "access_token", "card_number", "sms_code", "payload", "code"]
)
def test_user_secrets_are_hidden(field: str) -> None:
    policy = CatalogPolicy.load(Path("config/catalog_overrides.yaml"), ["public"])
    assert not policy.allows_field("public.users", field)


def test_business_aliases_and_contact_identifiers_are_available() -> None:
    policy = CatalogPolicy.load(Path("config/catalog_overrides.yaml"), ["public"])
    assert "мойки" in policy.aliases("public.carwash_carwashorder")
    for field in ("username", "phone", "full_name"):
        assert policy.allows_field("public.users", field)
    for field in ("owner_id", "business_owner_id", "win_number", "plate_number"):
        assert policy.allows_field("public.business_account_garagecar", field)


@pytest.mark.parametrize(
    "field",
    [
        "pinpp",
        "PinPp",
        "owner_pinpp",
        "pinpp_hash",
        "pnfl",
        "PNFL",
        "prev_pnfl",
        "customer_pnfl_value",
        "extra_data",
        "Extra_Data",
        "owner_extra_data",
        "extra_data_backup",
    ],
)
def test_sensitive_identity_and_unstructured_fields_are_hidden_in_every_schema(field: str) -> None:
    policy = CatalogPolicy.load(Path("config/catalog_overrides.yaml"), ["public", "garage_export"])
    for entity in ("public.business_account_garagecar", "garage_export.vehicle_export"):
        assert not policy.allows_field(entity, field)
