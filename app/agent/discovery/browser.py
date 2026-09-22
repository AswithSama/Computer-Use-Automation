import os
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID
from playwright.sync_api import sync_playwright


class BrowserSession:
    def __init__(self, headless: bool = False):
        self.headless = headless
        self.playwright = None
        self.browser = None
        self.page = None

    def start(self):
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=self.headless)
        self.page = self.browser.new_page()

    def open(self, url: str):
        if self.page is None:
            raise RuntimeError("Browser session has not been started.")

        self.page.goto(url, wait_until="domcontentloaded")

    def observe(self) -> str:
        if self.page is None:
            raise RuntimeError("Browser session has not been started.")

        return self.page.aria_snapshot(mode="ai")

    def capture_handoff_screenshot(
        self,
        *,
        evidence_dir: str | Path,
        intervention_id: UUID,
    ) -> str:
        """
        Capture the live application state before human handoff.

        This project uses synthetic demo data. Production deployments
        would require protected screenshot storage and access controls.
        """
        if self.page is None or self.page.is_closed():
            raise RuntimeError(
                "Cannot capture screenshot: browser page is unavailable."
            )

        screenshot_dir = Path(evidence_dir) / "screenshots"
        screenshot_dir.mkdir(
            parents=True,
            exist_ok=True,
            mode=0o700,
        )

        screenshot_path = (
            screenshot_dir / f"{intervention_id}.png"
        )

        image_bytes = self.page.screenshot(
            type="png",
            full_page=False,
            animations="disabled",
        )

        if not image_bytes:
            raise RuntimeError("Browser returned an empty screenshot.")

        descriptor = os.open(
            screenshot_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )

        with os.fdopen(descriptor, "wb") as image_file:
            image_file.write(image_bytes)

        return str(screenshot_path)

    def close(self):
        if self.browser:
            self.browser.close()

        if self.playwright:
            self.playwright.stop()