from __future__ import annotations

import importlib
import json
import logging
import re
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from dude.config import BrowserConfig, DudeConfig
from dude.logging import log_event


@dataclass(slots=True)
class BrowserRequest:
    action: str
    url: str | None
    headed: bool
    capture_screenshot: bool
    show_state_only: bool
    target_text: str | None = None
    input_text: str | None = None


@dataclass(slots=True)
class BrowserToolResult:
    executor: str
    command: list[str]
    exit_code: int | None
    stdout_text: str
    stderr_text: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def extract_url(text: str) -> str | None:
    url_match = re.search(r"https?://\S+", text)
    if url_match:
        return url_match.group(0).rstrip(".,)")

    domain_match = re.search(r"\b(?:www\.)?[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:/\S*)?", text)
    if domain_match:
        return f"https://{domain_match.group(0).rstrip('.,)')}"
    return None


def parse_browser_request(
    text: str,
    *,
    default_url: str,
    headless_by_default: bool,
) -> BrowserRequest:
    lowered = text.strip().lower()
    show_state_phrases = (
        "show me what you're doing",
        "show me what you are doing",
        "show current activity",
        "what are you doing",
        "show current browser state",
    )
    headed_phrases = (
        "show me the page",
        "deactivate headless",
        "disable headless",
        "visible browser",
        "headed browser",
        "show the browser",
    )
    screenshot_phrases = (
        "take a screenshot",
        "capture a screenshot",
        "screenshot the page",
        "capture the page",
        "show me the page",
        "show current activity",
    )
    summarize_phrases = (
        "summarize the page",
        "read the page",
        "what is on the page",
        "explain this page",
        "summarize this page",
    )
    link_phrases = (
        "show links",
        "list links",
        "what links are on the page",
        "extract links",
    )
    search_match = re.search(
        r"(?:search(?: the web| web)? for|look up|google)\s+(.+)",
        text,
        flags=re.IGNORECASE,
    )
    click_match = re.search(
        (
            r"\bclick\b(?:\s+the)?(?:\s+(?:link|button))?\s+[\"'“”]?(.+?)[\"'“”]?"
            r"(?:\s+on the page|\s+in the browser)?$"
        ),
        text.strip(),
        flags=re.IGNORECASE,
    )
    type_match = re.search(
        (
            r"\b(?:type|enter|fill)\b\s+[\"'“”](.+?)[\"'“”]\s+"
            r"(?:into|in)\s+[\"'“”](.+?)[\"'“”](?:\s+on the page|\s+in the browser)?$"
        ),
        text.strip(),
        flags=re.IGNORECASE,
    )

    show_state_only = any(phrase in lowered for phrase in show_state_phrases)
    headed = any(phrase in lowered for phrase in headed_phrases)
    url = extract_url(text)
    action = "open"
    target_text: str | None = None
    input_text: str | None = None

    if search_match:
        query = search_match.group(1).strip().rstrip(".")
        if query:
            url = (
                "https://www.google.com/search?q="
                + urllib.parse.quote_plus(query)
            )
    elif type_match:
        action = "type"
        input_text = type_match.group(1).strip()
        target_text = type_match.group(2).strip().rstrip(".")
    elif click_match:
        action = "click"
        target_text = click_match.group(1).strip().rstrip(".")
    elif any(phrase in lowered for phrase in summarize_phrases):
        action = "summarize"
    elif any(phrase in lowered for phrase in link_phrases):
        action = "links"

    if show_state_only and url is None and "browser" not in lowered and "page" not in lowered:
        return BrowserRequest(
            action="state",
            url=None,
            headed=False,
            capture_screenshot=False,
            show_state_only=True,
            target_text=None,
            input_text=None,
        )

    capture_screenshot = any(phrase in lowered for phrase in screenshot_phrases)
    if not headed and headless_by_default:
        capture_screenshot = True

    if action == "open" and url is None:
        url = default_url

    return BrowserRequest(
        action=action,
        url=url,
        headed=headed,
        capture_screenshot=capture_screenshot,
        show_state_only=False,
        target_text=target_text,
        input_text=input_text,
    )


