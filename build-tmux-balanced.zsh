#!/bin/zsh
set -euo pipefail
setup_dir="${0:A:h}"
brew_prefix="$(brew --prefix)"
source_dir="$setup_dir/.build/tmux-3.8"
archive="$setup_dir/.build/tmux-3.8.tar.gz"
mkdir -p "$setup_dir/.build"
if [[ ! -f "$archive" ]]; then
    /usr/bin/curl -fL https://github.com/tmux/tmux/releases/download/3.8/tmux-3.8.tar.gz -o "$archive"
fi
expected=e79c699c7e949dccd0a4a125e17b8d1261e311b16979dbc8eb34542f3966d82e
actual=$(/usr/bin/shasum -a 256 "$archive")
[[ "${actual%% *}" == "$expected" ]] || { print -u2 'Unexpected source archive checksum'; exit 1; }
if [[ ! -f "$source_dir/configure" ]]; then
    /usr/bin/tar -xzf "$archive" -C "$setup_dir/.build"
fi
if ! /usr/bin/grep -q mouse_resize_state "$source_dir/tmux.h"; then
    (cd "$source_dir" && /usr/bin/patch -p1 < "$setup_dir/tmux-balanced.patch")
fi
/bin/cp "$setup_dir/tmux-balanced-layout.c" "$source_dir/layout-balanced.c"
if [[ ! -f "$source_dir/Makefile" ]]; then
    cd "$source_dir"
    ./configure --prefix="$HOME/.local/opt/tmux-balanced/3.8" \
        --enable-utf8proc --enable-jemalloc \
        JEMALLOC_CFLAGS="-I$brew_prefix/opt/jemalloc/include" \
        JEMALLOC_LIBS="-L$brew_prefix/opt/jemalloc/lib -ljemalloc" \
        CPPFLAGS="-I$brew_prefix/opt/libevent/include -I$brew_prefix/opt/ncurses/include -I$brew_prefix/opt/utf8proc/include" \
        LDFLAGS="-L$brew_prefix/opt/libevent/lib -L$brew_prefix/opt/ncurses/lib -L$brew_prefix/opt/utf8proc/lib"
fi
cd "$source_dir"
make -j4
./tmux -V
cd "$setup_dir"
/usr/bin/python3 -m unittest -v test_tmux_balanced_native
