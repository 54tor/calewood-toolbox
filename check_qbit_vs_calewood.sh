#!/usr/bin/env bash
set -euo pipefail

# For each qBittorrent torrent, query Calewood /api/torrent/list?q=<hash> and report items
# that exist in Calewood but have no lacale_hash (unknown La-Cale hash).
#
# Usage:
#   ./check_qbit_vs_calewood.sh <CALEWOOD_TOKEN> <QBIT_BASE_URL> <QBIT_USERNAME> <QBIT_PASSWORD> [CALEWOOD_BASE_URL]
#
# Example:
#   ./check_qbit_vs_calewood.sh "$TOKEN" "https://qbittorrent.example" "user" "pass"

TOKEN="${1:?CALEWOOD_TOKEN}"
QBIT_BASE="${2:?QBIT_BASE_URL (ex: https://qbittorrent.example)}"
QBIT_USER="${3:?QBIT_USERNAME}"
QBIT_PASS="${4:?QBIT_PASSWORD}"
CALEWOOD_BASE="${5:-http://calewood.n0flow.io/api}"

# Normalize: allow passing base with or without trailing /api, but keep a base without it
# since the script appends /api/... paths below.
CALEWOOD_BASE="${CALEWOOD_BASE%/}"
if [[ "$CALEWOOD_BASE" == */api ]]; then
  CALEWOOD_BASE="${CALEWOOD_BASE%/api}"
fi

PER_PAGE=200

if ! command -v jq >/dev/null 2>&1; then
  echo "Missing dependency: jq" >&2
  exit 2
fi

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

cookie="$tmpdir/qbit.cookie"
qbit_items="$tmpdir/qbit_items.tsv"
qbit_items0="$tmpdir/qbit_items0.bin"

# qBittorrent login (cookie)
curl -fsS -c "$cookie" -b "$cookie" \
  -X POST \
  -d "username=$QBIT_USER&password=$QBIT_PASS" \
  "$QBIT_BASE/api/v2/auth/login" >/dev/null

# qBittorrent list (hash + name)
qbit_json="$tmpdir/qbit.json"
curl -fsS -b "$cookie" \
  "$QBIT_BASE/api/v2/torrents/info?filter=all" \
  > "$qbit_json"

jq -r '
    .[]
    | [(.hash // "" | ascii_downcase), (.name // "" | gsub("\\t";" "))]
    | @tsv
  ' "$qbit_json" \
| sed '/^\t/d' > "$qbit_items"

# NUL-delimited version for xargs -0 (avoids quote issues in names).
jq -j '
    .[]
    | ((.hash // "" | ascii_downcase) + "\t" + ((.name // "" | gsub("\t";" "))) + "\u0000")
  ' "$qbit_json" > "$qbit_items0"

total_qb="$(wc -l < "$qbit_items" | tr -d ' ')"
echo "qBittorrent: torrents=$total_qb" >&2

# Query Calewood for each qBittorrent hash and print those found but missing lacale_hash.
# Output columns: QBIT_HASH  CALEWOOD_ID  STATUS  SEEDBOX_PROGRESS  NAME
query_one() {
  local h="$1"
  local name="$2"
  local resp
  resp="$(curl -fsS -H "Authorization: Bearer $TOKEN" \
    "$CALEWOOD_BASE/api/torrent/list?q=$h&per_page=$PER_PAGE&p=1" || true)"
  [[ -z "$resp" ]] && return 0
  # Find first exact match on sharewood_hash or lacale_hash.
  echo "$resp" | jq -r --arg h "$h" --arg name "$name" '
      .data as $d
      | ($d | map(select(((.sharewood_hash // "" | ascii_downcase) == ($h|ascii_downcase)) or ((.lacale_hash // "" | ascii_downcase) == ($h|ascii_downcase)))) | .[0]) as $m
      | if ($m|type) == "object" then
          if (($m.lacale_hash // "")|tostring|length) == 0 then
            [($h|ascii_downcase), ($m.id|tostring), ($m.status // ""), (($m.seedbox_progress // "")|tostring), ($m.name // $name)] | @tsv
          else empty end
        else empty end
    ' 2>/dev/null
}

export -f query_one
export TOKEN CALEWOOD_BASE PER_PAGE

cat "$qbit_items0" \
| xargs -0 -P 20 -n 1 bash -lc 'h="${1%%$'\''\t'\''*}"; n="${1#*$'\''\t'\''}"; query_one "$h" "$n"' _ \
| awk 'BEGIN{print "QBIT_HASH\tCALEWOOD_ID\tSTATUS\tSEEDBOX_PROGRESS\tNAME"} {print}' \
| column -t -s $'\t'
