BEGIN;

CREATE OR REPLACE VIEW public.mcp_service_order_economics AS
WITH line_totals AS (
    SELECT
        oi.order_id,
        count(*) FILTER (WHERE oi.is_service = false) AS parts_line_count,
        count(*) FILTER (WHERE oi.is_service = false AND oi.incoming_price IS NOT NULL) AS parts_cost_known_line_count,
        sum(oi.count * COALESCE(NULLIF(oi.after_price, 0), oi.price_retail_sale, 0)) AS total_line_revenue,
        sum(oi.count * COALESCE(NULLIF(oi.after_price, 0), oi.price_retail_sale, 0))
            FILTER (WHERE oi.is_service = true) AS service_revenue,
        sum(oi.count * COALESCE(NULLIF(oi.after_price, 0), oi.price_retail_sale, 0))
            FILTER (WHERE oi.is_service = false) AS parts_revenue,
        sum(oi.count * oi.incoming_price)
            FILTER (WHERE oi.is_service = false AND oi.incoming_price IS NOT NULL) AS parts_cost,
        sum(
            oi.count * (
                COALESCE(NULLIF(oi.after_price, 0), oi.price_retail_sale, 0)
                - oi.incoming_price
            )
        ) FILTER (
            WHERE oi.is_service = false AND oi.incoming_price IS NOT NULL
        ) AS known_parts_gross_margin
    FROM public.order_items oi
    WHERE oi.status = 'ACTIVE'
    GROUP BY oi.order_id
),
labor_totals AS (
    SELECT
        m.order_id,
        sum(
            COALESCE(
                oi.count
                * COALESCE(NULLIF(oi.after_price, 0), oi.price_retail_sale, 0)
                / 1.12
                * m.percentage
                / 100
                * COALESCE(NULLIF(m.work_percentage, 0), e.work_percentage, 0)
                / 100,
                0
            )
        ) AS estimated_mechanic_cost
    FROM public.mechanics m
    JOIN public.order_items oi ON oi.id = m.order_item_id
    LEFT JOIN public.employees e ON e.id = m.mechanic_id
    WHERE m.status = 'ACTIVE' AND oi.is_service = true
    GROUP BY m.order_id
)
SELECT
    o.id AS order_id,
    o.order_number,
    o.status,
    o.order_status,
    o.payment_status,
    o.order_type,
    o.created_date,
    o.start_date,
    o.completed_date,
    o.closed_date,
    o.end_date,
    o.department_id,
    d.name AS department_name,
    o.contractor_id,
    o.customer_id,
    o.vehicle_id,
    o.contract_id,
    o.amount_of_payment,
    o.amount_after_payment,
    COALESCE(lt.total_line_revenue, 0) AS total_line_revenue,
    COALESCE(lt.service_revenue, 0) AS service_revenue,
    COALESCE(lt.parts_revenue, 0) AS parts_revenue,
    lt.parts_cost,
    lt.known_parts_gross_margin,
    COALESCE(labor.estimated_mechanic_cost, 0) AS estimated_mechanic_cost,
    COALESCE(lt.parts_line_count, 0) AS parts_line_count,
    COALESCE(lt.parts_cost_known_line_count, 0) AS parts_cost_known_line_count,
    CASE
        WHEN COALESCE(lt.parts_line_count, 0) = 0 THEN NULL
        ELSE round(
            lt.parts_cost_known_line_count::numeric / lt.parts_line_count::numeric * 100,
            2
        )
    END AS parts_cost_coverage_percent
FROM public.orders o
LEFT JOIN line_totals lt ON lt.order_id = o.id
LEFT JOIN labor_totals labor ON labor.order_id = o.id
LEFT JOIN public.cd_departments d ON d.id = o.department_id;

COMMENT ON VIEW public.mcp_service_order_economics IS
    'One row per service order with revenue, known parts cost, estimated mechanic cost, and cost coverage. This is not net profit because general operating expenses and taxes are not allocated to orders.';

CREATE OR REPLACE VIEW public.mcp_procurement_economics AS
WITH item_totals AS (
    SELECT
        wdi.wh_document_id,
        count(*) AS line_count,
        sum(wdi.count) AS item_quantity,
        sum(wdi.count * wdi.incoming_price) AS item_incoming_cost,
        sum(COALESCE(wdi.self_extra_costs, 0)) AS allocated_line_extra_costs
    FROM public.wh_document_items wdi
    GROUP BY wdi.wh_document_id
),
extra_totals AS (
    SELECT
        wec.wh_document_id,
        sum(wec.cost) FILTER (WHERE wec.status = 'ACTIVE') AS registered_extra_costs,
        sum(wec.currency_cost) FILTER (WHERE wec.status = 'ACTIVE') AS registered_currency_costs
    FROM public.wh_extra_costs wec
    GROUP BY wec.wh_document_id
)
SELECT
    wd.id AS warehouse_document_id,
    wd.reg_number,
    wd.reg_date,
    wd.created_date,
    wd.status,
    wd.document_status,
    wd.document_type,
    wd.action,
    wd.contractor_id,
    contractor.name AS contractor_name,
    wd.from_department_id,
    from_department.name AS from_department_name,
    wd.to_department_id,
    to_department.name AS to_department_name,
    wd.from_currency,
    from_currency.code AS from_currency_code,
    wd.to_currency,
    to_currency.code AS to_currency_code,
    wd.from_currency_rate,
    wd.to_currency_rate,
    wd.today_currency_uzs,
    wd.order_amount,
    wd.extra_costs AS document_extra_costs,
    COALESCE(items.line_count, 0) AS line_count,
    COALESCE(items.item_quantity, 0) AS item_quantity,
    items.item_incoming_cost,
    items.allocated_line_extra_costs,
    extras.registered_extra_costs,
    extras.registered_currency_costs
