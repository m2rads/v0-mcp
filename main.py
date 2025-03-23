import asyncio
from browser import Browser, BrowserConfig
from tools import monitor_v0_interactions_and_return_content, monitor_v0_interactions
from mcp.server.fastmcp import FastMCP

# Initialize MCP Server 
mcp = FastMCP("v0")

@mcp.tool()
async def monitor_v0_interactions(prompt: str):
    """Monitor v0.dev interactions and return the AI generated content"""
    return await monitor_v0_interactions_and_return_content(prompt)


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
    
    # Run the monitoring with the user's prompt and get the clean text content
    # clean_text = await monitor_v0_interactions_and_return_content(prompt)
    await monitor_v0_interactions(prompt)
    
    # Print and/or use the clean text content
    # if clean_text:
    #     print("-" * 30)
    #     print("Clean text content:")
    #     print("-" * 30)
    #     print(clean_text)
    #     print("-" * 30)
    # else:
    #     print("No clean text content returned")

if __name__ == "__main__":
    try:
        # To run the script with MCP, uncomment the line below
        # mcp.run(transport='stdio')

        # To run the script without MCP, uncomment the line below and comment out the line above
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nMonitoring stopped.")
    except Exception as e:
        print(f"Error: {e}")
