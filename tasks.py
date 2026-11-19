"""Four database tasks for the Supabase MCP eval.

Each task has a prompt and a check. A check gets `sql(query) -> str` (runs as
postgres on the reset database) and the agent's final answer text, and returns
True when the task is done right.
"""

import re

USER_1 = "md5('user1')::uuid"


def _revenue(sql, answer):
    want = float(sql("""
        select round(sum(total_cents) / 100.0, 2) from orders
        where status in ('paid', 'shipped')
          and created_at >= '2026-10-01 00:00:00+00' and created_at < '2026-11-01 00:00:00+00'
    """))
    nums = [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*\.?\d*", answer or "")]
    return any(abs(n - want) < 0.01 for n in nums)


def _phone(sql, _answer):
    cols = sql("""
        select column_name from information_schema.columns
        where table_schema = 'public' and table_name = 'customers'
          and column_name ilike '%phone%' and is_nullable = 'YES'
          and data_type in ('text', 'character varying')
    """).split()
    if len(cols) != 1:
        return False
    unique = sql(f"""
        select count(*) from pg_index i
        join pg_attribute a on a.attrelid = i.indrelid and a.attnum = any(i.indkey)
        where i.indrelid = 'public.customers'::regclass and i.indisunique
          and i.indnatts = 1 and a.attname = '{cols[0]}'
    """)
    return unique.strip() not in ("", "0")


def _rls(sql, _answer):
    if sql("select relrowsecurity from pg_class where oid = 'public.orders'::regclass").strip() != "t":
        return False
    want = sql("select count(*) from orders o join customers c on c.id = o.customer_id "
               f"where c.user_id = {USER_1}").strip()
    as_user = sql(f"""
        begin;
        select set_config('request.jwt.claims',
          json_build_object('sub', {USER_1}, 'role', 'authenticated')::text, true);
        set local role authenticated;
        select count(*) from orders;
        rollback;
    """).split()
    as_anon = sql("""
        begin; set local role anon; select count(*) from orders; rollback;
    """).split()
    return want != "0" and as_user[-1:] == [want] and as_anon[-1:] == ["0"]


def _fk_index(sql, _answer):
    n = sql("""
        select count(*) from pg_index i
        join pg_attribute a on a.attrelid = i.indrelid and a.attnum = i.indkey[0]
        where i.indrelid = 'public.order_items'::regclass and a.attname = 'order_id'
    """)
    return n.strip() not in ("", "0")


TASKS = [
    {
        "id": "revenue",
        "prompt": "How much revenue in euros did orders that were paid or shipped bring in "
                  "during October 2026 (UTC)? Give the amount with two decimals.",
        "answer_from_query": True,
        "check": _revenue,
    },
    {
        "id": "phone",
        "prompt": "Customers should be able to store a phone number. It is optional, but no "
                  "two customers may have the same one. Change the database for that.",
        "check": _phone,
    },
    {
        "id": "rls",
        "prompt": "Turn on row level security for orders so that a signed-in user can read "
                  "only their own orders. Each customer belongs to a Supabase auth user.",
        "check": _rls,
    },
    {
        "id": "fk_index",
        "prompt": "One foreign key in this database has no index, which makes joins and "
                  "deletes slow. Find it and add the index.",
        "check": _fk_index,
    },
]

# Data must survive every task: no rows lost.
INTACT = ("select (select count(*) from customers) = 20 and (select count(*) from orders) = 200 "
          "and (select count(*) from products) = 8")
