# Security notes

Guest sessions are not accounts. The IP and guest limits reduce abuse but do not stop it: a person using many IP addresses can still spend your AI credits. The global daily solve cap is the final backstop.

The global cap can be used up by one attacker, so it protects cost, not availability. Users behind one shared IP share the IP limits. Behind a CDN or host proxy, the real client IP needs extra configuration.

Rate-limit settings: `TRUSTED_PROXIES` (comma-separated IPs or CIDRs), `RATE_LIMIT_STORAGE_URI`, `IP_SOLVE_RATE_LIMIT` (default `10/minute`), `IP_SOLVE_DAILY_RATE_LIMIT` (default `100/day`), `GUEST_SOLVE_RATE_LIMIT` (default `5/minute`), `NEW_GUESTS_PER_IP_PER_HOUR` (default `20`), and `GLOBAL_DAILY_SOLVE_CAP` (default `200`). The IP and guest request limits cover `/solve`, `/solve-image`, and `/explain`; the global cap covers solve endpoints.

Admin diagnostics and usage reset use the server-only `ADMIN_TOKEN` (minimum 32 characters), generated with `python -c "import secrets; print(secrets.token_urlsafe(32))"`. Rotate it by replacing the API environment value and restarting the API. Send it only as the `X-Admin-Token` header from an operator-controlled environment; it must never be placed in a frontend `VITE_` variable or shipped frontend file because browser users can inspect those. Admin routes allow 10 requests per minute per IP and are blocked by the public nginx frontend.
