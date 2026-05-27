# Sandbox image for the OpenAI Codex CLI used by the /search benchmark.
# Mirrors the role of docker/sandbox-templates:claude-code — no /search
# skill harness needed since codex picks up guidance from the repo-root
# AGENTS.md mounted into the workspace at runtime.
FROM node:20-bookworm-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl tini \
 && rm -rf /var/lib/apt/lists/* \
 && npm install -g @openai/codex \
 # node:20-bookworm-slim ships with a `node` user at uid 1000 already.
 # Rename it (+ group + home) to `agent` so the host bind-mount owner
 # maps cleanly to the in-container user.
 && usermod -l agent -d /home/agent -m node \
 && groupmod -n agent node \
 && mkdir -p /home/agent/workspace /home/agent/.codex \
 && chown -R agent:agent /home/agent

USER agent
WORKDIR /home/agent/workspace
ENTRYPOINT ["tini", "--"]
CMD ["codex"]
