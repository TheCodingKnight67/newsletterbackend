# Production rollout: Supabase + Render + Vercel

The API and autonomous worker deploy from this backend repository as separate Render services. They share your existing Supabase database. The frontend deploys from the frontend repository to Vercel. No additional MCP server is needed for automatic Mailjet delivery: the worker already owns research, generation, and delivery. A separate existing MCP service can share this backend code, but its source/entrypoint is required before packaging it. The outbound MCP adapter supports a separately deployed Streamable HTTP service or a stdio server bundled into the worker image.

## 1. Preserve and protect the existing database

Back up Supabase before rollout. Keep the existing subscriber table; do not create a replacement Supabase project or point production at a local SQLite database. In Supabase's **Connect** panel, choose the direct connection or **Session pooler** URI on port **5432**. Avoid transaction pooling on port 6543 because the worker uses a session advisory lock. See [Supabase connection options](https://supabase.com/docs/guides/database/connecting-to-postgres).

Web/worker startup applies additive schema setup transactionally under a database lock, so a first push can start without a separately configured migration hook. The database connection must belong to a backend role with table ownership/BYPASSRLS privileges, such as the database owner, and must stay server-side. `init-db` adds app tables and enables row-level security on the app tables, revoking public/anon/authenticated table access. No frontend Supabase client is used by this application. Existing subscribers are preserved. If other applications directly access these same tables with browser roles, review those integrations before applying these permission changes.

## 2. Shared Render environment

Create the `newsletter-production` environment group referenced by `render.production.yaml` and attach it to the API and worker. Use the dashboard for secret values:

```dotenv
ENVIRONMENT=production
ADMIN_ENDPOINTS_ENABLED=false
PROD_DATABASE_URL=your-existing-supabase-session-or-direct-connection-uri
FRONTEND_URL=https://mailfromfandem.com
CORS_ORIGINS=https://mailfromfandem.com,https://newsfrontend-seven.vercel.app
ANTHROPIC_API_KEY=your-private-key
ANTHROPIC_MODEL=claude-sonnet-4-6
EMAIL_TRANSPORT=mailjet
MAILJET_API_KEY=your-private-public-key
MAILJET_API_SECRET=your-private-secret-key
MAILJET_SENDER_EMAIL=your-verified-sender@example.com
AUTOMATION_MODE=send
SCHEDULER_ENABLED=false
SCHEDULE_TIMEZONE=Europe/London
MONTHLY_BUDGET_USD=5.00
REQUEST_BUDGET_USD=0.50
PYTHONUNBUFFERED=1
```

Choose budgets appropriate to your confirmed subscriber count. These are estimated API costs, not guaranteed billing limits; configure Anthropic account spending controls too. Render automatically enables production protections, even if `ENVIRONMENT` has not been set yet. Recurring scheduling defaults to paused on Render. No `ADMIN_API_TOKEN` is required in production because **all admin routes return 404 even with a valid token**. OpenAPI/docs are also disabled there. The worker still operates independently of admin HTTP routes. Use the operator CLI from a trusted terminal for campaign and recovery operations.

