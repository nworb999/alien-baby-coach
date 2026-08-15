#!/bin/sh
set -eu
cd "$(dirname "$0")"

printf '\n1. Running deterministic end-to-end tests...\n\n'
python3 -m unittest -v

printf '\n2. Starting Alien Baby Coach.\n'
printf '   Pick a voice, describe a work situation, or type /help.\n'
printf '   Exit with /quit or Ctrl-D.\n\n'
exec python3 coach.py
