"""Supabase MCP eval: does an agent do database tasks better with Supabase's MCP
tools than with no tools at all?

Runs inside a Docker-in-Docker container (see README), never on the host:
  python3 supabase-eval/run.py --models haiku,sonnet --reps 2
It prints the plan and stops; add --yes to start.

Conditions:
  none  no tools. The model writes one SQL block without seeing the database;
        the runner executes it once.
  mcp   Supabase's MCP server (local, 127.0.0.1:54321/mcp) is the only tool set.
Before every run the database is reset to the same seeded shop.
"""

import argparse, json, os, re, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tasks import INTACT, TASKS  # noqa: E402

HERE = "/sandbox/work/supabase-eval"
DB = "supabase_db_supabase-eval"
MCP_URL = "http://127.0.0.1:54321/mcp"
BUILTIN = "Bash,Edit,Write,Read,Glob,Grep,WebFetch,WebSearch,Task,NotebookEdit,TodoWrite"
TIMEOUT = 300
MAX_TURNS = 25

NONE_SUFFIX = ("\n\nYou cannot see or query the database. Reply with exactly one ```sql code "
               "block that does this; it will be run once, as the postgres user, against the "
               "project's Postgres database.")
REVENUE_NONE = " The single value your query returns is taken as your answer."
MCP_SUFFIX = ("\n\nUse the Supabase tools you have to look at and change the database. "
              "When you are done, reply with a short summary.")


def sh(cmd, inp=None, timeout=120):
    return subprocess.run(cmd, input=inp, capture_output=True, text=True, timeout=timeout)


def sql(query):
    r = sh(["docker", "exec", "-i", DB, "psql", "-U", "postgres", "-qAt", "-v", "ON_ERROR_STOP=1"], query)
    return r.stdout.strip() if r.returncode == 0 else ""


def reset():
    r = sh(["docker", "exec", "-w", HERE, "tools", "supabase", "db", "reset"], timeout=300)
    if r.returncode != 0 or sql("select count(*) from orders") != "200":
        sys.exit("database reset failed:\n" + r.stderr[-2000:])


def preflight(n_runs):
    problems = []
    if sh(["docker", "exec", "agent", "test", "-s", "/secrets/claude-token"]).returncode != 0:
        problems.append("no Claude token at /secrets/claude-token in the agent container")
    cfg = json.load(open(f"{HERE}/mcp.json"))
    urls = [s.get("url", "") for s in cfg["mcpServers"].values()]
    if any(not u.startswith("http://127.0.0.1:") for u in urls):
        problems.append(f"MCP must be local only, got {urls}")
    seen = sh(["docker", "exec", "agent", "sh", "-c",
               "ls /root/.claude/CLAUDE.md /root/CLAUDE.md /eval/CLAUDE.md 2>/dev/null"]).stdout.strip()
    if seen:
        problems.append(f"instruction files visible to the agent: {seen}")
    if sql("select 1") != "1":
        problems.append("database not reachable; run setup.sh")
    if problems:
        sys.exit("preflight failed:\n- " + "\n- ".join(problems))
    print(f"preflight ok: token present, MCP {urls}, no instruction files, database up; {n_runs} runs")


def claude(prompt, model, condition):
    args = ["claude", "-p", "--model", model, "--output-format", "stream-json", "--verbose",
            "--max-turns", str(MAX_TURNS), "--disallowedTools", BUILTIN, "--strict-mcp-config"]
    if condition == "mcp":
        args += ["--mcp-config", "/eval/mcp.json", "--allowedTools", "mcp__supabase"]
    cmd = ["docker", "exec", "-i", "-w", "/tmp", "agent", "sh", "-c",
           'CLAUDE_CODE_OAUTH_TOKEN="$(cat /secrets/claude-token)" exec "$@"', "_", *args]
    t = time.time()
    try:
        r = sh(cmd, prompt, timeout=TIMEOUT)
        out, err = r.stdout, r.stderr[-500:]
    except subprocess.TimeoutExpired as e:
        out, err = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or ""), "timeout"
        sh(["docker", "restart", "-t", "1", "agent"])  # stop the agent so it can't touch the next run
    events = []
    for line in out.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    result = next((e for e in reversed(events) if e.get("type") == "result"), {})
    tools = [c.get("name") for e in events if e.get("type") == "assistant"
             for c in e.get("message", {}).get("content", []) if c.get("type") == "tool_use"]
    return {"answer": result.get("result", ""), "turns": result.get("num_turns"),
            "usage": result.get("usage", {}), "tools": tools, "seconds": round(time.time() - t, 1),
            "error": err if not result or result.get("is_error") else ""}, out


def run_one(task, model, condition):
    reset()
    prompt = task["prompt"] + (NONE_SUFFIX + (REVENUE_NONE if task.get("answer_from_query") else "")
                               if condition == "none" else MCP_SUFFIX)
    rec, raw = claude(prompt, model, condition)
    if condition == "none":
        blocks = re.findall(r"```sql\s*(.*?)```", rec["answer"] or "", re.S)
        rec["sql"] = blocks[-1].strip() if blocks else ""
        if rec["sql"]:
            ran = sql(rec["sql"])
            if task.get("answer_from_query"):
                rec["answer"] = ran
    rec["done"] = bool(task["check"](sql, rec["answer"]))
    rec["intact"] = sql(INTACT) == "t"
    return rec, raw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="haiku,sonnet")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--tasks", default=",".join(t["id"] for t in TASKS))
    ap.add_argument("--conditions", default="none,mcp")
    ap.add_argument("--out", default=time.strftime("%Y-%m-%d"))
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args()
    tasks = [t for t in TASKS if t["id"] in a.tasks.split(",")]
    grid = [(t, m, c, r) for t in tasks for c in a.conditions.split(",")
            for m in a.models.split(",") for r in range(1, a.reps + 1)]
    preflight(len(grid))
    n_mcp = sum(1 for g in grid if g[2] == "mcp")
    print(f"estimate: about {n_mcp * 40 + (len(grid) - n_mcp) * 5}k tokens "
          f"(~40k per MCP run, ~5k per no-tool run), about {len(grid)} database resets")
    if not a.yes:
        sys.exit("plan only; add --yes to run")
    os.makedirs(f"{HERE}/results/raw", exist_ok=True)
    path = f"{HERE}/results/{a.out}.jsonl"
    done = set()
    if os.path.exists(path):
        done = {(j["task"], j["model"], j["condition"], j["rep"]) for j in map(json.loads, open(path))}
    version = sh(["docker", "exec", "agent", "claude", "--version"]).stdout.strip()
    for t, m, c, r in grid:
        key = (t["id"], m, c, r)
        if key in done:
            continue
        rec, raw = run_one(t, m, c)
        rec.update(task=t["id"], model=m, condition=c, rep=r, claude=version)
        with open(path, "a") as f:
            f.write(json.dumps(rec) + "\n")
        with open(f"{HERE}/results/raw/{a.out}-{t['id']}-{m}-{c}-{r}.jsonl", "w") as f:
            f.write(raw)
        print(f"{t['id']:9} {m:7} {c:5} #{r}  done={rec['done']!s:5} intact={rec['intact']!s:5} "
              f"tools={len(rec['tools'])} {rec['seconds']}s {rec['error'][:80]}", flush=True)


if __name__ == "__main__":
    main()
