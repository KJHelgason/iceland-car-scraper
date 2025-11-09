# scrapers/dealerships/bilaland_seed_links.py
import asyncio
import re
from typing import List, Set, Tuple

from playwright.async_api import async_playwright, Page

BASE_URL = "https://bilaland.is/"
SELECT_XPATH = '/html/body/form/nav/div/div[4]/div/div/div/div/div/div[1]/div/div[1]/select'

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
        'xpath=/html/body/form/nav/div/div[4]/div/div/div/div/div/div[6]/div/input',  # specific xpath from scraper
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


async def _get_options(page: Page) -> List[Tuple[str, str]]:
    """Return list of (value, text) from the select, skipping placeholders."""
    await page.wait_for_selector(f'xpath={SELECT_XPATH}')
    option_els = await page.query_selector_all(f'xpath={SELECT_XPATH}/option')

    options: List[Tuple[str, str]] = []
    for idx, opt in enumerate(option_els):
        value = (await opt.get_attribute("value")) or ""
        text = ((await opt.inner_text()) or "").strip()
        # Skip the first option and any "all makes" placeholders
        if idx == 0:
            continue
        if not value.strip():
            continue
        if value in {"-1", "0"}:
            continue
        if re.search(r"\ball(ir|a|ir)? framleiðendur\b", text.lower()):  # "Allir framleiðendur"
            continue
        options.append((value, text))
    return options


async def discover_bilaland_links() -> List[str]:
    """
    Visit bilaland.is, iterate the make dropdown options (skipping 'All makes'),
    click 'Leita', and collect resulting SearchResults URLs. Returns a deduped list.
    """
    links: Set[str] = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(BASE_URL)
        await page.wait_for_load_state("domcontentloaded")

        options = await _get_options(page)
        print(f"Found {len(options)} dropdown options to test (excluding 'All makes').")

        for idx, (value, text) in enumerate(options, start=1):
            try:
                print(f"[{idx}/{len(options)}] Selecting option value='{value}' ({text})")

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
                    # Best effort—still check URL
                    pass

                current_url = page.url
                # Bilaland may use SearchResults.aspx or similar patterns
                # Skip individual CarDetails pages - we only want list/search pages
                if "CarDetails.aspx" in current_url:
                    print(f"  [SKIP] Detail page, not a list: {current_url}")
                elif "SearchResults.aspx" in current_url or "searchresults.aspx" in current_url.lower():
                    links.add(current_url)
                    print(f"  [+] Added URL: {current_url}")
                else:
                    # Sometimes results appear on same page with query params
                    if current_url != BASE_URL and ("?" in current_url or "schid=" in current_url):
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


if __name__ == "__main__":
    urls = asyncio.run(discover_bilaland_links())
    print("\nDiscovered listing URLs:")
    for u in urls:
        print(" -", u)
    print(f"Total: {len(urls)}")