Render services use the backend repository root, with `pip install -r requirements.txt` as build command. The API runs `python app.py`; the worker runs `python automation_worker.py`. `render.production.yaml` includes the web health path `/health`, a pre-deploy `init-db`, and worker shutdown grace time. Render pre-deploy commands require a paid service; if your existing API service lacks that feature, remove that field and run `python manage_production.py init-db` manually against Supabase before the first startup. A continuously running worker also adds hosting costs. Review these choices in the dashboard before creating services. See [Render worker documentation](https://render.com/docs/background-workers).

Keep **one worker instance**. During a worker redeploy the old worker finishes its current job; the new one may restart while waiting for the advisory lock. Do not bypass that lock. Configure trusted proxy addresses for the API if needed so public submission rate limits see the intended client IP, rather than a shared proxy address.

## 3. Frontend on Vercel

Set `REACT_APP_API_URL=https://mailfromfandem.onrender.com`, plus the existing display-name environment variables. Build with `npm run build` and publish `build`. The production bundle omits the admin studio route and its code. `vercel.json` preserves client-side confirmation and unsubscribe routes. Set `FRONTEND_URL` on Render to this exact HTTPS origin, then restart/redeploy the backend services.

The local development server retains `/automation` for experiments against a local database. Production admin endpoints cannot be re-enabled by supplying a token or toggling `ADMIN_ENDPOINTS_ENABLED=true`.

## 4. One-time update announcement for existing subscribers

Keep the recurring scheduler **off** throughout preparation. Run these operator commands against the production database using the same server environment, from `newsbackend` or a Render shell:

```shell
python manage_production.py init-db
python manage_production.py prepare-announcement
python manage_production.py announcement-status
```

Preparation snapshots **one message per confirmed email address** with a daily/weekly/monthly subscription, using that person's oldest confirmed character subscription. It excludes unconfirmed users and legacy `now` test subscriptions. The fixed campaign ID is `automatic-delivery-v1`: rerunning preparation does not add recipients or create duplicates. It also seeds schedules for all existing recurring subscriptions to avoid sending a flood of welcome emails when scheduling is enabled.

The worker generates character-styled **previews**, even though global send mode is enabled. Content explains that VOX TECH now sends automatically on the person's existing selected schedule, with a playful reference to the “annoying software dev” no longer manually sending messages. It does not promise round-the-clock email or change subscription frequencies. Saved Markdown character profiles are reused; missing characters incur the usual one-time lookup. All announcement jobs retain normal spending controls and unsubscribe checks.

Review generated previews before release:

```shell
python manage_production.py export-previews --directory review
```

The ignored review directory contains private HTML files named by job ID. Review locally or download it from your trusted server shell; do not publish it as a public frontend asset. Check `announcement-status` for failures and budget-blocked jobs. Fix configuration or budgets, then retry only generation:

```shell
python manage_production.py retry-generation --job JOB_ID
```

If research failed and a reviewed profile is needed, import it through the CLI because production admin HTTP routes are disabled:

```shell
python manage_production.py import-profile --character "Gojo Satoru" --series "Jujutsu Kaisen" --file path/to/reviewed-profile.md
```

When every active announcement is a completed preview, release the saved content:

```shell
python manage_production.py release-announcement
python manage_production.py announcement-status
```

Release is idempotent, does not regenerate content, and rechecks subscription consent. Ambiguous sends remain `delivery_unknown`; inspect Mailjet before any deliberate new request. Re-running campaign commands does not resend them. Do not change the campaign ID to work around failures.

After checking announcement delivery, set `SCHEDULER_ENABLED=true` on the shared environment and restart the worker. Existing recipients resume on their selected schedules. Newly confirmed subscriptions receive the normal welcome and recurring messages. The removed `now` option cannot be submitted, is ignored for scheduling, and pending old immediate test jobs are cancelled during worker recovery.

## 5. Verify the deployed system

- `/health` returns 200 only while the API can query the database.
- `/health/worker` returns 200 while the worker heartbeat is current, otherwise 503. Monitor this separately; it is not the API's own deploy health check.
- `/api/admin/automation/jobs`, `/api/admin/all-users`, `/api/users`, and `/api/testemail` return 404 in production, regardless of token.
- Check confirmation and unsubscribe links using your own address, then verify Mailjet delivery and mobile/desktop rendering.
- Verify deployment-specific PostgreSQL locking, RLS access, restart behavior, budget blocking, and alerting before treating the rollout as verified.

Local automated tests cover the application logic with SQLite/fake providers. They do not verify the live Supabase project, Render/Vercel account settings, or the missing external MCP implementation. No live deployment or production subscriber notification has been performed by these repository changes.
