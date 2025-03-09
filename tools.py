import asyncio
import json
import re
import base64
import os
import time
import traceback
from typing import Dict, List, Optional, Callable, Any
from browser import Browser, BrowserConfig

class NetworkMonitor:
    """Monitor and capture network traffic for v0.dev interactions"""
    
    def __init__(self, browser: Browser, debug: bool = False):
        self.browser = browser
        self.debug = debug
        self.page = None
        self.prompt_submitted = False  # Flag to track when prompt has been submitted
        self.network_log = []  # Store all network requests
        self.pending_tasks = []  # Keep track of pending async tasks
        self.vercel_ai_responses = []  # Store decoded Vercel AI SDK responses
        
        # Create captures directory if it doesn't exist
        self.capture_dir = "captures"
        os.makedirs(self.capture_dir, exist_ok=True)
        print(f"📁 Created captures directory at: {os.path.abspath(self.capture_dir)}")
        
        # Keep track of request IDs for matching requests and responses
        self.request_map = {}
        self.saved_files = []  # Track successfully saved files
        
    def log(self, message):
        """Log debug messages"""
        if self.debug:
            print(f"[DEBUG] {message}")
            
    async def setup(self, url: str = "https://v0.dev"):
        """Setup the page and network listeners"""
        print(f"Navigating to {url}...")
        
        # First make sure browser is set up
        if not self.browser.browser:
            await self.browser.setup()
            
        # Create a new page with modified request/response handlers
        self.page = await self.browser.new_page()
        
        # Set up event listeners for the page
        await self._setup_page_listeners()
        
        # Set up network listeners - must be done before enabling request interception
        self._setup_event_listeners()
        
        # Navigate to v0.dev
        await self.page.goto(url, wait_until="domcontentloaded")
        print("✅ Page loaded - ready to submit prompt")
        
        # Enable request and response handling - must be done after page load
        await self._setup_network_interception()
        
        return self.page
    
    async def _setup_page_listeners(self):
        """Set up page-level event listeners to capture fetch and XHR responses"""
        # Add script to intercept fetch responses
        try:
            await self.page.add_init_script("""
            // Store original fetch
            window._originalFetch = window.fetch;
            
            // Override fetch to capture responses
            window.fetch = async function(...args) {
                const url = args[0];
                const options = args[1] || {};
                
                // Call original fetch
                const response = await window._originalFetch(...args);
                
                // Clone the response so we can read the body
                const responseClone = response.clone();
                
                // Check if URL might be a Vercel AI SDK endpoint
                if (url.toString().includes('/api/') || url.toString().includes('/_stream/')) {
                    try {
                        // Try to read response body - depends on type
                        const contentType = response.headers.get('content-type');
                        let bodyData;
                        
                        if (contentType && contentType.includes('text/event-stream')) {
                            // For SSE streams, we need special handling
                            // Signal that this is an SSE stream
                            window._vercelAiSSE = window._vercelAiSSE || {};
                            window._vercelAiSSE[url] = true;
                        } else {
                            // For JSON or other formats, we can clone and read
                            if (contentType && contentType.includes('json')) {
                                bodyData = await responseClone.json();
                            } else {
                                bodyData = await responseClone.text();
                            }
                            
                            // Post message to allow detection from outside
                            window.postMessage({
                                type: 'fetch-response-captured',
                                url: url.toString(),
                                status: response.status,
                                contentType,
                                bodyData
                            }, '*');
                        }
                    } catch (err) {
                        console.error('Error capturing fetch response', err);
                    }
                }
                
                return response;
            };
            
            // Setup event source interceptor for SSE streams
            const originalEventSource = window.EventSource;
            window.EventSource = function(url, options) {
                console.log('EventSource created for URL:', url);
                
                // Notify that we're connecting to an SSE stream
                window.postMessage({
                    type: 'sse-connection',
                    url: url
                }, '*');
                
                const eventSource = new originalEventSource(url, options);
                
                // Intercept messages
                const originalAddEventListener = eventSource.addEventListener;
                eventSource.addEventListener = function(type, listener, options) {
                    if (type === 'message') {
                        const wrappedListener = function(event) {
                            // Capture the SSE message
                            window.postMessage({
                                type: 'sse-message',
                                url: url,
                                eventType: 'message',
                                data: event.data
                            }, '*');
                            
                            // Call original listener
                            listener(event);
                        };
                        return originalAddEventListener.call(this, type, wrappedListener, options);
                    }
                    return originalAddEventListener.call(this, type, listener, options);
                };
                
                return eventSource;
            };
            """)
            
            # Listen for window messages
            await self.page.evaluate("""() => {
                window.addEventListener('message', function(event) {
                    if (event.data && event.data.type) {
                        console.log('Intercepted message:', event.data.type, event.data.url);
                    }
                });
            }""")
            
            # Set up listener for console messages which may contain our captured data
            self.page.on("console", self._handle_console_message)
            
            print("✅ Page event listeners set up")
        except Exception as e:
            print(f"Error setting up page listeners: {e}")
    
    def _handle_console_message(self, msg):
        """Handle console messages that might contain our captured data"""
        if not self.prompt_submitted:
            return
            
        try:
            text = msg.text
            if "Intercepted message:" in text and "sse-message" in text:
                # This is likely a message about an SSE stream
                print(f"🔄 Detected SSE message in console")
                
                # Try to extract the URL and data
                if self.debug:
                    print(f"Console message: {text}")
        except Exception as e:
            if self.debug:
                print(f"Error handling console message: {e}")
    
    def _setup_event_listeners(self):
        """Set up basic event listeners"""
        if not self.page:
            raise Exception("Page not set up. Call setup() first.")
        
        # Listen for websocket connections
        self.page.on("websocket", self._log_websocket)
        
        # Add handler for responses to attempt to decode SSE streams
        self.page.on("response", self._check_for_sse)
        
        print("✅ Basic event listeners set up")
        
    async def _setup_network_interception(self):
        """Set up request interception after page is loaded"""
        if not self.page:
            raise Exception("Page not set up. Call setup() first.")
            
        # Create a CDP session for direct access to CDP protocol
        self.client = await self.page.context.new_cdp_session(self.page)
        
        # Enable Network domain in CDP
        await self.client.send("Network.enable")
        
        # Set up event listeners for network traffic
        self.client.on("Network.requestWillBeSent", self._handle_request_sent)
        self.client.on("Network.responseReceived", self._handle_response_received)
        self.client.on("Network.loadingFinished", self._handle_response_finished)
        
        # Enable Fetch domain to intercept responses for better SSE handling
        await self.client.send("Fetch.enable", {
            "patterns": [{"urlPattern": "**/chat/api/*"}, {"urlPattern": "**/_stream/**"}]
        })
        
        # Set up handler for Fetch events
        self.client.on("Fetch.requestPaused", self._handle_fetch_request)
        
        print("✅ Network interception enabled")
    
    async def _handle_fetch_request(self, event):
        """Handle a fetch request interception"""
        request_id = event.get("requestId")
        
        # Continue the request and get the response body
        await self.client.send("Fetch.continueRequest", {"requestId": request_id})
    
    async def _check_for_sse(self, response):
        """Check if a response is an SSE stream and handle it if so"""
        if not self.prompt_submitted:
            return
            
        url = response.url
        
        # Only check certain endpoints
        if "chat/api" in url or "_stream" in url:
            try:
                headers = await response.all_headers()
                content_type = headers.get("content-type", "")
                
                # Check if it's an SSE stream
                if "text/event-stream" in content_type or "text/event-stream" in headers.get("Content-Type", ""):
                    print(f"🔄 Detected SSE stream: {url}")
                    
                    try:
                        # Start streaming the response
                        reader = response.body_stream()
                        chunks = []
                        timestamp = int(time.time())
                        filename = f"{self.capture_dir}/sse_stream_{timestamp}.jsonl"
                        
                        # Write each chunk to the file as we receive it
                        with open(filename, "wb") as f:
                            try:
                                while True:
                                    chunk = await reader.read(1024)
                                    if not chunk:
                                        break
                                    chunks.append(chunk)
                                    f.write(chunk)
                            except Exception as e:
                                print(f"Error during stream reading: {e}")
                        
                        self.saved_files.append(filename)
                        print(f"📝 Saved SSE stream to {filename}")
                        
                        # Try to parse the SSE stream into events
                        full_data = b"".join(chunks)
                        events = self._parse_sse_stream(full_data)
                        
                        if events:
                            decoded_filename = f"{self.capture_dir}/sse_decoded_{timestamp}.jsonl"
                            with open(decoded_filename, "w") as f:
                                for event in events:
                                    f.write(json.dumps(event) + "\n")
                            self.saved_files.append(decoded_filename)
                            print(f"📝 Saved decoded SSE events to {decoded_filename}")
                            
                            # Store these in our vercel_ai_responses
                            self.vercel_ai_responses.extend(events)
                    except Exception as e:
                        print(f"Error handling SSE stream: {e}")
            except Exception as e:
                print(f"Error checking headers for SSE: {e}")
    
    def _parse_sse_stream(self, data):
        """Parse SSE stream data into events"""
        if not data:
            return []
            
        try:
            # Convert bytes to string
            if isinstance(data, bytes):
                text = data.decode('utf-8', errors='ignore')
            else:
                text = data
                
            # Split into events (separated by double newlines)
            events = []
            
            # Handle different event formats
            # Match "data: {json}" format
            data_matches = re.finditer(r'data: ({.*})', text)
            for match in data_matches:
                try:
                    json_str = match.group(1)
                    json_data = json.loads(json_str)
                    events.append(json_data)
                except:
                    pass
            
            # Match Vercel AI SDK format with "text: " prefix
            text_matches = re.finditer(r'data: (\{.*?"text":\s*".*?"\s*.*?})', text)
            for match in text_matches:
                try:
                    json_str = match.group(1)
                    json_data = json.loads(json_str)
                    events.append(json_data)
                except:
                    pass
            
            # If we couldn't parse any JSON, just split by data: lines
            if not events:
                for line in text.split('\n'):
                    if line.startswith('data: '):
                        events.append({"raw": line[6:]})
            
            return events
        except Exception as e:
            print(f"Error parsing SSE stream: {e}")
            if self.debug:
                traceback.print_exc()
            return []
    
    def _handle_request_sent(self, event):
        """Handle request events using CDP"""
        request_id = event.get("requestId")
        request = event.get("request", {})
        method = request.get("method")
        url = request.get("url")
        
        # Store request data for later use
        self.request_map[request_id] = {
            "id": request_id,
            "url": url,
            "method": method,
            "headers": request.get("headers", {}),
            "post_data": request.get("postData"),
            "timestamp": time.time()
        }
        
        # Add to network log
        self.network_log.append({
            "type": "request",
            "id": request_id,
            "method": method,
            "url": url,
            "timestamp": time.time()
        })
        
        # Only print and save if after prompt submission
        if self.prompt_submitted:
            if "v0.dev/chat/api/send" in url:
                print(f"⭐ [{method}] PROMPT SEND ENDPOINT: {url}")
                # Save POST data
                if method == "POST" and request.get("postData"):
                    self._save_request_payload(request_id, url, request.get("postData"))
            elif any(keyword in url for keyword in ["v0.dev", "vercel", "_stream", "api", "heap"]):
                print(f"📤 [{method}] {url}")
    
    def _handle_response_received(self, event):
        """Handle response headers received events using CDP"""
        request_id = event.get("requestId")
        response = event.get("response", {})
        url = response.get("url")
        status = response.get("status")
        
        # Add response info to the request data
        if request_id in self.request_map:
            self.request_map[request_id]["response"] = {
                "status": status,
                "headers": response.get("headers", {}),
                "content_type": response.get("headers", {}).get("content-type", "")
            }
        
        # Add to network log
        self.network_log.append({
            "type": "response",
            "id": request_id,
            "status": status,
            "url": url,
            "timestamp": time.time()
        })
        
        # Only print if after prompt submission
        if self.prompt_submitted:
            if "v0.dev/chat/api/send" in url:
                print(f"⭐ [{status}] RESPONSE FROM SEND ENDPOINT: {url}")
            elif "_stream" in url:
                print(f"🔄 [{status}] STREAM: {url}")
            elif any(keyword in url for keyword in ["v0.dev", "vercel", "api", "heap"]):
                print(f"📥 [{status}] {url}")
    
    def _handle_response_finished(self, event):
        """Handle response body finished loading events using CDP"""
        request_id = event.get("requestId")
        
        # Check if we have this request in our map
        if request_id not in self.request_map:
            return
        
        request_data = self.request_map[request_id]
        url = request_data.get("url", "")
        
        # Skip if not submitted yet or not an interesting URL
        if not self.prompt_submitted:
            return
            
        is_interesting = (
            "v0.dev/chat/api/send" in url or 
            "_stream" in url or 
            (("v0.dev" in url or "vercel" in url) and "api" in url)
        )
        
        if not is_interesting:
            return
            
        # Create a task to get and save the response body
        task = asyncio.create_task(self._get_and_save_response_body(request_id, url))
        self.pending_tasks.append(task)
    
    async def _get_and_save_response_body(self, request_id, url):
        """Get response body and save it to file"""
        try:
            # Get the response body using CDP
            result = await self.client.send("Network.getResponseBody", {"requestId": request_id})
            
            body = result.get("body", "")
            base64_encoded = result.get("base64Encoded", False)
            
            # Decode base64 if needed
            if base64_encoded and body:
                body_bytes = base64.b64decode(body)
            else:
                body_bytes = body.encode('utf-8')
            
            # Extract content type
            content_type = self.request_map.get(request_id, {}).get("response", {}).get("content_type", "")
            
            # Create a unique filename
            timestamp = int(time.time())
            url_part = url.split("/")[-1].split("?")[0][:30]
            filename = f"{self.capture_dir}/{url_part}_{timestamp}"
            
            # For SSE streams, try to parse them
            if "text/event-stream" in content_type:
                events = self._parse_sse_stream(body_bytes)
                if events:
                    json_filename = f"{filename}_sse.jsonl"
                    with open(json_filename, "w") as f:
                        for event in events:
                            f.write(json.dumps(event) + "\n")
                    print(f"📝 Saved parsed SSE events to {json_filename}")
                    self.saved_files.append(json_filename)
                    
                    # Also save the raw data
                    with open(f"{filename}_sse.raw", "wb") as f:
                        f.write(body_bytes)
                    print(f"📝 Saved raw SSE data to {filename}_sse.raw")
                    self.saved_files.append(f"{filename}_sse.raw")
                    
                    # Add to our vercel responses collection
                    self.vercel_ai_responses.extend(events)
                    return
            
            # Determine file type and save
            if "json" in content_type.lower():
                # Try to save as JSON
                try:
                    if isinstance(body_bytes, bytes):
                        json_text = body_bytes.decode('utf-8')
                    else:
                        json_text = body
                        
                    json_data = json.loads(json_text)
                    with open(f"{filename}.json", "w") as f:
                        json.dump(json_data, f, indent=2)
                    print(f"📝 Saved JSON response to {filename}.json")
                    self.saved_files.append(f"{filename}.json")
                except Exception as e:
                    # Save as raw if JSON parsing fails
                    with open(f"{filename}.txt", "wb") as f:
                        f.write(body_bytes)
                    print(f"📝 Saved text response to {filename}.txt")
                    self.saved_files.append(f"{filename}.txt")
            else:
                # Save as binary or text based on content
                if "_stream" in url or "binary" in content_type.lower():
                    with open(f"{filename}.bin", "wb") as f:
                        f.write(body_bytes)
                    print(f"📝 Saved binary response to {filename}.bin")
                    self.saved_files.append(f"{filename}.bin")
                    
                    # Also try to decode as text
                    try:
                        decoded = body_bytes.decode('utf-8', errors='ignore')
                        with open(f"{filename}_decoded.txt", "w") as f:
                            f.write(decoded)
                        print(f"📝 Saved decoded binary to {filename}_decoded.txt")
                        self.saved_files.append(f"{filename}_decoded.txt")
                    except:
                        pass
                else:
                    # Save as text
                    with open(f"{filename}.txt", "wb") as f:
                        f.write(body_bytes)
                    print(f"📝 Saved text response to {filename}.txt")
                    self.saved_files.append(f"{filename}.txt")
        except Exception as e:
            print(f"Error saving response body for {url}: {e}")
            if self.debug:
                traceback.print_exc()
    
    def _save_request_payload(self, request_id, url, post_data):
        """Save request POST data to file"""
        if not post_data:
            return
            
        try:
            timestamp = int(time.time())
            filename = f"{self.capture_dir}/send_request_{timestamp}.json"
            
            # Try to parse as JSON
            try:
                json_data = json.loads(post_data)
                with open(filename, "w") as f:
                    json.dump(json_data, f, indent=2)
                print(f"📝 Saved request payload to {filename}")
                self.saved_files.append(filename)
                
                # Print prompt if found
                if "prompt" in json_data:
                    print(f"📤 DETECTED PROMPT: {json_data['prompt'][:100]}...")
            except:
                # Save as plain text
                with open(filename, "w") as f:
                    f.write(post_data)
                print(f"📝 Saved request payload to {filename}")
                self.saved_files.append(filename)
        except Exception as e:
            print(f"Error saving request payload: {e}")
    
    def _log_websocket(self, websocket):
        """Log websocket connection"""
        url = websocket.url
        
        # Store in our log
        event = {
            "type": "websocket", 
            "url": url,
            "timestamp": time.time()
        }
        self.network_log.append(event)
        
        # Only print if after prompt submission
        if self.prompt_submitted:
            print(f"🔌 WebSocket connected: {url}")
            
            # Setup message listeners with payload capture
            websocket.on("message", lambda msg: self._log_websocket_message(websocket, msg))
    
    def _log_websocket_message(self, websocket, message):
        """Log and capture websocket messages"""
        if not self.prompt_submitted:
            return
            
        timestamp = int(time.time())
        url_part = websocket.url.split("/")[-1].split("?")[0][:30]
        filename = f"{self.capture_dir}/ws_{url_part}_{timestamp}.txt"
        
        print(f"📨 WebSocket message on {websocket.url} ({len(message)} bytes)")
        
        # Save the message content
        try:
            with open(filename, "w") as f:
                f.write(message)
            print(f"📝 Saved WebSocket message to {filename}")
            self.saved_files.append(filename)
            
            # Try to parse as JSON
            try:
                json_data = json.loads(message)
                json_filename = f"{self.capture_dir}/ws_{url_part}_{timestamp}.json"
                with open(json_filename, "w") as f:
                    json.dump(json_data, f, indent=2)
                print(f"📝 Saved parsed WebSocket JSON to {json_filename}")
                self.saved_files.append(json_filename)
            except:
                pass
        except Exception as e:
            print(f"Error saving WebSocket message: {e}")
    
    async def submit_prompt(self, prompt: str, wait_time: float = 2.0):
        """Type and submit a prompt to v0.dev"""
        if not self.page:
            raise Exception("Page not set up. Call setup() first.")
        
        # Wait for the textarea to appear
        await self.page.wait_for_selector("textarea", state="visible", timeout=30000)
        
        # Type the prompt
        print(f"\n🔤 Entering prompt: '{prompt}'")
        await self.page.fill("textarea", prompt)
        
        # Allow some time for the UI to register the text
        await asyncio.sleep(wait_time)
        
        # Press Enter to submit
        print("🚀 Submitting prompt...")
        await self.page.press("textarea", "Enter")
        
        # Set the flag that we've submitted the prompt - now we can start logging
        self.prompt_submitted = True
        
        print("\n📝 Prompt submitted - monitoring network traffic for responses")
        print("-" * 80)
        
    async def await_pending_tasks(self):
        """Wait for all pending tasks to complete"""
        if self.pending_tasks:
            print(f"Waiting for {len(self.pending_tasks)} pending capture tasks to complete...")
            await asyncio.gather(*self.pending_tasks, return_exceptions=True)
            self.pending_tasks = []
            print("All capture tasks completed.")
        
    def print_network_summary(self):
        """Print summary of network activity after prompt submission"""
        if not self.prompt_submitted or not self.network_log:
            print("No network activity logged yet.")
            return
            
        # Filter to just post-submission events
        submission_time = 0
        for event in self.network_log:
            if event.get("type") == "request" and self.prompt_submitted:
                submission_time = event.get("timestamp", 0)
                break
                
        if submission_time == 0:
            print("Could not determine prompt submission time.")
            return
            
        post_submission = [e for e in self.network_log if e.get("timestamp", 0) >= submission_time]
        
        print("\n=== NETWORK SUMMARY ===")
        print(f"Total network events after prompt submission: {len(post_submission)}")
        
        # Group by type
        requests = [e for e in post_submission if e.get("type") == "request"]
        responses = [e for e in post_submission if e.get("type") == "response"]
        websockets = [e for e in post_submission if e.get("type") == "websocket"]
        
        print(f"Requests: {len(requests)}")
        print(f"Responses: {len(responses)}")
        print(f"WebSockets: {len(websockets)}")
        
        # Count files saved
        print(f"Files saved to '{self.capture_dir}' directory: {len(self.saved_files)}")
        
        # Check if we have Vercel AI SDK responses
        if self.vercel_ai_responses:
            print(f"Vercel AI SDK responses captured: {len(self.vercel_ai_responses)}")
        
        # List important endpoints
        print("\n=== IMPORTANT ENDPOINTS ===")
        stream_endpoints = [e for e in post_submission if "_stream" in e.get("url", "")]
        api_endpoints = [e for e in post_submission if "api" in e.get("url", "") and "v0.dev" in e.get("url", "")]
        
        # Check for the send endpoint specifically
        send_endpoints = [e for e in post_submission if "v0.dev/chat/api/send" in e.get("url", "")]
        if send_endpoints:
            print("\nPrompt send endpoint:")
            seen_urls = set()
            for e in send_endpoints:
                if e.get("type") == "request":
                    url = e.get("url", "")
                    method = e.get("method", "")
                    if f"{method}:{url}" not in seen_urls:
                        print(f"  - [{method}] {url}")
                        seen_urls.add(f"{method}:{url}")
        
        if stream_endpoints:
            print("\nStreaming endpoints:")
            seen_urls = set()
            for e in stream_endpoints:
                url = e.get("url", "")
                if url not in seen_urls:
                    print(f"  - {url}")
                    seen_urls.add(url)
        
        if api_endpoints:
            print("\nAPI endpoints:")
            seen_urls = set()
            for e in api_endpoints:
                url = e.get("url", "")
                if url not in seen_urls and "send" not in url:  # Don't repeat the send endpoint
                    print(f"  - {url}")
                    seen_urls.add(url)
                    
        # Show extracted AI responses
        if self.vercel_ai_responses:
            print("\n=== VERCEL AI SDK RESPONSES ===")
            for i, resp in enumerate(self.vercel_ai_responses[:5], 1):  # Show first 5 responses
                if "text" in resp:
                    print(f"  {i}. {resp['text'][:100]}..." if len(resp['text']) > 100 else resp['text'])
                elif "raw" in resp:
                    print(f"  {i}. Raw: {resp['raw'][:100]}..." if len(resp['raw']) > 100 else resp['raw'])
                else:
                    print(f"  {i}. {json.dumps(resp)[:100]}..." if len(json.dumps(resp)) > 100 else json.dumps(resp))
            
            if len(self.vercel_ai_responses) > 5:
                print(f"  ... and {len(self.vercel_ai_responses) - 5} more responses")
                    
        if self.saved_files:
            print("\n=== SAVED FILES ===")
            for i, file in enumerate(self.saved_files[:10], 1):  # Show first 10 files
                print(f"  {i}. {os.path.basename(file)}")
            
            if len(self.saved_files) > 10:
                print(f"  ... and {len(self.saved_files) - 10} more files")

