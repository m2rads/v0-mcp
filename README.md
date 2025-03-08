# Browser Automation with Playwright

A simple browser automation script that opens v0.dev in a new tab, using your existing Chrome browser if available.

## Prerequisites

- Python 3.8+
- Chrome/Chromium browser

## Installation

1. Install dependencies using uv:

```bash
uv pip install -r requirements.txt
```

2. Install Playwright Chromium:

```bash
python -m playwright install chromium
```

## Usage

### Connect to existing Chrome browser

First, start Chrome with remote debugging enabled:

```bash
# macOS - MOST RELIABLE METHOD
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 --no-first-run

# Windows
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222

# Linux
google-chrome --remote-debugging-port=9222
```

Then run the script:

```bash
python main.py
```

The script will:
1. Connect to your existing Chrome browser
2. Open a new tab and navigate to v0.dev
3. Wait for you to press Enter to close

If the script cannot connect to an existing Chrome instance, it will automatically launch a new Chrome/Chromium browser.

## Troubleshooting

If you have trouble connecting to Chrome:

1. Make sure Chrome is running with the `--remote-debugging-port=9222` flag

2. Check if something is listening on port 9222:
   ```bash
   # macOS/Linux
   lsof -i :9222
   
   # Windows
   netstat -an | findstr 9222
   ```

3. If you see "Failed to launch browser", run:
   ```bash
   python -m playwright install --force chromium
   ```
