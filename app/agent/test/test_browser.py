from app.agent.discovery.browser import BrowserSession


def main():
    browser = BrowserSession(headless=False)

    try:
        browser.start()
        browser.open("http://127.0.0.1:8000")

        observation = browser.observe()

        print("\n--- CURRENT URL ---")
        print(browser.page.url)

        print("\n--- PAGE TITLE ---")
        print(browser.page.title())

        print("\n--- AI MODE ARIA SNAPSHOT ---")
        print(observation)

    finally:
        browser.close()


if __name__ == "__main__":
    main()