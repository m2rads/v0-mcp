import sys
import os
import time
from tools import NetworkMonitor

# Create a minimal test class that can access the protected method
class TestHelper:
    def __init__(self):
        # Create a bare minimum NetworkMonitor instance
        self.monitor = NetworkMonitor(None)
        self.monitor.capture_dir = "test_captures"
        self.monitor.chat_id = "test123"  # Dummy chat ID for test
        self.monitor.debug = False
        
        # Create test directory
        os.makedirs("test_captures", exist_ok=True)
    
    def clean_text(self, text):
        """Call the actual _clean_response_text method from tools.py"""
        return self.monitor._clean_response_text(text)

def test_with_file(file_path=None):
    """Test the _clean_response_text method with the given file or a default sample"""
    helper = TestHelper()
    
    # Load test data from file if provided
    if file_path and os.path.exists(file_path):
        print(f"Loading test data from: {file_path}")
        with open(file_path, 'r', encoding='utf-8') as f:
            unclean_text = f.read()
    else:
        # Sample problematic text with SVG content that might get truncated
        unclean_text = """
17:T6e64,[V0_FILE]typescriptreact:file="app/page.tsx"
"use client"

import React from 'react'

export default function Page() {
  return (
    <div>
      <svg
        xmlns="http://www.w3.org/2000/svg"
        width="24"
        height="24"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="h-5 w-5"
      >
        <path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4"></path>
        <path d="M9 18c-4.51 2-5-2-7-2"></path>
      </svg>
    </div>
  )
}
f:[["123456",false]]
18:T7f75,[V0_FILE]json:file="data.json"
{
  "users": [
    {
      "id": 1,
      "name": "John Doe", 
      "email": "john@example.com"
    },
    {
      "id": 2,
      "name": "Jane Smith",
      "email": "jane@example.com"
    }
  ]
}
f:["$","$L10",null,{"data":{"chat:id":"el5P5y1GnPy","block:output:initial":{"id":"b_7259OgflloJ","file":"$undefined","result":"$@11"},"@\"chat:sql-exec-provider\",\"el5P5y1GnPy\",":"$@12","@\"blocks-execution-states\",\"el5P5y1GnPy\",":"$Q13","@\"block:forked-from\",\"el5P5y1GnPy\",":"$Q14","@\"block:template-ids\",\"el5P5y1GnPy\",":"$Q15","@\"block:createdAt\",\"el5P5y1GnPy\",":"$Q16","@\"chat:drafts\",\"el5P5y1GnPy\",":null,"@\"chat:state\",\"el5P5y1GnPy\",":{"messages":[{"content":"create a landing page","role":"user","id":"k6UG5eFrLfZJ5YgiLaaghUJp9EL7Xt0y","attachments":[],"parentId":"$undefined","type":"message","authorId":"F3f4fityOYT2oUhvE1nD60IU","createdAt":"$D2025-03-22T05:24:35.423Z"},{"content":[[0,[["Thinking",{"closed":true,"chars":488},["p",{},["text",{},"Let me plan out a landing page with a clean, modern design. I'll create a structure that includes:"]],["ol",{"start":1},["li",{"index":1},["text",{},"Header with navigation"]],["li",{"index":2},["text",{},"Hero section with a compelling headline and call-to-action"]],["li",{"index":3},["text",{},"Features section to highlight key benefits"]],["li",{"index":4},["text",{},"Testimonials or
"""
    
    # Clean the text
    print("\n--- UNCLEAN TEXT ---")
    print(unclean_text[:500] + "..." if len(unclean_text) > 500 else unclean_text)
    print("\n--- CLEANING ---")
    clean_text = helper.clean_text(unclean_text)
    print("\n--- CLEAN TEXT ---")
    print(clean_text[:500] + "..." if clean_text and len(clean_text) > 500 else clean_text)
    
    # Save results to files for comparison
    timestamp = int(time.time())
    with open(f"test_captures/unclean_{timestamp}.txt", "w", encoding="utf-8") as f:
        f.write(unclean_text)
    
    if clean_text:
        with open(f"test_captures/clean_{timestamp}.txt", "w", encoding="utf-8") as f:
            f.write(clean_text)
        print(f"\nSaved results to test_captures/unclean_{timestamp}.txt and test_captures/clean_{timestamp}.txt")
    
    # Check for SVG and JSON content preservation
    if clean_text:
        svg_preserved = "stroke=\"currentColor\"" in clean_text and "</path>" in clean_text
        json_preserved = "\"users\":" in clean_text and "\"email\":" in clean_text
        garbage_removed = not "f:[\"$\",\"$L10\",null," in clean_text
        
        print(f"\nSVG content preserved: {svg_preserved}")
        print(f"JSON content preserved: {json_preserved}")
        print(f"Garbage removed: {garbage_removed}")
        
        if svg_preserved and json_preserved and garbage_removed:
            print("\n✅ TEST PASSED: Both SVG and JSON content were preserved correctly and garbage was removed")
        else:
            print("\n❌ TEST FAILED: Some content was not handled correctly")
            print("\nTo fix this, we need to update the _clean_response_text function in tools.py")

if __name__ == "__main__":
    # Use the first command-line argument as the file path if provided
    file_path = sys.argv[1] if len(sys.argv) > 1 else None
    test_with_file(file_path) 