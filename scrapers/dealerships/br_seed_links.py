import asyncio
from playwright.async_api import async_playwright

BASE_URL = "https://www.br.is/"


async def discover_br_links():
    """
    Discover make-specific URLs from BR (br.is) dropdown menu.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        print(f"Navigating to {BASE_URL}...")
        await page.goto(BASE_URL, wait_until="domcontentloaded")
        await asyncio.sleep(3)
        
        # Get the dropdown at the specified xpath
        try:
            dropdown = await page.wait_for_selector('xpath=/html/body/form/nav/div/div[4]/div/div/div/div/div/div[1]/div/div[1]/select', timeout=10000)
            print("Found dropdown menu")
        except Exception as e:
            print(f"Could not find dropdown: {e}")
            await browser.close()
            return []
        
        # Get all option elements
        options = await dropdown.query_selector_all('option')
        print(f"Found {len(options)} options in make dropdown")
        
        # Get the search button
        try:
            search_button = await page.wait_for_selector('xpath=/html/body/form/nav/div/div[4]/div/div/div/div/div/div[6]/div/input', timeout=10000)
            print("Found search button (Leita)")
        except Exception as e:
            print(f"Could not find search button: {e}")
            await browser.close()
            return []
        
        # First, collect all option values and texts before navigating
        option_data = []
        for option in options:
            try:
                value = await option.get_attribute('value')
                text = await option.inner_text()
                text = text.strip()
                
                # Skip empty options
                if not value or value == "" or not text:
                    continue
                    
                option_data.append({'value': value, 'text': text})
            except Exception as e:
                print(f"Error reading option: {e}")
                continue
        
        print(f"Collected {len(option_data)} valid make options")
        
        make_urls = []
        
        # Now iterate through the collected options
        for idx, opt in enumerate(option_data):
            try:
                value = opt['value']
                text = opt['text']
                
                print(f"[{idx + 1}/{len(option_data)}] Selecting make: {text} (value: {value})")
                
                # Re-find the dropdown on each iteration
                dropdown = await page.wait_for_selector('xpath=/html/body/form/nav/div/div[4]/div/div/div/div/div/div[1]/div/div[1]/select', timeout=10000)
                
                # Select the option in the dropdown
                await dropdown.select_option(value=value)
                await asyncio.sleep(1)
                
                # Re-find the search button
                search_button = await page.wait_for_selector('xpath=/html/body/form/nav/div/div[4]/div/div/div/div/div/div[6]/div/input', timeout=10000)
                
                # Click the search button
                await search_button.click()
                print("Clicked search button, waiting for navigation...")
                
                # Wait for navigation or a short delay
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=5000)
                except:
                    await asyncio.sleep(2)
                
                # Get the current URL after search
                current_url = page.url
                print(f"Result URL: {current_url}")
                make_urls.append(current_url)
                
                # Go back to base URL for next iteration
                await page.goto(BASE_URL, wait_until="domcontentloaded")
                await asyncio.sleep(2)
                
            except Exception as e:
                print(f"Error processing option '{text}': {e}")
                # Try to recover by going back to base URL
                try:
                    await page.goto(BASE_URL, wait_until="domcontentloaded")
                    await asyncio.sleep(2)
                except:
                    pass
                continue
        
        await browser.close()
        
        # Remove duplicates and save to file
        unique_urls = list(set(make_urls))
        unique_urls.sort()
        
        print(f"\n=== Discovered {len(unique_urls)} unique make URLs ===")
        for url in unique_urls:
            print(url)
        
        # Save to file
        with open("br_seed_links.txt", "w", encoding="utf-8") as f:
            for url in unique_urls:
                f.write(url + "\n")
        
        print(f"\nSaved {len(unique_urls)} URLs to br_seed_links.txt")
        return unique_urls


if __name__ == "__main__":
    asyncio.run(discover_br_links())
