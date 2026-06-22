#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
if [ "$#" -ne 2 ]; then
  echo "Usage: scripts/smoke_test.sh <port-a> <port-b>" >&2
  echo "Example: scripts/smoke_test.sh /dev/cu.usbserial-110 /dev/cu.usbserial-120" >&2
  exit 2
fi
python3 -m csi_lab1.smoke_test --port-a "$1" --port-b "$2"
