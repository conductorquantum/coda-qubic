#!/usr/bin/env bash
# Clone LBNL QubiC ``software`` and ``distributed_processor`` repos and
# install them editable into the current uv/virtualenv so
# ``load_qubic_dependencies()`` succeeds (simulator, compile, and RPC
# paths; local FPGA still needs pynq).
# Note: ``coda-node`` is installed from PyPI via pyproject.toml.
#
# Usage:
#   cd /path/to/coda-qubic
#   uv sync --dev
#   ./scripts/install-qubic-stack.sh              # installs under ./.qubic-stack
#   ./scripts/install-qubic-stack.sh /other/root  # custom tree layout (if QUBIC_ROOT unset)
#   QUBIC_ROOT=/other/root ./scripts/install-qubic-stack.sh  # wins over positional DIR
#
# Options:
#   --update, -u     git pull in existing clones (shallow fetch)
#   -h, --help       show this help
#
# Environment:
#   QUBIC_SOFTWARE_GIT_URL       default https://gitlab.com/LBL-QubiC/software.git
#   QUBIC_DISTPROC_GIT_URL       default https://gitlab.com/LBL-QubiC/distributed_processor.git
#   QUBIC_GIT_BRANCH             default master
#   QUBIC_GIT_DEPTH              default 1 (shallow clone)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

UPDATE=0
POSITIONAL=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --update | -u)
      UPDATE=1
      shift
      ;;
    -h | --help)
      cat <<'HELP'
Clone LBNL QubiC software + distributed_processor and pip-install
editable (uv). coda-node is installed from PyPI.

Usage: ./scripts/install-qubic-stack.sh [DIR] [--update]
  DIR   Install tree (default: ./.qubic-stack). Ignored if QUBIC_ROOT is set.

Options:
  --update, -u   git pull existing clones
  -h, --help     This message

Environment: QUBIC_ROOT, QUBIC_SOFTWARE_GIT_URL, QUBIC_DISTPROC_GIT_URL,
  QUBIC_GIT_BRANCH (default master), QUBIC_GIT_DEPTH (default 1).
HELP
      exit 0
      ;;
    -*)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
    *)
      POSITIONAL+=("$1")
      shift
      ;;
  esac
done

if [[ ${#POSITIONAL[@]} -gt 1 ]]; then
  echo "At most one install directory argument is allowed." >&2
  exit 2
fi

DEFAULT_ROOT="${REPO_ROOT}/.qubic-stack"
QUBIC_STACK_ROOT="${QUBIC_ROOT:-${POSITIONAL[0]:-$DEFAULT_ROOT}}"

SOFTWARE_URL="${QUBIC_SOFTWARE_GIT_URL:-https://gitlab.com/LBL-QubiC/software.git}"
DISTPROC_URL="${QUBIC_DISTPROC_GIT_URL:-https://gitlab.com/LBL-QubiC/distributed_processor.git}"
BRANCH="${QUBIC_GIT_BRANCH:-master}"
DEPTH="${QUBIC_GIT_DEPTH:-1}"

git_clone_or_update() {
  local url="$1" dest="$2" branch="$3"
  if [[ -d "${dest}/.git" ]]; then
    if [[ "$UPDATE" -eq 1 ]]; then
      git -C "$dest" fetch --depth="$DEPTH" origin "$branch"
      git -C "$dest" checkout "$branch"
      git -C "$dest" pull --ff-only origin "$branch"
    fi
  else
    mkdir -p "$(dirname "$dest")"
    git clone --depth "$DEPTH" --branch "$branch" "$url" "$dest"
  fi
}

echo "QubiC stack root: $QUBIC_STACK_ROOT"
mkdir -p "$QUBIC_STACK_ROOT"
git_clone_or_update "$SOFTWARE_URL" "$QUBIC_STACK_ROOT/software" "$BRANCH"
git_clone_or_update "$DISTPROC_URL" "$QUBIC_STACK_ROOT/distributed_processor" "$BRANCH"

for need in "$QUBIC_STACK_ROOT/software/pyproject.toml" \
  "$QUBIC_STACK_ROOT/distributed_processor/python/pyproject.toml"; do
  if [[ ! -f "$need" ]]; then
    echo "Expected file missing after clone: $need" >&2
    exit 1
  fi
done

cd "$REPO_ROOT"
if ! command -v uv &>/dev/null; then
  echo "uv not found. Install from https://docs.astral.sh/uv/" >&2
  exit 1
fi

echo "Installing editable distproc + lbl-qubic (pulls qubitconfig, numpy, … from PyPI)…"
uv pip install -e "$QUBIC_STACK_ROOT/distributed_processor/python" -e "$QUBIC_STACK_ROOT/software"

cat <<EOF

Done. Optional: export QUBIC_ROOT='$QUBIC_STACK_ROOT'
(Editable installs usually make this unnecessary unless you rely on sys.path injection.)

Run QubiC integration tests:
  uv run pytest tests/test_simulator_circuits.py tests/test_compile_integration.py
EOF
