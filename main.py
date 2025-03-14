import asyncio
from browser import Browser, BrowserConfig
from tools import monitor_v0_interactions

async def main():
    """Main function that gets a prompt from the user and monitors v0.dev interactions"""
    print("v0.dev Network Monitor")
    print("-" * 30)
    
    # Get prompt from user
    prompt = input("Enter your prompt for v0.dev: ")
    
    if not prompt.strip():
        print("No prompt provided. Exiting.")
        return
    
    print("-" * 30)
    print("Starting monitoring...")
    
    # Run the monitoring with the user's prompt
    await monitor_v0_interactions(prompt)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nMonitoring stopped.")
    except Exception as e:
        print(f"Error: {e}")
