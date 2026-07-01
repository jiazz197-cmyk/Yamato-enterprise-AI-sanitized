#!/usr/bin/env bash
# Render nginx/nginx.conf from nginx/nginx.conf.template.
#
# The template no longer needs envsubst (no Dify API key to inject — chat is now
# served by the backend under JWT auth). It is copied verbatim; nginx $variables
# are preserved as-is.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE="${ROOT}/nginx/nginx.conf.template"
OUT="${ROOT}/nginx/nginx.conf"

if [[ ! -f "$TEMPLATE" ]]; then
  echo "Missing template: $TEMPLATE" >&2
  exit 1
fi

cp "$TEMPLATE" "$OUT"
echo "Wrote $OUT"
