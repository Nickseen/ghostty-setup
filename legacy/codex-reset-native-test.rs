#[tokio::test]
async fn status_line_five_hour_countdown_uses_server_timestamp() {
    let (mut chat, _rx, _op_rx) = make_chatwidget_manual(/*model_override*/ None).await;
    let now = chrono::Utc::now().timestamp();
    let make_snapshot = |reset| RateLimitSnapshot {
        limit_id: None,
        limit_name: None,
        normal_model_slug: None,
        primary: Some(RateLimitWindow {
            used_percent: 3,
            window_duration_mins: Some(300),
            resets_at: reset,
        }),
        secondary: None,
        credits: None,
        individual_limit: None,
        plan_type: None,
        spend_control_reached: None,
        rate_limit_reached_type: None,
    };
    chat.on_rate_limit_snapshot(Some(make_snapshot(Some(now + 7200))));
    assert_eq!(
        chat.status_line_value_for_item(crate::bottom_pane::StatusLineItem::FiveHourLimit),
        Some("5h 97% left · ↻ 2ч 00м".to_string())
    );
    chat.on_rate_limit_snapshot(Some(make_snapshot(Some(now - 1))));
    assert_eq!(
        chat.status_line_value_for_item(crate::bottom_pane::StatusLineItem::FiveHourLimit),
        Some("5h 97% left".to_string())
    );
}
