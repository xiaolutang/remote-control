#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.local.env"

SERVER_IP="${RC_TEST_SERVER_IP:-}"
USERNAME="${RC_TEST_USERNAME:-}"
PASSWORD="${RC_TEST_PASSWORD:-}"

if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
fi

SERVER_IP="${SERVER_IP:-${RC_SERVER_IP:-}}"
USERNAME="${USERNAME:-prod_test}"
PASSWORD="${PASSWORD:-test123456}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --server-ip)
      SERVER_IP="${2:-}"
      shift 2
      ;;
    --username)
      USERNAME="${2:-}"
      shift 2
      ;;
    --password)
      PASSWORD="${2:-}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: $0 [--server-ip IP] [--username USER] [--password PASS]" >&2
      exit 1
      ;;
  esac
done

if [[ -z "${SERVER_IP}" ]]; then
  echo "Error: missing server ip." >&2
  echo "Set RC_TEST_SERVER_IP, or RC_SERVER_IP in $ENV_FILE, or pass --server-ip." >&2
  exit 1
fi

echo "Running production network e2e against ${SERVER_IP}"
exec dart run tool/production_network_e2e.dart \
  --server-ip "${SERVER_IP}" \
  --username "${USERNAME}" \
  --password "${PASSWORD}"
