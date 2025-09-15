# scrapers/dealerships/bilasolur_seed_specific.py
import asyncio
import re
from typing import List, Set, Tuple

from playwright.async_api import async_playwright, Page
from utils.normalizer import normalize_make
from scrapers.dealerships.bilasolur_scraper import scrape_bilasolur

BASE_URL = "https://bilasolur.is/"
SELECT_XPATH = '/html/body/form/div[5]/div/div[1]/div[1]/select'

# ---- target makes (will be normalized) ----
RAW_TARGET_MAKES = {
    "aiways", "byd", "capron", "chrysler", "honqi", "hummer",
    "isuzu", "maxus", "mg", "polestar", "smart", "ssangyong", "weinsberg"
}
# fix common typo/alias (honqi -> hongqi)
ALIASES = {"honqi": "hongqi"}

TARGET_MAKES = {normalize_make(ALIASES.get(m, m)) for m in RAW_TARGET_MAKES}
TARGET_MAKES.discard(None)


async def _try_click_search(page: Page) -> bool:
    """Click the 'Leita' button using a few robust selectors."""
    # Preferred: role-based lookup
    try:
        btn = page.get_by_role("button", name=re.compile(r"^Leita$", re.I))
        if await btn.count():
            await btn.first.click()
            return True
    except Exception:
        pass

    # Common fallbacks
    candidates = [
        'input[type="submit"][value*="Leita"]',
        'button:has-text("Leita")',
        'input[type="button"][value*="Leita"]',
        'input[value*="Leita"]',
    ]
    for sel in candidates:
        try:
            el = await page.query_selector(sel)
            if el:
                await el.click()
                return True
        except Exception:
            continue

    # Last resort: submit the enclosing form
    try:
        form = await page.query_selector("form")
        if form:
            await form.evaluate("(f) => f.submit()")
            return True
    except Exception:
        pass

    return False


async def _get_all_options(page: Page) -> List[Tuple[str, str]]:
    """Return list of (value, text) from the select, skipping placeholders."""
    await page.wait_for_selector(f'xpath={SELECT_XPATH}')
    option_els = await page.query_selector_all(f'xpath={SELECT_XPATH}/option')

    options: List[Tuple[str, str]] = []
    for idx, opt in enumerate(option_els):
        value = (await opt.get_attribute("value")) or ""
        text = ((await opt.inner_text()) or "").strip()

        # Skip first option & obvious 'all makes' placeholders
        if idx == 0:
            continue
        if not value.strip():
            continue
        if value in {"-1", "0"}:
            continue
        if re.search(r"\ball(ir|a|ir)? framleiðendur\b", text.lower()):
            continue

        options.append((value, text))
    return options


async def discover_links_for_targets() -> List[str]:
    """
    Visit bilasolur.is, iterate the make dropdown, but ONLY for our target makes.
    Click 'Leita' and collect SearchResults URLs. Returns a deduped list.
    """
    links: Set[str] = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(BASE_URL)
        await page.wait_for_load_state("domcontentloaded")

        options = await _get_all_options(page)
        print(f"Found {len(options)} dropdown options (excl. 'All makes').")
        print(f"Target makes (normalized): {sorted(TARGET_MAKES)}")

        # Filter options to our target makes only (normalize the option text)
        filtered = []
        for value, text in options:
            nm = normalize_make(text)
            if nm in TARGET_MAKES:
                filtered.append((value, text, nm))

        print(f"Will process {len(filtered)} target options.")

        for idx, (value, text, nm) in enumerate(filtered, start=1):
            try:
                print(f"[{idx}/{len(filtered)}] Selecting '{text}' (normalized '{nm}') with value='{value}'")

                # Re-acquire the select each loop (avoid stale element)
                await page.wait_for_selector(f'xpath={SELECT_XPATH}')
                await page.locator(f'xpath={SELECT_XPATH}').select_option(value=value)

                clicked = await _try_click_search(page)
                if not clicked:
                    print("  [WARN] Could not find/click a 'Leita' button. Skipping this option.")
                    # Go back to base for next iteration
                    await page.goto(BASE_URL)
                    await page.wait_for_load_state("domcontentloaded")
                    continue

                # Wait for navigation / network to settle
                try:
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass

                current_url = page.url
                if "SearchResults.aspx" in current_url or "searchresults.aspx" in current_url.lower():
                    links.add(current_url)
                    print(f"  [+] Added URL: {current_url}")
                else:
                    print(f"  [INFO] Not a SearchResults URL (current: {current_url})")

                # Return to the start page for the next option
                await page.goto(BASE_URL)
                await page.wait_for_load_state("domcontentloaded")

            except Exception as e:
                print(f"  [ERROR] Failed on option value='{value}' ({text}): {e}")
                # Try to recover: go back to base
                try:
                    await page.goto(BASE_URL)
                    await page.wait_for_load_state("domcontentloaded")
                except Exception:
                    pass

        await browser.close()

    return sorted(links)


async def main():
    print("Discovering Bilasólur URLs for target makes...")
    urls = await discover_links_for_targets()
    print(f"Discovered {len(urls)} URLs. Starting scrape...\n")

    if not urls:
        print("No URLs found for the requested makes.")
        return

    # Try to call the scraper with start_urls (if your bilasolur_scraper supports it).
    # If not, we fall back to iterating one by one.
    try:
        for i, u in enumerate(urls, 1):
            print(f"Scraping ({i}/{len(urls)}): {u}")
            await scrape_bilasolur(start_urls=[u], max_pages=500)
    except TypeError:
        print("[INFO] Your scrape_bilasolur doesn't accept start_urls; scraping each URL separately...")
        for i, u in enumerate(urls, 1):
            print(f"  -> Scraping ({i}/{len(urls)}): {u}")
            await scrape_bilasolur(start_urls=[u], max_pages=500)


if __name__ == "__main__":
    asyncio.run(main())
