import asyncio
from playwright.async_api import async_playwright

async def save_fb_cookies():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto("https://www.facebook.com/")
        print("Log in manually, then press ENTER here when done...")
        input()
        await context.storage_state(path="fb_state.json")
        await browser.close()
        print("Cookies saved to fb_state.json")

asyncio.run(save_fb_cookies())
