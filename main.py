import asyncio
import sys
import os
import json
from urllib.request import urlopen
from playwright.async_api import async_playwright

async def get_chrome_debugging_url():
    """Get the WebSocket URL for Chrome debugging"""
    try:
        # Try to get the WebSocket URL from Chrome's debugging JSON
        response = urlopen("http://localhost:9222/json/version")
        data = json.loads(response.read())
        return data.get("webSocketDebuggerUrl")
    except Exception as e:
        print(f"Failed to get Chrome debugging URL: {e}")
        return None

async def run_browser_automation():
    async with async_playwright() as p:
        browser = None
        
        # Try multiple connection methods to Chrome
        print("Attempting to connect to Chrome...")
        
        # Method 1: Connect via WebSocket URL
        ws_url = await get_chrome_debugging_url()
        if ws_url:
            try:
                print(f"Connecting using WebSocket URL: {ws_url}")
                browser = await p.chromium.connect(ws_endpoint=ws_url)
                print("✅ Connected to Chrome using WebSocket URL")
            except Exception as e:
                print(f"Failed to connect using WebSocket URL: {e}")
                browser = None
        
        # Method 2: Connect via CDP
        if not browser:
            try:
                cdp_urls = [
                    "http://127.0.0.1:9222",  # Try localhost IP explicitly
                    "http://localhost:9222"    # Try localhost name
                ]
                
                for cdp_url in cdp_urls:
                    try:
                        print(f"Connecting using CDP URL: {cdp_url}")
                        browser = await p.chromium.connect_over_cdp(cdp_url)
                        print(f"✅ Connected to Chrome using CDP at {cdp_url}")
                        break
                    except Exception as e:
                        print(f"Failed to connect to {cdp_url}: {e}")
            except Exception as e:
                print(f"All CDP connection attempts failed: {e}")
        
        # If we still can't connect, launch a new browser
        if not browser:
            print("\nCould not connect to existing Chrome. Launching new browser...")
            try:
                browser = await p.chromium.launch(
                    headless=False,
                    args=["--no-sandbox", "--disable-gpu"]
                )
                print("✅ Launched new Chromium browser")
            except Exception as e:
                print(f"Failed to launch browser: {e}")
                print("Please run: python -m playwright install chromium")
                return
        
        if not browser:
            print("Failed to connect to or launch Chrome/Chromium.")
            return
            
        try:
            # Create a new context
            context = await browser.new_context(
                viewport={'width': 1280, 'height': 800},
                ignore_https_errors=True
            )
            
            # Create a new page
            page = await context.new_page()
            
            # Navigate to v0.dev
            print("\nNavigating to v0.dev...")
            
            try:
                response = await page.goto("https://v0.dev", 
                                         wait_until="domcontentloaded", 
                                         timeout=30000)
                
                print("✅ Navigation complete!")
                print("Current URL:", page.url)
                
                # Wait for user input
                print("\nPress Enter to close...")
                input()
                
            except Exception as nav_error:
                print(f"Navigation error: {nav_error}")
            
        except Exception as e:
            print(f"An error occurred: {e}")
            
        finally:
            # Always clean up resources
            try:
                if 'context' in locals() and context:
                    await context.close()
                
                # Only close browser if we launched it (not if we connected to existing Chrome)
                if browser and not ws_url and 'connect' not in str(browser.__class__):
                    await browser.close()
                    
            except Exception as cleanup_error:
                print(f"Error during cleanup: {cleanup_error}")

def main():
    try:
        asyncio.run(run_browser_automation())
    except KeyboardInterrupt:
        print("\nScript terminated by user.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
