#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./verify_my_archives.sh "CALEWOOD_TOKEN" "https://calewood.example" "10.0.23.22" "user" "pass"
#
# Optional:
#   OPEN=1  (open missing downloads in batches of 10 with 1s pause)

CALEWOOD_TOKEN="${1:?calewood token}"
CALEWOOD_BASE_URL="${2:?calewood base url (e.g. http://calewood.n0flow.io/api)}"

# Normalize: allow passing base with or without trailing /api, but keep a base without it
# since this script appends /api/... paths.
CALEWOOD_BASE_URL="${CALEWOOD_BASE_URL%/}"
if [[ "$CALEWOOD_BASE_URL" == */api ]]; then
  CALEWOOD_BASE_URL="${CALEWOOD_BASE_URL%/api}"
fi
QBIT_BASE_URL="${3:?qbit base url (e.g. http://10.0.0.2)}"
QBIT_USER="${4:?qbit username}"
QBIT_PASS="${5:?qbit password}"

PER_PAGE=200

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

archives_jsonl="$tmp/archives.jsonl"
qbit_hashes="$tmp/qbit_hashes.txt"
missing_jsonl="$tmp/missing.jsonl"
unknown_jsonl="$tmp/unknown.jsonl"

# 1) Fetch all my-archives (paged)
page=1
while :; do
  resp="$tmp/page_${page}.json"
  curl -fsS \
    -H "Authorization: Bearer ${CALEWOOD_TOKEN}" \
    "${CALEWOOD_BASE_URL}/api/archive/list?status=my-archives&per_page=${PER_PAGE}&p=${page}&v1_only=0" \
    -o "$resp"

  jq -c '.data[]' "$resp" >> "$archives_jsonl" || true
  has_more="$(jq -r '.meta.has_more // false' "$resp")"
  [[ "$has_more" == "true" ]] || break
  page=$((page+1))
done

# 2) Fetch all qBittorrent hashes (offline set)
cookiejar="$tmp/qb.cookies.txt"

# qBittorrent WebUI uses a login endpoint that sets a cookie (Basic auth won't work).
curl -fsS \
  -c "$cookiejar" \
  -H "Referer: ${QBIT_BASE_URL}" \
  --data-urlencode "username=${QBIT_USER}" \
  --data-urlencode "password=${QBIT_PASS}" \
  "${QBIT_BASE_URL}/api/v2/auth/login" \
  >/dev/null

curl -fsS \
  -b "$cookiejar" \
  "${QBIT_BASE_URL}/api/v2/torrents/info?limit=999999" \
| jq -r '.[].hash' \
| tr '[:upper:]' '[:lower:]' \
| sort -u > "$qbit_hashes"

# 3) Compare
jq -c '
  . as $it
  | ($it.lacale_hash // "" | ascii_downcase) as $h
  | if ($h|length)==0 then
      {"kind":"unknown_hash","id":$it.id,"size_bytes":($it.size_bytes//0),"name":$it.name}
    else
      {"kind":"has_hash","hash":$h,"id":$it.id,"size_bytes":($it.size_bytes//0),"name":$it.name}
    end
' "$archives_jsonl" \
| while read -r line; do
    kind="$(jq -r '.kind' <<<"$line")"
    if [[ "$kind" == "unknown_hash" ]]; then
      echo "$line" >> "$unknown_jsonl"
      continue
    fi
    h="$(jq -r '.hash' <<<"$line")"
    if ! grep -qxF "$h" "$qbit_hashes"; then
      echo "$line" >> "$missing_jsonl"
    fi
  done

# 4) Stats
total="$(wc -l < "$archives_jsonl" | tr -d ' ')"
missing_count=0; [[ -f "$missing_jsonl" ]] && missing_count="$(wc -l < "$missing_jsonl" | tr -d ' ')"
unknown_count=0; [[ -f "$unknown_jsonl" ]] && unknown_count="$(wc -l < "$unknown_jsonl" | tr -d ' ')"

total_gib="$(jq -s '[.[].size_bytes] | add // 0 | . / 1024 / 1024 / 1024' "$archives_jsonl" 2>/dev/null || echo 0)"
missing_gib="$(jq -s '[.[].size_bytes] | add // 0 | . / 1024 / 1024 / 1024' "$missing_jsonl" 2>/dev/null || echo 0)"

echo "total=$total missing=$missing_count unknown_hash=$unknown_count total_gib=$(printf '%.2f' "$total_gib") missing_gib=$(printf '%.2f' "$missing_gib")" >&2

# 5) Print missing table
if [[ -f "$missing_jsonl" ]]; then
  jq -r '[.id, (.size_bytes/1024/1024/1024|floor|tostring + " GiB"), .hash, .name] | @tsv' "$missing_jsonl" \
  | (printf "ID\tSIZE_GIB\tLACALE_HASH\tNAME\n"; cat) \
  | column -t -s $'\t'
fi

# 6) Optional open missing downloads
if [[ "${OPEN:-0}" == "1" && -f "$missing_jsonl" ]]; then
  opener="$(command -v xdg-open || command -v open || true)"
  if [[ -z "$opener" ]]; then
    echo "No opener found (xdg-open/open)." >&2
    exit 1
  fi
  i=0
  while read -r h; do
    url="https://la-cale.space/api/torrents/download/${h}"
    "$opener" "$url" >/dev/null 2>&1 || echo "$url"
    i=$((i+1))
    if (( i % 10 == 0 )); then sleep 1; fi
  done < <(jq -r '.hash' "$missing_jsonl")
fi
