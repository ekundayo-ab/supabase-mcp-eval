# supabase-mcp-eval

Does an agent do everyday Supabase database work better with Supabase's MCP server than with no tools at all? I gave Claude Code four small tasks on a seeded shop database and ran each one twice per model, once with the local Supabase MCP server as its only tool set and once with no tools, where it has to write the SQL blind.

## Result (19 Nov 2026, 32 runs)

Claude Code 2.1.328, models `claude-haiku-5-5` and `claude-sonnet-5-5`, 2 runs per cell. Supabase CLI 3.2.0, MCP server 0.17.0, Postgres 17, all local.

| Task | No tools, haiku | No tools, sonnet | Supabase MCP, haiku | Supabase MCP, sonnet |
|---|---|---|---|---|
| revenue: October revenue in euros from paid and shipped orders | 0/2 | 0/2 | 2/2 | 2/2 |
| phone: optional phone number, unique per customer | 2/2 | 2/2 | 2/2 | 2/2 |
| rls: row level security, a user reads only their own orders | 2/2 | 0/2 | 2/2 | 2/2 |
| fk_index: find the foreign key with no index and add one | 0/2 | 0/2 | 2/2 | 2/2 |

| Condition | Done | Data intact | Avg MCP calls | Avg seconds | Avg tokens |
|---|---|---|---|---|---|
| No tools | 6/16 | 16/16 | 0 | 10 | 19k |
| Supabase MCP | 16/16 | 16/16 | 3.6 | 13 | 72k |

What this shows:

1. **The tools mattered where the answer depends on what is in the database.** Blind, every model guessed a `total_amount` column. The shop stores money as `total_cents`, so all four revenue queries failed. With MCP, all four runs listed the tables first and got 3,009.51.
2. **Blind SQL can't tell your tables from Supabase's own.** For the missing index, all four blind runs wrote a clever query that looks for every unindexed foreign key in the database. That also finds foreign keys in Supabase's `storage` and `auth` schemas, which the `postgres` user doesn't own: three runs failed on `must be owner of table`, and one stopped itself because it found 9 candidates instead of 1. With MCP, every run found `order_items.order_id` and indexed only that.
3. **A bigger model was not safer blind.** Both Haiku runs wrote a `DO` block that checks the schema at run time (is there an `orders.user_id`? if not, go through `customers.user_id`) and only then creates the policy. That worked. Sonnet wrote a more careful version with a helper function in a private schema, guessed its return type wrong (uuid, but the ids are bigint), and both runs failed to apply.
4. **When the task needs no knowledge of the data, tools add cost and nothing else.** The phone column passed 4/4 either way. MCP runs used about 3.8 times the tokens and 3 more seconds on average.
5. **Nothing was damaged.** After every run the 20 customers, 200 orders and 8 products were all still there.

Read this with care:

- **Small numbers.** 2 runs per model per cell. A 2/2 is a hint, not a rate.
- **The blind baseline is harsh on purpose.** It answers "what does the agent lose without any way to look?", not "is MCP better than a human pasting the schema into the prompt". A schema-in-the-prompt condition is the obvious next one.
- **One task set, one database.** The tasks are mine, written to need things you only learn by looking (cents, statuses, which schema is yours).

Every run, one JSON line each: [results/2026-11-19.jsonl](results/2026-11-19.jsonl). The full Claude Code stream of every run: [results/raw/](results/raw/).

## How a run works

1. Before every run, `supabase db reset` rebuilds the same shop from [the migration](supabase/migrations/20261119000000_shop.sql): 20 customers linked to auth users by `user_id`, 8 products, 200 orders with money in cents, and `order_items.order_id` left without an index.
2. `run.py` starts `claude -p` with the task:
   - **none**: no MCP server, and every built-in tool that can read files or run commands disabled. The reply must be one SQL block; the runner executes it once as `postgres`, and for the revenue task the query's result is the answer.
   - **mcp**: the local Supabase MCP server (`http://127.0.0.1:54321/mcp`) is the only tool set.
3. [tasks.py](tasks.py) checks the database afterwards:
   - revenue: the answer contains the right amount.
   - phone: exactly one new nullable text column with "phone" in its name, with a unique index on it alone.
   - rls: RLS is on, a signed-in user sees exactly their own 10 orders, and `anon` sees 0.
   - fk_index: an index starts with `order_items.order_id`.

   Each check was tested both ways before the runs: it fails on the untouched database and passes after a correct fix.
4. A safety check runs first and stops everything unless the MCP address is local, the agent sees no instruction files, and the database is up.

Everything runs inside one Docker-in-Docker container: the Supabase stack, the Supabase CLI and Claude Code each in their own inner container. Nothing is mounted from the host, and no tool could reach anything outside that local database.

## Run it

Needs Docker. Inside a Docker-in-Docker container with this folder at `/sandbox/work/supabase-eval`, and a Claude Code token at `/dev/shm/claude/claude-token`:

```
sh supabase-eval/setup.sh
python3 supabase-eval/run.py --models haiku,sonnet --reps 2          # prints the plan
python3 supabase-eval/run.py --models haiku,sonnet --reps 2 --yes    # runs it
python3 supabase-eval/report.py supabase-eval/results/<date>.jsonl
```