async def monitor_v0_interactions(prompt="Build a calendar app with month and day view"):
    """Main function to monitor v0.dev interactions with a specific prompt"""
    # Configure browser
    config = BrowserConfig(
        headless=False,
        debug=False,
        disable_security=True,
        extra_args=["--disable-web-security", "--enable-logging"]  # Allow cross-origin requests and enable more logging
    )
    
    # Initialize browser and monitor
    browser = Browser(config)
    monitor = NetworkMonitor(browser, debug=True)  # Enable debug mode for more info
    
    try:
        # Set up page and monitoring
        await monitor.setup()
        
        # Submit the prompt and wait for responses
        await monitor.submit_prompt(prompt)
        
        print("\n🔍 Capturing network activity and saving payloads...")
        print("Check the 'captures' directory for saved request/response data")
        print("Monitoring for 30 seconds to capture responses...")
        
        # Wait for some time to capture network activity (extended to 30s for more time to capture responses)
        for i in range(30):
            print(f"Capturing... {i+1}/30 seconds", end="\r")
            await asyncio.sleep(1)
        
        print("\nCapture period complete. Processing pending tasks...")
        await monitor.await_pending_tasks()
        
        # Print summary of what we captured
        monitor.print_network_summary()
        
        print("\nPress Enter to view captures directory contents...")
        input()
        
        # Show the contents of the captures directory
        capture_dir = os.path.abspath(monitor.capture_dir)
        print(f"\n📁 Contents of {capture_dir}:")
        try:
            files = os.listdir(capture_dir)
            if files:
                for i, file in enumerate(files, 1):
                    file_path = os.path.join(capture_dir, file)
                    size = os.path.getsize(file_path)
                    print(f"  {i}. {file} ({size} bytes)")
            else:
                print("  (directory is empty)")
        except Exception as e:
            print(f"  Error listing directory: {e}")
            
        print("\nPress Enter to exit...")
        input()
        
    except Exception as e:
        print(f"An error occurred: {e}")
        traceback.print_exc()
    finally:
        try:
            # Wait for pending tasks to complete
            if hasattr(monitor, 'pending_tasks') and monitor.pending_tasks:
                await asyncio.gather(*monitor.pending_tasks, return_exceptions=True)
        except:
            pass
            
        # Clean up resources (this will keep the user's Chrome open)
        await browser.close() 