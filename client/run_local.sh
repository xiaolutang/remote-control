#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.local.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Error: $ENV_FILE not found."
  echo "Create it with: echo 'RC_SERVER_IP=192.168.x.x' > $ENV_FILE"
  exit 1
fi

source "$ENV_FILE"

if [[ -z "${RC_SERVER_IP:-}" ]]; then
  echo "Error: RC_SERVER_IP is empty in $ENV_FILE"
  exit 1
fi

echo "Running with SERVER_IP=$RC_SERVER_IP"
flutter run --dart-define=SERVER_IP="$RC_SERVER_IP" "$@"
