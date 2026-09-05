"""Wake-bot for the Streamlit Cloud app: opens nfledge.streamlit.app in headless
Chromium; if the app is in deep sleep (wake-button page), clicks it and verifies
spin-up. Silent when the app is already awake. Prints (→ telegram) only when it
had to wake the app or when something failed."""

import os
import sys

from playwright.sync_api import sync_playwright

URL = "https://nfledge.streamlit.app/"


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(URL, timeout=90000, wait_until="domcontentloaded")
            page.wait_for_timeout(6000)
            wake_btn = page.get_by_text("get this app back up", exact=False)
            asleep = page.get_by_text("gone to sleep", exact=False)
            if wake_btn.count() > 0 or asleep.count() > 0:
                if wake_btn.count() > 0:
                    wake_btn.first.click()
                page.wait_for_timeout(25000)
                ok = page.get_by_text("NFL Edge", exact=False).count() > 0
                print("😴➡️⏰ NFL Edge app was deep-asleep — clicked wake. "
                      f"Spin-up: {'OK ✅' if ok else '⚠️ check nfledge.streamlit.app'}")
            # else: awake — stay silent
        except Exception as e:
            print(f"⚠️ wake-bot error: {type(e).__name__}: {str(e)[:200]}")
        finally:
            browser.close()
    os._exit(0)


if __name__ == "__main__":
    main()
