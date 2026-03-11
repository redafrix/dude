from __future__ import annotations

import logging
from pathlib import Path

from dude.browser import BrowserController, parse_browser_request
from dude.config import load_config


def test_parse_browser_request_defaults_to_headless_capture() -> None:
    request = parse_browser_request(
        "open browser https://example.com/docs",
        default_url="https://fallback.test",
        headless_by_default=True,
    )

    assert request.action == "open"
    assert request.url == "https://example.com/docs"
    assert request.headed is False
    assert request.capture_screenshot is True
    assert request.show_state_only is False


def test_parse_browser_request_detects_visible_mode() -> None:
    request = parse_browser_request(
        "open the browser and show me the page https://example.com",
        default_url="https://fallback.test",
        headless_by_default=True,
    )

    assert request.action == "open"
    assert request.url == "https://example.com"
    assert request.headed is True
    assert request.show_state_only is False


def test_parse_browser_request_detects_show_state_only() -> None:
    request = parse_browser_request(
        "show me what you're doing",
        default_url="https://fallback.test",
        headless_by_default=True,
    )

    assert request.action == "state"
    assert request.url is None
    assert request.headed is False
    assert request.capture_screenshot is False
    assert request.show_state_only is True


def test_parse_browser_request_builds_search_url() -> None:
    request = parse_browser_request(
        "search web for discord linux download",
        default_url="https://fallback.test",
        headless_by_default=True,
    )

    assert request.action == "open"
    assert request.url is not None
    assert "google.com/search" in request.url
    assert "discord+linux+download" in request.url


def test_parse_browser_request_detects_summarize_action() -> None:
    request = parse_browser_request(
        "summarize the page",
        default_url="https://fallback.test",
        headless_by_default=True,
    )

    assert request.action == "summarize"
    assert request.url is None


def test_browser_controller_can_summarize_current_page(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = load_config(Path("configs/default.yaml"))
    config.browser.artifact_dir = tmp_path / "browser"
    controller = BrowserController(config, logging.getLogger("test"))
    controller._save_state(
        {
            "updated_at": "now",
            "mode": "headless",
            "engine": "playwright",
            "url": "https://example.com",
            "title": "Example",
            "screenshot_path": None,
        }
    )

    monkeypatch.setattr(
        controller,
        "_inspect_page",
        lambda url, working_dir, capture_screenshot: {
            "command": ["browser", "inspect"],
            "url": url,
            "title": "Example Domain",
            "excerpt": "Example body text for the page summary.",
            "links": [],
            "screenshot_path": "",
        },
    )

    result = controller.execute_request("summarize the page", tmp_path)

    assert result.exit_code == 0
    assert "Page summary for https://example.com." in result.stdout_text
    assert "Example body text for the page summary." in result.stdout_text
