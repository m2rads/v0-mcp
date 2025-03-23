import asyncio
import json
import re
import base64
import os
import time
import traceback
from typing import Dict, List, Optional, Callable, Any, Union
from browser import Browser, BrowserConfig

# Add utility functions at the top level to help parse Vercel AI SDK streams
def extract_event_data(line: str) -> Optional[str]:
    """Extract data from an SSE event line."""
    if line.startswith('data: '):
        return line[6:].strip()
    return None

def parse_sse_chunk(chunk: str) -> List[Dict[str, Any]]:
    """Parse a chunk of SSE text into structured events."""
    events = []
    for line in chunk.split('\n'):
        line = line.strip()
        if not line or line.startswith(':'):  # Skip comments and empty lines
            continue
        
        data = extract_event_data(line)
        if data:
            try:
                # Try to parse as JSON
                json_data = json.loads(data)
                events.append(json_data)
            except json.JSONDecodeError:
                # If not valid JSON, store as raw text
                events.append({"raw": data})
    
    return events

class NetworkMonitor:
    """Monitor and capture network traffic for v0.dev interactions"""
    
    def __init__(self, browser: Browser, debug: bool = False):
        """Monitor and capture network traffic for v0.dev interactions"""
        self.browser = browser
        self.debug = debug
        self.page = None
        self.prompt_submitted = False  # Flag to track when prompt has been submitted
        self.network_log = []  # Store all network requests
        self.pending_tasks = []  # Keep track of pending async tasks
        self.vercel_ai_responses = []  # Store decoded Vercel AI SDK responses
        self.chat_id = None  # Store the chat ID extracted from the URL
        
        # Create captures directory if it doesn't exist
        self.capture_dir = "captures"
        os.makedirs(self.capture_dir, exist_ok=True)
        
        # Keep track of request IDs for matching requests and responses
        self.request_map = {}
        self.saved_files = []  # Track successfully saved files
        
        # To assemble complete SSE messages across chunks
        self.partial_sse_data = ""
        
        # Store assembled content from streaming responses
        self.assembled_content = ""
        
        print(f"📁 NetworkMonitor initialized. Files will be saved to: {self.capture_dir}/")
        
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
        
        # Store the original context for later reference
        self.original_context = self.page.context
        
        # Add event listener to page for focus changes
        await self.page.evaluate("""() => {
            window.addEventListener('blur', () => {
                console.log('MONITOR_TAB_LOST_FOCUS');
            });
            window.addEventListener('focus', () => {
                console.log('MONITOR_TAB_GAINED_FOCUS');
            });
        }""")
        
        # Set up event listeners for the page
        await self._setup_page_listeners()
        
        # Set up network listeners - must be done before enabling request interception
        self._setup_event_listeners()
        
        # Navigate to v0.dev
        await self.page.goto(url, wait_until="domcontentloaded")
        print("Page loaded - ready for prompt")
        
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
            
            # Set up listener for URL changes
            self.page.on('framenavigated', self._handle_navigation)
            
            if self.debug:
                print("Page event listeners set up")
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
            elif "MONITOR_TAB_LOST_FOCUS" in text:
                print("⚠️ Monitored tab lost focus - monitoring will continue")
            elif "MONITOR_TAB_GAINED_FOCUS" in text:
                print("✅ Monitored tab gained focus")
        except Exception as e:
            if self.debug:
                print(f"Error handling console message: {e}")
    
    def _handle_navigation(self, frame):
        """Handle navigation events to detect chat_id changes"""
        if frame is self.page.main_frame and not self.chat_id:  # Only proceed if chat_id isn't set yet
            url = frame.url
            if 'v0.dev/chat/' in url:
                # Extract chat_id from URL
                url_parts = url.split('/')
                for i, part in enumerate(url_parts):
                    if part == 'chat' and i < len(url_parts) - 1:
                        potential_chat_id = url_parts[i+1].split('?')[0]  # Remove query parameters
                        if potential_chat_id and potential_chat_id != 'api':
                            self.chat_id = potential_chat_id
                            print(f"🆔 Detected chat_id: {self.chat_id}")
                            break
    
    def _setup_event_listeners(self):
        """Set up basic event listeners"""
        if not self.page:
            raise Exception("Page not set up. Call setup() first.")
        
        # Listen for websocket connections
        self.page.on("websocket", self._log_websocket)
        
        # Add handler for responses to attempt to decode SSE streams
        self.page.on("response", self._check_for_sse)
        
        if self.debug:
            print("Basic event listeners set up")
        
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
        
        # Set page as target so events from this page will be processed even when not in focus
        await self.client.send("Page.enable")
        
        if self.debug:
            print("Network interception enabled")
    
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
                    print(f"🔍 _check_for_sse: Detected SSE stream from URL: {url}")
                    # Start streaming the response
                    try:
                        # Start streaming the response
                        reader = response.body_stream()
                        chunks = []
                        timestamp = int(time.time())
                        
                        # Only save if the URL contains "chat"
                        if "chat" in url.lower():
                            filename = f"{self.capture_dir}/sse_stream_{timestamp}.jsonl"
                            decoded_filename = f"{self.capture_dir}/sse_decoded_{timestamp}.jsonl"
                            full_response_filename = f"{self.capture_dir}/full_response_{timestamp}.txt"
                            
                            print(f"💾 _check_for_sse: Will save SSE stream to: {filename}")
                            print(f"💾 _check_for_sse: Will save decoded events to: {decoded_filename}")
                            
                            # Keep track of partial SSE data across chunks
                            partial_data = ""
                            
                            # Write each chunk to the file as we receive it
                            with open(filename, "wb") as raw_file, open(decoded_filename, "w") as decoded_file:
                                try:
                                    while True:
                                        chunk = await reader.read(1024)
                                        if not chunk:
                                            break
                                        
                                        # Save the raw chunk
                                        chunks.append(chunk)
                                        raw_file.write(chunk)
                                        
                                        # Try to decode and parse this chunk
                                        try:
                                            chunk_text = chunk.decode('utf-8', errors='ignore')
                                            
                                            # Combine with any partial data from previous chunk
                                            combined_text = partial_data + chunk_text
                                            
                                            # If we have incomplete lines, save them for the next chunk
                                            lines = combined_text.split('\n')
                                            if not combined_text.endswith('\n'):
                                                partial_data = lines.pop()
                                            else:
                                                partial_data = ""
                                                
                                            # Parse the complete lines in this chunk
                                            events = parse_sse_chunk('\n'.join(lines))
                                            
                                            # Write decoded events to file
                                            for event in events:
                                                decoded_file.write(json.dumps(event) + "\n")
                                                decoded_file.flush()  # Ensure data is written immediately
                                                
                                                # Store Vercel AI responses for later
                                                self.vercel_ai_responses.append(event)
                                                
                                                # Extract text content if available and update assembled content
                                                if isinstance(event, dict):
                                                    if "text" in event:
                                                        self.assembled_content += event["text"]
                                                    elif "raw" in event and isinstance(event["raw"], str):
                                                        try:
                                                            # Try to parse raw as JSON
                                                            raw_json = json.loads(event["raw"])
                                                            if isinstance(raw_json, dict) and "text" in raw_json:
                                                                self.assembled_content += raw_json["text"]
                                                        except:
                                                            pass
                                        
                                        except Exception as e:
                                            pass
                                
                                except Exception as e:
                                    pass
                            
                            self.saved_files.append(filename)
                            self.saved_files.append(decoded_filename)
                            
                            # Process the full stream content
                            full_data = b"".join(chunks)
                            events = self._parse_sse_stream(full_data)
                            
                            # Save the fully assembled text content
                            if self.assembled_content:
                                # Create a clean filename without timestamp for easy access
                                clean_filename = f"{self.capture_dir}/full_response.txt"
                                with open(clean_filename, "w") as f:
                                    f.write(self.assembled_content)
                                print(f"💾 _check_for_sse: Saved assembled content to: {clean_filename}")
                                if clean_filename not in self.saved_files:
                                    self.saved_files.append(clean_filename)
                        else:
                            print(f"ℹ️ _check_for_sse: URL doesn't contain 'chat', not saving files")
                    
                    except Exception as e:
                        print(f"❌ _check_for_sse: Error processing SSE stream: {e}")
            except Exception as e:
                print(f"❌ _check_for_sse: Error checking headers: {e}")
    
    def _parse_sse_stream(self, data: Union[bytes, str]) -> List[Dict[str, Any]]:
        """
        Parse SSE stream data into structured events, with special handling for Vercel AI SDK format.
        
        The Vercel AI SDK uses a format like:
        data: {"type":"data","value":[{"text":"some content"}]}
        data: {"type":"data","value":[{"text":" more content"}]}
        data: {"type":"message_annotations","value":[{"type":"finish_reason","message":"stop"}]}
        """
        if not data:
            return []
            
        try:
            # Convert bytes to string
            if isinstance(data, bytes):
                text = data.decode('utf-8', errors='ignore')
            else:
                text = data
            
            # Store raw data for debug
            if self.debug:
                timestamp = int(time.time())
                debug_filename = f"{self.capture_dir}/raw_sse_{timestamp}.txt"
                with open(debug_filename, "w") as f:
                    f.write(text)
                print(f"💾 _parse_sse_stream: Saved raw SSE data for debugging to: {debug_filename}")
            
            # Initialize event collection
            events = []
            assembled_text = ""
            
            # Process different Vercel AI SDK event formats
            
            # First, try to extract standard SSE lines (data: {json})
            lines = text.split('\n')
            for i, line in enumerate(lines):
                line = line.strip()
                if not line or line.startswith(':'):  # Skip comments and empty lines
                    continue
                
                # Extract data from "data: " prefixed lines
                if line.startswith('data: '):
                    data_content = line[6:]
                    try:
                        # Try to parse as JSON
                        parsed = json.loads(data_content)
                        
                        # Handle Vercel AI SDK format with type and value fields
                        if isinstance(parsed, dict) and 'type' in parsed and 'value' in parsed:
                            if parsed['type'] == 'data' and isinstance(parsed['value'], list):
                                # Extract text from the value array
                                for item in parsed['value']:
                                    if isinstance(item, dict) and 'text' in item:
                                        text_content = item['text']
                                        assembled_text += text_content
                                        events.append({
                                            "event_type": "data",
                                            "text": text_content,
                                            "assembled_text": assembled_text
                                        })
                            
                            elif parsed['type'] == 'message_annotations':
                                # Handle annotations like finish_reason
                                events.append({
                                    "event_type": "message_annotations",
                                    "annotations": parsed['value']
                                })
                        # Handle direct text field
                        elif isinstance(parsed, dict) and 'text' in parsed:
                            text_content = parsed['text']
                            assembled_text += text_content
                            events.append({
                                "event_type": "direct_text",
                                "text": text_content,
                                "assembled_text": assembled_text
                            })
                        # Handle content field (sometimes used instead of text)
                        elif isinstance(parsed, dict) and 'content' in parsed:
                            text_content = parsed['content']
                            assembled_text += text_content
                            events.append({
                                "event_type": "content",
                                "text": text_content,
                                "assembled_text": assembled_text
                            })
                        else:
                            # Handle other JSON formats
                            events.append(parsed)
                    except json.JSONDecodeError:
                        # If not valid JSON, store as raw text
                        events.append({"raw": data_content})
            
            # If we couldn't parse any structured events, fall back to regex patterns
            if not events:
                # Try to extract JSON with text field
                text_matches = re.finditer(r'data: (\{.*?"text":\s*".*?"\s*.*?\})', text)
                for match in text_matches:
                    try:
                        json_str = match.group(1)
                        json_data = json.loads(json_str)
                        events.append(json_data)
                        if 'text' in json_data:
                            assembled_text += json_data['text']
                    except:
                        pass
                
                # Try to extract JSON with content field
                content_matches = re.finditer(r'data: (\{.*?"content":\s*".*?"\s*.*?\})', text)
                for match in content_matches:
                    try:
                        json_str = match.group(1)
                        json_data = json.loads(json_str)
                        events.append(json_data)
                        if 'content' in json_data:
                            assembled_text += json_data['content']
                    except:
                        pass
                
                # If still no events, try basic JSON pattern
                if not events:
                    json_matches = re.finditer(r'data: ({.*?})', text)
                    for match in json_matches:
                        try:
                            json_str = match.group(1)
                            json_data = json.loads(json_str)
                            events.append(json_data)
                        except:
                            pass
            
            # If we have extracted content, save the assembled text
            if assembled_text:
                self.assembled_content += assembled_text
                
                # Only save files if we're processing chat-related content
                if any("chat" in str(event) for event in events):
                    timestamp = int(time.time())
                    
                    # Save to timestamped file
                    timestamped_filename = f"{self.capture_dir}/assembled_content_{timestamp}.txt"
                    with open(timestamped_filename, "w") as f:
                        f.write(self.assembled_content)
                    print(f"💾 _parse_sse_stream: Saved timestamped assembled content to: {timestamped_filename}")
                    
                    # Also save to a consistent filename for easy access
                    consistent_filename = f"{self.capture_dir}/assembled_content.txt"
                    with open(consistent_filename, "w") as f:
                        f.write(self.assembled_content)
                    print(f"💾 _parse_sse_stream: Updated consistent assembled content file: {consistent_filename}")
                    
                    print(f"📝 Updated assembled text content (total: {len(self.assembled_content)} chars)")
                else:
                    print(f"ℹ️ _parse_sse_stream: No 'chat' in events, not saving assembled content")
            
            # If we still have no events, just return raw chunks
            if not events:
                for line in text.split('\n'):
                    if line.startswith('data: '):
                        events.append({"raw": line[6:]})
            
            return events
        except Exception as e:
            print(f"❌ _parse_sse_stream: Error parsing SSE stream: {e}")
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
        
        # Only print and save if after prompt submission and in debug mode
        if self.prompt_submitted and self.debug:
            if "v0.dev/chat/" in url and "_rsc=" in url:
                print(f"[{method}] CONTENT REQUEST: {url}")
            elif "v0.dev/chat/api/send" in url:
                print(f"[{method}] PROMPT SEND ENDPOINT: {url}")
                # Save POST data
                if method == "POST" and request.get("postData"):
                    self._save_request_payload(request_id, url, request.get("postData"))
            elif any(keyword in url for keyword in ["v0.dev", "vercel", "_stream", "api", "heap"]):
                print(f"[{method}] {url}")
    
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
        
        # Only print if after prompt submission and in debug mode
        if self.prompt_submitted and self.debug:
            # Special handling for v0.dev content responses
            if "v0.dev/chat/" in url and "_rsc=" in url:
                print(f"[{status}] CONTENT RESPONSE: {url}")
                # Create a task to capture this response specifically
                task = asyncio.create_task(self._capture_content_response(request_id, url))
                self.pending_tasks.append(task)
            elif "v0.dev/chat/api/send" in url:
                print(f"[{status}] RESPONSE FROM SEND ENDPOINT: {url}")
            elif "_stream" in url:
                print(f"[{status}] STREAM: {url}")
            elif any(keyword in url for keyword in ["v0.dev", "vercel", "api", "heap"]):
                print(f"[{status}] {url}")
        elif self.prompt_submitted:
            # Always capture important responses even if not in debug mode
            if "v0.dev/chat/" in url and "_rsc=" in url:
                task = asyncio.create_task(self._capture_content_response(request_id, url))
                self.pending_tasks.append(task)
    
    async def _capture_content_response(self, request_id, url):
        """Capture and save content responses from v0.dev"""
        try:
            # Get the response body using CDP
            result = await self.client.send("Network.getResponseBody", {"requestId": request_id})
            
            body = result.get("body", "")
            base64_encoded = result.get("base64Encoded", False)
            
            # Decode base64 if needed
            if base64_encoded and body:
                body_bytes = base64.b64decode(body)
                body_text = body_bytes.decode('utf-8', errors='ignore')
            else:
                body_text = body
            
            # Create a unique filename based on the URL
            timestamp = int(time.time())
            
            # Extract a meaningful name from the URL
            url_parts = url.split('/')
            print(f"url_parts: {url_parts}")
            file_name = None
            
            # Skip if URL contains community or projects
            if 'community' in url_parts or 'projects' in url_parts:
                print(f"ℹ️ _capture_content_response: URL contains community/projects, skipping: {url}")
                return
            
            # Look for meaningful segments in the URL
            for part in url_parts:
                if part.startswith("chat/") and len(part) > 5:
                    file_name = part.split('?')[0]  # Remove query parameters
                    break
            
            if not file_name:
                # Fallback to the last part of the URL
                file_name = url_parts[-1].split('?')[0]
                print(f"ℹ️ last part of the url: {file_name}")
            
            # Clean up the filename
            file_name = file_name.replace('/', '_').replace('?', '_').replace('=', '_')
            
            # Only save if the URL contains "chat"
            if "chat" in url.lower():
                filename = f"{self.capture_dir}/{file_name}_{timestamp}.txt"

                # Check for pattern: name-with-dashes-chatid_timestamp
                pattern = f'-{self.chat_id}_'
                if not re.search(pattern, filename):
                    print(f"filename does not match expected pattern: {filename} - not saving response")
                    return
                
                with open(filename, "w") as f:
                    f.write(body_text)
                
                print(f"💾 _capture_content_response: Saved response to: {filename}")
                self.saved_files.append(filename)
                
                # Also save a cleaned version with only the code
                clean_text = self._clean_response_text(body_text)
                if clean_text:
                    clean_filename = f"{self.capture_dir}/{file_name}_clean_{timestamp}.txt"
                    with open(clean_filename, "w") as f:
                        f.write(clean_text)
                    
                    print(f"💾 _capture_content_response: Saved cleaned response to: {clean_filename}")
                    self.saved_files.append(clean_filename)
            else:
                print(f"ℹ️ _capture_content_response: URL doesn't contain 'chat', not saving files")
                
        except Exception as e:
            print(f"❌ _capture_content_response: Error capturing content: {e}")
            
    def _clean_response_text(self, text):
        """Clean the response text to extract only the code sections"""
        try:
            # Look for all V0_FILE sections
            v0_file_pattern = r'(\w+:T\w+,\[V0_FILE\][^"]+".+?")'
            v0_sections = list(re.finditer(v0_file_pattern, text))
            
            if not v0_sections:
                print("⚠️ _clean_response_text: No V0_FILE sections found in text")
                return None
                
            print(f"📋 _clean_response_text: Found {len(v0_sections)} V0_FILE sections")
            
            # Process each section to extract clean code
            clean_sections = []
            mdx_sections = []  # New array to store MDX formatted sections
            unique_files = {}  # Dictionary to track unique filenames
            
            for i, section_match in enumerate(v0_sections):
                section_start = section_match.start()
                section_marker = section_match.group(0)
                
                # Extract the file path for deduplication
                file_path_match = re.search(r'\[V0_FILE\][^"]+file="([^"]+)"', section_marker)
                if not file_path_match:
                    continue
                file_path = file_path_match.group(1)
                
                # Skip if this file has already been processed
                if file_path in unique_files:
                    print(f"🔄 _clean_response_text: Skipping duplicate file: {file_path}")
                    continue
                
                # Mark this file as processed
                unique_files[file_path] = True
                
                # Determine where this section ends
                if i < len(v0_sections) - 1:
                    next_section_start = v0_sections[i+1].start()
                    section_text = text[section_start:next_section_start]
                else:
                    # For the last section, go to the end of the text
                    section_text = text[section_start:]
                
                # Split into lines for processing
                lines = section_text.split('\n')
                
                # The first line contains the V0_FILE marker
                clean_lines = [lines[0]]
                
                # Extract language type from marker for MDX format
                language_match = re.search(r'\[V0_FILE\](\w+):file="', section_marker)
                language_type = language_match.group(1) if language_match else "text"
                
                # Start actual code from the line after the marker
                code_lines = []
                for j in range(1, len(lines)):
                    line = lines[j]
                    
                    # Check if this line looks like metadata (e.g., "19:[["b_RRDRw9zzXnD",false]]")
                    if re.match(r'^\d+:\[\["[^"]+",', line):
                        continue
                        
                    # Check for cursor position marker
                    if '<CURRENT_CURSOR_POSITION>' in line:
                        continue
                        
                    # Check for other non-code patterns
                    if re.match(r'^\w+:\[\[', line):
                        continue
                    
                    code_lines.append(line)
                
                # MODIFIED: Instead of trying to find the "last meaningful line",
                # we'll use a different approach to handle trailing content better
                
                # First, keep all non-empty lines by default
                filtered_code_lines = []
                
                # Check if we're dealing with a file that might have SVG or JSON content
                is_svg_or_json = file_path.endswith('.svg') or file_path.endswith('.json') or '.tsx' in file_path or '.jsx' in file_path
                
                # Track nesting level for brackets to better handle complex structures
                nesting_level = 0
                in_special_content = False
                
                for line in code_lines:
                    # Count opening and closing brackets/tags to track nesting
                    if is_svg_or_json:
                        # For SVG/JSX files, we need to track tag and brace nesting
                        opens = line.count('<') + line.count('{')
                        closes = line.count('>') + line.count('}')
                        
                        # Detect if we're in a special content block (like SVG or JSON)
                        if '<svg' in line or '={[' in line or '= {' in line:
                            in_special_content = True
                        
                        # Once we're in special content, be more careful about what we exclude
                        if in_special_content:
                            filtered_code_lines.append(line)
                            continue
                        
                        nesting_level += opens - closes
                    
                    # Skip lines that are clearly non-code metadata
                    if re.match(r'^f:\[\["', line) or re.match(r'^[\d]+:\[\[', line):
                        # But only if we're not in a nested structure
                        if nesting_level <= 0 and not in_special_content:
                            break
                    
                    # Add the line to our filtered list if it's not empty or is part of a nested structure
                    if line.strip() or nesting_level > 0 or in_special_content:
                        filtered_code_lines.append(line)
                
                # Add all the filtered code lines
                clean_lines.extend(filtered_code_lines)
                
                # Create traditional clean text section
                clean_sections.append('\n'.join(clean_lines))
                
                # Create Cursor-style formatted section - THIS IS THE KEY CHANGE
                code_block = '\n'.join(filtered_code_lines)
                mdx_section = f"```{language_type}:{file_path}\n{code_block}\n```"
                mdx_sections.append(mdx_section)
            
            # Combine all clean sections (original format)
            clean_text = '\n\n'.join(clean_sections)
            
            # Combine all MDX sections (new format)
            mdx_text = '\n\n'.join(mdx_sections)
            
            # Verify that we have code sections
            if "[V0_FILE]" not in clean_text:
                print("⚠️ _clean_response_text: Extracted text doesn't contain V0_FILE markers, using original text")
                return None
                
            # Save MDX formatted output
            timestamp = int(time.time())
            mdx_filename = f"{self.capture_dir}/cursor_formatted_{timestamp}.md"
            with open(mdx_filename, "w") as f:
                f.write(mdx_text)
            
            print(f"💾 _clean_response_text: Saved Cursor-style formatted output to: {mdx_filename}")
            self.saved_files.append(mdx_filename)
            
            # Also create individual files for each code section (original functionality)
            for i, section_text in enumerate(clean_sections):
                # Extract the file path from the V0_FILE marker
                file_path_match = re.search(r'\[V0_FILE\][^"]+file="([^"]+)"', section_text)
                if file_path_match:
                    file_path = file_path_match.group(1)
                    
                    # Extract only the code part (everything after the first line)
                    code_lines = section_text.split('\n')[1:]
                    
                    # Create a clean filename for this specific section
                    timestamp = int(time.time())
                    clean_filename = f"{self.capture_dir}/file_{file_path.replace('/', '_')}_{timestamp}.txt"
                    
                    with open(clean_filename, "w") as f:
                        f.write('\n'.join(code_lines))
                    
                    print(f"💾 _clean_response_text: Saved individual file to: {clean_filename}")
                    self.saved_files.append(clean_filename)
            
            return clean_text
            
        except Exception as e:
            print(f"❌ _clean_response_text: Error cleaning response text: {e}")
            if self.debug:
                traceback.print_exc()
            return None
    
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
        # task = asyncio.create_task(self._get_and_save_response_body(request_id, url))
        # self.pending_tasks.append(task)
        return
        
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
            
            # Only save if url_part is "chat"
            if url_part.lower() == "chat":
                filename = f"{self.capture_dir}/{url_part}_{timestamp}"
                
                # For SSE streams, try to parse them
                if "text/event-stream" in content_type:
                    events = self._parse_sse_stream(body_bytes)
                    if events:
                        json_filename = f"{filename}_sse.jsonl"
                        with open(json_filename, "w") as f:
                            for event in events:
                                f.write(json.dumps(event) + "\n")
                        self.saved_files.append(json_filename)
                        
                        # Also save the raw data
                        raw_filename = f"{filename}_sse.raw"
                        with open(raw_filename, "wb") as f:
                            f.write(body_bytes)
                        self.saved_files.append(raw_filename)
                        
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
                        json_filename = f"{filename}.json"
                        with open(json_filename, "w") as f:
                            json.dump(json_data, f, indent=2)
                        self.saved_files.append(json_filename)
                    except Exception as e:
                        # Save as raw if JSON parsing fails
                        text_filename = f"{filename}.txt"
                        with open(text_filename, "wb") as f:
                            f.write(body_bytes)
                        self.saved_files.append(text_filename)
                else:
                    # Save as binary or text based on content
                    if "_stream" in url or "binary" in content_type.lower():
                        bin_filename = f"{filename}.bin"
                        with open(bin_filename, "wb") as f:
                            f.write(body_bytes)
                        self.saved_files.append(bin_filename)
                        
                        # Also try to decode as text
                        try:
                            decoded = body_bytes.decode('utf-8', errors='ignore')
                            decoded_filename = f"{filename}_decoded.txt"
                            with open(decoded_filename, "w") as f:
                                f.write(decoded)
                            self.saved_files.append(decoded_filename)
                        except:
                            print(f"ℹ️ _get_and_save_response_body: Could not decode binary as text")
                    else:
                        # Save as text
                        text_filename = f"{filename}.txt"
                        with open(text_filename, "wb") as f:
                            f.write(body_bytes)
                        self.saved_files.append(text_filename)
            else:
                print(f"ℹ️ _get_and_save_response_body: URL part '{url_part}' is not 'chat', not saving files")
        except Exception as e:
            print(f"❌ _get_and_save_response_body: Error saving response body for {url}: {e}")
            if self.debug:
                traceback.print_exc()
    
    def _save_request_payload(self, request_id, url, post_data):
        """Save request POST data to file"""
        if not post_data:
            return
            
        try:
            print(f"🔍 _save_request_payload: Processing request payload from URL: {url}")
            # Only save if the URL contains "chat"
            if "chat" in url.lower():
                timestamp = int(time.time())
                filename = f"{self.capture_dir}/send_request_{timestamp}.json"
                
                # Try to parse as JSON
                try:
                    json_data = json.loads(post_data)
                    with open(filename, "w") as f:
                        json.dump(json_data, f, indent=2)
                    self.saved_files.append(filename)
                    
                    # Print prompt if found and in debug mode
                    if "prompt" in json_data and self.debug:
                        print(f"DETECTED PROMPT: {json_data['prompt'][:100]}...")
                except:
                    # Save as plain text
                    with open(filename, "w") as f:
                        f.write(post_data)
                    self.saved_files.append(filename)
            else:
                print(f"ℹ️ _save_request_payload: URL doesn't contain 'chat', not saving files")
        except Exception as e:
            print(f"❌ _save_request_payload: Error saving request payload: {e}")
    
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
        
        # Only print if after prompt submission and in debug mode
        if self.prompt_submitted and self.debug:
            print(f"WebSocket connected: {url}")
        
        # Setup message listeners with payload capture
        websocket.on("message", lambda msg: self._log_websocket_message(websocket, msg))
    
    def _log_websocket_message(self, websocket, message):
        """Log and capture websocket messages"""
        if not self.prompt_submitted:
            return
        
        # Only save if the URL contains "chat"
        if "chat" in websocket.url.lower():
            print(f"🔍 _log_websocket_message: Processing WebSocket message from URL: {websocket.url}")
            timestamp = int(time.time())
            url_part = websocket.url.split("/")[-1].split("?")[0][:30]
            filename = f"{self.capture_dir}/ws_{url_part}_{timestamp}.txt"
            
            if self.debug:
                print(f"WebSocket message on {websocket.url} ({len(message)} bytes)")
            
            # Save the message content
            try:
                with open(filename, "w") as f:
                    f.write(message)
                self.saved_files.append(filename)
                
                # Try to parse as JSON
                try:
                    json_data = json.loads(message)
                    json_filename = f"{self.capture_dir}/ws_{url_part}_{timestamp}.json"
                    with open(json_filename, "w") as f:
                        json.dump(json_data, f, indent=2)
                    self.saved_files.append(json_filename)
                except:
                    print(f"ℹ️ _log_websocket_message: Message is not valid JSON, only saved as text")
            except Exception as e:
                print(f"❌ _log_websocket_message: Error saving WebSocket message: {e}")
        else:
            print(f"ℹ️ _log_websocket_message: WebSocket URL doesn't contain 'chat', not saving message")
    
    async def submit_prompt(self, prompt: str, wait_time: float = 2.0):
        """Type and submit a prompt to v0.dev"""
        if not self.page:
            raise Exception("Page not set up. Call setup() first.")
        
        # Wait for the textarea to appear
        await self.page.wait_for_selector("textarea", state="visible", timeout=30000)
        
        # Type the prompt
        print("Entering prompt...")
        await self.page.fill("textarea", prompt)
        
        # Allow some time for the UI to register the text
        await asyncio.sleep(wait_time)
        
        # Reset the chat_id before submitting
        self.chat_id = None
        print("Resetting chat_id before submission")
        
        # Try multiple methods to submit the prompt
        print("Submitting prompt...")
        
        # Method 1: Try to find and click a send button
        try:
            # Look for various button selectors that might be the send button
            selectors = [
                "button[type='submit']", 
                "button.send-button", 
                "button:has(svg)",
                "button:right-of(textarea)",
                "button[aria-label='Send message']",
                "button[aria-label='Submit']",
                "button.submit",
                "button.submit-button"
            ]
            
            for selector in selectors:
                button = await self.page.query_selector(selector)
                if button:
                    await button.click()
                    print("Prompt submitted via button click")
                    break
            else:
                # If no button found with selectors, try to find any button near the textarea
                textarea = await self.page.query_selector("textarea")
                if textarea:
                    # Get the bounding box of the textarea
                    bbox = await textarea.bounding_box()
                    if bbox:
                        # Click in the area to the right of the textarea (where send buttons often are)
                        await self.page.mouse.click(
                            bbox["x"] + bbox["width"] + 20, 
                            bbox["y"] + bbox["height"] / 2
                        )
                        print("Prompt submitted via click near textarea")
                    else:
                        # Fallback to Enter key
                        await self.page.press("textarea", "Enter")
                        print("Prompt submitted via Enter key")
                else:
                    # Fallback to Enter key
                    await self.page.press("textarea", "Enter")
                    print("Prompt submitted via Enter key")
        except Exception as e:
            # Fallback to pressing Enter if any error occurs
            await self.page.press("textarea", "Enter")
            print("Prompt submitted via Enter key (after error)")
        
        # Set the flag that we've submitted the prompt - now we can start logging
        self.prompt_submitted = True
        
        print("Monitoring for responses...")
        
        # Wait a short time to see if we get a URL change
        try:
            print("Waiting for URL change to detect chat_id...")
            # We don't need to block here - the navigation handler will catch the URL change
        except Exception as e:
            print(f"Error waiting for URL change: {e}")
    
    async def await_pending_tasks(self):
        """Wait for all pending tasks to complete"""
        if self.pending_tasks:
            await asyncio.gather(*self.pending_tasks, return_exceptions=True)
            self.pending_tasks = []

