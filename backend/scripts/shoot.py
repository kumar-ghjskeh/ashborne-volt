"""Capture verification screenshots of the running app (Vite on :5173) across
light/dark themes and desktop/mobile layouts. Output -> ../../screenshots/phase4/."""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:5173"
OUT = Path(__file__).parents[2] / "screenshots" / "phase4"
OUT.mkdir(parents=True, exist_ok=True)


def set_theme(page, theme):
    page.add_init_script(f"window.localStorage.setItem('ashborne-theme','{theme}');")


def wait_cards(page, timeout=20000):
    page.wait_for_selector(".job-card", timeout=timeout)
    page.wait_for_timeout(700)


def shoot():
    with sync_playwright() as p:
        browser = p.chromium.launch()

        # ── Desktop 1440x900 ──
        dctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2)

        for theme in ("light", "dark"):
            page = dctx.new_page()
            set_theme(page, theme)
            page.goto(BASE, wait_until="networkidle")
            wait_cards(page)
            page.screenshot(path=str(OUT / f"01_desktop_{theme}_all.png"))
            # open a job → details panel
            page.locator(".job-card").first.click()
            page.wait_for_timeout(900)
            page.screenshot(path=str(OUT / f"02_desktop_{theme}_detail.png"))
            page.close()

        # Companies / Data Health (parser confidence) — light
        page = dctx.new_page()
        set_theme(page, "light")
        page.goto(BASE, wait_until="networkidle")
        wait_cards(page)
        page.get_by_role("button", name="Companies").click()
        page.wait_for_timeout(1500)
        page.screenshot(path=str(OUT / "03_desktop_companies.png"), full_page=True)
        page.close()
        dctx.close()

        # ── Mobile 390x844 (iPhone-ish) ──
        mctx = browser.new_context(
            viewport={"width": 390, "height": 844}, device_scale_factor=3, is_mobile=True
        )
        for theme in ("light", "dark"):
            page = mctx.new_page()
            set_theme(page, theme)
            page.goto(BASE, wait_until="networkidle")
            wait_cards(page)
            page.screenshot(path=str(OUT / f"04_mobile_{theme}_list.png"))
            if theme == "light":
                # open filters drawer
                page.get_by_role("button", name="Filters").click()
                page.wait_for_selector(".mobile-drawer", timeout=5000)
                page.wait_for_timeout(700)
                page.screenshot(path=str(OUT / "05_mobile_filters_drawer.png"))
                # close drawer via its "Done" button, then open a job sheet
                page.locator('.mobile-drawer button[title="Done"]').click()
                page.wait_for_timeout(500)
                # Direct DOM click — avoids the sticky header intercepting the
                # pointer when Playwright scrolls a top card into view.
                page.locator(".job-card").nth(2).evaluate("el => el.click()")
                page.wait_for_selector(".mobile-sheet", timeout=5000)
                page.wait_for_timeout(900)
                page.screenshot(path=str(OUT / "06_mobile_job_sheet.png"))
            page.close()
        mctx.close()
        browser.close()

    pngs = sorted(OUT.glob("*.png"))
    print(f"Saved {len(pngs)} screenshots to {OUT}")
    for f in pngs:
        print(f"  {f.name}  ({f.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    try:
        shoot()
    except Exception as e:
        print(f"SHOOT ERROR: {e}", file=sys.stderr)
        raise
