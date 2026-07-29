#!/usr/bin/env bash
# Run once after cloning: sets this repo's git hooks to the versioned ones in
# .githooks/ (default .git/hooks/ is not committed, so hooks must be wired up
# explicitly per clone).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

chmod +x .githooks/pre-commit
git config core.hooksPath .githooks

echo "Hooks installed (core.hooksPath=.githooks)."
echo "Optional: install gitleaks locally so pre-commit can actually scan:"
echo "  https://github.com/gitleaks/gitleaks#installing"
