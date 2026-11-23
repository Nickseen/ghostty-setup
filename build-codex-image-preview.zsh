#!/bin/zsh
set -euo pipefail
setup_dir="${0:A:h}"
source_dir="$setup_dir/.build/codex-image-preview-src"
source "$setup_dir/build-env.zsh"
if [[ ! -f "$source_dir/codex-rs/Cargo.toml" ]]; then
    git clone --depth 1 --branch rust-v0.169.0 https://github.com/openai/codex.git "$source_dir"
fi
if ! rg -q preview_composer_image "$source_dir/codex-rs/tui/src/app/owned_transcript.rs"; then
    git -C "$source_dir" apply --check "$setup_dir/codex-image-preview.patch"
    git -C "$source_dir" apply "$setup_dir/codex-image-preview.patch"
fi
# Cached preview sources may still use one oversized tmux packet per image.
if ! rg -q 'Wrap each Kitty chunk independently' "$source_dir/codex-rs/tui/src/pets/image_protocol.rs"; then
    git -C "$source_dir" apply --check "$setup_dir/codex-image-transport.patch"
    git -C "$source_dir" apply "$setup_dir/codex-image-transport.patch"
fi
if ! rg -q 'macos::clipboard_png' "$source_dir/codex-rs/tui/src/clipboard_paste.rs"; then
    git -C "$source_dir" apply --check "$setup_dir/codex-image-paste.patch"
    git -C "$source_dir" apply "$setup_dir/codex-image-paste.patch"
fi
if ! rg -q 'let reusable_images' "$source_dir/codex-rs/tui/src/custom_terminal.rs"; then
    git -C "$source_dir" apply --check "$setup_dir/codex-image-scroll.patch"
    git -C "$source_dir" apply "$setup_dir/codex-image-scroll.patch"
fi
# Cargo resolves the unused V8 host workspace member too. Its Git source recursively
# fetches Chromium submodules. Use the identical checked-out source for metadata;
# the CLI uses the official separately packaged code-mode host executable.
export CODEX_IMAGE_BUILD_SOURCE="$source_dir"
python3 "$setup_dir/prepare-codex-image-build.py"
cd "$source_dir/codex-rs"
cargo +1.99.1 build --profile dev-small -p codex-cli --bin codex -j 6
env -u NO_COLOR cargo +1.99.1 test --profile dev-small -p codex-tui --lib image_click_preview -j 6
env -u NO_COLOR cargo +1.99.1 test --profile dev-small -p codex-tui --lib clipboard_paste::macos::tests -j 6
env -u NO_COLOR cargo +1.99.1 test --profile dev-small -p codex-tui --lib custom_terminal::tests -j 6
