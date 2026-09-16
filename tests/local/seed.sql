CREATE TABLE public.users (
    id bigint PRIMARY KEY, username text NOT NULL, password text,
    profile jsonb, status text NOT NULL
);
CREATE TABLE public.carwash_carwashorder (
    id bigint PRIMARY KEY, user_id bigint NOT NULL REFERENCES public.users(id),
    status text NOT NULL, amount numeric(16,2), created_at timestamptz NOT NULL
);
CREATE INDEX ON public.carwash_carwashorder(user_id);
CREATE TABLE public.django_session (session_key text PRIMARY KEY, session_data text);
CREATE TABLE public.compound (id bigint, access_token text, PRIMARY KEY(id, access_token));
CREATE SCHEMA garage_export;
CREATE VIEW garage_export.profile_export AS SELECT id, username FROM public.users;
CREATE MATERIALIZED VIEW public.order_totals AS
    SELECT user_id, sum(amount) AS amount FROM public.carwash_carwashorder GROUP BY user_id;
INSERT INTO public.users VALUES
    (1, 'synthetic-customer-a', 'never-expose-a', '{"access_token":"hidden"}', 'active'),
    (2, 'synthetic-customer-b', 'never-expose-b', '{}', 'active');
INSERT INTO public.carwash_carwashorder VALUES
    (1,1,'paid',10000,'2026-01-01T00:00:00Z'),
    (2,1,'paid',20000,'2026-01-02T00:00:00Z'),
    (3,2,'cancelled',5000,'2026-01-03T00:00:00Z');
REFRESH MATERIALIZED VIEW public.order_totals;
ALTER TABLE public.users ADD COLUMN full_name text;
UPDATE public.users SET username = '+998 (90) 123-45-67', full_name = 'Synthetic Customer A' WHERE id = 1;
UPDATE public.users SET username = '998901234568', full_name = 'Synthetic Customer B' WHERE id = 2;
CREATE TABLE public.user_additional_phone (
    id bigint PRIMARY KEY, user_id bigint NOT NULL REFERENCES public.users(id), number varchar(15)
);
INSERT INTO public.user_additional_phone VALUES
    (1,1,'901234567'), (2,1,'00998931234567'), (3,2,'+998931234567');
CREATE TABLE public.business_account_garagecar (
    id bigint PRIMARY KEY, owner_id bigint REFERENCES public.users(id), business_owner_id bigint,
    plate_number text NOT NULL, win_number text, brand_id bigint, model_id bigint, year integer
);
INSERT INTO public.business_account_garagecar VALUES
    (1,1,NULL,'01 A 123 BC','1hgcm82633a004352',10,20,2020),
    (2,1,NULL,'01a123bc','1HGCM82633A004352',10,20,2021),
    (3,2,1,'10B456CD','JH4KA8260MC000001',11,21,2022),
    (4,NULL,1,'01-A-123-BC',NULL,12,22,NULL);
ALTER TABLE public.business_account_garagecar
    ADD COLUMN pinpp text,
    ADD COLUMN prev_pnfl text,
    ADD COLUMN extra_data text;
UPDATE public.business_account_garagecar SET
    pinpp = 'sensitive-synthetic-pinpp',
    prev_pnfl = 'sensitive-synthetic-prev-pnfl',
    extra_data = 'sensitive-synthetic-extra-data';
CREATE VIEW garage_export.vehicle_export AS
    SELECT id, owner_id, plate_number, win_number, pinpp, prev_pnfl, extra_data
    FROM public.business_account_garagecar;
