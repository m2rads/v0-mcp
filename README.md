# Browser Automation with Playwright

A simple browser automation script that opens v0.dev in a new tab, using your existing Chrome browser and preserving all your accounts and cookies.

## Features

- Connects to your existing Chrome browser with all your accounts/cookies
- Creates a new tab to navigate to v0.dev
- Falls back to launching Chrome with your profile if not already running
- Keeps your Chrome instance open after the script finishes

## Prerequisites

- Python 3.8+
- Google Chrome browser

## Installation

Install Playwright:

```bash
# Using pip
pip install playwright

# OR using uv
uv pip install playwright
```

## Usage

### Option 1: Connect to your existing Chrome browser (recommended)

1. First, start Chrome with remote debugging enabled:

```bash
# macOS
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222
```

2. Then run the script:

```bash
python main.py
```

### Option 2: Let the script handle everything

Simply run the script, and it will:
1. Check if Chrome is running with debugging enabled
2. If not, launch Chrome with your profile and the debugging port
3. Connect to Chrome and open a new tab to v0.dev
4. Keep your Chrome instance running when you exit

```bash
python main.py
```

## How it works

1. The script first tries to connect to an existing Chrome browser with remote debugging
2. If none is found, it launches Chrome with your user profile
3. It opens a new tab in your Chrome and navigates to v0.dev
4. When you press Enter, it closes the automation but keeps your Chrome running

## Troubleshooting

If you have issues:

1. Try closing all Chrome instances and run the script - it will launch Chrome with your profile
2. For browser installation issues:
   ```bash 
   python -m playwright install chromium
   ```
3. If you want more detailed logs, set `debug=True` in the BrowserConfig
