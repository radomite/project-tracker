#!/bin/sh
set -eu
# Use the compiled, image-matched Mathlib without creating a second checkout.
case "${1:-}" in
  lake|sh|bash) exec "$@" ;;
esac
export LEAN_PATH="$(pwd):$(cat /opt/mathlib/lean-path)${LEAN_PATH:+:$LEAN_PATH}"
exec lean-compiler "$@"
