from jarvis.ingestion.cli.health_report import _format_table


def test_health_report_table_includes_latest_published_column() -> None:
    table = _format_table(
        [
            {
                "id": 1,
                "name": "ТАСС",
                "health_status": "green",
                "consecutive_failures": 0,
                "parse_success": 1.0,
                "extraction_success": 0.98,
                "avg_latency_minutes": 12.5,
                "source_utility": 0.44,
                "latest_published_at": "2026-04-13 10:15:00+00:00",
                "staleness_hours": 0.5,
                "runs_24h": 48,
                "items_new_24h": 320,
                "items_in_last_feed": 916,
            }
        ]
    )

    assert "latest_pub" in table
    assert "2026-04-13 10:15:00+00:00" in table
