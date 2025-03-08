import asyncio
import os
import json
import subprocess
import sys
import platform
import time
from dataclasses import dataclass
from urllib.request import urlopen
from typing import Optional, List
from playwright.async_api import async_playwright, Browser as PlaywrightBrowser, Page

@dataclass
class BrowserConfig:
    """Configuration for browser automation"""
    headless: bool = False
    chrome_instance_path: Optional[str] = None
    extra_args: List[str] = None
    disable_security: bool = True
    debug: bool = False
    
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
        self.is_connected_to_existing = False
        self.log(f"Browser initialized with config: headless={config.headless}, chrome_path={config.chrome_instance_path}")
    
    def log(self, message):
        """Log debug messages if debug is enabled"""
        if self.config.debug:
            print(f"[DEBUG] {message}")
        
    async def setup(self):
        """Initialize browser and connect to existing instance or launch new one"""
        self.playwright = await async_playwright().start()
        self.browser = await self._setup_browser()
        return self.browser
    
    async def _get_chrome_tabs(self):
        """Get information about available Chrome tabs"""
        try:
            response = urlopen("http://localhost:9222/json")
            return json.loads(response.read())
        except Exception as e:
            self.log(f"Failed to get Chrome tabs: {e}")
            return []
    
    async def _get_debugging_url(self):
        """Get WebSocket URL for Chrome debugging"""
        try:
            response = urlopen("http://localhost:9222/json/version")
            data = json.loads(response.read())
            websocket_url = data.get("webSocketDebuggerUrl")
            self.log(f"Got Chrome debugging URL: {websocket_url}")
            return websocket_url
        except Exception as e:
            self.log(f"Failed to get debugging URL: {e}")
            return None
    
    async def _check_chrome_running(self):
        """Check if Chrome is running with remote debugging port"""
        try:
            response = urlopen("http://localhost:9222/json/version")
            if response.getcode() == 200:
                self.log("Chrome is running with debugging port")
                return True
        except Exception as e:
            self.log(f"Chrome not running with debugging port: {e}")
        return False
    
    async def _launch_chrome_instance(self):
        """Launch Chrome with remote debugging port"""
        if not os.path.exists(self.config.chrome_instance_path):
            print(f"⚠️ Chrome not found at: {self.config.chrome_instance_path}")
            return False
        
        try:
            # First check if Chrome is already running normally and kill it
            if platform.system() == "Darwin":  # macOS
                try:
                    self.log("Checking for existing Chrome processes")
                    subprocess.run(["pkill", "-f", "Google Chrome"], 
                                  stdout=subprocess.DEVNULL, 
                                  stderr=subprocess.DEVNULL)
                    # Give it a moment to shut down
                    time.sleep(1)
                except:
                    pass
            
            cmd = [
                self.config.chrome_instance_path,
                "--remote-debugging-port=9222",
                "--no-first-run",
                "--no-default-browser-check",
                # Don't use incognito to keep user's cookies
                "--user-data-dir=" + os.path.expanduser("~/Library/Application Support/Google/Chrome") 
                if platform.system() == "Darwin" else "",
            ] + self.config.extra_args
            
            print(f"Launching Chrome with your profile...")
            self.log(f"Command: {' '.join(cmd)}")
            
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # Wait for Chrome to start
            for i in range(5):
                self.log(f"Waiting for Chrome to start (attempt {i+1}/5)")
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
                print("✅ Connected to existing Chrome instance with your profile")
                self.is_connected_to_existing = True
                return browser
            except Exception as e:
                print(f"Failed to connect to existing Chrome: {e}")
        
        # Try to launch Chrome if not running
        if not await self._check_chrome_running():
            print("No Chrome instance with debugging port found.")
            print("Launching Chrome with your profile...")
            if await self._launch_chrome_instance():
                try:
                    # Give Chrome a moment to fully initialize
                    await asyncio.sleep(2)
                    browser = await self.playwright.chromium.connect_over_cdp("http://localhost:9222")
                    print("✅ Connected to Chrome with your profile")
                    self.is_connected_to_existing = True
                    return browser
                except Exception as e:
                    print(f"Failed to connect to launched Chrome: {e}")
        
        # As a fallback, launch a browser through Playwright
        print("⚠️ Could not connect to Chrome. Launching a new browser instance...")
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
        print("✅ Launched new browser instance (without your profile)")
        return browser

    async def new_page(self):
        """Create a new page in the browser"""
        if not self.browser:
            raise Exception("Browser not initialized. Call setup() first.")
            
        # For existing Chrome, create a new context only if needed
        if self.is_connected_to_existing:
            # Get existing contexts
            contexts = self.browser.contexts
            if contexts:
                # Use the first existing context
                context = contexts[0]
            else:
                # Create a new context if none exists
                context = await self.browser.new_context()
        else:
            # For new browser instances, always create a new context
            context = await self.browser.new_context()
            
        # Create and return a new page
        return await context.new_page()

    async def close(self):
        """Close browser resources without closing the user's existing Chrome"""
        try:
            # Only close the browser if we launched it ourselves
            if self.browser and not self.is_connected_to_existing:
                self.log("Closing launched browser")
                await self.browser.close()
            elif self.browser and self.is_connected_to_existing:
                self.log("Not closing connected Chrome (keeping your instance running)")
                
            if self.playwright:
                await self.playwright.stop()
        except Exception as e:
            print(f"Error during cleanup: {e}")

async def automate_browser():
    """Main automation function that navigates to v0.dev"""
    config = BrowserConfig(
        headless=False,
        extra_args=["--disable-gpu"] if platform.system() == "Darwin" else [],
        debug=False  # Set to True for more detailed logs
    )
    
    browser_manager = Browser(config)
    try:
        # Setup browser - connects to existing Chrome or launches a new one
        await browser_manager.setup()
        
        # Create a new page directly using our helper method
        page = await browser_manager.new_page()
        
        # Navigate to v0.dev
        print("\nNavigating to v0.dev...")
        await page.goto("https://v0.dev", wait_until="domcontentloaded")
        
        print("✅ Navigation successful!")
        print("Current URL:", page.url)
        
        # Wait for user input before closing
        print("\nPress Enter to close the automation (your Chrome will remain open)...")
        input()
        
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
