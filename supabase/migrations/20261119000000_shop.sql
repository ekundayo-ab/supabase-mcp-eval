-- A small shop. Every value is generated, so each reset gives the same data.
-- Things an agent can only know by looking: money is in cents, the order
-- statuses, customers link to auth users by user_id, and order_items.order_id
-- has no index.

create table public.customers (
  id bigint generated always as identity primary key,
  user_id uuid not null unique,
  email text not null unique,
  created_at timestamptz not null default '2026-01-01'
);

create table public.products (
  id bigint generated always as identity primary key,
  sku text not null unique,
  name text not null,
  price_cents integer not null,
  archived boolean not null default false
);

create table public.orders (
  id bigint generated always as identity primary key,
  customer_id bigint not null references public.customers (id),
  status text not null check (status in ('pending', 'paid', 'shipped', 'refunded')),
  total_cents integer not null,
  created_at timestamptz not null
);
create index orders_customer_id_idx on public.orders (customer_id);

create table public.order_items (
  id bigint generated always as identity primary key,
  order_id bigint not null references public.orders (id),
  product_id bigint not null references public.products (id),
  qty integer not null,
  price_cents integer not null
);
create index order_items_product_id_idx on public.order_items (product_id);

insert into public.customers (user_id, email)
select md5('user' || i)::uuid, 'customer' || i || '@example.test'
from generate_series(1, 20) i;

insert into public.products (sku, name, price_cents, archived)
select 'SKU-' || i, 'Product ' || i, 500 + i * 250, i in (7, 8)
from generate_series(1, 8) i;

insert into public.orders (customer_id, status, total_cents, created_at)
select 1 + (i % 20),
       (array['pending', 'paid', 'shipped', 'refunded'])[1 + (i * 7) % 4],
       1000 + (i * 137) % 9000,
       timestamptz '2026-09-01 00:00:00+00' + i * interval '7 hours'
from generate_series(1, 200) i;

insert into public.order_items (order_id, product_id, qty, price_cents)
select o.id, 1 + ((o.id + k) % 8), 1 + (k % 2), 500 + (1 + ((o.id + k) % 8)) * 250
from public.orders o, generate_series(0, 2) k
where k <= o.id % 3;
