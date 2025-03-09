# V0.dev Response Capture Tool

A tool that connects to your browser, navigates to v0.dev, submits prompts, and captures all network responses - including the streamed AI responses. This allows you to save the complete output from v0.dev for further analysis or use.

## Features

- Connects to your existing Chrome browser with all your accounts/cookies
- Navigates to v0.dev and submits your prompt
- Captures all network activity, focusing on streamed AI responses
- Decodes the Vercel AI SDK streaming format to extract complete responses
- Saves responses to files for later reference
- Provides tools to extract and view responses from saved files

## Prerequisites

- Python 3.8+
- Google Chrome browser

## Installation

1. Clone this repository
2. Install dependencies:

```bash
# Using pip
pip install -r requirements.txt

# OR using uv
uv pip install -r requirements.txt

# Install Playwright browsers
python -m playwright install chromium
```

## Usage

### Capturing a v0.dev response

Run the script with a prompt to capture the response:

```bash
# Use the default prompt (calendar app)
python main.py

# Specify a custom prompt
python main.py monitor --prompt "Build a landing page for a coffee shop with a menu section and contact form"
```

The script will:
1. Connect to your Chrome browser (or launch a new instance)
2. Navigate to v0.dev
3. Submit your prompt
4. Capture all network activity, including the streaming responses
5. Save the responses to the `captures` directory

### Listing captured files

List all the files in your captures directory:

```bash
python main.py list
```

### Extracting responses from captured files

Extract and display the complete response from a captured file:

```bash
python main.py extract captures/full_response_1234567890.txt
```

This will:
1. Parse and decode the captured file
2. Extract the complete text response
3. Display it in the terminal
4. Save a clean version to a new file

## How It Works

### Vercel AI SDK Streaming Format

v0.dev uses the Vercel AI SDK to stream responses in a Server-Sent Events (SSE) format:

```
data: {"type":"data","value":[{"text":"Building"}]}
data: {"type":"data","value":[{"text":" a"}]}
data: {"type":"data","value":[{"text":" calendar"}]}
data: {"type":"message_annotations","value":[{"type":"finish_reason","message":"stop"}]}
```

Our tool:
1. Captures these streamed responses
2. Decodes the format to extract the text content
3. Assembles the complete response
4. Saves both raw and processed data

### File Types

The tool saves several types of files:
- `sse_stream_*.jsonl`: Raw SSE stream data
- `sse_decoded_*.jsonl`: Decoded JSON events from the stream
- `assembled_content_*.txt`: Assembled text content from the stream
- `full_response_*.txt`: Complete, cleaned response text

## Troubleshooting

If you have issues:

1. Try closing all Chrome instances and run the script - it will launch Chrome with your profile
2. For browser installation issues:
   ```bash 
   python -m playwright install chromium
   ```
3. If responses aren't being captured properly, increase the monitoring time in `tools.py`

## Advanced Usage

### Directly using the extraction tool

You can also use the extraction function directly from the `tools.py` file:

```bash
python tools.py extract captures/your_captured_file.jsonl
```

### Custom monitoring duration

By default, the script monitors for 60 seconds. For complex prompts that take longer, you can modify the `monitor_v0_interactions` function in `tools.py` to increase the monitoring time.
