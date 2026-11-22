#!/bin/zsh

# Open a Quick Look window and activate its qlmanage process once it exists.
if (( $# != 1 )) || [[ ! -f "$1" ]]; then
    print -u2 'Usage: quicklook-front.sh FILE'
    exit 2
fi

/usr/bin/qlmanage -p "$1" >/dev/null 2>&1 &
ql_pid=$!

/usr/bin/osascript "${0:A:h}/quicklook-front.applescript" "$ql_pid"
