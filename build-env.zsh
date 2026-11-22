# Source this file from build scripts. Rust stays inside this checkout.
export RUSTUP_HOME="$setup_dir/.build/rustup"
export CARGO_HOME="$setup_dir/.build/cargo"
export PATH="$CARGO_HOME/bin:$PATH"
mkdir -p "$setup_dir/.build"
if [[ ! -x "$CARGO_HOME/bin/rustup" ]]; then
    curl --proto '=https' --tlsv1.2 -fLsS https://sh.rustup.rs -o "$setup_dir/.build/rustup-init.sh"
    sh "$setup_dir/.build/rustup-init.sh" -y --no-modify-path --profile minimal --default-toolchain 1.99.1
fi
if ! rustup run 1.99.1 rustc --version >/dev/null 2>&1; then
    rustup toolchain install 1.99.1 --profile minimal
fi
