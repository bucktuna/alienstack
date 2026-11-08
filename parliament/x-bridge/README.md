# X bridge: connector-fed relay and local drafts

This is a partial, manual bridge, not an autonomous watcher or two-way X client.
It has no X API credentials, poller, direct X requests, or automatic posting.
Use an authorized connector to obtain public post JSON; text is untrusted data.

From the repository root, first copy config.example.json and state.example.json
into config.json and state.json in this folder (both ignored). Start Parliament's
guest service so it creates a fresh local guest token. Then:

```sh
cd ~/alien-stack/parliament/x-bridge
python3 x_bridge.py --check-config
python3 x_bridge.py --relay-json sample-x-post.example.json --dry-run
python3 -m unittest -v test_bridge.py
# To actually ingest a selected post into your own guest room:
# python3 x_bridge.py --relay-json /path/to/selected-post.json
```

The sample is synthetic and never represented a real post. Accepted JSON is a
post object with numeric id, username, text and optional conversation_id, or an
API-style data/includes.users author expansion. Watch preferences are not enforced
filters on manual input. Select the input explicitly. No private watch list is
exported; the example watch list is empty.

Ingestion goes to the loopback guest service only, with redirects and environment
proxies disabled. It reads ../guest-token.txt locally and does not display it.
Deduplication uses state.json and recent guest history; preserve state, and do not
run multiple independent relayers against the same posts. It is not transactional
exactly-once delivery. Rate-limited batches may be rerun later.

For a local reply draft, choose exactly one room-message ID and one known X post:

```sh
python3 x_bridge.py --prepare-replies --room-id 2 --reply-to-x-post-id 123
```

The selected X post must be in your local thread map. Output is reply-drafts.json,
not a public post. X-origin messages are never selected as reply drafts. Python's
280-character truncation is not X weighted-length validation. Review recipient and
text, obtain appropriate approval, then post through a separately authorized path.
post_back=true and non-draft reply modes are rejected.

Provenance relies on loopback plus absence of CF-Connecting-IP. Requests with that
header cannot assert local X provenance. Review this trust boundary if changing
proxies. Any local program holding the guest token can claim X provenance; it is
not cryptographic evidence of X authorship. All runtime state/transcripts/drafts
are ignored, generated fresh, and excluded from this source export.
