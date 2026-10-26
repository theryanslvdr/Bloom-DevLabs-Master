"""Bloom Labs FastAPI server."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI
from motor.motor_asyncio import AsyncIOMotorClient
from starlette.middleware.cors import CORSMiddleware

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from emailit_client import EmailitClient  # noqa: E402
from openrouter_client import OpenRouterClient  # noqa: E402
from version import RELEASE  # noqa: E402
from paypal_client import PayPalClient  # noqa: E402
from paypal_routes import paypal_admin_router, paypal_router  # noqa: E402
from gym_upgrade_routes import gym_upgrade_router  # noqa: E402
from warm_leads_routes import warm_leads_router, warm_leads_admin_router  # noqa: E402
from company_setup_routes import (  # noqa: E402
    company_setup_router,
    companies_me_router,
    company_invites_router,
)
from paypal_webhooks import paypal_webhook_router  # noqa: E402
from nifty_client import NiftyClient  # noqa: E402
from blog_routes import blog_admin_router, blog_public_router  # noqa: E402
from public_routes import public_router  # noqa: E402
from onboarding_routes import (  # noqa: E402
    onboarding_admin_router,
    onboarding_client_router,
    onboarding_public_router,
)
from leads_routes import (  # noqa: E402
    drip_tick,
    leads_admin_router,
    leads_public_router,
)
from milestone_routes import (  # noqa: E402
    milestone_admin_router,
    milestone_client_router,
    nifty_comment_poll,
    nifty_timeline_refresh,
    nifty_webhook_router,
)
from breezedocs_client import BreezeDocsClient  # noqa: E402
from breezedocs_routes import (  # noqa: E402
    breezedocs_admin_router,
    breezedocs_client_router,
    breezedocs_sync_cron,
)
from companies_routes import (  # noqa: E402
    companies_admin_router,
    contacts_admin_router,
    migrate_clients_to_companies,
)
from support_clearance_routes import (  # noqa: E402
    support_admin_router,
    support_public_router,
    support_client_router,
    backfill_support_uids,
)
from project_brief_routes import (  # noqa: E402
    brief_admin_router,
    brief_client_router,
)
from project_mode_routes import pm_admin_router, pm_client_router  # noqa: E402
from project_files_routes import pf_admin_router, pf_client_router  # noqa: E402
import object_storage  # noqa: E402
from demo_routes import demo_router  # noqa: E402
from public_tour_routes import public_tour_router  # noqa: E402
from contact_routes import (  # noqa: E402
    client_contact_router,
    contact_admin_router,
)
from publitio_routes import (  # noqa: E402
    publitio_admin_router,
    publitio_client_router,
)
from google_drive_routes import (  # noqa: E402
    gdrive_admin_router,
    gdrive_oauth_router,
)
from support_subscription_routes import (  # noqa: E402
    support_sub_client_router,
    support_sub_admin_router,
    seed_support_plans,
    expire_overdue_subscriptions,
)
from brief_contract_routes import brief_contract_router  # noqa: E402
from ab_test_routes import public_ab_router, ab_admin_router  # noqa: E402
from audit_routes import audit_public_router, audit_admin_router  # noqa: E402
from affiliate_routes import (  # noqa: E402
    affiliate_public_router,
    affiliate_me_router,
    affiliate_admin_router,
)
from ab_v2_routes import (  # noqa: E402
    public_v2_router,
    admin_v2_router,
    auto_complete_expired_tests,
)
from nifty_workspaces_routes import nifty_workspaces_router  # noqa: E402
from google_calendar_client import GoogleCalendarClient  # noqa: E402
from google_calendar_routes import (  # noqa: E402
    calendar_admin_router,
    calendar_milestones_router,
    calendar_oauth_router,
)
from blog_extras_routes import blog_extras_router  # noqa: E402
from integrations_admin_routes import integrations_admin_router  # noqa: E402
from seo_routes import seo_router, run_seo_scan  # noqa: E402
from invoice_routes import (  # noqa: E402
    invoice_admin_router,
    invoice_client_router,
    invoice_public_router,
)
from subscription_routes import (  # noqa: E402
    subscription_admin_router,
    subscription_client_router,
)
from client_routes import (  # noqa: E402
    client_admin_router,
    client_auth_router,
    client_portal_router,
)
from integrations import (  # noqa: E402
    notification_router,
    sync_router,
    webhook_router,
)
from routes import (  # noqa: E402
    _generate_and_save_routine,
    _today_str,
    ai_router,
    auth_router,
    authority_router,
    casestudy_router,
    content_router,
    dashboard_router,
    ensure_authority_metric,
    ensure_seed_user,
    ensure_settings,
    metrics_router,
    pipeline_router,
    routine_router,
    settings_router,
    testimonial_router,
    tl_router,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
log = logging.getLogger("server")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ.get("DB_NAME", "bloom_labs")
    # Aggressive timeouts so a slow/unreachable Mongo doesn't hang K8s readiness.
    # Motor defaults serverSelectionTimeoutMS to 30s which exceeds the readiness probe budget.
    client = AsyncIOMotorClient(
        mongo_url,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        socketTimeoutMS=10000,
    )
    db = client[db_name]
    app.state.mongo = client
    app.state.db = db

    # Initialize integration clients
    app.state.openrouter = OpenRouterClient()
    app.state.emailit = EmailitClient()
    app.state.paypal = PayPalClient()
    app.state.paypal.bind_db(db)
    app.state.nifty = NiftyClient()
    app.state.nifty.bind_db(db)
    app.state.breezedocs = BreezeDocsClient()
    app.state.breezedocs.bind_db(db)
    app.state.google_calendar = GoogleCalendarClient()
    app.state.google_calendar.bind_db(db)

    # Init Emergent Object Storage (best-effort — uploads degrade gracefully
    # with a 503 if the EMERGENT_LLM_KEY is missing).
    try:
        object_storage.init_storage()
    except Exception as exc:
        log.warning("Object storage init failed (uploads disabled): %s", exc)

    # Background scheduler — daily 5am routine generation
    scheduler = AsyncIOScheduler(timezone="UTC")

    async def auto_generate_routine() -> None:
        try:
            target_date = _today_str()
            existing = await db.routines.find_one({"date": target_date})
            if existing:
                return
            log.info("5am cron: generating routine for %s", target_date)
            await _generate_and_save_routine(
                db, app.state.openrouter, target_date=target_date, force=False
            )
        except Exception as exc:
            log.exception("Auto-routine cron failed: %s", exc)

    scheduler.add_job(auto_generate_routine, CronTrigger(hour=5, minute=0))

    async def drip_cron() -> None:
        try:
            res = await drip_tick(db, app)
            if res.get("sent", 0) > 0 or res.get("failed", 0) > 0:
                log.info("Drip tick: %s", res)
        except Exception as exc:
            log.exception("Drip cron failed: %s", exc)

    async def nifty_comment_cron() -> None:
        try:
            res = await nifty_comment_poll(app)
            if res.get("polled", 0) > 0:
                log.info("Nifty comment poll: %s", res)
        except Exception as exc:
            log.exception("Nifty comment cron failed: %s", exc)

    async def nifty_timeline_cron() -> None:
        try:
            res = await nifty_timeline_refresh(app)
            if res.get("refreshed", 0) > 0:
                log.info("Nifty timeline refresh: %s", res)
        except Exception as exc:
            log.exception("Nifty timeline cron failed: %s", exc)

    async def breezedocs_sync_cron_wrapper() -> None:
        try:
            res = await breezedocs_sync_cron(app.state.db, app.state.breezedocs)
            if res.get("synced", 0) > 0:
                log.info("BreezeDocs sync: %s", res)
        except Exception as exc:
            log.exception("BreezeDocs sync cron failed: %s", exc)

    async def support_subscription_expiry_cron() -> None:
        try:
            count = await expire_overdue_subscriptions(app.state.db)
            if count:
                log.info("Support subscription expiry: %d row(s) flipped", count)
        except Exception as exc:
            log.exception("Support subscription expiry cron failed: %s", exc)

    async def prototype_drip_cron() -> None:
        try:
            from gym_prototype_drip import prototype_drip_tick

            res = await prototype_drip_tick(app.state.db, app)
            if res.get("sent", 0) > 0 or res.get("failed", 0) > 0 or res.get("skipped", 0) > 0:
                log.info("Prototype drip tick: %s", res)
        except Exception as exc:
            log.exception("Prototype drip cron failed: %s", exc)

    async def company_setup_reminder_cron() -> None:
        try:
            from reactivation_crons import company_setup_reminder_tick

            res = await company_setup_reminder_tick(app.state.db)
            if res.get("sent", 0) > 0 or res.get("failed", 0) > 0:
                log.info("Company setup reminder tick: %s", res)
        except Exception as exc:
            log.exception("Company setup reminder cron failed: %s", exc)

    async def warm_lead_reengagement_cron() -> None:
        try:
            from reactivation_crons import warm_lead_reengagement_tick

            res = await warm_lead_reengagement_tick(app.state.db)
            if res.get("sent", 0) > 0 or res.get("failed", 0) > 0:
                log.info("Warm-lead re-engagement tick: %s", res)
        except Exception as exc:
            log.exception("Warm-lead re-engagement cron failed: %s", exc)

    async def seo_page_scan_cron() -> None:
        try:
            res = await run_seo_scan(app.state.db, app.state.openrouter)
            if res.get("new_urls"):
                log.info("SEO scan: %d new URL(s)", len(res["new_urls"]))
        except Exception as exc:
            log.exception("SEO page-scan cron failed: %s", exc)

    async def ab_v2_expiry_cron() -> None:
        try:
            res = await auto_complete_expired_tests(app.state.db)
            if res.get("completed", 0) > 0:
                log.info("A/B v2 expiry: %s", res)
        except Exception as exc:
            log.exception("A/B v2 expiry cron failed: %s", exc)

    # Hourly drip ticks
    scheduler.add_job(drip_cron, CronTrigger(minute=15))
    # Hourly prototype-buyer drip (offset by 5 min so it doesn't collide with
    # the generic lead-magnet drip)
    scheduler.add_job(prototype_drip_cron, CronTrigger(minute=20))
    # Every 5 min Nifty comment poll
    scheduler.add_job(nifty_comment_cron, CronTrigger(minute="*/5"))
    # Daily 8am Nifty timeline refresh
    scheduler.add_job(nifty_timeline_cron, CronTrigger(hour=8, minute=0))
    # Every 10 min BreezeDocs status sync (no webhooks in their API)
    scheduler.add_job(breezedocs_sync_cron_wrapper, CronTrigger(minute="*/10"))
    # Daily 3am UTC — flip expired bundled support subscriptions to "expired"
    scheduler.add_job(support_subscription_expiry_cron, CronTrigger(hour=3, minute=0))
    # Daily 9am UTC — company-setup wizard reminder for purchasers who haven't completed it
    scheduler.add_job(company_setup_reminder_cron, CronTrigger(hour=9, minute=0))
    # Daily 10am UTC — 48h warm-lead re-engagement
    scheduler.add_job(warm_lead_reengagement_cron, CronTrigger(hour=10, minute=0))
    # Daily 11am UTC — SEO page-diff scan + (optional) OpenRouter enrichment
    scheduler.add_job(seo_page_scan_cron, CronTrigger(hour=11, minute=0))
    # Hourly — auto-complete expired A/B tests (calc winner & notify)
    scheduler.add_job(ab_v2_expiry_cron, CronTrigger(minute=25))

    app.state.scheduler = scheduler

    # Defer slow work (DB seeding + scheduler.start) to a background task so
    # uvicorn can bind the port and answer /health immediately. The deployer's
    # supervisor wrapper kills the container if the port isn't bound within 60s,
    # so the lifespan must yield as quickly as possible. Seeding and scheduler
    # init are best-effort and can complete after the app is already serving.
    async def _warmup() -> None:
        try:
            await ensure_seed_user(db)
            await ensure_settings(db)
            await ensure_authority_metric(db)
            # TTL index on the affiliate rate-limit bucket so it never grows
            # unbounded — rows expire 5 minutes after insertion.
            try:
                await db.affiliate_click_rl.create_index(
                    "ts", expireAfterSeconds=300, name="ttl_5min"
                )
            except Exception as exc:
                log.warning("affiliate_click_rl TTL index init failed: %s", exc)
            # Phase B: seed companies + contacts from legacy clients (idempotent)
            mig_res = await migrate_clients_to_companies(db)
            if mig_res.get("created", 0) > 0:
                log.info("Companies migration: %s", mig_res)
            # Phase C: backfill support UIDs for all companies missing one.
            await backfill_support_uids(db)
            # Phase H (Feb 2026): seed 6 support subscription plans
            try:
                pp = getattr(app.state, "paypal", None)
                await seed_support_plans(db, pp)
            except Exception as exc:
                log.warning("Support plan seed failed: %s", exc)
        except Exception as exc:
            log.exception("Startup seed failed: %s", exc)
        try:
            scheduler.start()
        except Exception as exc:
            log.exception("Scheduler start failed: %s", exc)
        log.info("Bloom Labs API warmup complete")

    warmup_task = asyncio.create_task(_warmup())
    log.info("Bloom Labs API ready at /api")

    try:
        yield
    finally:
        if not warmup_task.done():
            warmup_task.cancel()
        try:
            if scheduler.running:
                scheduler.shutdown(wait=False)
        except Exception:
            pass
        client.close()
        log.info("Bloom Labs API shut down")


app = FastAPI(title="Bloom Labs API", version="1.0.0", lifespan=lifespan)


# Root-level health endpoint outside /api — production K8s readiness probes and
# deployer-managed health checks tend to hit /health without the /api prefix.
@app.get("/health", include_in_schema=False)
async def root_health() -> dict:
    return {"status": "healthy", "release": RELEASE}


# Top-level /api router
api = APIRouter(prefix="/api")


@api.get("/")
async def root() -> dict:
    return {
        "name": "Bloom Labs API",
        "status": "ok",
        "time": datetime.now(timezone.utc).isoformat(),
    }


@api.get("/health")
async def health() -> dict:
    return {"status": "healthy", "release": RELEASE}


# Mount sub-routers under /api
api.include_router(auth_router)
api.include_router(routine_router)
api.include_router(ai_router)
api.include_router(pipeline_router)
api.include_router(metrics_router)
api.include_router(content_router)
api.include_router(casestudy_router)
api.include_router(testimonial_router)
api.include_router(tl_router)
api.include_router(authority_router)
api.include_router(settings_router)
api.include_router(dashboard_router)
api.include_router(webhook_router)
api.include_router(notification_router)
api.include_router(sync_router)
api.include_router(paypal_router)
api.include_router(gym_upgrade_router)
api.include_router(warm_leads_router)
api.include_router(warm_leads_admin_router)
api.include_router(company_setup_router)
api.include_router(companies_me_router)
api.include_router(company_invites_router)
api.include_router(paypal_admin_router)
api.include_router(paypal_webhook_router)
api.include_router(client_auth_router)
api.include_router(client_portal_router)
api.include_router(client_admin_router)
api.include_router(public_router)
api.include_router(blog_extras_router)
api.include_router(integrations_admin_router)
api.include_router(seo_router)
api.include_router(invoice_admin_router)
api.include_router(invoice_client_router)
api.include_router(invoice_public_router)
api.include_router(subscription_admin_router)
api.include_router(subscription_client_router)
api.include_router(blog_public_router)
api.include_router(blog_admin_router)
api.include_router(onboarding_public_router)
api.include_router(onboarding_client_router)
api.include_router(onboarding_admin_router)
api.include_router(leads_public_router)
api.include_router(leads_admin_router)
api.include_router(nifty_webhook_router)
api.include_router(milestone_client_router)
api.include_router(milestone_admin_router)
api.include_router(breezedocs_admin_router)
api.include_router(breezedocs_client_router)
api.include_router(companies_admin_router)
api.include_router(contacts_admin_router)
api.include_router(support_admin_router)
api.include_router(support_public_router)
api.include_router(support_client_router)
api.include_router(brief_admin_router)
api.include_router(brief_client_router)
api.include_router(pm_admin_router)
api.include_router(pm_client_router)
api.include_router(pf_admin_router)
api.include_router(pf_client_router)
api.include_router(demo_router)
api.include_router(public_tour_router)
api.include_router(client_contact_router)
api.include_router(contact_admin_router)
api.include_router(publitio_client_router)
api.include_router(publitio_admin_router)
api.include_router(gdrive_admin_router)
api.include_router(gdrive_oauth_router)
api.include_router(support_sub_client_router)
api.include_router(support_sub_admin_router)
api.include_router(brief_contract_router)
api.include_router(public_ab_router)
api.include_router(ab_admin_router)
api.include_router(public_v2_router)
api.include_router(admin_v2_router)
api.include_router(audit_public_router)
api.include_router(audit_admin_router)
api.include_router(affiliate_public_router)
api.include_router(affiliate_me_router)
api.include_router(affiliate_admin_router)
api.include_router(nifty_workspaces_router)
api.include_router(calendar_oauth_router)
api.include_router(calendar_admin_router)
api.include_router(calendar_milestones_router)

app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
