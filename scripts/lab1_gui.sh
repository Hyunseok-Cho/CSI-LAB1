#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
python3 -m csi_lab1.lab1_gui "$@"
