# app/infrastructure/http/source_repositories.py
# ============================================================================
# HTTP Source Repository Adapters
#
# Keeps the existing MCP ports and result shapes while moving all source SQL
# behind the authenticated Orient read API.
# ============================================================================
from __future__ import annotations

from typing import Any

from app.domain.customer_lookup import CustomerPage, CustomerQuery, VehiclePage, VehicleQuery
from app.domain.data_api import CatalogReadPage
from app.domain.errors import CatalogError, DataSourceUnavailableError
from app.domain.models import (
    AggregateMetric,
    AggregationResult,
    CatalogSnapshot,
    DatabaseContext,
    EntityInfo,
    FilterOperator,
    FilterSpec,
    RecordPage,
    RecordView,
    RelationInfo,
    SortSpec,
)
from app.infrastructure.http.source_client import OrientSourceHttpClient
from app.infrastructure.policy import CatalogPolicy


def _wire_filters(filters: list[FilterSpec]) -> list[FilterSpec]:
    result = []
    for item in filters:
        value = item.value
        if (
            item.operator == FilterOperator.ILIKE
            and isinstance(value, str)
            and value.startswith("%")
            and value.endswith("%")
        ):
            value = value[1:-1]
        result.append(item.model_copy(update={"value": value}))
    return result


class HttpCatalogRepository:
    def __init__(self, client: OrientSourceHttpClient, policy: CatalogPolicy) -> None:
        self.client = client
        self.policy = policy

    async def load_catalog(self) -> CatalogSnapshot:
        entities: dict[str, EntityInfo] = {}
        after_entity = None
        first: CatalogReadPage | None = None
        while True:
            reply = await self.client.read(
                "catalog",
                after_entity=after_entity,
                limit=100,
                fingerprint=first.fingerprint if first else None,
            )
            page = CatalogReadPage.model_validate(reply.payload)
            if first is None:
                first = page
            if first.fingerprint != page.fingerprint:
                raise CatalogError("catalog_changed_during_request")
            for entity in page.entities:
                if (
                    not self.policy.allows_entity(entity.name)
                    or any(
                        not self.policy.allows_field(entity.name, field.name)
                        for field in entity.fields
                    )
                    or any(field.data_type in {"json", "jsonb", "bytea"} for field in entity.fields)
                ):
                    raise DataSourceUnavailableError("orient_read_api_policy_mismatch")
                if entity.name in entities:
                    raise DataSourceUnavailableError("orient_read_api_catalog_invalid")
                entities[entity.name] = entity
            if page.next_after_entity is None:
                return CatalogSnapshot(
                    entities=entities,
                    fingerprint=first.fingerprint,
                    loaded_at=first.loaded_at,
                )
            if not page.entities or (
                after_entity is not None and page.next_after_entity <= after_entity
            ):
                raise DataSourceUnavailableError("orient_read_api_catalog_invalid")
            after_entity = page.next_after_entity


class HttpRecordRepository:
    def __init__(self, client: OrientSourceHttpClient) -> None:
        self.client = client

    async def search(
        self,
        *,
        entity: EntityInfo,
        fields: list[str],
        filters: list[FilterSpec],
        order_by: list[SortSpec],
        limit: int,
        offset: int,
        fingerprint: str,
    ) -> RecordPage:
        reply = await self.client.read(
            "search",
            entity_name=entity.name,
            fields=fields,
            filters=_wire_filters(filters),
            order_by=order_by,
            limit=limit,
            offset=offset,
            fingerprint=fingerprint,
        )
        return RecordPage.model_validate(reply.payload)

    async def get_one(
        self,
        *,
        entity: EntityInfo,
        key: dict[str, Any],
        fields: list[str],
    ) -> RecordView | None:
        reply = await self.client.read("get-one", entity_name=entity.name, key=key, fields=fields)
        return None if reply.payload is None else RecordView.model_validate(reply.payload)

    async def aggregate(
        self,
        *,
        entity: EntityInfo,
        metrics: list[AggregateMetric],
        group_by: list[str],
        filters: list[FilterSpec],
        limit: int,
        fingerprint: str,
    ) -> AggregationResult:
        reply = await self.client.read(
            "aggregate",
            entity_name=entity.name,
            metrics=metrics,
            group_by=group_by,
            filters=_wire_filters(filters),
            limit=limit,
            fingerprint=fingerprint,
        )
        return AggregationResult.model_validate(reply.payload)

    async def related(
        self,
        *,
        current_entity: EntityInfo,
        key: dict[str, Any],
        relation: RelationInfo,
        related_entity: EntityInfo,
        fields: list[str],
        limit: int,
        offset: int,
        fingerprint: str,
    ) -> RecordPage:
        reply = await self.client.read(
            "related",
            entity_name=current_entity.name,
            key=key,
            relation_name=relation.name,
            fields=fields,
            limit=limit,
            offset=offset,
            fingerprint=fingerprint,
        )
        return RecordPage.model_validate(reply.payload)

    async def get_context(self, *, source: str, snapshot: CatalogSnapshot) -> DatabaseContext:
        if source != self.client.source:
            raise DataSourceUnavailableError("orient_read_api_source_mismatch")
        reply = await self.client.read("context", fingerprint=snapshot.fingerprint)
        return DatabaseContext.model_validate(reply.payload)


class HttpCustomerLookupRepository:
    def __init__(self, client: OrientSourceHttpClient) -> None:
        self.client = client

    async def customers(self, query: CustomerQuery) -> CustomerPage:
        reply = await self.client.read("customers", customers=query)
        return CustomerPage.model_validate(reply.payload)

    async def vehicles(self, query: VehicleQuery) -> VehiclePage:
        reply = await self.client.read("vehicles", vehicles=query)
        return VehiclePage.model_validate(reply.payload)
