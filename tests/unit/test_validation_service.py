# tests/unit/test_validation_service.py
# ============================================================================
# Query Validation Tests
#
# Covers field allowlists, bounded filters, keys, and numeric aggregation rules.
# ============================================================================

from __future__ import annotations

import pytest

from app.domain.errors import QueryValidationError
from app.domain.models import AggregateFunction, AggregateMetric, FilterOperator, FilterSpec
from app.services.validation_service import QueryValidationService


def test_validate_text_filter_normalizes_ilike(orders_entity: object) -> None:
    validator = QueryValidationService()
    entity = orders_entity
    result = validator.validate_filters(
        entity,  # type: ignore[arg-type]
        [FilterSpec(field="status", operator=FilterOperator.ILIKE, value=" open ")],
    )

    assert result[0].value == "%open%"


def test_validate_filters_rejects_short_scan_pattern(orders_entity: object) -> None:
    validator = QueryValidationService()

    with pytest.raises(QueryValidationError, match="invalid_text_filter"):
        validator.validate_filters(  # type: ignore[arg-type]
            orders_entity,
            [FilterSpec(field="status", operator=FilterOperator.ILIKE, value="x")],
        )


def test_validate_fields_rejects_unexposed_field(orders_entity: object) -> None:
    with pytest.raises(QueryValidationError, match="field_not_allowed"):
        QueryValidationService().validate_fields(  # type: ignore[arg-type]
            orders_entity, ["id", "password_hash"]
        )


def test_validate_aggregation_requires_numeric_sum(orders_entity: object) -> None:
    validator = QueryValidationService()

    with pytest.raises(QueryValidationError, match="aggregate_field_not_numeric"):
        validator.validate_aggregation(  # type: ignore[arg-type]
            orders_entity,
            [AggregateMetric(function=AggregateFunction.SUM, field="status")],
            [],
        )

    metrics, groups = validator.validate_aggregation(  # type: ignore[arg-type]
        orders_entity,
        [AggregateMetric(function=AggregateFunction.SUM, field="total")],
        ["status"],
    )
    assert metrics[0].field == "total"
    assert groups == ["status"]
