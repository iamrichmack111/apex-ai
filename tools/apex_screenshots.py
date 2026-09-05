from pathlib import Path
from playwright.sync_api import sync_playwright
import os
import time

BASE = os.environ.get("APEX_URL", "http://127.0.0.1:8765")
OUT = Path("docs/screenshots")
OUT.mkdir(parents=True, exist_ok=True)

def visible(page, selector):
    try:
        loc = page.locator(selector)
        return loc.count() > 0 and loc.first.is_visible()
    except Exception:
        return False

def click_first(page, selectors):
    for selector in selectors:
        try:
            loc = page.locator(selector)
            if loc.count() and loc.first.is_visible():
                loc.first.click(timeout=4000)
                page.wait_for_timeout(700)
                return True
        except Exception:
            pass
    return False

def fill_first(page, selectors, value):
    for selector in selectors:
        try:
            loc = page.locator(selector)
            if loc.count() and loc.first.is_visible():
                loc.first.fill(value)
                return True
        except Exception:
            pass
    return False

def shot(page, filename):
    path = OUT / filename
    page.screenshot(
        path=str(path),
        full_page=True,
        animations="disabled"
    )
    print(f"✓ {path}")

chrome_candidates = [
    os.environ.get("PLAYWRIGHT_CHROME"),
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/snap/bin/chromium",
]

chrome = next(
    (p for p in chrome_candidates if p and Path(p).exists()),
    None
)

if not chrome:
    raise SystemExit(
        "Chrome/Chromium is not installed. "
        "No large browser download was attempted."
    )

with sync_playwright() as p:
    browser = p.chromium.launch(
        executable_path=chrome,
        headless=True,
        args=[
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--disable-background-networking",
        ],
    )

    context = browser.new_context(
        viewport={"width": 1600, "height": 1000},
        device_scale_factor=1,
        reduced_motion="reduce",
    )

    page = context.new_page()

    print(f"Opening {BASE}")
    page.goto(BASE, wait_until="domcontentloaded", timeout=120000)
    page.wait_for_timeout(1800)

    # LOGIN PAGE
    shot(page, "01-login.png")

    # Create a disposable local screenshot account when necessary.
    if visible(page, "#authScreen"):
        username = (
            os.environ.get("APEX_SCREENSHOT_USER")
            or f"apex_docs_{int(time.time())}"
        )
        password = (
            os.environ.get("APEX_SCREENSHOT_PASS")
            or "ApexDocs2026!"
        )

        existing = bool(os.environ.get("APEX_SCREENSHOT_USER"))

        if existing:
            click_first(page, [
                "#loginTab",
                "button:has-text('Login')",
                "button:has-text('Sign in')",
            ])
        else:
            click_first(page, [
                "#signupTab",
                "button:has-text('Sign up')",
                "button:has-text('Create account')",
                "button:has-text('Register')",
            ])

        fill_first(page, [
            "#authUsername",
            "input[name='username']",
            "input[autocomplete='username']",
            "input[type='text']",
        ], username)

        fill_first(page, [
            "#authPassword",
            "input[name='password']",
            "input[autocomplete='current-password']",
            "input[type='password']",
        ], password)

        click_first(page, [
            "#authSubmit",
            "button[type='submit']",
            "button:has-text('Create account')",
            "button:has-text('Sign up')",
            "button:has-text('Login')",
        ])

        page.wait_for_timeout(2200)

    # MAIN WORKSPACE
    shot(page, "02-workspace.png")

    # IMAGE STUDIO — screenshot only; DO NOT submit generation.
    if click_first(page, [
        "#imageModeBtn",
        "[data-mode='image']",
        "button:has-text('Image')",
    ]):
        page.wait_for_timeout(500)
        shot(page, "03-image-studio.png")

    # Return to Chat
    click_first(page, [
        "#chatModeBtn",
        "[data-mode='chat']",
        "button:has-text('Chat')",
    ])

    # SETTINGS
    opened_settings = click_first(page, [
        "#settingsBtn",
        "[data-action='settings']",
        "button[aria-label*='Settings']",
        "button:has-text('Settings')",
    ])

    if opened_settings:
        shot(page, "04-settings.png")

        # INTELLIGENCE
        if click_first(page, [
            '[data-settings-tab="intelligence"]',
            '[data-tab="intelligence"]',
            "button:has-text('Intelligence')",
        ]):
            shot(page, "05-intelligence.png")

        # APPEARANCE / THEMES
        if click_first(page, [
            '[data-settings-tab="appearance"]',
            '[data-tab="appearance"]',
            "button:has-text('Appearance')",
            "button:has-text('Themes')",
            "button:has-text('Theme')",
        ]):
            shot(page, "06-themes.png")

        # KNOWLEDGE / RAG
        if click_first(page, [
            '[data-settings-tab="knowledge"]',
            '[data-tab="knowledge"]',
            "button:has-text('Knowledge')",
            "button:has-text('RAG')",
        ]):
            shot(page, "07-knowledge.png")

        # Close settings.
        click_first(page, [
            '[data-close="settingsModal"]',
            "#settingsClose",
            "button[aria-label='Close']",
            "button:has-text('Close')",
        ])

    # MOBILE WORKSPACE
    page.set_viewport_size({
        "width": 390,
        "height": 844
    })
    page.wait_for_timeout(800)
    shot(page, "08-mobile.png")

    browser.close()

print()
print("Playwright screenshots complete.")
