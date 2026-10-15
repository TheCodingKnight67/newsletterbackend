"""Offline integration tests: no API credits, production database, or email calls."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from anthropic.types import Usage

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['PROD_DATABASE_URL'] = 'sqlite://'
os.environ['DATABASE_URL'] = 'sqlite://'

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from automation_api import router, limit_submissions
from automation_config import Settings
from automation_delivery import email_parts
from email_design import normalize_theme, stored_theme
from automation_queue import character_id, enqueue, next_delivery, schedule_due, user_payload
from automation_worker import Worker
from database import Base, get_db


class FakeMessages:
    def __init__(self):
        self.searches = 0
        self.generations = 0
        self.failure = None

    def count_tokens(self, **params):
        return SimpleNamespace(input_tokens=500)

    def create(self, **params):
        research = 'tools' in params
        if research:
            self.searches += 1
            assert params['tools'][0]['max_uses'] == 1
            blocks = [{'type': 'text', 'text': '## Background\nA fictional teacher.\n## Personality traits\nConfident.\n## Speech patterns\nPlayful.\n## Writing guidance\nBe encouraging.\n## Uncertainties\nNone.'},
                      {'type': 'web_search_tool_result', 'content': [{'type': 'web_search_result', 'url': 'https://example.com/gojo', 'title': 'Character'}]}]
        else:
            self.generations += 1
            assert 'email' not in json.loads(params['messages'][0]['content'])['request']
            if self.failure:
                raise self.failure
            blocks = [{'type': 'text', 'text': json.dumps({'subject': 'You have got this', 'body': 'Keep going!\n\nYour friends at VOX TECH', 'theme': {'background': '#101020', 'card': '#ffffff', 'text': '#111111', 'accent': '#3858bf', 'font': 'sans'}})}]
        # Real SDK defaults include explicit null cache counters, not just absent keys.
        stats = Usage(input_tokens=600, output_tokens=100).model_dump()
        stats['server_tool_use'] = {'web_search_requests': int(research)}
        raw = {'content': blocks, 'stop_reason': 'end_turn', 'usage': stats}
        return SimpleNamespace(model_dump=lambda: raw)


class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        temp_root = Path(__file__).resolve().parent / '.test-temp'
        temp_root.mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=temp_root)
        self.addCleanup(self.tmp.cleanup)
        self.settings = Settings(characters_dir=Path(self.tmp.name), scheduler=False)
        self.messages = FakeMessages()
        self.sends = []
        self.worker = Worker(self.settings, SimpleNamespace(messages=self.messages),
                             sender=lambda job, url, theme=None: self.sends.append(job.id) or 'receipt')
        self.payload = {'email': 'friend@example.com', 'character_name': 'Gojo Satoru',
                        'character_series': 'Jujutsu Kaisen', 'message_type': 'uplift', 'notes': ''}

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def job(self, mode='preview', key=None):
        return enqueue(self.db, self.payload, mode, key)

    def user(self, **overrides):
        values = dict(email='friend@example.com', character_name='Gojo Satoru', character_series='Jujutsu Kaisen',
                      message_type='uplift', frequency='daily', daily_time='both', confirmed=True,
                      unsubscribe_token='unsubscribe', created_at=datetime(2026, 1, 31, 12))
        values.update(overrides)
        user = models.User(**values)
        self.db.add(user)
        self.db.commit()
        return user

    def test_research_cached_across_requests_and_worker_hosts(self):
        first = self.job()
        self.worker.process(self.db, first)
        self.assertEqual(first.status, 'preview')
        self.assertEqual(self.sends, [])
        profile_path = Path(self.tmp.name) / (character_id('Gojo Satoru', 'Jujutsu Kaisen') + '.md')
        self.assertIn('https://example.com/gojo', profile_path.read_text(encoding='utf-8'))
        profile_path.unlink()
        second = self.job()
        self.worker.process(self.db, second)
        self.assertTrue(profile_path.exists())
        self.assertEqual(self.messages.searches, 1)
        self.assertEqual(self.messages.generations, 2)
        self.assertEqual(self.db.query(models.ModelUsage).count(), 3)

    def test_identity_handles_collisions_case_and_path_traversal(self):
        self.assertEqual(character_id('GOJO  Satoru', 'JUJUTSU KAISEN'), character_id('Gojo Satoru', 'Jujutsu Kaisen'))
        self.assertNotEqual(character_id('A B', 'Series'), character_id('A-B', 'Series'))
        self.assertNotEqual(character_id('Gojo', 'A'), character_id('Gojo', 'B'))
        self.assertNotIn('..', character_id('../../gojo', '../../series'))

    def test_idempotency(self):
        first = self.job(key='same')
        self.assertEqual(first.id, self.job(key='same').id)
        with self.assertRaises(ValueError):
            enqueue(self.db, dict(self.payload, notes='different'), 'preview', 'same')

    def test_budget_blocks_before_billed_call_and_can_retry(self):
        self.settings.request_budget = 0.0001
        job = self.job()
        self.worker.process(self.db, job)
        self.assertEqual(job.status, 'budget_blocked')
        self.assertEqual(self.messages.searches, 0)
        self.assertEqual(self.db.query(models.CharacterProfile).count(), 0)
        self.settings.request_budget = 0.5
        self.worker.process(self.db, job)
        self.assertEqual(job.status, 'preview')

    def test_missing_api_key_has_actionable_error_and_no_lookup_marker(self):
        worker = Worker(self.settings)
        job = self.job()
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': '', 'ANTHROPIC_AUTH_TOKEN': ''}):
            worker.process(self.db, job)
        self.assertEqual(job.status, 'failed')
        self.assertIn('ANTHROPIC_API_KEY', job.error)
        self.assertEqual(self.db.query(models.ModelUsage).count(), 0)
        self.assertEqual(self.db.query(models.CharacterProfile).count(), 0)

    def test_monthly_budget_includes_unknown_reservations(self):
        self.db.add(models.ModelUsage(job_id='old', phase='generation', model=self.settings.model, cost_usd=5, state='unknown'))
        self.db.commit()
        job = self.job()
        self.worker.process(self.db, job)
        self.assertEqual(job.status, 'budget_blocked')
        self.assertEqual(self.messages.searches, 0)

    def test_research_failure_does_not_repeat_lookup(self):
        class Transient(Exception):
            status_code = 503
        original = self.messages.create
        def fail(**params):
            self.messages.searches += 1
            raise Transient()
        self.messages.create = fail
        job = self.job()
        self.worker.process(self.db, job)
        self.assertEqual(job.status, 'failed')
        self.messages.create = original
        self.worker.process(self.db, self.job())
        self.assertEqual(self.messages.searches, 1)
        self.assertEqual(self.db.query(models.ModelUsage).first().state, 'unknown')

    def test_transient_generation_retries_without_research(self):
        class Transient(Exception):
            status_code = 503
        self.messages.failure = Transient()
        job = self.job()
        self.worker.process(self.db, job)
        self.assertEqual(job.status, 'queued')
        self.messages.failure = None
        self.worker.process(self.db, job)
        self.assertEqual(job.status, 'preview')
        self.assertEqual(self.messages.searches, 1)

    def test_send_and_ambiguous_send_are_never_automatically_replayed(self):
        self.settings.mode = 'send'
        job = self.job('send')
        self.worker.process(self.db, job)
        self.assertEqual(job.status, 'sent')
        self.assertFalse(self.worker.tick(self.db))
        ambiguous = self.job('send')
        def lost_ack(job, url, theme=None):
            raise TimeoutError('possibly sent')
        self.worker.sender = lost_ack
        self.worker.process(self.db, ambiguous)
        self.assertEqual(ambiguous.status, 'delivery_unknown')
        self.worker.recover(self.db)
        self.assertFalse(self.worker.tick(self.db))
        self.assertEqual(len(self.sends), 1)

    def test_restart_recovery_and_unsubscribe_cancellation(self):
        user = self.user()
        job = enqueue(self.db, user_payload(user), 'send', user_id=user.id)
        self.db.delete(user)
        self.db.commit()
        self.worker.process(self.db, job)
        self.assertEqual(job.status, 'cancelled')
        interrupted = self.job()
        interrupted.status = 'sending'
        self.db.commit()
        self.worker.recover(self.db)
        self.assertEqual(interrupted.status, 'delivery_unknown')

    def test_scheduling_both_times_dst_and_month_end(self):
        user = self.user()
        self.assertEqual(next_delivery(user, datetime(2026, 7, 1, 6), self.settings), datetime(2026, 7, 1, 7))
        self.assertEqual(next_delivery(user, datetime(2026, 7, 1, 8), self.settings), datetime(2026, 7, 1, 20))
        user.frequency = 'monthly'
        self.assertEqual(next_delivery(user, datetime(2026, 2, 1), self.settings), datetime(2026, 2, 28, 8))
        user.frequency = 'weekly'
        self.assertEqual(next_delivery(user, datetime(2026, 2, 1), self.settings), datetime(2026, 2, 7, 8))

    def test_scheduled_welcome_and_coalesced_due_job(self):
        user = self.user()
        now = datetime(2026, 7, 1, 6)
        schedule_due(self.db, self.settings, now)
        schedule_due(self.db, self.settings, now)
        self.assertEqual(self.db.query(models.EmailJob).count(), 1)
        schedule_due(self.db, self.settings, now + timedelta(days=20))
        self.assertEqual(self.db.query(models.EmailJob).count(), 2)

    def test_removed_immediate_subscriptions_are_rejected_and_not_scheduled(self):
        from schemas import UserSubscribe
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            UserSubscribe(**self.payload, frequency='now')
        self.user(frequency='now')
        self.settings.scheduler = True
        self.assertFalse(self.worker.tick(self.db))
        self.assertEqual(self.db.query(models.EmailJob).count(), 0)
        old_job = self.job(key='immediate:legacy')
        self.worker.recover(self.db)
        self.assertEqual(old_job.status, 'cancelled')

    def test_scheduler_recovers_partial_commit_after_mode_change(self):
        user = self.user()
        key = f'welcome:{user.id}:{user.created_at.isoformat()}'
        enqueue(self.db, user_payload(user), 'preview', key, user.id)
        self.settings.mode = 'send'
        schedule_due(self.db, self.settings, datetime(2026, 7, 1, 6))
        self.assertEqual(self.db.query(models.EmailJob).count(), 1)
        self.assertIsNotNone(self.db.get(models.SubscriptionSchedule, user.id))

    def test_reused_subscription_id_cannot_send_old_job(self):
        user = self.user()
        job = enqueue(self.db, user_payload(user), 'send', user_id=user.id)
        user.created_at = job.created_at + timedelta(seconds=1)
        self.db.commit()
        self.worker.process(self.db, job)
        self.assertEqual(job.status, 'cancelled')
        self.assertEqual(self.messages.searches, 0)

    def test_admin_auth_preview_and_send_gating(self):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: self.db
        client = TestClient(app)
        with patch.dict(os.environ, {'ADMIN_API_TOKEN': 'test-secret', 'AUTOMATION_MODE': 'preview'}):
            self.assertEqual(client.get('/api/admin/automation/jobs').status_code, 401)
            headers = {'X-Admin-Token': 'test-secret', 'Idempotency-Key': 'request1'}
            response = client.post('/api/admin/automation/jobs', headers=headers, json=dict(self.payload, preview=True))
            self.assertEqual(response.status_code, 202, response.text)
            again = client.post('/api/admin/automation/jobs', headers=headers, json=dict(self.payload, preview=True))
            self.assertEqual(response.json()['id'], again.json()['id'])
            self.assertEqual(client.post('/api/admin/automation/jobs', headers=headers, json=dict(self.payload, preview=False)).status_code, 409)
            self.assertEqual(client.post('/api/admin/automation/jobs', headers=headers, json=dict(self.payload, email='invalid')).status_code, 422)

    def test_rate_limit_is_persistent(self):
        request = SimpleNamespace(client=SimpleNamespace(host='127.0.0.1'))
        for _ in range(3):
            limit_submissions(request, 'friend@example.com', self.db)
        with self.assertRaises(Exception) as caught:
            limit_submissions(request, 'friend@example.com', self.db)
        self.assertEqual(caught.exception.status_code, 429)

    def test_email_markup_escapes_generated_text_and_has_unsubscribe(self):
        job = self.job()
        job.body = '<script>bad()</script>'
        text, markup = email_parts(job, 'https://example.com/unsubscribe/token')
        self.assertNotIn('<script>', markup)
        self.assertIn('&lt;script&gt;', markup)
        self.assertIn('Unsubscribe', text)
        self.assertIn('AI-generated', markup)

    def test_generated_design_is_persisted_and_previewed(self):
        job = self.job()
        self.worker.process(self.db, job)
        theme = stored_theme(self.db, job)
        self.assertEqual(theme['accent'], '#3858bf')
        self.assertEqual(theme['font'], 'sans')
        from automation_api import job_view
        self.assertIn('background-color:#101020', job_view(self.db, job)['html_preview'])

    def test_invalid_css_tokens_are_rejected_and_content_is_escaped(self):
        theme = normalize_theme({'accent': 'red; background:url(https://bad.test)', 'font': ['bad'], 'card': '#ffffff', 'text': '#ffffff'}, self.payload)
        self.assertEqual(theme['accent'], '#42baff')
        self.assertEqual(theme['text'], '#000000')
        job = self.job()
        job.subject = '<img src=x onerror=alert(1)>'
        job.body = '<script>bad()</script>'
        _, markup = email_parts(job, theme=theme)
        self.assertNotIn('<script>', markup)
        self.assertNotIn('<img', markup)
        self.assertIn('role="presentation"', markup)
        with self.assertRaises(ValueError):
            email_parts(job, 'javascript:alert(1)')

    def test_missing_mailjet_configuration_is_retryable_before_delivery(self):
        from automation_delivery import deliver
        self.settings.mode = 'send'
        self.worker.sender = deliver
        job = self.job('send')
        with patch.dict(os.environ, {'EMAIL_TRANSPORT': 'mailjet', 'MAILJET_API_KEY': '', 'MAILJET_API_SECRET': '', 'MAILJET_SENDER_EMAIL': ''}):
            self.worker.process(self.db, job)
        self.assertEqual(job.status, 'failed')
        self.assertIn('MAILJET_API_KEY', job.error)
        self.assertIsNotNone(job.body)

    def test_send_preview_transition_reuses_content_and_rejects_duplicate_clicks(self):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: self.db
        client = TestClient(app)
        job = self.job()
        self.worker.process(self.db, job)
        with patch.dict(os.environ, {'ADMIN_API_TOKEN': 'test-secret', 'AUTOMATION_MODE': 'send'}):
            url = f'/api/admin/automation/jobs/{job.id}/send'
            headers = {'X-Admin-Token': 'test-secret'}
            self.assertEqual(client.post(url, headers=headers).status_code, 202)
            self.assertEqual(client.post(url, headers=headers).status_code, 409)
        self.settings.mode = 'send'
        self.worker.process(self.db, job)
        self.assertEqual(job.status, 'sent')
        self.assertEqual(self.messages.generations, 1)

    def test_delivery_unknown_cannot_be_retried_via_api(self):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: self.db
        job = self.job()
        job.status = 'delivery_unknown'
        self.db.commit()
        with patch.dict(os.environ, {'ADMIN_API_TOKEN': 'test-secret'}):
            response = TestClient(app).post(f'/api/admin/automation/jobs/{job.id}/retry', headers={'X-Admin-Token': 'test-secret'})
            self.assertEqual(response.status_code, 409)

    def test_production_admin_endpoints_disabled_even_with_valid_token(self):
        from app import app
        app.dependency_overrides[get_db] = lambda: self.db
        try:
            with patch.dict(os.environ, {'ENVIRONMENT': 'production', 'ADMIN_API_TOKEN': 'test-secret'}):
                client = TestClient(app)
                for path in ['/api/admin/automation/jobs', '/api/admin/all-users', '/api/admin/confirmed-user-ids', '/api/users', '/api/testemail']:
                    response = client.get(path, headers={'X-Admin-Token': 'test-secret'})
                    self.assertEqual(response.status_code, 404, path)
        finally:
            app.dependency_overrides.clear()

    def test_render_detected_as_production_without_environment_variable(self):
        from runtime_env import is_production
        from automation_api import require_admin
        from fastapi import HTTPException
        with patch.dict(os.environ, {'ENVIRONMENT': 'development', 'RENDER': 'true', 'SCHEDULER_ENABLED': ''}):
            self.assertTrue(is_production())
            self.assertFalse(Settings().scheduler)
            with self.assertRaises(HTTPException) as error:
                require_admin('test-secret')
            self.assertEqual(error.exception.status_code, 404)

    def test_campaign_snapshots_unique_confirmed_addresses_and_prevents_welcome_flood(self):
        from manage_production import prepare_announcement, campaign_jobs
        first = self.user()
        self.user(character_name='Vox', unsubscribe_token='second')
        self.user(email='unconfirmed@example.com', confirmed=False, unsubscribe_token='third')
        self.user(email='legacy@example.com', frequency='now', unsubscribe_token='fourth')
        self.assertEqual(prepare_announcement(self.db, self.settings), 1)
        self.user(email='new@example.com', unsubscribe_token='fifth')
        self.assertEqual(prepare_announcement(self.db, self.settings), 1)
        job = campaign_jobs(self.db, 'automatic-delivery-v1').one()
        self.assertEqual(job.user_id, first.id)
        self.assertEqual(json.loads(job.payload)['purpose'], 'automation_update')
        self.assertEqual(job.mode, 'preview')
        self.assertEqual(self.db.query(models.SubscriptionSchedule).count(), 2)

    def test_campaign_release_requires_completed_previews_and_is_idempotent(self):
        from manage_production import prepare_announcement, release_announcement, campaign_jobs
        self.user()
        prepare_announcement(self.db, self.settings)
        self.settings.mode = 'send'
        with self.assertRaises(ValueError):
            release_announcement(self.db, self.settings)
        self.db.rollback()
        job = campaign_jobs(self.db, 'automatic-delivery-v1').one()
        with patch.object(self.messages, 'create', wraps=self.messages.create) as create:
            self.worker.process(self.db, job)
        generation = [call.kwargs for call in create.call_args_list if 'tools' not in call.kwargs][0]
        self.assertIn('annoying software dev', generation['system'])
        self.assertEqual(job.status, 'preview')
        self.assertEqual(release_announcement(self.db, self.settings), 1)
        self.assertEqual(release_announcement(self.db, self.settings), 0)
        self.worker.process(self.db, job)
        self.assertEqual(job.status, 'sent')
        self.assertEqual(self.messages.generations, 1)
        self.assertEqual(len(self.sends), 1)

    def test_campaign_honors_unsubscribe_before_release(self):
        from manage_production import prepare_announcement, release_announcement, campaign_jobs
        user = self.user()
        prepare_announcement(self.db, self.settings)
        job = campaign_jobs(self.db, 'automatic-delivery-v1').one()
        self.worker.process(self.db, job)
        self.db.delete(user)
        self.db.commit()
        self.settings.mode = 'send'
        self.assertEqual(release_announcement(self.db, self.settings), 0)
        self.assertEqual(job.status, 'cancelled')

    def test_worker_heartbeat_and_production_sqlite_rejection(self):
        from production import validate_environment
        self.worker.tick(self.db)
        self.assertIsNotNone(self.db.get(models.WorkerHeartbeat, 1))
        with patch.dict(os.environ, {'ENVIRONMENT': 'production'}):
            with self.assertRaisesRegex(RuntimeError, 'PostgreSQL'):
                validate_environment('worker')

    def test_lost_worker_lock_stops_before_delivery(self):
        self.settings.mode = 'send'
        job = self.job('send')
        def lost_lock():
            raise RuntimeError('Worker lost its database lock')
        self.worker.lock_check = lost_lock
        self.worker.process(self.db, job)
        self.assertEqual(job.status, 'failed')
        self.assertEqual(self.sends, [])

    def test_batch_drains_due_jobs_reuses_profile_and_does_not_resend(self):
        from threading import Event
        from automation_worker import run_jobs
        first, second = self.job('send'), self.job('send')
        self.settings.mode = 'send'
        self.assertEqual(run_jobs(self.worker, self.db, Event(), batch=True), 2)
        self.assertEqual(set(self.sends), {first.id, second.id})
        self.assertEqual(self.messages.searches, 1)
        self.assertEqual(run_jobs(self.worker, self.db, Event(), batch=True), 0)
        self.assertEqual(len(self.sends), 2)

    def test_batch_job_limit_and_future_retry_remain_queued(self):
        from threading import Event
        from automation_worker import run_jobs
        from time_utils import utc_now
        self.job()
        self.job()
        future = self.job()
        future.available_at = utc_now() + timedelta(hours=1)
        self.db.commit()
        self.assertEqual(run_jobs(self.worker, self.db, Event(), batch=True, max_jobs=1), 1)
        self.assertEqual(self.db.query(models.EmailJob).filter_by(status='queued').count(), 2)
        self.assertEqual(run_jobs(self.worker, self.db, Event(), batch=True), 1)
        self.assertEqual(future.status, 'queued')

    def test_batch_time_limit_and_shutdown_finish_current_job(self):
        from threading import Event
        from automation_worker import run_jobs
        from unittest.mock import Mock
        stopping = Event()
        worker = Mock()
        worker.tick.return_value = True
        with patch('automation_worker.time.monotonic', side_effect=[0, 0, 1200]):
            self.assertEqual(run_jobs(worker, self.db, stopping, batch=True), 1)
        worker.tick.assert_called_once()
        worker.tick.reset_mock()
        worker.tick.side_effect = lambda db: stopping.set() or True
        self.assertEqual(run_jobs(worker, self.db, stopping, batch=True), 1)
        worker.tick.assert_called_once()

    def test_batch_tick_failure_is_not_reported_as_success(self):
        from threading import Event
        from automation_worker import run_jobs
        with patch.object(self.worker, 'tick', side_effect=RuntimeError('database failure')):
            with self.assertRaisesRegex(RuntimeError, 'database failure'):
                run_jobs(self.worker, self.db, Event(), batch=True)

    def test_cron_heartbeat_allows_half_hour_between_runs(self):
        from app import worker_health
        from time_utils import utc_now
        from fastapi import HTTPException
        self.db.add(models.WorkerHeartbeat(id=1, updated_at=utc_now() - timedelta(minutes=35)))
        self.db.commit()
        with patch.dict(os.environ, {'WORKER_HEARTBEAT_MAX_AGE_SECONDS': '3600'}):
            self.assertEqual(worker_health(self.db), {'status': 'ok'})
        with patch.dict(os.environ, {'WORKER_HEARTBEAT_MAX_AGE_SECONDS': '600'}):
            with self.assertRaises(HTTPException):
                worker_health(self.db)

    def test_journal_rejects_invalid_recipients_and_external_image_urls(self):
        from schemas import JournalRequest
        from pydantic import ValidationError
        for payload in [dict(email='invalid', journalEntry='hello', style='plain'),
                        dict(email='friend@example.com', journalEntry='hello', style='custom', customBackground='https://example.com/image.png')]:
            with self.assertRaises(ValidationError):
                JournalRequest(**payload)


if __name__ == '__main__':
    unittest.main()
