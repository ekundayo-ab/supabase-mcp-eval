#!/bin/sh
# Runs inside a Docker-in-Docker container, from /sandbox/work:  sh supabase-eval/setup.sh
# Everything below lives inside that container, nothing on the host:
#   tools  Debian container with the Supabase CLI (runs `supabase start` / `db reset`)
#   agent  Node container with Claude Code; sees the token read-only, the eval folder read-only
#   the local Supabase stack, from supabase/config.toml and supabase/migrations
set -eu
cd /sandbox/work/supabase-eval

apk add --no-cache curl python3 >/dev/null

if ! [ -x /usr/local/bin/supabase ]; then
	arch=$(uname -m | sed 's/aarch64/arm64/;s/x86_64/amd64/')
	curl -fsSL -o /tmp/sb.tgz "https://github.com/supabase/cli/releases/latest/download/supabase_linux_${arch}.tar.gz"
	tar -xzf /tmp/sb.tgz -C /usr/local/bin supabase
fi

docker inspect tools >/dev/null 2>&1 || docker run -d --name tools --network host \
	-v /var/run/docker.sock:/var/run/docker.sock -v /sandbox/work:/sandbox/work -w /sandbox/work \
	-v /usr/local/bin/docker:/usr/local/bin/docker:ro -v /usr/local/bin/supabase:/usr/local/bin/supabase:ro \
	debian:bookworm-slim sleep infinity >/dev/null

if ! docker inspect agent >/dev/null 2>&1; then
	mkdir -p /dev/shm/claude
	docker run -d --name agent --network host \
		-v /dev/shm/claude:/secrets:ro -v /sandbox/work/supabase-eval:/eval:ro \
		node:22-bookworm-slim sleep infinity >/dev/null
	docker exec agent npm install -g --silent @anthropic-ai/claude-code >/dev/null
fi
mkdir -p /dev/shm/claude
docker start tools agent >/dev/null

docker exec -w "$PWD" tools supabase start -x logflare,vector,imgproxy >/dev/null
docker exec -w "$PWD" tools supabase db reset >/dev/null 2>&1
echo "ready: Supabase $(docker exec tools supabase --version), Claude Code $(docker exec agent claude --version)"
