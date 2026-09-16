# app/infrastructure/policy.py
# ============================================================================
# Catalog Access Policy
#
# Loads the versioned server-side allow/deny and semantic metadata policy used
# to filter PostgreSQL catalog objects before they reach services or tools.
# ============================================================================

from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class AccessPolicyConfig(BaseModel):
    version: int = 1
    schemas: list[str] = Field(default_factory=lambda: ["public"])
    allowed_entities: list[str] = Field(default_factory=lambda: ["*"])
    denied_entities: list[str] = Field(default_factory=list)
    denied_field_patterns: list[str] = Field(default_factory=list)
    denied_fields: dict[str, list[str]] = Field(default_factory=dict)
    entity_aliases: dict[str, list[str]] = Field(default_factory=dict)
    entity_descriptions: dict[str, str] = Field(default_factory=dict)
    field_descriptions: dict[str, str] = Field(default_factory=dict)
    enum_values: dict[str, list[str]] = Field(default_factory=dict)


class CatalogPolicy:
    def __init__(self, config: AccessPolicyConfig, configured_schemas: list[str]) -> None:
        requested = set(configured_schemas)
        self.schemas = [schema for schema in config.schemas if schema in requested]
        if not self.schemas:
            raise ValueError("policy_has_no_allowed_schemas")
        self._config = config
        self._field_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in config.denied_field_patterns
        ]

    @classmethod
    def load(cls, path: Path, configured_schemas: list[str]) -> CatalogPolicy:
        with path.open("r", encoding="utf-8") as handle:
            raw: Any = yaml.safe_load(handle) or {}
        return cls(AccessPolicyConfig.model_validate(raw), configured_schemas)

    def allows_entity(self, entity: str) -> bool:
        schema, separator, _ = entity.partition(".")
        if not separator or schema not in self.schemas:
            return False
        if not any(
            fnmatch.fnmatchcase(entity, pattern) for pattern in self._config.allowed_entities
        ):
            return False
        return not any(
            fnmatch.fnmatchcase(entity, pattern) for pattern in self._config.denied_entities
        )

    def allows_field(self, entity: str, field: str) -> bool:
        if field in self._config.denied_fields.get(entity, []):
            return False
        return not any(pattern.search(field) for pattern in self._field_patterns)

    def aliases(self, entity: str) -> list[str]:
        return list(self._config.entity_aliases.get(entity, []))

    def entity_description(self, entity: str, fallback: str | None) -> str | None:
        return self._config.entity_descriptions.get(entity, fallback)

    def field_description(self, entity: str, field: str, fallback: str | None) -> str | None:
        return self._config.field_descriptions.get(f"{entity}.{field}", fallback)

    def enum_values(self, entity: str, field: str) -> list[str]:
        return list(self._config.enum_values.get(f"{entity}.{field}", []))
