#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: rsync-opensource.sh [-n|--dry-run] [--clean] <destination>

Options:
  -n, --dry-run   Show what would be transferred, write nothing.
  --clean         Wipe destination first (preserving .git/ and .github/).
                  Guarantees a clean mirror with no stale files from a
                  previous run. Without this, rsync only adds/updates.
  -h, --help      Show this help.
EOF
}

DRY_RUN=""
CLEAN=""
DEST=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--dry-run) DRY_RUN="-n"; shift ;;
    --clean) CLEAN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    --) shift; break ;;
    -*) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
    *)
      if [[ -n "$DEST" ]]; then
        echo "too many arguments" >&2
        usage >&2
        exit 2
      fi
      DEST="$1"
      shift
      ;;
  esac
done

if [[ -z "$DEST" ]]; then
  echo "destination is required" >&2
  usage >&2
  exit 2
fi

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -d "$DEST" ]]; then
  echo "destination directory does not exist: $DEST" >&2
  exit 1
fi
DEST="$(cd "$DEST" && pwd)"

if [[ "$SRC" == "$DEST" ]]; then
  echo "destination must differ from source" >&2
  exit 1
fi

if ! git -C "$SRC" rev-parse --git-dir >/dev/null 2>&1; then
  echo "source is not a git repo: $SRC" >&2
  exit 1
fi

cd "$SRC"

FILE_LIST="$(mktemp)"
trap 'rm -f "$FILE_LIST"' EXIT

git ls-files --cached --others --exclude-standard | awk '
BEGIN {
  allow[".claude"]   = 1
  allow[".codex"]    = 1
  allow["build"]     = 1
  allow["docker"]    = 1
  allow["docs"]      = 1
  allow["helm"]      = 1
  allow["infra"]     = 1
  allow["licenses"]  = 1
  allow["packages"]  = 1
  allow["scripts"]   = 1
  allow["services"]  = 1

  drop_root[".gitlab-ci.yml"]                 = 1
  drop_root[".nspect-allowlist.toml"]         = 1
  drop_root[".container-scan-policy_v2.json"] = 1
  drop_root["TODO.md"]                        = 1
  drop_root["coverage.xml"]                   = 1

  drop_path[".claude/commands/todo.md"]              = 1
  drop_path[".claude/commands/skill-alignment.md"]   = 1
  drop_path["scripts/apply_spdx_headers.py"]         = 1
  drop_path["scripts/generate_third_party_notice.sh"] = 1
  drop_path["scripts/_generate_third_party_notice.py"] = 1

  # CI-only deepsearch-api compose files (mount fixtures from the
  # deleted tests/opensearch-data dir; root docker-compose.yml does NOT
  # include them, so dropping is safe).
  drop_path["infra/compose/deepsearch-api.yml"]              = 1
  drop_path["infra/compose/deepsearch-api.container-test.yml"] = 1
  drop_path["infra/compose/deepsearch-api.test.yml"]         = 1

  # Test driver script that only invoked the deleted tests/ dir.
  drop_path["services/deepsearch_api/test_in_docker_compose.sh"] = 1

  # Any path component matching one of these is dropped (recursive).
  # Covers packages/X/tests/, services/Y/tests/, nested deeper tests/,
  # the custom services/storage/storage/test_storage_api/, and
  # packages/search-utils/integration_tests/. ci/ at the top level is
  # already filtered by the allowlist, but listed here for clarity.
  drop_component["tests"]             = 1
  drop_component["test_storage_api"]  = 1
  drop_component["integration_tests"] = 1
  drop_component["ci"]                = 1

  # Basename drops: any file matching this name at any depth.
  # GitLab CI configs reference the deleted ci/ dir and the root
  # .gitlab-ci.yml is already excluded; drop the per-package ones too.
  drop_basename[".gitlab-ci.yml"] = 1
}
{
  path = $0
  n = split(path, parts, "/")
  top = parts[1]

  if (n == 1) {
    if (top in drop_root) next
    if (top ~ /^usdsearch-.*\.tgz$/) next
    print path
    next
  }

  if (!(top in allow)) next
  if (path in drop_path) next
  if (parts[n] in drop_basename) next

  if (index(path, "packages/storage-api/protos/")  == 1) next
  if (index(path, "packages/storage-api/scripts/") == 1) next
  if (index(path, "services/deepsearch_api/docker/") == 1) next
  if (index(path, "services/asset-graph/samples/")   == 1) next

  for (i = 1; i < n; i++) {
    if (parts[i] in drop_component) next
  }

  print path
}
' > "$FILE_LIST"

LINE_COUNT="$(wc -l < "$FILE_LIST")"

echo "Source:      $SRC"
echo "Destination: $DEST"
[[ -n "$DRY_RUN" ]] && echo "Mode:        dry-run"
[[ -n "$CLEAN"   ]] && echo "Clean:       yes (will wipe destination)"
echo "Files:       $LINE_COUNT"
echo

if [[ -n "$CLEAN" ]]; then
  echo "==> Cleaning destination (preserving .git/, .github/)"
  if [[ -z "$DRY_RUN" ]]; then
    find "$DEST" -mindepth 1 -maxdepth 1 \
      ! -name '.git' ! -name '.github' \
      -exec rm -rf {} +
  else
    find "$DEST" -mindepth 1 -maxdepth 1 \
      ! -name '.git' ! -name '.github' \
      -printf '[dry-run] would remove: %p\n'
  fi
fi

echo "==> Syncing"
rsync -av $DRY_RUN \
  --files-from="$FILE_LIST" \
  "$SRC/" "$DEST/"

echo
echo "Done."
