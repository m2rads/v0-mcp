import asyncio
import platform
import sys
from browser import Browser, BrowserConfig

async def main_automation():
    """Main automation function that navigates to v0.dev"""
    # Configure browser options
    config = BrowserConfig(
        headless=False,
        extra_args=["--disable-gpu"] if platform.system() == "Darwin" else [],
        debug=False  # Set to True for more detailed logs
    )
    
    # Initialize browser manager
    browser_manager = Browser(config)
    try:
        # Setup and connect to browser
        await browser_manager.setup()
        
        # Navigate to v0.dev and get the page object
        page = await browser_manager.navigate("https://v0.dev")
        
        # Wait for user input before closing
        print("\nPress Enter to close the automation (your Chrome will remain open)...")
        input()
        
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        # Clean up resources (this will keep the user's Chrome open)
        await browser_manager.close()

def main():
    """Entry point for the script"""
    try:
        asyncio.run(main_automation())
    except KeyboardInterrupt:
        print("\nScript terminated by user.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    main()
