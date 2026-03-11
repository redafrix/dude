from dude.config import NormalizationConfig
from dude.normalize import TranscriptNormalizer


def test_normalizer_formats_math_expression() -> None:
    normalizer = TranscriptNormalizer(NormalizationConfig())
    result = normalizer.normalize("alpha minus two plus three")
    assert result.text == "alpha - 2 + 3"
    assert result.changed is True


def test_normalizer_formats_shell_and_filename_tokens() -> None:
    normalizer = TranscriptNormalizer(NormalizationConfig())
    result = normalizer.normalize("dash dash verbose python dot py")
    assert result.text == "--verbose python.py"
    assert result.changed is True
