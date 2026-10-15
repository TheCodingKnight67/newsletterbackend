from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sendanemail import send_journal_email
import secrets
import models
import schemas
from database import engine, get_db
import os
from dotenv import load_dotenv

from email_service import send_confirmation_email
from automation_api import router as automation_router, require_admin, limit_submissions
from sqlalchemy.exc import IntegrityError
from contextlib import asynccontextmanager
from production import initialize_database, validate_environment
from sqlalchemy import text
from time_utils import utc_now
from runtime_env import is_production, deployment_revision


load_dotenv()
@asynccontextmanager
async def lifespan(app):
    validate_environment('web')
    initialize_database()
    yield

production_mode = is_production()
app = FastAPI(lifespan=lifespan, docs_url=None if production_mode else '/docs',
              redoc_url=None if production_mode else '/redoc', openapi_url=None if production_mode else '/openapi.json')
app.include_router(automation_router)
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
default_origins = FRONTEND_URL
if production_mode:
    default_origins += ',https://mailfromfandem.com,https://newsfrontend-seven.vercel.app'
CORS_ORIGINS = [origin.strip() for origin in os.getenv('CORS_ORIGINS', default_origins).split(',') if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {"message": "Welcome to the Newsletter API! 💖"}


@app.get('/health')
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text('SELECT 1'))
    except Exception:
        raise HTTPException(503, 'Database unavailable')
    return {'status': 'ok', 'revision': deployment_revision()}


@app.get('/health/worker')
def worker_health(db: Session = Depends(get_db)):
    heartbeat = db.get(models.WorkerHeartbeat, 1)
    max_age = int(os.getenv('WORKER_HEARTBEAT_MAX_AGE_SECONDS', '600'))
    if heartbeat is None or (utc_now() - heartbeat.updated_at).total_seconds() > max_age:
        raise HTTPException(503, 'Worker heartbeat is stale')
    return {'status': 'ok'}


@app.post("/api/subscribe", response_model=schemas.UserResponse)
def subscribe(user_data: schemas.UserSubscribe, request: Request, db: Session = Depends(get_db)):
    limit_submissions(request, user_data.email, db)
    print("🎬 Starting subscription process...")



    print("✅ Email is unique, creating user...")

    # Generate confirmation token
    confirmation_token = secrets.token_urlsafe(32)

    # Create new user
    new_user = models.User(
        email=user_data.email,
        character_name=user_data.character_name,
        character_series=user_data.character_series,
        message_type=user_data.message_type,
        frequency=user_data.frequency,
        daily_time=user_data.daily_time,
        notes=user_data.notes,
        confirmation_token=confirmation_token,
        confirmed=False
    )

    print("💾 Saving to database...")
    db.add(new_user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, detail="This character subscription already exists")
    db.refresh(new_user)
    # DON'T CLOSE THE DB! Remove: db.close()

    print("📧 About to send confirmation email...")

    # Send confirmation email! yipprr
    try:
        email_sent = send_confirmation_email(
            user_email=user_data.email,
            confirmation_token=confirmation_token,
        )
        print(f"✨ Email sent result: {email_sent}")
    except Exception as e:
        print(f"❌ Email error: {e}")
        email_sent = False

    if not email_sent:
        print("⚠️ Warning: Confirmation email failed to send")

    print("🎉 Returning user data...")
    return new_user


@app.get("/api/unsubscribe/{token}")
def unsubscribe(token: str, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.unsubscribe_token == token).first()

    if not user:
        raise HTTPException(status_code=404, detail="Invalid unsubscribe link")

    # Store email for the response
    user_email = user.email
    character = user.character_name

    # Delete the user completely
    db.query(models.EmailJob).filter(models.EmailJob.user_id == user.id, models.EmailJob.status.in_(['queued', 'preview', 'budget_blocked'])).update({'status': 'cancelled'})
    db.query(models.SubscriptionSchedule).filter_by(user_id=user.id).delete()
    db.delete(user)
    db.commit()

    return {
        "message": f"Successfully unsubscribed {user_email} from {character} emails! Sorry to see you go! 💔",
        "email": user_email,
        "character": character
    }

@app.get("/api/confirm/{token}")
def confirm_subscription(token: str, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.confirmation_token == token).first()

    if not user:
        raise HTTPException(status_code=404, detail="Invalid confirmation token")

    if user.confirmed:
        return {"message": "Already confirmed!"}

    user.confirmed = True
    user.unsubscribe_token = secrets.token_urlsafe(32)
    db.commit()

    return {"message": "Subscription confirmed! 🎉"}


@app.post("/api/send-journal")
def send_journal(journal_data: schemas.JournalRequest, request: Request, db: Session = Depends(get_db)):
    limit_submissions(request, journal_data.email, db)
    try:
        success = send_journal_email(journal_data.email, journal_data.journalEntry,
                                     journal_data.style, journal_data.customBackground)
    except Exception:
        raise HTTPException(502, 'Email provider unavailable')
    if not success:
        raise HTTPException(502, 'Email provider did not acknowledge delivery')
    return {"message": "Journal sent successfully! 💌"}


@app.get("/api/users", dependencies=[Depends(require_admin)])
def get_users(db: Session = Depends(get_db)):
    print("users r here")
    users = db.query(models.User).all()
    return users


@app.get("/api/testemail", dependencies=[Depends(require_admin)])
def testemail():
    print("🧪 Testing email service...")
    try:
        from email_service import send_confirmation_email
        print("✅ Import successful")

        result = send_confirmation_email(
            user_email="test-email@example.com", 
            confirmation_token="test-token-123"
        )
        print(f"📧 Email result: {result}")
        return {"success": result}
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return {"error": str(e)}


@app.get("/api/admin/confirmed-user-ids", dependencies=[Depends(require_admin)])
def get_confirmed_user_ids(db: Session = Depends(get_db)):
    """
    Get just the IDs of confirmed users who are ready for emails
    Perfect for looping through!
    """
    users = db.query(models.User.id).filter(models.User.confirmed == True).all()

    # Extract just the IDs from the query result
    user_ids = [user.id for user in users]

    return {
        "total": len(user_ids),
        "user_ids": user_ids
    }


@app.get("/api/admin/all-users", dependencies=[Depends(require_admin)])
def get_all_users(db: Session = Depends(get_db)):
    users = db.query(models.User).filter(models.User.confirmed == True).all()

    user_list = []
    for user in users:
        user_list.append({
            "id": user.id,
            "email": user.email,
            "character_name": user.character_name,
            "character_series": user.character_series,
            "message_type": user.message_type,
            "frequency": user.frequency,
            "daily_time": user.daily_time,
            "notes": user.notes,
            "confirmed": user.confirmed,
            "created_at": user.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "unsubscribe_token": user.unsubscribe_token,
        })

    return {
        "total_users": len(user_list),
        "users": user_list
    }




if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.getenv("PORT", "1000")))
