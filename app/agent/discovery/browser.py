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

    def close(self):
        if self.browser:
            self.browser.close()

        if self.playwright:
            self.playwright.stop()