FROM public.wh_documents wd
LEFT JOIN item_totals items ON items.wh_document_id = wd.id
LEFT JOIN extra_totals extras ON extras.wh_document_id = wd.id
LEFT JOIN public.contractors contractor ON contractor.id = wd.contractor_id
LEFT JOIN public.cd_departments from_department ON from_department.id = wd.from_department_id
LEFT JOIN public.cd_departments to_department ON to_department.id = wd.to_department_id
LEFT JOIN public.currency_types from_currency ON from_currency.id = wd.from_currency
LEFT JOIN public.currency_types to_currency ON to_currency.id = wd.to_currency;

COMMENT ON VIEW public.mcp_procurement_economics IS
    'Warehouse procurement and movement documents with incoming item cost, allocated costs, registered extra costs, counterparties, departments, and currency context.';

CREATE OR REPLACE VIEW public.mcp_customer_vehicle_service_history AS
SELECT
    o.id AS order_id,
    o.order_number,
    o.order_status,
    o.payment_status,
    o.order_type,
    o.created_date AS order_created_date,
    o.start_date,
    o.completed_date,
    o.closed_date,
    o.end_date,
    o.department_id,
    department.name AS department_name,
    o.contractor_id AS order_contractor_id,
    COALESCE(NULLIF(order_contractor.name, ''), concat_ws(' ', order_contractor.last_name, order_contractor.first_name, order_contractor.middle_name)) AS order_contractor_name,
    COALESCE(order_contractor.mobile, order_contractor.phone) AS order_contractor_phone,
    order_contractor.email AS order_contractor_email,
    order_contractor.external_contractor_id,
    o.customer_id,
    COALESCE(NULLIF(customer.name, ''), concat_ws(' ', customer.last_name, customer.first_name, customer.middle_name)) AS customer_name,
    COALESCE(customer.mobile, customer.phone) AS customer_phone,
    customer.email AS customer_email,
    o.vehicle_id,
    vehicle.name AS vehicle_name,
    vehicle.vin,
    vehicle.optional_vin,
    vehicle.state_number,
    vehicle.engine_number,
    vehicle.mileage AS vehicle_mileage,
    vehicle.brand_id,
    brand.name AS brand_name,
    vehicle.model_id,
    model.name AS model_name,
    vehicle.year_id,
    year.year AS vehicle_year,
    vehicle.color_id,
    color.name AS color_name,
    vehicle.contractor_id AS vehicle_owner_id,
    COALESCE(NULLIF(vehicle_owner.name, ''), concat_ws(' ', vehicle_owner.last_name, vehicle_owner.first_name, vehicle_owner.middle_name)) AS vehicle_owner_name,
    COALESCE(vehicle_owner.mobile, vehicle_owner.phone) AS vehicle_owner_phone,
    o.amount_of_payment,
    o.amount_after_payment
FROM public.orders o
LEFT JOIN public.cd_departments department ON department.id = o.department_id
LEFT JOIN public.contractors order_contractor ON order_contractor.id = o.contractor_id
LEFT JOIN public.contractors customer ON customer.id = o.customer_id
LEFT JOIN public.vehicles vehicle ON vehicle.id = o.vehicle_id
LEFT JOIN public.contractors vehicle_owner ON vehicle_owner.id = vehicle.contractor_id
LEFT JOIN public.brands brand ON brand.id = vehicle.brand_id
LEFT JOIN public.models model ON model.id = vehicle.model_id
LEFT JOIN public.years year ON year.id = vehicle.year_id
LEFT JOIN public.colors color ON color.id = vehicle.color_id;

COMMENT ON VIEW public.mcp_customer_vehicle_service_history IS
    'One row per service order with customer, vehicle, VIN, registration number, owner, branch, dates, and payment totals for cross-system conversion analysis.';

GRANT USAGE ON SCHEMA public TO orient_mcp_reader;
GRANT SELECT ON TABLE
    public.contractor_and_categories,
    public.contractor_categories,
    public.contractor_ex_ids,
    public.contractor_groups,
    public.contractors,
    public.employees,
    public.employees_work,
    public.positions,
    public.vehicles,
    public.vehicle_last_visit_dates,
    public.vehicle_repair,
    public.extra_cost_types,
    public.wh_extra_costs,
    public."Manager_salary_group_by",
    public."Master_salary_group_by",
    public.employee_salary,
    public.manager_salary,
    public.mcp_service_order_economics,
    public.mcp_procurement_economics,
    public.mcp_customer_vehicle_service_history
TO orient_mcp_reader;

COMMIT;
