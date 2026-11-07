# Deploying the public demo

One server runs the whole stack behind Caddy, which serves HTTPS on one address: the web app at `/`, and the API at `/api`. Demo mode adds one-click sign-in, a role switcher and a guided tour.

**Only for the demo.** The demo accounts share a public password, and anyone with the link can make paid model calls. Use a key with a hard spending limit, and never put real data in it.

## 1. The server

- **Size:** Ubuntu 22.04 or 24.04, 2 vCPU, 4 GB RAM, 30 GB disk.
- **Cloud firewall:** allow only TCP 22, 80 and 443. Docker bypasses the server's own firewall, so the provider's firewall is the one that counts.
- **Docker:** install it with `curl -fsSL https://get.docker.com | sh`. You need Compose 2.24 or later.

## 2. Configure

```bash
git clone https://github.com/AnoushkaSundar/brandlint.git && cd brandlint
cp .env.example .env
```

In `.env`:
- **`JWT_SECRET` and `LITELLM_MASTER_KEY`:** set each to a fresh random value, from `openssl rand -hex 32`.
- **`SITE_HOST`:** add this line. With no domain, use the server's IP in sslip.io form, such as `SITE_HOST=203.0.113.7.sslip.io`.

Create `.env.litellm` holding `ANTHROPIC_API_KEY=...`. Leave Gemini out: its free tier may use the data.

## 3. Start, then load the demo

```bash
C="docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml"
$C up -d --build
$C exec api alembic upgrade head
$C exec api python -m app.auth.seed
$C exec api python -m app.admin.seed --without-rules
$C exec api python /deploy/preload.py
```

The preload ingests and approves the guideline, adds the override history, and reviews the three demo pieces, which takes about a minute. Caddy gets the HTTPS certificate by itself on the first visit.

## 4. Check it

Open `https://<SITE_HOST>/login` and choose **Continue as Creator**. Open the **Demo guide** at the top right, and follow a few steps.

## Reset

To clear what judges changed, delete the database volume, then rerun the four setup commands:

```bash
$C down && docker volume rm brandlint_pgdata && $C up -d
```

## Not included

The local model for restricted data needs a GPU. Without it, restricted pieces keep their code checks, and their AI checks come back UNSURE for a reviewer.
