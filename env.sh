# Source this before working on wowvoice:  source ~/wowvoice/env.sh
# Keeps every tool, Python install, cache and model download inside ~/wowvoice.
export WOWVOICE="$HOME/wowvoice"
export PATH="$WOWVOICE/tools/bin:$PATH"
export UV_PYTHON_INSTALL_DIR="$WOWVOICE/tools/python"
export UV_CACHE_DIR="$WOWVOICE/.cache/uv"
export UV_PYTHON_PREFERENCE=only-managed
export HF_HOME="$WOWVOICE/models/hf"
export TORCH_HOME="$WOWVOICE/.cache/torch"
# uv writes a small credentials/lock folder under XDG_DATA_HOME; keep that inside wowvoice too.
uv()  { XDG_DATA_HOME="$WOWVOICE/.cache/xdg-data" command uv "$@"; }
uvx() { XDG_DATA_HOME="$WOWVOICE/.cache/xdg-data" command uvx "$@"; }
# GitHub CLI (tools/bin/gh): login + token stay inside wowvoice (.cache is never committed)
export GH_CONFIG_DIR="$WOWVOICE/.cache/gh"
