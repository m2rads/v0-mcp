import asyncio
import platform
import sys
import os
import argparse
from browser import Browser, BrowserConfig
from tools import monitor_v0_interactions, extract_v0_response

async def main_automation(prompt=None):
    """Main automation function that monitors v0.dev interactions"""
    # Default calendar app prompt with specific details to trigger a more complex response
    if prompt is None:
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
    print("Prompt will be submitted automatically:")
    print(f"Prompt: {prompt}")
    print("-" * 80)
    
    # Use our monitor_v0_interactions function from tools.py with the detailed prompt
    await monitor_v0_interactions(prompt)

def extract_response(file_path):
    """Extract and display a response from a previously captured file"""
    if not os.path.exists(file_path):
        print(f"Error: File not found at {file_path}")
        return

    print(f"Extracting response from {file_path}...")
    response = extract_v0_response(file_path)
    
    if response:
        print("\n" + "=" * 80)
        print("EXTRACTED RESPONSE:")
        print("=" * 80)
        print(response)
        print("=" * 80)
        
        # Save to a clean .txt file if it's not already one
        if not file_path.endswith('.txt'):
            output_file = f"{os.path.splitext(file_path)[0]}_clean.txt"
            with open(output_file, 'w') as f:
                f.write(response)
            print(f"Saved clean response to {output_file}")
    else:
        print(f"Could not extract response from {file_path}")

def list_captures():
    """List all captured files in the captures directory"""
    captures_dir = "captures"
    if not os.path.exists(captures_dir):
        print(f"Error: Captures directory not found at {captures_dir}")
        return

    files = sorted(os.listdir(captures_dir))
    if not files:
        print("No captured files found.")
        return

    print(f"\nFound {len(files)} captured files:")
    for i, file in enumerate(files, 1):
        file_path = os.path.join(captures_dir, file)
        size = os.path.getsize(file_path)
        print(f"  {i:2d}. {file} ({size} bytes)")
        
        # Show preview for certain file types
        if file.endswith('.txt') and ('full_response' in file or 'assembled_content' in file):
            try:
                with open(file_path, 'r') as f:
                    content = f.read(200)  # Get a short preview
                    if content:
                        print(f"      Preview: {content[:100]}...")
            except Exception:
                pass

def main():
    """Entry point for the script"""
    parser = argparse.ArgumentParser(description='v0.dev Network Monitor and Response Extractor')
    
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # Monitor command
    monitor_parser = subparsers.add_parser('monitor', help='Monitor v0.dev and capture responses')
    monitor_parser.add_argument('--prompt', '-p', type=str, help='Custom prompt to submit to v0.dev')
    
    # Extract command
    extract_parser = subparsers.add_parser('extract', help='Extract response from a captured file')
    extract_parser.add_argument('file', type=str, help='Path to the captured file')
    
    # List command
    subparsers.add_parser('list', help='List all captured files')
    
    args = parser.parse_args()
    
    try:
        if args.command == 'monitor' or args.command is None:
            # Default to monitor if no command specified
            asyncio.run(main_automation(args.prompt if hasattr(args, 'prompt') and args.prompt else None))
        elif args.command == 'extract':
            extract_response(args.file)
        elif args.command == 'list':
            list_captures()
        else:
            parser.print_help()
    except KeyboardInterrupt:
        print("\nScript terminated by user.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        import traceback
        traceback.print_exc()  # Print full stack trace for better debugging

if __name__ == "__main__":
    main()