async def monitor_v0_interactions(prompt):
    """Main function to monitor v0.dev interactions with a specific prompt"""
    # Configure browser
    config = BrowserConfig(
        headless=False,
        debug=False,
        disable_security=True,
        extra_args=[
            "--disable-web-security", 
            "--enable-logging",
            "--process-per-tab"  # Use separate processes for tabs to maintain monitoring
        ]
    )
    
    # Initialize browser and monitor
    browser = Browser(config)
    monitor = NetworkMonitor(browser, debug=False)  # Disable debug mode for less output
    
    try:
        # Set up page and monitoring
        await monitor.setup()
        
        # Make the monitoring more resilient to tab switching
        print("✨ Tab monitoring active - you can now safely switch to other tabs")
        
        # Submit the prompt and wait for responses
        await monitor.submit_prompt(prompt)
        
        print("Monitoring network traffic. Press Ctrl+C to stop.")
        
        # Wait indefinitely, checking for user input to stop
        try:
            while True:
                await asyncio.sleep(1)
                # Ensure the CDP session is still attached to our page
                if monitor.client and monitor.page:
                    try:
                        # Ping the client to ensure it's still connected
                        await monitor.client.send("Runtime.evaluate", {"expression": "1"})
                    except Exception as e:
                        print("⚠️ Lost connection to monitored tab, reconnecting...")
                        # Reconnect the CDP session
                        monitor.client = await monitor.page.context.new_cdp_session(monitor.page)
                        await monitor._setup_network_interception()
        except KeyboardInterrupt:
            print("\nMonitoring stopped.")
        
        # Process pending tasks
        await monitor.await_pending_tasks()
        
        # Print minimal summary
        print("Capture complete.")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        # Clean up resources
        # await browser.close()
        pass

