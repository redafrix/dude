from dude.metrics import LatencyRecorder


def test_turn_metrics_marks() -> None:
    metrics = LatencyRecorder()
    metrics.mark("one")
    payload = metrics.to_deltas_ms()
    assert "one" in payload
    assert payload["one"] >= 0.0
