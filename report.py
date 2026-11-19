"""Turn results/<date>.jsonl into a markdown table:  python3 report.py results/2026-11-19.jsonl"""

import json, sys
from collections import defaultdict

rows = [json.loads(l) for l in open(sys.argv[1])]
tasks = list(dict.fromkeys(r["task"] for r in rows))
models = list(dict.fromkeys(r["model"] for r in rows))
cell = defaultdict(list)
for r in rows:
    cell[(r["task"], r["condition"], r["model"])].append(r)


def tokens(r):
    u = r.get("usage") or {}
    return sum(u.get(k) or 0 for k in ("input_tokens", "cache_read_input_tokens",
                                       "cache_creation_input_tokens", "output_tokens"))


print(f"Claude Code {rows[0]['claude'].split()[0]}, {len(rows)} runs, models {', '.join(models)}.\n")
print("| Task | " + " | ".join(f"No tools, {m}" for m in models) + " | "
      + " | ".join(f"Supabase MCP, {m}" for m in models) + " |")
print("|---|" + "---|" * (2 * len(models)))
for t in tasks:
    cells = []
    for c in ("none", "mcp"):
        for m in models:
            rs = cell[(t, c, m)]
            cells.append(f"{sum(r['done'] for r in rs)}/{len(rs)}")
    print(f"| {t} | " + " | ".join(cells) + " |")
print()
print("| Condition | Done | Data intact | Avg tool calls | Avg seconds | Avg tokens |")
print("|---|---|---|---|---|---|")
for c, name in (("none", "No tools"), ("mcp", "Supabase MCP")):
    rs = [r for r in rows if r["condition"] == c]
    n = len(rs)
    print(f"| {name} | {sum(r['done'] for r in rs)}/{n} | {sum(r['intact'] for r in rs)}/{n} | "
          f"{sum(len([x for x in r['tools'] if x.startswith('mcp__')]) for r in rs) / n:.1f} | "
          f"{sum(r['seconds'] for r in rs) / n:.0f} | {sum(tokens(r) for r in rs) / n / 1000:.0f}k |")
