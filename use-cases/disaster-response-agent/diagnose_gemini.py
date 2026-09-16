"""
Standalone Gemini connectivity check - bypasses Agent Kernel entirely so you see the REAL
error from Google/LiteLLM instead of Agent Kernel's generic "Invalid model or resource not
found" wrapper message.

Usage:
    python diagnose_gemini.py
"""

import os

import litellm

litellm._turn_on_debug()  # print the raw HTTP request/response LiteLLM sends to Google

api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    raise SystemExit("GEMINI_API_KEY is not set in this session. Set it and re-run.")

model = f"gemini/{os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash')}"
print(f"Using model: {model}")
print(f"Key prefix: {api_key[:8]}... (length {len(api_key)})\n")

try:
    response = litellm.completion(
        model=model,
        messages=[{"role": "user", "content": "Say hello in one word."}],
        api_key=api_key,
    )
    print("\n SUCCESS:")
    print(response.choices[0].message.content)
except Exception as e:
    print("\n FAILURE - real underlying error:")
    print(f"  Type: {type(e).__name__}")
    print(f"  Message: {e}")
