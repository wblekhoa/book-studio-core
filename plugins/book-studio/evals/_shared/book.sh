#!/bin/bash
# Seed an eval workspace with the synthetic book. $1 = "finished" also builds a finished project.
set -euo pipefail
EVALS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 "$EVALS/_shared/make_book.py" synthetic.epub
if [ "${1:-}" = "finished" ]; then
  python3 "$EVALS/_shared/make_finished_project.py" "$(dirname "$EVALS")"
  rm -f answers.json response-*.json
fi
