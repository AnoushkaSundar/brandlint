#!/usr/bin/env bash
# Fails if an LLM provider SDK is imported anywhere outside api/app/gateway/.
set -euo pipefail
pattern='^\s*(import|from)\s+(openai|anthropic|litellm|google\.genai|google\.generativeai|cohere|mistralai)\b'
hits=$(grep -rEn --include='*.py' "$pattern" api | grep -v '^api/app/gateway/' || true)
js_pattern="from ['\"](openai|@anthropic-ai/sdk|@google/genai)['\"]|require\(['\"](openai|@anthropic-ai/sdk|@google/genai)['\"]\)"
js_hits=$(grep -rEn --include='*.ts' --include='*.tsx' --include='*.js' "$js_pattern" web --exclude-dir=node_modules || true)
if [[ -n "$hits$js_hits" ]]; then
  echo "LLM SDK imported outside api/app/gateway/. Use llm.call() instead:"
  echo "$hits"; echo "$js_hits"
  exit 1
fi
echo "OK: no LLM SDK imports outside the gateway."
