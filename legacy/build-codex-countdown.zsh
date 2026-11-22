#!/bin/zsh
set -euo pipefail
setup_dir="${0:A:h}"
source_dir="${1:-/private/tmp/codex-reset-source-0.165.0}"
export RUSTUP_HOME="$setup_dir/.build/rustup"
export CARGO_HOME="$setup_dir/.build/cargo"
export PATH="$CARGO_HOME/bin:$PATH"
if [[ ! -d "$source_dir/.git" ]]; then
    git clone --depth 1 --branch rust-v0.165.0 https://github.com/openai/codex.git "$source_dir"
fi
/usr/bin/python3 "$setup_dir/apply-codex-countdown.py" "$source_dir"
cd "$source_dir/codex-rs"
cargo build --profile dev-small -p codex-cli --bin codex -j 4
cargo test --profile dev-small -p codex-tui --lib status_line_five_hour_countdown_uses_server_timestamp -j 4
