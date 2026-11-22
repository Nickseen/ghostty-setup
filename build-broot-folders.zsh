#!/bin/zsh
set -euo pipefail
setup_dir="${0:A:h}"
source_dir="$setup_dir/.build/broot-folders-src"
source "$setup_dir/build-env.zsh"
if [[ ! -f "$source_dir/Cargo.toml" ]]; then
    git clone --depth 1 --branch v1.61.0 https://github.com/Canop/broot.git "$source_dir"
fi
if [[ ! -f "$source_dir/src/tree/folder_folding.rs" ]]; then
    (cd "$source_dir" && /usr/bin/patch -p1 < "$setup_dir/broot-folders.patch")
fi
if ! /usr/bin/grep -q BROOT_HIDE_SCROLLBAR "$source_dir/src/display/displayable_tree.rs"; then
    (cd "$source_dir" && /usr/bin/patch -p1 < "$setup_dir/broot-no-scrollbar.patch")
fi
if ! /usr/bin/grep -q 'pub struct NestedLineStatusComputer' "$source_dir/src/git/status.rs"; then
    (cd "$source_dir" && /usr/bin/patch -p1 < "$setup_dir/broot-nested-git.patch")
fi
if ! /usr/bin/grep -q 'pub mod input_events;' "$source_dir/src/lib.rs"; then
    (cd "$source_dir" && /usr/bin/patch -p1 < "$setup_dir/broot-scroll.patch")
fi
/bin/cp "$setup_dir/broot-input-events.rs" "$source_dir/src/input_events.rs"
if ! /usr/bin/grep -q "Self::New => 'U'" "$source_dir/src/git/status.rs"; then
    (cd "$source_dir" && /usr/bin/patch -p1 < "$setup_dir/broot-untracked-u.patch")
fi
if ! /usr/bin/grep -q BROOT_SHORTCUT_HINTS "$source_dir/src/app/standard_status.rs"; then
    (cd "$source_dir" && /usr/bin/patch -p1 < "$setup_dir/broot-shortcut-hints.patch")
fi
export CARGO_PROFILE_RELEASE_LTO=false
export CARGO_PROFILE_RELEASE_CODEGEN_UNITS=16
export CARGO_PROFILE_RELEASE_OPT_LEVEL=2
(cd "$source_dir" && cargo +1.99.1 build --release --locked --features clipboard -j 4)
rustc +1.99.1 --edition 2024 --test "$source_dir/src/tree/folder_folding.rs" -o "$setup_dir/.build/test-broot-folding"
"$setup_dir/.build/test-broot-folding"
cd "$setup_dir"
/usr/bin/python3 -m unittest -v test_broot_folders test_broot_nested_git test_broot_scroll