async def monitor_v0_interactions_and_return_content(prompt):
    """Modified version of monitor_v0_interactions that returns the clean text instead of saving to file"""
    # Configure browser
    config = BrowserConfig(
        headless=False,
        debug=False,
        disable_security=True,
        extra_args=[
            "--disable-web-security", 
            "--enable-logging",
            "--process-per-tab"  # Use separate processes for tabs to maintain monitoring
        ]
    )
    
    # Initialize browser and monitor with custom class
    browser = Browser(config)
    monitor = ContentReturningMonitor(browser, debug=False)  # Use the modified monitor class
    
    try:
        # Set up page and monitoring
        await monitor.setup()
        
        # Make the monitoring more resilient to tab switching
        print("✨ Tab monitoring active - you can now safely switch to other tabs")
        
        # Submit the prompt and wait for responses
        await monitor.submit_prompt(prompt)
        
        print("Monitoring network traffic. Press Ctrl+C to stop.")
        
        # Wait until we get content or timeout
        max_wait_time = 300  # Maximum wait time in seconds
        wait_start = time.time()
        
        try:
            while True:
                # Return clean_text once we have it
                if monitor.clean_text_content:
                    return monitor.clean_text_content
                
                # Check if we've waited too long
                if time.time() - wait_start > max_wait_time:
                    print("Reached maximum wait time, returning any content available")
                    return monitor.clean_text_content or "No content captured within timeout period"
                
                await asyncio.sleep(1)
                # Ensure the CDP session is still attached to our page
                if monitor.client and monitor.page:
                    try:
                        # Ping the client to ensure it's still connected
                        await monitor.client.send("Runtime.evaluate", {"expression": "1"})
                    except Exception as e:
                        print("⚠️ Lost connection to monitored tab, reconnecting...")
                        # Reconnect the CDP session
                        monitor.client = await monitor.page.context.new_cdp_session(monitor.page)
                        await monitor._setup_network_interception()
        except KeyboardInterrupt:
            print("\nMonitoring stopped.")
        
        # Process pending tasks
        await monitor.await_pending_tasks()
        
        # Return the captured content or a default message
        return monitor.clean_text_content or "No content captured before stopping"
            
    except Exception as e:
        print(f"Error: {e}")
        return f"Error occurred: {e}"
    finally:
        # Clean up resources
        # await browser.close()
        pass

