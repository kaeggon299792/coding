from types import SimpleNamespace

from services import news_alert_policy


def _detail(**overrides):
    values = {
        "importance": "high",
        "impact_direction": "negative",
        "summary": "기금 상한이 15%로 오르는 방안이 논의 중이며 시행일은 미확정입니다.",
        "evidence": ["현재 상한은 10%입니다.", "업계가 공식 반대 의견을 냈습니다."],
        "company_impact": "비용 증가 가능성이 있습니다. 수익성 영향은 추정입니다.",
        "inferences": [],
        "follow_up_items": ["최종 누진 구간", "시행 시점"],
        "executive_report_required": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_alert_format_is_mobile_and_high_only_has_executive_notice():
    article = SimpleNamespace(title="기금 개편안", original_url="https://example.com/a?x=1&y=2")
    lines = news_alert_policy.build_issue_lines(
        "관광기금 인상",
        _detail(),
        [article],
        lambda value: str(value).replace("&", "&amp;"),
    )
    assert len(lines) <= 15
    assert lines[0] == "📌 관광기금 인상"
    assert lines[1] == "중요도: 높음 | 영향: 부정"
    assert "핵심" in lines
    assert "당사 영향" in lines
    assert "확인 필요" in lines
    assert "기사: 기금 개편안" in lines
    assert "https://example.com/a?x=1&amp;y=2" in lines
    assert lines[-1] == "⚠️ 경영진 보고 검토 필요"

    medium = news_alert_policy.build_issue_lines(
        "참고 이슈",
        _detail(importance="medium", executive_report_required=False),
        [article],
        str,
    )
    assert "⚠️ 경영진 보고 검토 필요" not in medium


def test_policy_patches_legacy_worker_without_api_or_schema_changes():
    analyzer = SimpleNamespace(DETAIL_SYSTEM_PROMPT="old")
    sender = SimpleNamespace(escape_html=str, build_issue_message=None)
    news_alert_policy.apply_news_alert_policy(analyzer, sender)
    assert "30초" in analyzer.DETAIL_SYSTEM_PROMPT
    message = sender.build_issue_message(
        "이슈", _detail(), [SimpleNamespace(title="기사", original_url="https://example.com")]
    )
    assert message.startswith("📌 이슈\n중요도: 높음 | 영향: 부정")
    assert len([line for line in message.splitlines() if line.strip()]) <= 15


def test_policy_routes_issue_alerts_to_member_news_preference(monkeypatch):
    class Connection:
        closed = False

        def close(self):
            self.closed = True

    connection = Connection()
    broadcasts = []
    monkeypatch.setattr(news_alert_policy, "dashboard_db", lambda: connection)
    monkeypatch.setattr(
        news_alert_policy.member_telegram,
        "broadcast",
        lambda conn, preference, text: broadcasts.append((conn, preference, text))
        or {"recipients": 1, "sent": 1, "failed": 0},
    )
    analyzer = SimpleNamespace(DETAIL_SYSTEM_PROMPT="old")
    sender = SimpleNamespace(escape_html=lambda value: str(value).replace("&", "&amp;"))
    news_alert_policy.apply_news_alert_policy(analyzer, sender)
    entry = {
        "issue_title": "카지노 뉴스",
        "detail_result": _detail(),
        "articles": [SimpleNamespace(
            title="기사", original_url="https://example.com/a?x=1&y=2"
        )],
        "is_update": False,
    }

    assert sender.send_issue_notifications([entry]) == [entry]
    assert broadcasts[0][0] is connection
    assert broadcasts[0][1] == "news"
    assert "x=1&y=2" in broadcasts[0][2]
    assert connection.closed
