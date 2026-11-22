//! Countdown for the active account's reported five-hour quota window.

pub(crate) fn reset_countdown(reset: Option<i64>, now: i64) -> Option<String> {
    let seconds = reset?.saturating_sub(now);
    if seconds <= 0 {
        return None;
    }
    let minutes = seconds.saturating_add(59) / 60;
    let hours = minutes / 60;
    let minutes = minutes % 60;
    Some(if hours > 0 {
        format!("↻ {hours}ч {minutes:02}м")
    } else {
        format!("↻ {minutes}м")
    })
}

#[cfg(test)]
mod tests {
    use super::reset_countdown;

    #[test]
    fn rounds_up_and_counts_down_across_hour_boundary() {
        assert_eq!(reset_countdown(Some(7261), 0).as_deref(), Some("↻ 2ч 02м"));
        assert_eq!(reset_countdown(Some(7261), 3661).as_deref(), Some("↻ 1ч 00м"));
        assert_eq!(reset_countdown(Some(7261), 7201).as_deref(), Some("↻ 1м"));
        assert_eq!(reset_countdown(Some(7261), 7260).as_deref(), Some("↻ 1м"));
    }

    #[test]
    fn missing_or_expired_reset_does_not_invent_a_new_window() {
        assert_eq!(reset_countdown(None, 0), None);
        assert_eq!(reset_countdown(Some(100), 100), None);
        assert_eq!(reset_countdown(Some(100), 101), None);
    }
}
