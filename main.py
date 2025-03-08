import asyncio
import os
import json
import subprocess
import sys
import platform
from dataclasses import dataclass
from urllib.request import urlopen
from typing import Optional
from playwright.async_api import async_playwright, Browser as PlaywrightBrowser

@dataclass
class BrowserConfig:
    """Configuration for browser automation"""
    headless: bool = False
    chrome_instance_path: Optional[str] = None
    extra_args: list[str] = None
    disable_security: bool = True
    
    def __post_init__(self):
        if self.extra_args is None:
            self.extra_args = []
        
        # Set default Chrome path based on platform
        if not self.chrome_instance_path:
            if platform.system() == "Darwin":  # macOS
                self.chrome_instance_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
            elif platform.system() == "Windows":
                self.chrome_instance_path = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
            elif platform.system() == "Linux":
                self.chrome_instance_path = "/usr/bin/google-chrome"

class Browser:
    """Playwright browser automation with support for connecting to existing instances"""
    
    def __init__(self, config: BrowserConfig = BrowserConfig()):
        self.config = config
        self.playwright = None
        self.browser = None
        
    async def setup(self):
        """Initialize browser and connect to existing instance or launch new one"""
        self.playwright = await async_playwright().start()
        self.browser = await self._setup_browser()
        return self.browser
    
    async def _get_debugging_url(self):
        """Get WebSocket URL for Chrome debugging"""
        try:
            response = urlopen("http://localhost:9222/json/version")
            data = json.loads(response.read())
            return data.get("webSocketDebuggerUrl")
        except Exception:
            return None
    
    async def _check_chrome_running(self):
        """Check if Chrome is running with remote debugging port"""
        try:
            response = urlopen("http://localhost:9222/json/version")
            if response.getcode() == 200:
                return True
        except:
            pass
        return False
    
    async def _launch_chrome_instance(self):
        """Launch Chrome with remote debugging port"""
        if not os.path.exists(self.config.chrome_instance_path):
            print(f"Chrome not found at: {self.config.chrome_instance_path}")
            return False
        
        try:
            cmd = [
                self.config.chrome_instance_path,
                "--remote-debugging-port=9222",
                "--no-first-run",
                "--no-default-browser-check"
            ] + self.config.extra_args
            
            print(f"Launching Chrome: {' '.join(cmd)}")
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # Wait for Chrome to start
            for _ in range(5):
                if await self._check_chrome_running():
                    return True
                await asyncio.sleep(1)
        except Exception as e:
            print(f"Failed to start Chrome: {e}")
        
        return False
    
    async def _setup_browser(self) -> PlaywrightBrowser:
        """Connect to existing Chrome or launch a new one"""
        # First try to connect to existing Chrome
        if await self._check_chrome_running():
            print("Connecting to existing Chrome instance...")
            try:
                browser = await self.playwright.chromium.connect_over_cdp("http://localhost:9222")
                print("✅ Connected to existing Chrome instance")
                return browser
            except Exception as e:
                print(f"Failed to connect to existing Chrome: {e}")
        
        # Try to launch Chrome if not running
        if not await self._check_chrome_running():
            print("No Chrome instance with debugging port found. Launching new instance...")
            if await self._launch_chrome_instance():
                try:
                    browser = await self.playwright.chromium.connect_over_cdp("http://localhost:9222")
                    print("✅ Connected to launched Chrome instance")
                    return browser
                except Exception as e:
                    print(f"Failed to connect to launched Chrome: {e}")
        
        # As a fallback, launch a browser through Playwright
        print("Launching new browser through Playwright...")
        security_args = []
        if self.config.disable_security:
            security_args = [
                "--disable-web-security",
                "--disable-site-isolation-trials",
                "--no-sandbox"
            ]
            
        browser = await self.playwright.chromium.launch(
            headless=self.config.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--no-first-run"
            ] + security_args + self.config.extra_args
        )
        print("✅ Launched new browser instance")
        return browser

    async def close(self):
        """Close browser resources"""
        try:
            if self.browser and "connect" not in str(self.browser.__class__):
                await self.browser.close()
                
            if self.playwright:
                await self.playwright.stop()
        except Exception as e:
            print(f"Error during cleanup: {e}")

async def automate_browser():
    """Main automation function that navigates to v0.dev"""
    config = BrowserConfig(
        headless=False,
        extra_args=["--disable-gpu"] if platform.system() == "Darwin" else []
    )
    
    browser_manager = Browser(config)
    try:
        browser = await browser_manager.setup()
        
        # Create a new context and page
        context = await browser.new_context()
        page = await context.new_page()
        
        # Navigate to v0.dev
        print("\nNavigating to v0.dev...")
        await page.goto("https://v0.dev", wait_until="domcontentloaded")
        
        print("✅ Navigation successful!")
        print("Current URL:", page.url)
        
        # Wait for user input before closing
        print("\nPress Enter to close...")
        input()
        
        # Close context
        await context.close()
        
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        await browser_manager.close()

def main():
    """Entry point for the script"""
    try:
        asyncio.run(automate_browser())
    except KeyboardInterrupt:
        print("\nScript terminated by user.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    main()
