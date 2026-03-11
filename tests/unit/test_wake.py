from dude.wake import PhraseWakeDetector


def test_phrase_wake_detector_with_inline_request() -> None:
    detector = PhraseWakeDetector("dude")
    decision = detector.detect("Dude, hello")
    assert decision.triggered is True
    assert decision.remainder == "hello"
    assert decision.backend == "transcript"


def test_phrase_wake_detector_without_wake() -> None:
    detector = PhraseWakeDetector("dude")
    decision = detector.detect("hello there")
    assert decision.triggered is False
