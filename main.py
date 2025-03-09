import asyncio
import platform
import sys
from browser import Browser, BrowserConfig
from tools import monitor_v0_interactions

async def main_automation():
    """Main automation function that monitors v0.dev interactions"""
    # Calendar app prompt with specific details to trigger a more complex response
    prompt = """
    Build a calendar app with:
    - Month view with ability to navigate between months
    - Day view showing hourly slots
    - Ability to add events with title, start time, end time
    - Color coding for different event types
    - Responsive design for mobile and desktop
    """
    
    print("-" * 80)
    print("Starting v0.dev network monitoring...")
    print("Will intercept all network traffic, including binary streaming responses")
    print("Calendar app prompt will be submitted automatically")
    print("-" * 80)
    
    # Use our monitor_v0_interactions function from tools.py with the detailed prompt
    await monitor_v0_interactions(prompt)

def main():
    """Entry point for the script"""
    try:
        asyncio.run(main_automation())
    except KeyboardInterrupt:
        print("\nScript terminated by user.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        import traceback
        traceback.print_exc()  # Print full stack trace for better debugging

if __name__ == "__main__":
    main()
