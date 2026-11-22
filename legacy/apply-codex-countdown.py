#!/usr/bin/python3
"""Apply the local footer-only change to official Codex rust-v0.165.0."""
from pathlib import Path
import re
import sys

root = Path(sys.argv[1]) / 'codex-rs/tui/src'
here = Path(__file__).resolve().parent


def replace(relative, before, after):
    path = root / relative
    text = path.read_text()
    if after in text or re.sub(r'\s+', '', after) in re.sub(r'\s+', '', text):
        return
    if text.count(before) != 1:
        raise SystemExit(f'Unexpected Codex source in {relative}; no blind replacement')
    path.write_text(text.replace(before, after, 1))


replace('status/rate_limits.rs',
        '    /// Human-readable local reset time.\n    pub resets_at: Option<String>,',
        '    /// Server-provided Unix timestamp, retained for the live footer countdown.\n'
        '    pub reset_timestamp: Option<i64>,\n'
        '    /// Human-readable local reset time.\n    pub resets_at: Option<String>,')
replace('status/rate_limits.rs',
        '            used_percent: f64::from(window.used_percent),\n            resets_at,',
        '            used_percent: f64::from(window.used_percent),\n'
        '            reset_timestamp: window.resets_at,\n            resets_at,')
# Display-only fixtures don't report an absolute reset timestamp.
for relative in ('status/rate_limits.rs', 'status/tests.rs'):
    path = root / relative
    text = path.read_text()
    text = re.sub(r'(RateLimitWindowDisplay \{\n\s+used_percent: [^\n]+,\n)(\s+resets_at:)',
                  lambda m: m[1] + re.match(r'\s*', m[2])[0] + 'reset_timestamp: None,\n' + m[2], text)
    text = re.sub(r'(RateLimitWindowDisplay \{\n\s+used_percent,\n)(\s+resets_at:)',
                  lambda m: m[1] + re.match(r'\s*', m[2])[0] + 'reset_timestamp: None,\n' + m[2], text)
    path.write_text(text)

(root / 'status/reset_countdown.rs').write_text((here / 'codex-reset-native.rs').read_text())
replace('status/mod.rs', 'mod rate_limits;\n', 'mod rate_limits;\npub(crate) mod reset_countdown;\n')
replace('chatwidget/status_controls.rs',
        '        Some(format!("{label} {remaining:.0}% left"))',
        '        let mut text = format!("{label} {remaining:.0}% left");\n'
        '        if window.window_minutes == Some(300)\n'
        '            && let Some(countdown) = crate::status::reset_countdown::reset_countdown(\n'
        '                window.reset_timestamp, chrono::Utc::now().timestamp(),\n'
        '            )\n'
        '        {\n'
        '            text.push_str(" · ");\n'
        '            text.push_str(&countdown);\n'
        '        }\n'
        '        Some(text)')
replace('chatwidget/status_surfaces.rs',
        '    pub(super) fn refresh_status_line_if_workspace_headline_due(&mut self) {',
        '    /// Refresh a native footer countdown even while the conversation is idle.\n'
        '    pub(super) fn refresh_status_line_reset_countdown(&mut self) {\n'
        '        let selections = self.status_surface_selections();\n'
        '        let has_reset = self.rate_limit_snapshots_by_limit_id.get("codex")\n'
        '            .and_then(five_hour_status_window)\n'
        '            .is_some_and(|(window, _)| window.reset_timestamp.is_some());\n'
        '        if has_reset && selections.status_line_items.contains(&StatusLineItem::FiveHourLimit) {\n'
        '            self.refresh_status_line_from_selections(&selections);\n'
        '            self.frame_requester.schedule_frame_in(Duration::from_secs(30));\n'
        '        }\n'
        '    }\n\n'
        '    pub(super) fn refresh_status_line_if_workspace_headline_due(&mut self) {')
replace('chatwidget.rs',
        '        self.refresh_status_line_if_workspace_headline_due();',
        '        self.refresh_status_line_reset_countdown();\n'
        '        self.refresh_status_line_if_workspace_headline_due();')
tests = root / 'chatwidget/tests/status_and_layout.rs'
test_text = (here / 'codex-reset-native-test.rs').read_text()
if 'async fn status_line_five_hour_countdown_uses_server_timestamp' not in tests.read_text():
    tests.write_text(tests.read_text() + '\n' + test_text)
print('Native Codex footer countdown patch applied')