class _HtmlSummaryParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_title = False
        self.in_script = False
        self.in_style = False
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.links: list[dict[str, str]] = []
        self._current_href: str | None = None
        self._current_link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self.in_title = True
        elif tag == "script":
            self.in_script = True
        elif tag == "style":
            self.in_style = True
        elif tag == "a":
            attr_map = dict(attrs)
            self._current_href = attr_map.get("href")
            self._current_link_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        elif tag == "script":
            self.in_script = False
        elif tag == "style":
            self.in_style = False
        elif tag == "a":
            href = (self._current_href or "").strip()
            text = " ".join(" ".join(self._current_link_text).split()).strip()
            if href:
                self.links.append({"href": href, "text": text})
            self._current_href = None
            self._current_link_text = []

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)
        if self.in_script or self.in_style:
            return
        compact = " ".join(data.split()).strip()
        if compact:
            self.text_parts.append(compact)
            if self._current_href is not None:
                self._current_link_text.append(compact)

    @property
    def title(self) -> str:
        return " ".join(" ".join(self.title_parts).split()).strip()

    @property
    def body_text(self) -> str:
        return " ".join(self.text_parts).strip()


class BrowserController:
    def __init__(self, config: DudeConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        self.browser_config: BrowserConfig = config.browser
        self.artifact_dir = (
            self.browser_config.artifact_dir
            if self.browser_config.artifact_dir is not None
            else config.runtime.state_dir / "browser"
        )
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.artifact_dir / "last-browser-state.json"

    def execute_request(self, request_text: str, working_dir: Path) -> BrowserToolResult:
        request = parse_browser_request(
            request_text,
            default_url=self.browser_config.default_url,
            headless_by_default=self.browser_config.headless_by_default,
        )
        if request.show_state_only:
            return self.show_state()
        if request.action == "summarize":
            return self._summarize_page(request, working_dir)
        if request.action == "links":
            return self._extract_links(request, working_dir)
        if request.action == "click":
            return self._click_page_target(request)
        if request.action == "type":
            return self._type_into_page_target(request)
        if request.url is None:
            return BrowserToolResult(
                executor="browser",
                command=[],
                exit_code=1,
                stdout_text="",
                stderr_text="Could not determine a URL or browser target from the request.",
            )
        if request.headed:
            return self._launch_visible_browser(request.url, working_dir)
        return self._capture_page(request.url, working_dir)

    def show_state(self) -> BrowserToolResult:
        state = self.get_state()
        if state is None:
            return BrowserToolResult(
                executor="browser",
                command=[],
                exit_code=0,
                stdout_text="No browser activity has been recorded yet.",
                stderr_text="",
            )

        url = str(state.get("url", "unknown"))
        mode = str(state.get("mode", "unknown"))
        screenshot_path = state.get("screenshot_path")
        excerpt = str(state.get("page_excerpt", "")).strip()
        title = str(state.get("title", "")).strip()
        updated_at = str(state.get("updated_at", "unknown"))
        detail = f"Last browser activity used {mode} mode at {updated_at} for {url}."
        if title:
            detail += f" Title: {title}."
        if excerpt:
            detail += f" Excerpt: {excerpt[:220]}."
        if screenshot_path:
            detail += f" Screenshot: {screenshot_path}."
        return BrowserToolResult(
            executor="browser",
            command=[],
            exit_code=0,
            stdout_text=detail,
            stderr_text="",
        )

    def get_state(self) -> dict[str, object] | None:
        return self._load_state()

    def _resolve_url_for_request(self, request: BrowserRequest) -> str | None:
        if request.url is not None:
            return request.url
        state = self.get_state()
        if state is None:
            return None
        url = str(state.get("url", "")).strip()
        return url or None

    def _capture_page(self, url: str, working_dir: Path) -> BrowserToolResult:
        if self.browser_config.preferred_engine == "playwright":
            try:
                return self._capture_with_playwright(url)
            except Exception as exc:
                log_event(
                    self.logger,
                    "browser_playwright_fallback",
                    error=str(exc),
                    url=url,
                )

        return self._capture_with_chrome_cli(url, working_dir)

    def _click_page_target(self, request: BrowserRequest) -> BrowserToolResult:
        url = self._resolve_url_for_request(request)
        if url is None:
            return BrowserToolResult(
                executor="browser",
                command=[],
                exit_code=1,
                stdout_text="",
                stderr_text="No browser page is available to click yet.",
            )
        target_text = (request.target_text or "").strip()
        if not target_text:
            return BrowserToolResult(
                executor="browser",
                command=[],
                exit_code=1,
                stdout_text="",
                stderr_text="No click target was found in the browser request.",
            )
        try:
            return self._click_with_playwright(
                url,
                target_text=target_text,
                capture_screenshot=request.capture_screenshot,
            )
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Playwright is required for browser click automation. "
                "Install it with `uv sync --extra browser`."
            ) from exc

    def _type_into_page_target(self, request: BrowserRequest) -> BrowserToolResult:
        url = self._resolve_url_for_request(request)
        if url is None:
            return BrowserToolResult(
                executor="browser",
                command=[],
                exit_code=1,
                stdout_text="",
                stderr_text="No browser page is available to type into yet.",
            )
        field_target = (request.target_text or "").strip()
        input_text = request.input_text or ""
        if not field_target or not input_text:
            return BrowserToolResult(
                executor="browser",
                command=[],
                exit_code=1,
                stdout_text="",
                stderr_text="Browser typing requires both input text and a target field.",
            )
        try:
            return self._type_with_playwright(
                url,
                field_target=field_target,
                input_text=input_text,
                capture_screenshot=request.capture_screenshot,
            )
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Playwright is required for browser typing automation. "
                "Install it with `uv sync --extra browser`."
            ) from exc

    def _summarize_page(self, request: BrowserRequest, working_dir: Path) -> BrowserToolResult:
        url = self._resolve_url_for_request(request)
        if url is None:
            return BrowserToolResult(
                executor="browser",
                command=[],
                exit_code=1,
                stdout_text="",
                stderr_text="No browser page is available to summarize yet.",
            )
        inspection = self._inspect_page(
            url,
            working_dir,
            capture_screenshot=request.capture_screenshot,
        )
        excerpt = str(inspection["excerpt"]).strip()
        title = str(inspection["title"]).strip()
        message = f"Page summary for {url}."
        if title:
            message += f" Title: {title}."
        if excerpt:
            message += f" Excerpt: {excerpt}."
        screenshot_path = str(inspection.get("screenshot_path", "")).strip()
        if screenshot_path:
            message += f" Screenshot: {screenshot_path}."
        return BrowserToolResult(
            executor="browser",
            command=list(inspection["command"]),
            exit_code=0,
            stdout_text=message,
            stderr_text="",
        )

    def _extract_links(self, request: BrowserRequest, working_dir: Path) -> BrowserToolResult:
        url = self._resolve_url_for_request(request)
        if url is None:
            return BrowserToolResult(
                executor="browser",
                command=[],
                exit_code=1,
                stdout_text="",
                stderr_text="No browser page is available to inspect yet.",
            )
        inspection = self._inspect_page(
            url,
            working_dir,
            capture_screenshot=request.capture_screenshot,
        )
        links = list(inspection["links"])
        if not links:
            message = f"No links were extracted from {url}."
        else:
            link_lines = [
                f"{index + 1}. {link['text'] or link['href']} -> {link['href']}"
                for index, link in enumerate(links[:8])
            ]
            message = f"Top links on {url}:\n" + "\n".join(link_lines)
        screenshot_path = str(inspection.get("screenshot_path", "")).strip()
        if screenshot_path:
            message += f"\nScreenshot: {screenshot_path}."
        return BrowserToolResult(
            executor="browser",
            command=list(inspection["command"]),
            exit_code=0,
            stdout_text=message,
            stderr_text="",
        )

    def _capture_with_playwright(self, url: str) -> BrowserToolResult:
        sync_api = importlib.import_module("playwright.sync_api")
        chrome_path = self._find_chrome_path()
        screenshot_path = self._next_screenshot_path(url)
        command = ["playwright", "chromium"]
        with sync_api.sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                executable_path=str(chrome_path) if chrome_path is not None else None,
            )
            context = browser.new_context(
                viewport={
                    "width": self.browser_config.viewport_width,
                    "height": self.browser_config.viewport_height,
                }
            )
            page = context.new_page()
            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self.browser_config.navigation_timeout_ms,
            )
            page.wait_for_timeout(self.browser_config.settle_time_ms)
            page.screenshot(path=str(screenshot_path), full_page=True)
            title = page.title()
            current_url = page.url
            browser.close()

        self._save_state(
            {
                "updated_at": _utc_now(),
                "mode": "headless",
                "engine": "playwright",
                "url": current_url,
                "title": title,
                "screenshot_path": str(screenshot_path),
            }
        )
        message = (
            f"Opened {current_url} in a headless browser and saved a screenshot to "
            f"{screenshot_path}."
        )
        if title:
            message += f" Title: {title}."
        return BrowserToolResult(
            executor="browser",
            command=command,
            exit_code=0,
            stdout_text=message,
            stderr_text="",
        )

    def _capture_with_chrome_cli(self, url: str, working_dir: Path) -> BrowserToolResult:
        chrome_path = self._find_chrome_path()
        if chrome_path is None:
            raise RuntimeError("No Chrome/Chromium executable found for headless capture.")

        screenshot_path = self._next_screenshot_path(url)
        command = [
            str(chrome_path),
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            f"--window-size={self.browser_config.viewport_width},{self.browser_config.viewport_height}",
            f"--screenshot={screenshot_path}",
            url,
        ]
        completed = subprocess.run(
            command,
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=max(10, self.browser_config.navigation_timeout_ms // 1000 + 10),
        )
        title = ""
        if completed.returncode == 0:
            self._save_state(
                {
                    "updated_at": _utc_now(),
                    "mode": "headless",
                    "engine": "chrome_cli",
                    "url": url,
                    "title": title,
                    "screenshot_path": str(screenshot_path),
                }
            )
        stdout_text = (
            f"Opened {url} in a headless browser and saved a screenshot to {screenshot_path}."
            if completed.returncode == 0
            else ""
        )
        return BrowserToolResult(
            executor="browser",
            command=command,
            exit_code=completed.returncode,
            stdout_text=stdout_text,
            stderr_text=completed.stderr.strip(),
        )

    def _launch_visible_browser(self, url: str, working_dir: Path) -> BrowserToolResult:
        if chrome_path := self._find_chrome_path():
            command = [str(chrome_path), "--new-window", url]
        elif firefox_path := shutil.which("firefox"):
            command = [firefox_path, "--new-window", url]
        else:
            command = ["xdg-open", url]

        process = subprocess.Popen(
            command,
            cwd=working_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        time.sleep(0.2)
        self._save_state(
            {
                "updated_at": _utc_now(),
                "mode": "headed",
                "engine": Path(command[0]).name,
                "url": url,
                "title": "",
                "screenshot_path": None,
                "pid": process.pid,
            }
        )
        return BrowserToolResult(
            executor="browser",
            command=command,
            exit_code=None,
            stdout_text=f"Opened a visible browser window to {url}.",
            stderr_text="",
        )

    def _click_with_playwright(
        self,
        url: str,
        *,
        target_text: str,
        capture_screenshot: bool,
    ) -> BrowserToolResult:
        sync_api = importlib.import_module("playwright.sync_api")
        chrome_path = self._find_chrome_path()
        screenshot_path = self._next_screenshot_path(url) if capture_screenshot else None
        command = ["playwright", "click", target_text]
        with sync_api.sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                executable_path=str(chrome_path) if chrome_path is not None else None,
            )
            context = browser.new_context(
                viewport={
                    "width": self.browser_config.viewport_width,
                    "height": self.browser_config.viewport_height,
                }
            )
            page = context.new_page()
            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self.browser_config.navigation_timeout_ms,
            )
            page.wait_for_timeout(self.browser_config.settle_time_ms)

            locator = None
            name_pattern = re.compile(re.escape(target_text), re.IGNORECASE)
            candidate_locators = [
                page.get_by_role("link", name=name_pattern).first,
                page.get_by_role("button", name=name_pattern).first,
                page.get_by_text(target_text, exact=False).first,
            ]
            last_error = "No clickable target matched."
            for candidate in candidate_locators:
                try:
                    candidate.wait_for(state="visible", timeout=1500)
                    locator = candidate
                    break
                except Exception as exc:  # noqa: BLE001
                    last_error = str(exc)
            if locator is None:
                browser.close()
                return BrowserToolResult(
                    executor="browser",
                    command=command,
                    exit_code=1,
                    stdout_text="",
                    stderr_text=(
                        f"Could not find a clickable target for '{target_text}'. "
                        f"{last_error}"
                    ),
                )

            locator.click(timeout=self.browser_config.navigation_timeout_ms)
            page.wait_for_timeout(self.browser_config.settle_time_ms)
            if screenshot_path is not None:
                page.screenshot(path=str(screenshot_path), full_page=True)
            title = page.title()
            current_url = page.url
            excerpt = " ".join(page.locator("body").inner_text().split())[:800].strip()
            browser.close()

        self._save_state(
            {
                "updated_at": _utc_now(),
                "mode": "headless",
                "engine": "playwright",
                "url": current_url,
                "title": title,
                "screenshot_path": str(screenshot_path) if screenshot_path is not None else None,
                "page_excerpt": excerpt,
                "last_action": "click",
                "last_target_text": target_text,
            }
        )
        message = f"Clicked '{target_text}' on {url}."
        if current_url != url:
            message += f" Current page: {current_url}."
        if title:
            message += f" Title: {title}."
        if screenshot_path is not None:
            message += f" Screenshot: {screenshot_path}."
        return BrowserToolResult(
            executor="browser",
            command=command,
            exit_code=0,
            stdout_text=message,
            stderr_text="",
        )

    def _type_with_playwright(
        self,
        url: str,
        *,
        field_target: str,
        input_text: str,
        capture_screenshot: bool,
    ) -> BrowserToolResult:
        sync_api = importlib.import_module("playwright.sync_api")
        chrome_path = self._find_chrome_path()
        screenshot_path = self._next_screenshot_path(url) if capture_screenshot else None
        command = ["playwright", "type", field_target]
        with sync_api.sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                executable_path=str(chrome_path) if chrome_path is not None else None,
            )
            context = browser.new_context(
                viewport={
                    "width": self.browser_config.viewport_width,
                    "height": self.browser_config.viewport_height,
                }
            )
            page = context.new_page()
            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self.browser_config.navigation_timeout_ms,
            )
            page.wait_for_timeout(self.browser_config.settle_time_ms)

            locator = None
            name_pattern = re.compile(re.escape(field_target), re.IGNORECASE)
            candidate_locators = [
                page.get_by_label(name_pattern).first,
                page.get_by_placeholder(name_pattern).first,
                page.get_by_role("textbox", name=name_pattern).first,
                page.locator(
                    f"input[name='{field_target}'], textarea[name='{field_target}']"
                ).first,
            ]
            last_error = "No editable field matched."
            for candidate in candidate_locators:
                try:
                    candidate.wait_for(state="visible", timeout=1500)
                    locator = candidate
                    break
                except Exception as exc:  # noqa: BLE001
                    last_error = str(exc)
            if locator is None:
                browser.close()
                return BrowserToolResult(
                    executor="browser",
                    command=command,
                    exit_code=1,
                    stdout_text="",
                    stderr_text=(
                        f"Could not find an editable field for '{field_target}'. "
                        f"{last_error}"
                    ),
                )

            locator.fill(input_text, timeout=self.browser_config.navigation_timeout_ms)
            page.wait_for_timeout(self.browser_config.settle_time_ms)
            if screenshot_path is not None:
                page.screenshot(path=str(screenshot_path), full_page=True)
            title = page.title()
            current_url = page.url
            excerpt = " ".join(page.locator("body").inner_text().split())[:800].strip()
            browser.close()

        self._save_state(
            {
                "updated_at": _utc_now(),
                "mode": "headless",
                "engine": "playwright",
                "url": current_url,
                "title": title,
                "screenshot_path": str(screenshot_path) if screenshot_path is not None else None,
                "page_excerpt": excerpt,
                "last_action": "type",
                "last_target_text": field_target,
                "last_input_text": input_text,
            }
        )
        message = f"Entered text into '{field_target}' on {url}."
        if current_url != url:
            message += f" Current page: {current_url}."
        if title:
            message += f" Title: {title}."
        if screenshot_path is not None:
            message += f" Screenshot: {screenshot_path}."
        return BrowserToolResult(
            executor="browser",
            command=command,
            exit_code=0,
            stdout_text=message,
            stderr_text="",
        )

    def _inspect_page(
        self,
        url: str,
        working_dir: Path,
        *,
        capture_screenshot: bool,
    ) -> dict[str, object]:
        if self.browser_config.preferred_engine == "playwright":
            try:
                return self._inspect_with_playwright(url, capture_screenshot=capture_screenshot)
            except Exception as exc:
                log_event(
                    self.logger,
                    "browser_playwright_inspect_fallback",
                    error=str(exc),
                    url=url,
                )
        return self._inspect_with_http(url, working_dir, capture_screenshot=capture_screenshot)

    def _inspect_with_playwright(
        self,
        url: str,
        *,
        capture_screenshot: bool,
    ) -> dict[str, object]:
        sync_api = importlib.import_module("playwright.sync_api")
        chrome_path = self._find_chrome_path()
        screenshot_path = self._next_screenshot_path(url) if capture_screenshot else None
        command = ["playwright", "inspect", url]
        with sync_api.sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                executable_path=str(chrome_path) if chrome_path is not None else None,
            )
            context = browser.new_context(
                viewport={
                    "width": self.browser_config.viewport_width,
                    "height": self.browser_config.viewport_height,
                }
            )
            page = context.new_page()
            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self.browser_config.navigation_timeout_ms,
            )
            page.wait_for_timeout(self.browser_config.settle_time_ms)
            if screenshot_path is not None:
                page.screenshot(path=str(screenshot_path), full_page=True)
            title = page.title()
            current_url = page.url
            excerpt = " ".join(page.locator("body").inner_text().split())[:800].strip()
            links = page.evaluate(
                """
                () => Array.from(document.querySelectorAll('a'))
                  .slice(0, 16)
                  .map(link => ({
                    href: link.href || '',
                    text: (link.innerText || link.textContent || '').trim()
                  }))
                """
            )
            browser.close()

        self._save_state(
            {
                "updated_at": _utc_now(),
                "mode": "headless",
                "engine": "playwright",
                "url": current_url,
                "title": title,
                "screenshot_path": str(screenshot_path) if screenshot_path is not None else None,
                "page_excerpt": excerpt,
                "links": links,
            }
        )
        return {
            "command": command,
            "url": current_url,
            "title": title,
            "excerpt": excerpt,
            "links": links,
            "screenshot_path": str(screenshot_path) if screenshot_path is not None else "",
        }

    def _inspect_with_http(
        self,
        url: str,
        working_dir: Path,
        *,
        capture_screenshot: bool,
    ) -> dict[str, object]:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "DudeBrowser/0.1"},
        )
        timeout_seconds = max(10, self.browser_config.navigation_timeout_ms // 1000)
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            html = response.read().decode("utf-8", errors="replace")
            final_url = response.geturl()

        parser = _HtmlSummaryParser()
        parser.feed(html)
        excerpt = parser.body_text[:800].strip()
        links = parser.links[:16]
        screenshot_path = ""
        command = ["http_inspect", url]
        if capture_screenshot:
            capture_result = self._capture_with_chrome_cli(final_url, working_dir)
            if capture_result.exit_code == 0:
                state = self.get_state() or {}
                screenshot_path = str(state.get("screenshot_path", "")).strip()
                command = capture_result.command
        self._save_state(
            {
                "updated_at": _utc_now(),
                "mode": "headless",
                "engine": "http_inspect",
                "url": final_url,
                "title": parser.title,
                "screenshot_path": screenshot_path or None,
                "page_excerpt": excerpt,
                "links": links,
            }
        )
        return {
            "command": command,
            "url": final_url,
            "title": parser.title,
            "excerpt": excerpt,
            "links": links,
            "screenshot_path": screenshot_path,
        }

    def _find_chrome_path(self) -> Path | None:
        if self.browser_config.executable_path is not None:
            return self.browser_config.executable_path
        for candidate in ("google-chrome", "chromium-browser", "chromium"):
            resolved = shutil.which(candidate)
            if resolved:
                return Path(resolved)
        return None

    def _next_screenshot_path(self, url: str) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", url).strip("-").lower()[:60] or "page"
        return self.artifact_dir / f"{stamp}-{slug}.png"

    def _load_state(self) -> dict[str, object] | None:
        if not self.state_path.exists():
            return None
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def _save_state(self, payload: dict[str, object]) -> None:
        self.state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
