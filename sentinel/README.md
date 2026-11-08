# Sentinel layer

This is a configuration/persona layer, **not an Open WebUI fork**. Open WebUI must
be installed separately. WEBUI_NAME sets Sentinel as the custom label; upstream
may retain an Open WebUI credit/suffix in the UI. There is no patched branding bundle.

The only exported standalone model prompt is qwen14b-english.Modelfile (English
language instruction). persona.EXAMPLE.md is explicitly new example content, not
an export of the deployed persona. No database, chat, account, or API credential
is included or was read to obtain the persona.

1. Install Open WebUI in .venv, as described in the root README.
2. Copy sentinel.env.example to sentinel.env, set the URL and exact CORS origin.
3. Start locally with that env before exposing the tunnel. For initial admin
   bootstrap only, temporarily enable signup on loopback, create the admin, then
   turn signup off again. Never bootstrap a public, unauthenticated instance.
4. Optional: `ollama create sentinel-english -f qwen14b-english.Modelfile`.
5. Put your persona in the supported Open WebUI model/settings UI, not its database.

The example disables persistent config so environment values are authoritative;
existing installations may have stored overrides. Automations stay off: this
package adds no scheduled jobs, downtime trigger, or scheduling logic.

Environment reference: https://docs.openwebui.com/reference/env-configuration/
Review version-specific settings and upstream security updates before deploying.
