# Automatic character emails

For the Supabase/Render/Vercel production rollout and subscriber update announcement, follow [DEPLOYMENT.md](DEPLOYMENT.md). Production disables all admin endpoints and omits the frontend studio; use the operator CLI there.

The FastAPI app accepts subscriptions; a separate Python worker uses a durable SQL queue to research characters, generate emails with Sonnet 4.6, and deliver through the existing Mailjet integration or a configured MCP email tool. The React admin studio is at `/automation`. Its admin token stays in component memory and is never bundled into the frontend or saved in local storage.

## Run locally

From `newsbackend`:

```powershell
pip install -r requirements.txt
# Merge .env.example into your existing .env; preserve your database and email secrets.
python app.py
```

In another terminal in the same directory:

```powershell
python automation_worker.py
# Or process one queued request:
python automation_worker.py --once
# Or process a bounded batch and exit (Render cron every 30 minutes):
python automation_worker.py --batch --max-jobs 25 --max-seconds 1200
```

The batch exits when idle, after 25 processed jobs, or before starting another job after 20 minutes. It finishes the current job first. Future retries and remaining jobs wait for the next run. Use `render.cron.yaml` for the optional cron service; see [deployment instructions](DEPLOYMENT.md#recommended-scheduled-render-cron-job). Start with `AUTOMATION_MODE=preview` and `SCHEDULER_ENABLED=false` until the announcement has been prepared and reviewed. Cron and continuous workers must not run against the same database at the same time.

From `newsletter`, run `npm start` with `REACT_APP_API_URL=http://localhost:1000`. Set backend `FRONTEND_URL` to the actual React origin (your other service uses port 3001). Open `/automation`, connect with your `ADMIN_API_TOKEN`, and queue a preview. An Anthropic API key with API credits is required; a Claude chat subscription is separate. Preview generation costs API credits, but never sends the character email. Subscription confirmation emails still use Mailjet.

When ready, set `AUTOMATION_MODE=send` on **both API and worker** and restart them. Newly scheduled requests will send automatically; existing completed previews stay previews until you click **Send this preview**. There is no separate deployment or live sending enabled by this change.

## Character memory

Profiles are saved at `characters/<franchise>/<character>-<identity-hash>.md`. Normalized franchise and character names determine the ID, with a hash to avoid punctuation collisions. Case/spacing variations share memory; aliases like `Gojo` versus `Gojo Satoru` require consistent names or manual profile imports.

On first use, Sonnet is given the basic Anthropic web search tool with `max_uses: 1`. The worker requires a completed single search and source URLs before accepting the profile. The Markdown includes research date, model, background, personality, speech guidance, uncertainties, and source URLs. Later generations have no search tools. The database stores the profile too and re-creates the Markdown file after a worker host restart. Keep the worker directory private and writable.

A durable research marker prevents automatic repeat searches after failure or interruption. Use `PUT /api/admin/automation/profiles` with a reviewed `character_name`, `character_series`, and `markdown`, then retry failed generation. Stop the worker first for an interrupted lookup, restart it to mark interrupted research as failed, then import the replacement. Editing the local file alone does not override a database profile; the admin import API does. Existing local files can seed a character that has no database record.

## Schedule and queue

Subscriptions support daily, weekly and monthly schedules. The temporary **Right now** option has been removed. Legacy one-off test subscriptions are ignored by the scheduler and their pending immediate jobs are cancelled on worker recovery.

The worker discovers confirmed subscribers, including existing subscribers, and queues one welcome message. Daily schedules use 08:00 and/or 21:00 Europe/London, configurable in the environment. Weekly messages use the signup weekday at 08:00. Monthly messages use the signup day, clamped to month end, at 08:00. Daylight-saving transitions follow the configured IANA timezone. No per-user timezone is currently collected. Missed slots are coalesced into one message when the worker resumes. Unsubscribe cancels pending/preview jobs; consent is also rechecked before sending.

Jobs use unique dedupe keys and admin requests can supply `Idempotency-Key`. One worker per database is enforced by a PostgreSQL advisory lock or an OS lock for a local SQLite file. Use PostgreSQL in deployment; SQLite API and worker must share the same absolute database file on the same machine. Do not deploy SQLite on ephemeral independent service disks. Tables are added with SQLAlchemy `create_all`; existing user columns are unchanged. Back up your database before deploying.

Retries apply to transient generation failures with backoff. Character research is never automatically repeated. Model timeouts retain the reserved cost because the request may have been billed. A `sending` job is committed before invoking the email provider. If the worker crashes or the provider fails to acknowledge a send, the job becomes `delivery_unknown` and is never automatically replayed. Inspect Mailjet/MCP logs before any deliberate new request. This is duplicate prevention at the cost of possible missed emails, not a guarantee of exactly-once delivery. Mailjet `CustomID` is a tracking identifier, not an idempotency guarantee.

## Limits and observation

Defaults: 1,000 generation output tokens, 1,800 research output tokens, 16,000 initial input tokens, $0.50 estimated request budget, and $5 estimated monthly budget. All are configurable. Initial input is checked with Anthropic token counting before the model call. Research reserves an additional 50,000 input tokens for search results. Usage records capture model, input/output tokens, searches, estimated cost, and unknown charges; jobs record status, attempts, timestamps, and errors.

The budget is an **estimate**, not a guaranteed provider billing ceiling. Search-result input can exceed its reserved allowance; actual returned usage is recorded and the job stops before generation if that happens. A timed-out request's true usage is unknown. Set a provider-side spend limit/credit balance as the final spending control. Costs use configurable rates; change them when changing models. These rates were checked against [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing): Sonnet 4.6 $3/million input tokens, $15/million output tokens, and web search $0.01/search. [Web search documentation](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool) documents `max_uses`.

Authentication is required for automation and existing admin/user-list endpoints through `X-Admin-Token`. Subscription submissions have database-backed hourly IP/address limits. Configure trusted proxy addresses in your server when behind a proxy; do not trust arbitrary forwarded headers. Prompts, research, and personalization are treated as untrusted data; the model has no delivery tools and cannot choose the recipient. Generated content is plain text and HTML-escaped by the delivery adapter. These controls reduce prompt injection risk but cannot guarantee model behavior. The unrelated existing journal endpoint remains a separate feature.

Useful routes (all under `/api/admin/automation`, all require `X-Admin-Token`):

- `GET /status` and `GET /jobs` (latest 50 jobs and usage)
- `POST /jobs`: `{ "email": "you@example.com", "character_name": "Gojo Satoru", "character_series": "Jujutsu Kaisen", "message_type": "uplift", "notes": "I have exams soon", "preview": true }`
- `POST /jobs/{id}/send`: send a completed preview when global sending is enabled
- `POST /jobs/{id}/retry`: retry failed/budget-blocked generation after fixing configuration
- `PUT /profiles`: import a reviewed Markdown profile

## Email design and Mailjet setup

Each new generated email includes a validated character-specific colour palette and font category in the same Sonnet response, with no additional model request or web lookup. Tokens are stored in `email_designs` and rendered into a table-based layout with inline CSS, escaped text, readable contrast, a plain-text alternative, and subscription unsubscribe links. The studio shows the actual HTML in a sandboxed iframe. Existing previews get a default design; Gojo, Vox, and Tanjiro have character-specific fallback palettes. Other existing previews use the general palette until a new generation supplies a custom theme. Email-client appearance can vary; test your own inbox.

Configure these in the ignored `newsbackend/.env`, not `.env.example`:

```dotenv
EMAIL_TRANSPORT=mailjet
MAILJET_API_KEY=your-mailjet-public-api-key
MAILJET_API_SECRET=your-mailjet-secret-api-key
MAILJET_SENDER_EMAIL=your-verified-sender@example.com
```

Use the API key and secret from your Mailjet account and validate the sender address there. The Send API uses both `HTMLPart` and `TextPart`; see [Mailjet's basic email documentation](https://dev.mailjet.com/docs/email-api/send-api-v31/send-basic-email). Restart API and worker after changing credentials. For local sending use `AUTOMATION_MODE=send` in both terminals and leave `SCHEDULER_ENABLED=false` to keep recurring subscriptions paused. New tables are created on restart. Missing delivery configuration fails before the send state, so it can be fixed and retried without regenerating the saved email.

## External MCP service

The supplied `SMTP_*`, `TASK_API_BASE`, and `TASK_API_TOKEN` settings belong to another service whose MCP implementation is absent from this folder. They do not specify how to invoke its email tool. Configure `EMAIL_TRANSPORT=mcp`, `MCP_EMAIL_TOOL`, and either a Streamable HTTP `MCP_SERVER_URL` (optional bearer token) or `MCP_SERVER_COMMAND` plus JSON `MCP_SERVER_ARGS` for stdio. SSE-only servers need an additional adapter. `MCP_EMAIL_FIELDS` maps logical `recipient`, `subject`, `text`, `html`, and optional `idempotency_key` to the server's actual parameter names. Check that server's schema and success semantics before enabling send mode. The adapter invokes only the configured email tool and records its receipt. Until the actual MCP connection and schema are known, this adapter is unverified against your service; use previews or the existing Mailjet transport.

## Deployment and verification

Keep the existing web service and add an always-running background worker with build command `pip install -r requirements.txt` and start command `python automation_worker.py`, rooted at this backend. Both services need the same PostgreSQL URL and automation settings. The worker needs Anthropic credentials and the chosen transport credentials. A separate hosted worker may add hosting charges. No blueprint deployment is performed automatically.

Run offline tests from `newsbackend`:

```powershell
python -m unittest discover -s tests -v
```

Tests use a fresh in-memory SQLite database and fake model/email services; they never connect to your production database, spend credits, or send mail. Test a real preview after configuring the key, then send to your own inbox before enabling automatic subscription delivery.
