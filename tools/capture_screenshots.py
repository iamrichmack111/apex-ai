import os
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = os.environ.get("APEX_BASE_URL", "http://127.0.0.1:8765")
OUT = Path("docs/screenshots")
OUT.mkdir(parents=True, exist_ok=True)

chrome_candidates = [
    os.environ.get("PLAYWRIGHT_CHROME"),
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/snap/bin/chromium",
]
chrome = next((p for p in chrome_candidates if p and Path(p).exists()), None)

with sync_playwright() as p:
    launch_args = {"headless": True}
    if chrome:
        launch_args["executable_path"] = chrome

    browser = p.chromium.launch(**launch_args)
    context = browser.new_context(
        viewport={"width": 1600, "height": 1000},
        device_scale_factor=1,
    )
    page = context.new_page()

    page.goto(BASE, wait_until="networkidle", timeout=120000)
    page.wait_for_timeout(1800)

    page.screenshot(
        path=str(OUT / "login.png"),
        full_page=True,
    )

    app_visible = False

    try:
        if page.locator("#authScreen").is_visible():
            user = os.environ.get(
                "APEX_SCREENSHOT_USER",
                f"apex_demo_{int(time.time())}"
            )
            password = os.environ.get(
                "APEX_SCREENSHOT_PASS",
                "ApexScreenshotDemo2026!"
            )

            if os.environ.get("APEX_SCREENSHOT_USER"):
                page.locator("#loginTab").click()
            else:
                page.locator("#signupTab").click()

            page.locator("#authUsername").fill(user)
            page.locator("#authPassword").fill(password)
            page.locator("#authSubmit").click()

            try:
                page.wait_for_selector(
                    "#app:not(.hidden)",
                    timeout=30000
                )
            except Exception:
                if not os.environ.get("APEX_SCREENSHOT_USER"):
                    page.locator("#loginTab").click()
                    page.locator("#authUsername").fill(user)
                    page.locator("#authPassword").fill(password)
                    page.locator("#authSubmit").click()
                    page.wait_for_selector(
                        "#app:not(.hidden)",
                        timeout=30000
                    )

        app_visible = page.locator("#app").is_visible()
    except Exception as exc:
        print("Authentication/setup warning:", exc)

    if app_visible:
        page.wait_for_timeout(2200)

        page.screenshot(
            path=str(OUT / "dashboard.png"),
            full_page=True,
        )

        if page.locator("#settingsBtn").count():
            page.locator("#settingsBtn").click()
            page.wait_for_timeout(900)

            if page.locator('[data-settings-tab="appearance"]').count():
                page.locator('[data-settings-tab="appearance"]').click()
                page.wait_for_timeout(700)
                page.screenshot(
                    path=str(OUT / "themes.png"),
                    full_page=True,
                )

            if page.locator('[data-settings-tab="intelligence"]').count():
                page.locator('[data-settings-tab="intelligence"]').click()
                page.wait_for_timeout(700)
                page.screenshot(
                    path=str(OUT / "intelligence.png"),
                    full_page=True,
                )

            close = page.locator('[data-close="settingsModal"]')
            if close.count():
                close.click()
                page.wait_for_timeout(500)

        if page.locator("#imageModeBtn").count():
            page.locator("#imageModeBtn").click()
            page.wait_for_timeout(900)
            page.screenshot(
                path=str(OUT / "image-mode.png"),
                full_page=True,
            )

        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(900)
        page.screenshot(
            path=str(OUT / "mobile.png"),
            full_page=True,
        )

    browser.close()

print("Playwright screenshots saved to docs/screenshots/")
