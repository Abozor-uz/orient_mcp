# app/domain/errors.py
# ============================================================================
# Domain Errors
#
# Sanitized error classes shared across services and presentation. Messages are
# stable machine-readable codes and never contain SQL, credentials, or PII.
# ============================================================================


class OrientMcpError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class CatalogError(OrientMcpError):
    pass


class QueryValidationError(OrientMcpError):
    pass


class DataSourceUnavailableError(OrientMcpError):
    pass
