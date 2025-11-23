from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import secrets
import models
import schemas
from database import engine, get_db
import os
from dotenv import load_dotenv

from email_service import send_confirmation_email


load_dotenv()
models.Base.metadata.create_all(bind=engine)

app = FastAPI()
FRONTEND_URL = os.getenv("FRONTEND_URL")
print(FRONTEND_URL)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {"message": "Welcome to the Newsletter API! 💖"}


@app.post("/api/subscribe", response_model=schemas.UserResponse)
def subscribe(user_data: schemas.UserSubscribe, db: Session = Depends(get_db)):
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
    db.commit()
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
    db.commit()
    user.unsubscribe_token = secrets.token_urlsafe(32)

    return {"message": "Subscription confirmed! 🎉"}


@app.get("/api/users")
def get_users(db: Session = Depends(get_db)):
    print("users r here")
    users = db.query(models.User).all()
    return users


@app.get("/api/testemail")
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


@app.get("/api/admin/all-users")
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
            "created_at": user.created_at.strftime("%Y-%m-%d %H:%M:%S")
        })

    return {
        "total_users": len(user_list),
        "users": user_list
    }




print("BRIGHTER")
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=1000, reload=True)