# Stop the shared Codex server before clearing credentials. A new CLI launch
# starts a fresh server with the next account's credentials.
codex() {
  if (( $# == 1 )) && [[ "$1" == logout ]]; then
    if ! command codex remote-control stop; then
      print -u2 'Codex: daemon stop failed; continuing with logout.'
    fi
    command codex logout
    return $?
  fi

  command codex "$@"
}
