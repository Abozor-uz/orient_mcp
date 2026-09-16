# app/infrastructure/postgres/customer_lookup_repository.py
# ============================================================================
# Orient Customer Lookup Repository
#
# Parameterized, read-only joins over verified Orient model columns. EXISTS
# avoids duplicate customers when additional phone rows overlap.
# ============================================================================

from __future__ import annotations

from psycopg import sql

from app.domain.customer_lookup import (
    CustomerMatch,
    CustomerPage,
    CustomerQuery,
    VehicleMatch,
    VehiclePage,
    VehicleQuery,
)
from app.infrastructure.postgres.pool import PostgresPool


def _phone(column: str) -> sql.Composed:
    identifier = sql.Identifier(*column.split("."))
    digits = sql.SQL("regexp_replace({}, '[^0-9]', '', 'g')").format(identifier)
    international = sql.SQL("regexp_replace({}, '^00', '')").format(digits)
    return sql.SQL(
        "CASE WHEN btrim({}) ~ '^[+]?[0-9 ().-]+$' THEN "
        "CASE WHEN length({}) = 9 THEN '998' || {} ELSE {} END ELSE NULL END"
    ).format(identifier, international, international, international)


def _vehicle_identifier(column: str) -> sql.Composed:
    return sql.SQL("upper(regexp_replace({}, '[[:space:]-]', '', 'g'))").format(
        sql.Identifier(*column.split("."))
    )


class PostgresCustomerLookupRepository:
    def __init__(self, pool: PostgresPool) -> None:
        self._pool = pool

    async def customers(self, query: CustomerQuery) -> CustomerPage:
        primary: sql.Composable = sql.SQL("FALSE")
        additional: sql.Composable = sql.SQL("FALSE")
        parameters: dict[str, str | int | None] = {
            "phone": query.phone,
            "customer": query.customer_id,
            "after": query.after_id,
            "limit": query.limit + 1,
        }
        if query.phone is not None:
            primary = sql.SQL("coalesce({} = %(phone)s, FALSE)").format(_phone("u.username"))
            additional = sql.SQL(
                "EXISTS (SELECT 1 FROM public.user_additional_phone p "
                "WHERE p.user_id = u.id AND {} = %(phone)s)"
            ).format(_phone("p.number"))
        conditions: list[sql.Composable] = [sql.SQL("u.id > %(after)s")]
        if query.customer_id is not None:
            conditions.append(sql.SQL("u.id = %(customer)s"))
        if query.phone is not None:
            conditions.append(sql.SQL("({} OR {})").format(primary, additional))
        statement = sql.SQL(
            "SELECT u.id AS customer_id, u.username AS phone, u.full_name, "
            "{} AS matched_primary_phone, {} AS matched_additional_phone "
            "FROM public.users u WHERE {} ORDER BY u.id LIMIT %(limit)s"
        ).format(primary, additional, sql.SQL(" AND ").join(conditions))
        async with self._pool.transaction() as connection:
            result = await connection.execute(statement, parameters)
            rows = list(await result.fetchall())
        customers = [CustomerMatch.model_validate(row) for row in rows[: query.limit]]
        more = len(rows) > query.limit
        return CustomerPage(
            customers=customers,
            has_more=more,
            next_after_id=customers[-1].customer_id if more else None,
        )

    async def vehicles(self, query: VehicleQuery) -> VehiclePage:
        conditions: list[sql.Composable] = [sql.SQL("g.id > %(after)s")]
        parameters: dict[str, str | int | None] = {
            "plate": query.plate_number,
            "vin": query.vin,
            "customer": query.customer_id,
            "after": query.after_id,
            "limit": query.limit + 1,
        }
        if query.plate_number is not None:
            conditions.append(
                sql.SQL("{} = %(plate)s").format(_vehicle_identifier("g.plate_number"))
            )
        if query.vin is not None:
            conditions.append(sql.SQL("{} = %(vin)s").format(_vehicle_identifier("g.win_number")))
        if query.customer_id is not None:
            conditions.append(sql.SQL("g.owner_id = %(customer)s"))
        statement = sql.SQL(
            "SELECT g.id AS vehicle_id, g.plate_number, g.win_number AS vin, "
            "g.owner_id AS customer_id, u.username AS customer_phone, "
            "u.full_name AS customer_name, g.business_owner_id, "
            "g.brand_id, g.model_id, g.year "
            "FROM public.business_account_garagecar g "
            "LEFT JOIN public.users u ON u.id = g.owner_id "
            "WHERE {} ORDER BY g.id LIMIT %(limit)s"
        ).format(sql.SQL(" AND ").join(conditions))
        async with self._pool.transaction() as connection:
            result = await connection.execute(statement, parameters)
            rows = list(await result.fetchall())
        vehicles = [VehicleMatch.model_validate(row) for row in rows[: query.limit]]
        more = len(rows) > query.limit
        return VehiclePage(
            vehicles=vehicles,
            has_more=more,
            next_after_id=vehicles[-1].vehicle_id if more else None,
        )
