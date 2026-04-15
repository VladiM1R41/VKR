from jarvis.ingestion.services.health import determine_health_status


def test_determine_health_status_green_when_metrics_are_healthy() -> None:
    assert (
        determine_health_status(
            consecutive_failures=0,
            parse_success_rate=1.0,
            extraction_success_rate=0.95,
        )
        == "green"
    )


def test_determine_health_status_yellow_on_degraded_parse_rate() -> None:
    assert (
        determine_health_status(
            consecutive_failures=0,
            parse_success_rate=0.90,
            extraction_success_rate=0.95,
        )
        == "yellow"
    )


def test_determine_health_status_red_on_recent_http_4xx() -> None:
    assert (
        determine_health_status(
            consecutive_failures=0,
            parse_success_rate=1.0,
            extraction_success_rate=0.95,
            recent_http_4xx=True,
        )
        == "red"
    )


def test_determine_health_status_yellow_on_many_http_errors() -> None:
    assert (
        determine_health_status(
            consecutive_failures=0,
            parse_success_rate=1.0,
            extraction_success_rate=0.95,
            http_errors_count_24h=6,
        )
        == "yellow"
    )


def test_determine_health_status_uses_lower_threshold_for_paywall_sources() -> None:
    assert (
        determine_health_status(
            consecutive_failures=0,
            parse_success_rate=1.0,
            extraction_success_rate=0.75,
            allow_low_extraction=True,
        )
        == "green"
    )


def test_determine_health_status_yellow_on_duplicate_rate_deviation() -> None:
    assert (
        determine_health_status(
            consecutive_failures=0,
            parse_success_rate=1.0,
            extraction_success_rate=0.95,
            duplicate_rate_deviation=0.31,
        )
        == "yellow"
    )


def test_determine_health_status_keeps_green_when_extraction_not_measured_yet() -> None:
    assert (
        determine_health_status(
            consecutive_failures=0,
            parse_success_rate=1.0,
            extraction_success_rate=None,
        )
        == "green"
    )
