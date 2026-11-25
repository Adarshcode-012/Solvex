# Accepted security risks

## ChromaDB 1.5.9 advisories

These advisories have no fix version reported by `pip-audit`. SolveX uses
`chromadb.PersistentClient` in-process in `backend/memory/brain.py`; it does not
start or connect to a Chroma server. The affected HTTP API and server-side RBAC
paths are therefore not reachable in the current deployment. Keep Chroma
in-process, run one application worker, and do not expose Chroma to the network.

| Advisory | Applies here | Reason and mitigation |
| --- | --- | --- |
| CVE-2026-45829 (GHSA-f4j7-r4q5-qw2c; PYSEC-2026-311) | No, for the current deployment | The issue requires an unauthenticated request to Chroma's collection HTTP endpoint with `trust_remote_code=true`. SolveX uses an in-process `PersistentClient` and does not expose that endpoint. Keep Chroma in-process, use one worker, and do not expose it to the network. |
| CVE-2026-45830 (GHSA-2wm9-hf6c-p5cr; PYSEC-2026-3813) | No, for the current deployment | The issue requires authenticated access to Chroma's multi-tenant HTTP API. SolveX does not run a Chroma server or use its multi-tenant API. Keep Chroma in-process, use one worker, and do not expose it to the network. |
| CVE-2026-45831 (GHSA-xph7-9rjv-w5fr; PYSEC-2026-3815) | No, for the current deployment | The issue is in Chroma's `SimpleRBACAuthorizationProvider`; SolveX does not configure that server-side authorization provider. Keep Chroma in-process, use one worker, and do not expose it to the network. |
| CVE-2026-45833 (GHSA-36p7-vc44-83pf; PYSEC-2026-3814) | No, for the current deployment | The issue requires authenticated collection updates through Chroma's HTTP API and `UPDATE_COLLECTION` permission. SolveX uses local in-process collections and does not expose that API. Keep Chroma in-process, use one worker, and do not expose it to the network. |

## LiteLLM proxy advisory

**GHSA-7hp6-4w63-5g45 / CVE-2026-114612** affects the LiteLLM proxy's
authentication and administration path. The GitHub advisory describes the
affected actor and impact as: “An authenticated user with `internal_user`
privileges can escalate to `proxy_admin` and achieve remote code execution.”
[Source: GitHub Security Advisory](https://github.com/advisories/GHSA-7hp6-4w63-5g45).

This does not apply to SolveX's current use: `backend/utils/ai_router.py` calls
LiteLLM's Python `acompletion` library function and does not run or configure a
LiteLLM proxy server, its internal-user authentication, or its MCP stdio
endpoint. No proxy-specific mitigation is needed; reassess this risk before
deploying a LiteLLM proxy. The library dependency remains at 1.96.2.