class ContentReturningMonitor(NetworkMonitor):
    """Modified NetworkMonitor that stores clean_text_content for retrieval"""
    
    def __init__(self, browser, debug=False):
        """Initialize with a property to store clean text content"""
        super().__init__(browser, debug)
        self.clean_text_content = None
    
    async def _capture_and_return_content_response(self, request_id, url):
        """Modified version that captures content and stores it for return instead of just saving to file"""
        try:
            # Get the response body using CDP
            result = await self.client.send("Network.getResponseBody", {"requestId": request_id})
            
            body = result.get("body", "")
            base64_encoded = result.get("base64Encoded", False)
            
            # Decode base64 if needed
            if base64_encoded and body:
                body_bytes = base64.b64decode(body)
                body_text = body_bytes.decode('utf-8', errors='ignore')
            else:
                body_text = body
            
            # Create a unique filename based on the URL
            timestamp = int(time.time())
            
            # Extract a meaningful name from the URL
            url_parts = url.split('/')
            print(f"url_parts: {url_parts}")
            file_name = None
            
            # Skip if URL contains community or projects
            if 'community' in url_parts or 'projects' in url_parts:
                print(f"ℹ️ _capture_and_return_content_response: URL contains community/projects, skipping: {url}")
                return
            
            # Look for meaningful segments in the URL
            for part in url_parts:
                if part.startswith("chat/") and len(part) > 5:
                    file_name = part.split('?')[0]  # Remove query parameters
                    break
            
            if not file_name:
                # Fallback to the last part of the URL
                file_name = url_parts[-1].split('?')[0]
                print(f"ℹ️ last part of the url: {file_name}")
            
            # Clean up the filename
            file_name = file_name.replace('/', '_').replace('?', '_').replace('=', '_')
            
            # Only process if the URL contains "chat"
            if "chat" in url.lower():
                # Generate the full filename just for pattern matching
                filename = f"{self.capture_dir}/{file_name}_{timestamp}.txt"
                
                # Check for pattern in the full filename - exactly as in the original method
                pattern = f'-{self.chat_id}_'
                if not re.search(pattern, filename):
                    # Skip pattern check - we don't want to return early here
                    # This is the key fix - the original method was checking the pattern in the full filename
                    # but we'll proceed anyway to catch all content
                    print(f"⚠️ Pattern not found but processing anyway: {filename}")
                
                print(f"📝 _capture_and_return_content_response: Processing content from: {url}")
                
                # Get cleaned version with only the code
                clean_text = self._clean_response_text(body_text)
                if clean_text:
                    # Store the clean text for later retrieval
                    self.clean_text_content = clean_text
                    print(f"✅ _capture_and_return_content_response: Clean text content stored for retrieval ({len(clean_text)} chars)")
            else:
                print(f"ℹ️ _capture_and_return_content_response: URL doesn't contain 'chat', not processing")
                
        except Exception as e:
            print(f"❌ _capture_and_return_content_response: Error capturing content: {e}")
    
    # Override the handle_response_received method to capture content directly
    def _handle_response_received(self, event):
        """Handle response headers received events using CDP"""
        # Call the original method first
        super()._handle_response_received(event)
        
        # Add our custom processing for all responses
        if self.prompt_submitted:
            request_id = event.get("requestId")
            response = event.get("response", {})
            url = response.get("url")
            
            # Look for potential v0.dev content in all responses after prompt submission
            if "v0.dev/chat/" in url:
                print(f"🔍 Custom monitor checking URL: {url}")
                # Create a task to capture this response
                task = asyncio.create_task(self._capture_and_return_content_response(request_id, url))
                self.pending_tasks.append(task)