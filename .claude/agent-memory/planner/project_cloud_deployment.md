---
name: Cloud deployment decision
description: Decision to deploy secondBrain to Oracle Cloud free-tier ARM VPS (not Railway), with reordered 6-phase plan
type: project
---

Cloud deployment plan finalized (2026-04-19). Target: Oracle Cloud free-tier ARM Ampere A1 VM (2 OCPU, 12GB RAM) with Docker Compose, nginx reverse proxy, and Let's Encrypt SSL.

**Why:** Mariano chose self-hosted VPS over Railway for full data sovereignty and $0 cost. Oracle Cloud free tier provides more than enough resources. Multi-device access is the primary goal.

**How to apply:** Phase execution order is 0 (VM provision) -> 4 (containerize+deploy) -> 1 (API key auth) -> 2 (server-side sync) -> 3 (server-side state) -> 5 (CLI packaging+login). Auth uses `sb_live_` prefixed API keys with bcrypt hashing. CLI becomes a thin client with only {server_url, api_key, cached user_id}. All infrastructure files live under `infra/`. Detailed plan at `specs/plan-cloud-deployment.md`.
