"""
Quick smoke check — verifies Playwright can reach and interact with:
  1. SauceDemo (https://www.saucedemo.com)
  2. PHP Travels (https://phptravels.net/demo)
Run: python smoke_check.py
"""
import asyncio
from playwright.async_api import async_playwright


async def check_saucedemo(browser):
    print("\n--- SauceDemo ---")
    page = await browser.new_page()
    try:
        await page.goto("https://www.saucedemo.com", timeout=15000)
        title = await page.title()
        print(f"  title     : {title}")

        # Check login form exists
        username = page.locator("#user-name")
        password = page.locator("#password")
        btn      = page.locator("#login-button")
        print(f"  username field visible : {await username.is_visible()}")
        print(f"  password field visible : {await password.is_visible()}")
        print(f"  login button visible   : {await btn.is_visible()}")

        # Try logging in with standard_user
        await username.fill("standard_user")
        await password.fill("secret_sauce")
        await btn.click()
        await page.wait_for_url("**/inventory.html", timeout=8000)
        print(f"  login OK  : redirected to {page.url}")
        print("  RESULT    : PASS")
    except Exception as e:
        print(f"  RESULT    : FAIL — {e}")
    finally:
        await page.close()


async def check_phptravels(browser):
    print("\n--- PHP Travels ---")
    page = await browser.new_page()
    try:
        await page.goto("https://phptravels.net", timeout=20000)
        title = await page.title()
        print(f"  title     : {title}")
        print(f"  url       : {page.url}")

        # Check for basic nav / search elements
        body_text = await page.inner_text("body")
        has_hotel  = "hotel" in body_text.lower()
        has_flight = "flight" in body_text.lower()
        has_tour   = "tour" in body_text.lower()
        print(f"  has 'hotel'  : {has_hotel}")
        print(f"  has 'flight' : {has_flight}")
        print(f"  has 'tour'   : {has_tour}")

        if has_hotel or has_flight:
            print("  RESULT    : PASS")
        else:
            print("  RESULT    : PARTIAL — page loaded but content unexpected")
    except Exception as e:
        print(f"  RESULT    : FAIL — {e}")
    finally:
        await page.close()


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        await check_saucedemo(browser)
        await check_phptravels(browser)
        await browser.close()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
