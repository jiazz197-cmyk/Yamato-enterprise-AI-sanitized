#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[layer-check] 1/3 usecases must not import integrations"
if grep -R --line-number --include="*.py" "from app.integrations" app/usecases; then
  echo "[layer-check] FAILED: app/usecases should depend on ports/adapters only."
  exit 1
fi

echo "[layer-check] 2/3 remediated routes must not import integrations"
if grep -R --line-number --include="*.py" "from app.integrations" \
  app/api/v1/chat_summary.py \
  app/api/v1/quotation_generation.py \
  app/api/v1/document_processing.py \
  app/api/v1/pdf2image.py \
  app/api/v1/image2url.py \
  app/api/v1/file_manager.py \
  app/api/v1/context_compression.py \
  app/api/v1/closing_form.py \
  app/api/v1/sqlserver_queries.py; then
  echo "[layer-check] FAILED: remediated routes still import integrations directly."
  exit 1
fi

echo "[layer-check] 3/3 ports must contain Protocol definitions"
if ! grep -R --line-number --include="*.py" "Protocol" app/ports >/dev/null; then
  echo "[layer-check] FAILED: Protocol not found under app/ports."
  exit 1
fi

echo "[layer-check] PASSED"
