#!/usr/bin/python3
"""Show Codex's reported five-hour reset in the tmux status line."""
from datetime import datetime
import argparse
import json
import math
import os
from pathlib import Path
import time


def latest_reset(folder):
    candidates = sorted(folder.rglob('*.jsonl'), key=lambda p: p.stat().st_mtime,
                        reverse=True)[:24]
    latest = None
    for path in candidates:
        try:
            with path.open('rb') as stream:
                size = stream.seek(0, 2)
                stream.seek(max(0, size - 2 * 1024 * 1024))
                lines = stream.read().splitlines()
            for line in reversed(lines):
                if b'"rate_limits"' not in line or b'"resets_at"' not in line:
                    continue
                try:
                    event = json.loads(line)
                    limits = event.get('payload', {}).get('rate_limits') or {}
                    if limits.get('limit_id') not in (None, 'codex'):
                        continue
                    window = next((limits.get(k) for k in ('primary', 'secondary')
                                   if (limits.get(k) or {}).get('window_minutes') == 300), None)
                    if not window or not isinstance(window.get('resets_at'), (int, float)):
                        continue
                    stamp = datetime.fromisoformat(event['timestamp'].replace('Z', '+00:00')).timestamp()
                    candidate = {'observed': stamp, 'reset': window['resets_at']}
                    if latest is None or stamp > latest['observed']:
                        latest = candidate
                    break
                except (ValueError, TypeError, KeyError):
                    continue
        except OSError:
            continue
    return latest


def format_countdown(reset, now):
    remaining = reset - now
    if remaining <= 0:
        return ''  # Wait for Codex to report the next window; never invent one.
    minutes = math.ceil(remaining / 60)
    hours, minutes = divmod(minutes, 60)
    value = f'{hours}ч {minutes:02d}м' if hours else f'{minutes}м'
    return '5ч ↻ ' + value


def format_exact(reset, now):
    if reset <= now:
        return ''
    return datetime.fromtimestamp(reset).astimezone().strftime('%d.%m => %H:%M')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exact', action='store_true')
    args = parser.parse_args()
    home = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
    cache = Path.home() / '.cache/ghostty-setup/codex-reset.json'
    now = time.time()
    try:
        data = json.loads(cache.read_text())
        if data.get('home') != str(home) or now - data.get('checked', 0) > 30:
            data = None
    except (OSError, ValueError, TypeError):
        data = None
    if data is None:
        data = {'home': str(home), 'checked': now, 'limit': latest_reset(home / 'sessions')}
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            temporary = cache.with_name(f'.codex-reset-{os.getpid()}.json')
            temporary.write_text(json.dumps(data))
            temporary.replace(cache)
        except OSError:
            pass
    if data.get('limit'):
        formatter = format_exact if args.exact else format_countdown
        value = formatter(data['limit']['reset'], now)
        if value:
            print(value)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, TypeError):
        pass  # A status helper must never print tracebacks into tmux.
