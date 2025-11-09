"""
Discover Brimborg make-specific search URLs from the dropdown menu.
This script navigates to the Brimborg used cars page, opens the make dropdown,
and collects all unique search URLs for each make.
"""
import asyncio
from playwright.async_api import async_playwright

BASE_URL = "https://notadir.brimborg.is/is"
DROPDOWN_XPATH = "/html/body/div[1]/div[2]/div[2]/div[2]/div[1]/div[2]/div/div/div/div[2]/div/form/div[2]/div[1]/span/select"


async def discover_brimborg_links():
    """
    Navigate to Brimborg used cars page and collect all make-specific search URLs.
    """
    discovered_urls = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        print(f"Navigating to {BASE_URL}...")
        await page.goto(BASE_URL)
        
        # Wait for the page to load
        await asyncio.sleep(3)
        
        try:
            # Find the dropdown using xpath
            dropdown = await page.query_selector(f'xpath={DROPDOWN_XPATH}')
            
            if not dropdown:
                print("Dropdown not found!")
                await browser.close()
                return discovered_urls
            
            # Get all options from the dropdown
            options = await dropdown.query_selector_all('option')
            print(f"Found {len(options)} options in the make dropdown")
            
            for option in options:
                # Get the value attribute (which should contain the make ID)
                value = await option.get_attribute('value')
                text = await option.inner_text()
                
                # Skip empty or "All" options
                if not value or value == "" or value == "0":
                    print(f"Skipping option: {text} (value: {value})")
                    continue
                
                # Construct the search URL with the make filter
                # The URL pattern appears to use query parameters
                search_url = f"{BASE_URL}/notadir-bilar?brand={value}"
                
                print(f"Make: {text.strip()} -> {search_url}")
                discovered_urls.append(search_url)
            
        except Exception as e:
            print(f"Error discovering links: {e}")
        
        await browser.close()
    
    print(f"\n=== Discovered {len(discovered_urls)} unique make URLs ===")
    for url in discovered_urls:
        print(url)
    
    return discovered_urls


if __name__ == "__main__":
    urls = asyncio.run(discover_brimborg_links())
    
    # Save to file
    if urls:
        with open("brimborg_seed_links.txt", "w") as f:
            for url in urls:
                f.write(url + "\n")
        print(f"\nSaved {len(urls)} URLs to brimborg_seed_links.txt")
