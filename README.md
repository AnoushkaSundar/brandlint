# BrandLint

Pre-publication brand governance: every draft is reviewed against an approved rulebook, every finding cites its source, and people make every decision.

Team **anoushkasundar**: Alapan Sen, Anoushka Sundar. Built for Inkloom AI's brand-governance problem statement.

- **Checks:** tone, terminology, messaging, unsupported claims, visual misuse and accessibility, on text, DOCX, PDF, HTML and images.
- **No source, no flag:** a finding must cite a rule or an approved fact. Anything uncited goes to a guideline-gap log, never to the creator.
- **Agents propose, people decide:** nothing is auto-approved or auto-fixed, and no AI can change a rule.
- **Deterministic verdicts:** pass or fail comes from code, or from constrained AI at temperature 0 on a pinned model, cached and replayable.

Design: [`docs/design.md`](docs/design.md) · Contracts: [`docs/contracts.md`](docs/contracts.md) · Demo: [`docs/demo.md`](docs/demo.md) · Timeline: [`docs/timeline.md`](docs/timeline.md) · Project context: [`CLAUDE.md`](CLAUDE.md)

## Run it

You need Docker with Compose. The stack uses about 2 GB of memory once built.

**1. Create your environment file**

```bash
cp .env.example .env
```

In `.env`, set `JWT_SECRET` and `LITELLM_MASTER_KEY` to long random strings. Then set the three mock switches, which are on by default:

```bash
USE_MOCK_ENGINE=false
USE_MOCK_GATEWAY=false
USE_MOCK_MEMORY=false
```

**2. Add the provider keys**

Create `.env.litellm` in the repo root. Only the LiteLLM proxy reads this file, so keys never reach the API or the web app. Both files are git-ignored.

```bash
ANTHROPIC_API_KEY=your-key
GEMINI_API_KEY=your-key   # optional: the second voter on claims
```

Don't put these keys in `.env`, and don't give the LiteLLM service `.env`: if it sees `DATABASE_URL`, LiteLLM changes that database's schema.

**3. Start it and load the demo brand**

```bash
docker compose up --build -d
docker compose exec api alembic upgrade head
docker compose exec api python -m app.auth.seed
docker compose exec api python -m app.admin.seed
```

**4. Open it**

Go to <http://localhost:3000>. The API is at <http://localhost:8000>. Every demo account uses the password `brandlint-demo`, which is for local use only.

| Role | Email |
|---|---|
| Creator | `creator@tarnhollow.example` |
| Reviewer | `reviewer@tarnhollow.example` |
| Manager | `manager@tarnhollow.example` |
| Legal | `legal@tarnhollow.example` |
| Admin | `admin@tarnhollow.example` |

The demo pieces are in [`demo/pieces/`](demo/pieces). Upload one as the creator, then follow [`docs/demo.md`](docs/demo.md).

### Optional: restricted data on a local model

Restricted data never goes to a cloud model. To run it locally:

```bash
docker compose --profile local-llm up -d ollama
docker compose --profile local-llm exec ollama ollama pull llama3.2:1b
```

This needs a capable server: on a laptop CPU, one call took two minutes or more. Without it, or if it's too slow, code checks still run and AI checks come back UNSURE for a reviewer. Restricted text is never sent elsewhere.

## Test it

```bash
docker compose exec api pytest                              # backend tests
docker compose exec api python -m app.engine.evaluation     # eval set, calls the real model
cd web && npx playwright test                               # end-to-end tests
```

## How a review works

1. **Parse:** the draft becomes chunks with stable ids and content hashes.
2. **Tier 0, code:** terms, expired facts, hidden text, required elements and injection patterns. These appear first, in well under a second.
3. **Tier 1, constrained AI:** one verdict per rule, from a fixed enum, with a control question code already knows the answer to. Each verdict is cached with the inputs needed to replay it.
4. **Voting:** high-severity AI findings are checked again from two other angles, and claims also go to a second provider. Any disagreement sends the finding to a reviewer as UNSURE.
5. **Critic:** code removes duplicates and sends uncited findings to the gap log.
6. **Tier 2, generative:** fixes and rule amendments. They never decide pass or fail, and code plus the original specialist check a fix before anyone sees it.

Every model call goes through one gateway. It applies a versioned policy table by data class, replaces protected values and personal data with numbered tokens such as `[PRODUCT_1]`, blocks replies that contain anything the model was never given, and logs the call. Only the LiteLLM proxy holds provider keys.

## Measured results

On the demo blog and LinkedIn post, with real models and mocks off:

| Measure | Result |
|---|---|
| Time to first finding | 0.05 to 0.13 seconds |
| Full blog review | About 12 seconds first time, under 2 seconds from cache |
| Planted issues found | 10 of 10 |
| Injected attacks that got through | 0 of 7 |
| Replay identical | Every AI finding checked on the demo blog, 5 of 5 |

This is a small eval set, and some labels were written after reading real output, so treat these as a demo check rather than a benchmark. See [`eval/README.md`](eval/README.md).

## Known limits

- **Second voter:** it uses Google's free tier, where submitted data may be used to improve their products, so the policy table allows it for public data only. A real deployment needs a paid tier.
- **One main provider:** internal data has no separate zero-retention provider.
- **Precedent matching:** it uses text similarity, because there's no embedding model yet.
- **Graph:** it reads the Postgres edge table. The Neo4j sync wasn't built.
- **Fix attempts:** the count is held in memory, so a restart resets it.
- **Not built:** LiteLLM's guardrail backstops, and repeated vote splits as a governance signal.
- **Hand-labelled:** the eval set covers two demo pieces and three tone rules.

## Stack

Next.js, Tailwind and shadcn/ui · FastAPI, SQLAlchemy and Alembic · LangGraph as a fixed graph · PostgreSQL with pgvector · LiteLLM, Presidio and Ollama · python-docx, PyMuPDF, BeautifulSoup and Tesseract.
