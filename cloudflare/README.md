# Optional named tunnel

Install cloudflared from its official distribution, then on **your own machine**:

```bash
cloudflared tunnel login
cloudflared tunnel create alien-stack
cloudflared tunnel route dns alien-stack oracle.example.com
cloudflared tunnel route dns alien-stack parliament.example.com
cloudflared tunnel route dns alien-stack sentinel.example.com
```

Replace example.com with a domain in your account. The interactive login requires
your authorization. Copy config.example.yml to a private local config, fill in the
new tunnel UUID and absolute credentials path, then validate and run:

```bash
cloudflared tunnel --config /path/to/private-config.yml ingress validate
cloudflared tunnel --config /path/to/private-config.yml run alien-stack
```

Do not copy someone else's tunnel ID, certificate, or credentials. cert.pem and
credentials JSON belong outside the checkout with restrictive permissions. This
repo contains no real DNS record, account ID, tunnel UUID, or guest link.

Parliament's bearer guest path must be generated locally, not placed in this
config. Sentinel requires its own login. Consider Cloudflare Access/WAF on the
public Oracle and Parliament services; rate limiting alone is not authentication.
Keep Ollama, the private board, admin endpoints and any image backend off ingress.
The catch-all returns 404; removing ingress is not the same as deleting DNS.

Reference: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/create-local-tunnel/
