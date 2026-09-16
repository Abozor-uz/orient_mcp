# app/services/validation_service.py
# ============================================================================
# Structured Query Validation
#
# Enforces the bounded generic-tool contract before any dynamic SQL reaches the
# repository layer.
# ============================================================================

from __future__ import annotations

import re
from typing import Any

from app.domain.errors import QueryValidationError
from app.domain.models import (
    AggregateFunction,
    AggregateMetric,
    EntityInfo,
    FilterOperator,
    FilterSpec,
    RelationInfo,
    SortSpec,
)

_ALIAS_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")


class QueryValidationService:
    def validate_fields(self, entity: EntityInfo, fields: list[str]) -> list[str]:
        if not fields or len(fields) > 30 or len(fields) != len(set(fields)):
            raise QueryValidationError("invalid_fields")
        available = {field.name for field in entity.fields}
        if not set(fields).issubset(available):
            raise QueryValidationError("field_not_allowed")
        return fields

    def validate_filters(self, entity: EntityInfo, filters: list[FilterSpec]) -> list[FilterSpec]:
        if len(filters) > 5:
            raise QueryValidationError("too_many_filters")
        field_map = {field.name: field for field in entity.fields}
        validated: list[FilterSpec] = []
        for raw_item in filters:
            item = raw_item.model_copy(deep=True)
            field = field_map.get(item.field)
            if field is None:
                raise QueryValidationError("filter_field_not_allowed")
            if item.operator == FilterOperator.ILIKE:
                if (
                    not field.is_text
                    or not isinstance(item.value, str)
                    or len(item.value.strip()) < 3
                ):
                    raise QueryValidationError("invalid_text_filter")
                item.value = f"%{item.value.strip()}%"
            elif item.operator == FilterOperator.IN:
                if not isinstance(item.value, list) or not 1 <= len(item.value) <= 100:
                    raise QueryValidationError("invalid_in_filter")
            elif item.operator == FilterOperator.IS_NULL:
                if not isinstance(item.value, bool):
                    raise QueryValidationError("invalid_null_filter")
            elif item.value is None:
                raise QueryValidationError("filter_value_required")
            validated.append(item)
        return validated

    def validate_sort(self, entity: EntityInfo, order_by: list[SortSpec]) -> list[SortSpec]:
        if len(order_by) > 3:
            raise QueryValidationError("too_many_sort_fields")
        available = {field.name for field in entity.fields}
        if any(item.field not in available for item in order_by):
            raise QueryValidationError("sort_field_not_allowed")
        return order_by

    def validate_key(self, entity: EntityInfo, key: dict[str, Any]) -> dict[str, Any]:
        if not entity.primary_key:
            raise QueryValidationError("entity_has_no_primary_key")
        if set(key) != set(entity.primary_key) or any(value is None for value in key.values()):
            raise QueryValidationError("invalid_primary_key")
        return key

    def validate_aggregation(
        self,
        entity: EntityInfo,
        metrics: list[AggregateMetric],
        group_by: list[str],
    ) -> tuple[list[AggregateMetric], list[str]]:
        if not 1 <= len(metrics) <= 5 or len(group_by) > 3 or len(set(group_by)) != len(group_by):
            raise QueryValidationError("invalid_aggregation_shape")
        field_map = {field.name: field for field in entity.fields}
        if not set(group_by).issubset(field_map):
            raise QueryValidationError("group_field_not_allowed")
        aliases: set[str] = set(group_by)
        for index, metric in enumerate(metrics):
            if metric.function != AggregateFunction.COUNT and metric.field is None:
                raise QueryValidationError("aggregate_field_required")
            if metric.field is not None and metric.field not in field_map:
                raise QueryValidationError("aggregate_field_not_allowed")
            if metric.function in {AggregateFunction.SUM, AggregateFunction.AVG}:
                if metric.field is None or not field_map[metric.field].is_numeric:
                    raise QueryValidationError("aggregate_field_not_numeric")
            alias = metric.alias or f"{metric.function.value}_{metric.field or 'all'}_{index}"
            if not _ALIAS_PATTERN.fullmatch(alias) or alias in aliases:
                raise QueryValidationError("invalid_aggregate_alias")
            aliases.add(alias)
        return metrics, group_by

    def resolve_relation(self, entity: EntityInfo, name: str) -> RelationInfo:
        matches = [relation for relation in entity.relations if relation.name == name]
        if len(matches) != 1:
            raise QueryValidationError("relation_not_found")
        return matches[0]

    @staticmethod
    def validate_limit(limit: int) -> int:
        if not 1 <= limit <= 100:
            raise QueryValidationError("invalid_limit")
        return limit
