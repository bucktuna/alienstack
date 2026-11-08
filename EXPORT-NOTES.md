# Export validation and limitations

This is a sanitized source snapshot, not a runtime deployment. No live source or
service was changed or restarted. No git remote is configured; nothing was pushed.

## Persona provenance

The allowlisted standalone Qwen Modelfile contains only the English-language rule.
No complete Sentinel persona was exported. persona.EXAMPLE.md and Parliament's
bots.example.json are newly labeled examples, not copies of private model/room data.
No application database was opened.

## Talk snapshot

The captured files include recording/hold-to-talk UI, /api/talk submission/status,
per-visitor history, CPU faster-whisper STT, streaming Llama, and sentence audio
rendering. Code wiring appears present; complete runtime/audio testing was not
performed for this export. An active implementation may have newer files.
The original requirements.txt/lock omitted faster-whisper. requirements-talk.txt
adds version 1.2.1, verified installed in the source environment. Use that add-on.
The Talk tab is in /oracle/, not at a separate /talk/ route.

## Validation

- Python AST syntax: all 15 .py files, plus the two Python CLI scripts, passed.
- Shell syntax: five launchers/compiler wrappers passed.
- Browser JavaScript: node --check passed.
- Isolated X bridge tests: 10/11 passed. The source regression test expects a
  non-loopback request to have local provenance, but current code returns public.
  This stale assertion was preserved, not weakened to hide the discrepancy.
- Isolated policy tests: 52/55 passed. Two tests assume the exact private deployed
  personas, and one needs deployment instruction/link files intentionally not
  exported. The example personas are not those fixtures. The suite is retained
  for adaptation to a fresh deployment; do not interpret it as a green CI suite.
- Tests ran against temporary copies with temporary state, not live services.
- Oracle runtime/render/API tests were NOT run (would require downloaded weights
  and might exercise an existing service on its default port).

## Security scan

Gitleaks 8.24.3 found zero credentials after sanitization. Additional checks found
zero private host labels, real deployment domains, private LAN addresses, absolute
personal home paths, known API key prefixes, or matches for the actual live guest
bearer (compared in memory only, never printed or copied). Sensitive-name hits
are code variable names and placeholders, not credential values. A single long
hex/base64-looking string in the upstream model card is its public model SHA256;
it is retained as third-party attribution/integrity documentation, not a secret.

Excluded: app databases/data, credentials, member/passcode files, private links,
transcripts/state, recordings/renders, models/weights, logs, caches, backups,
phone artifacts, image workflows and cryptocurrency node files. The model
weights and dependencies must be installed separately under their own licenses.
