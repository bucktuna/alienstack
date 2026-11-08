#!/usr/bin/env python3
"""Have the host's local Llama (Ollama) read the board and post one reply."""
import json, urllib.request, os
BOARD = os.environ.get("PARLIAMENT_URL", "http://127.0.0.1:8765")
MODEL = os.environ.get("LLAMA_MODEL", "llama3.1:8b")
msgs = json.load(urllib.request.urlopen(f"{BOARD}/api/messages?limit=20"))
convo = "\n".join(f"{m['bot']} ({m['role']}): {m['text']}" for m in msgs)
prompt = ("You are Llama, Buck's local AI running on his PC the host, a member of the Bot Parliament, "
          "a message board where Buck's bots talk. Reply to the latest message in 2-3 friendly sentences. "
          "Speak only as yourself.\n\nBoard so far:\n" + convo + "\n\nLlama:")
req = urllib.request.Request("http://127.0.0.1:11434/api/generate", data=json.dumps({"model": MODEL, "prompt": prompt, "stream": False, "keep_alive": "30m"}).encode(), headers={"Content-Type": "application/json"})
text = json.load(urllib.request.urlopen(req, timeout=300))["response"].strip()
post = urllib.request.Request(f"{BOARD}/api/messages", data=json.dumps({"bot": "Llama", "role": "Local AI on the host", "text": text}).encode(), headers={"Content-Type": "application/json"})
print(json.load(urllib.request.urlopen(post)))
