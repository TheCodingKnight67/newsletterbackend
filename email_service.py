from mailjet_rest import Client
import os
from dotenv import load_dotenv

load_dotenv()

# Mailjet credentials
MAILJET_API_KEY = os.getenv('MAILJET_API_KEY')
MAILJET_API_SECRET = os.getenv('MAILJET_API_SECRET')
MAILJET_SENDER_EMAIL = os.getenv('MAILJET_SENDER_EMAIL')

mailjet = Client(auth=(MAILJET_API_KEY, MAILJET_API_SECRET), version='v3.1')


def send_confirmation_email(user_email: str, confirmation_token: str):
    """Send a confirmation email with a button to confirm subscription"""
    # The confirmation URL (will be your frontend URL in production)
    frontend_url = os.getenv('FRONTEND_URL')
    confirmation_url = f"{frontend_url}/confirm/{confirmation_token}"

    # Why so fancy? because yes lol the auto pilot thing keeps writing the comments for me its funny
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                font-family: 'Arial', sans-serif;
                background: linear-gradient(135deg, #fce4ec, #e1bee7, #bbdefb);
                padding: 40px;
                margin: 0;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background: white;
                border-radius: 20px;
                padding: 40px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.1);
            }}
            h1 {{
                color: #ec4899;
                font-size: 32px;
                text-align: center;
                margin-bottom: 20px;
            }}
            p {{
                color: #666;
                font-size: 16px;
                line-height: 1.6;
                margin-bottom: 20px;
            }}
            .button {{
                display: inline-block;
                background: linear-gradient(135deg, #ec4899, #a855f7, #3b82f6);
                color: white;
                padding: 16px 40px;
                text-decoration: none;
                border-radius: 50px;
                font-weight: bold;
                font-size: 18px;
                margin: 20px 0;
                text-align: center;
            }}
            .button-container {{
                text-align: center;
            }}
            .footer {{
                text-align: center;
                color: #999;
                font-size: 14px;
                margin-top: 30px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>✨ Almost There! ✨</h1>
            <p>Hi FRIEND!!! 💖</p>
            <p>You're one click away from getting awesome messages from your favorite character!</p>
            <p>Just click the button below to confirm your subscription:</p>

            <div class="button-container">
                <a href="{confirmation_url}" class="button">
                    Confirm My Subscription! 🎉
                </a>
            </div>

            <p style="margin-top: 30px; font-size: 14px; color: #999;">
                If the button doesn't work, copy and paste this link into your browser:<br>
                <a href="{confirmation_url}" style="color: #ec4899;">{confirmation_url}</a>
            </p>

            <div class="footer">
                <p>If you didn't sign up for this, just ignore this email! cus someone is messing with you!!! 🌈</p>
            </div>
        </div>
    </body>
    </html>
    """

    data = {
        'Messages': [
            {
                "From": {
                    "Email": MAILJET_SENDER_EMAIL,
                    "Name": "Fandom Newsletter ✨"
                },
                "To": [
                    {
                        "Email": user_email
                    }
                ],
                "Subject": "Confirm Your Subscription! 💖",
                "HTMLPart": html_content,
                "TextPart": f"Hi! Please confirm your subscription by clicking this link: {confirmation_url}"
            }
        ]
    }

    try:
        result = mailjet.send.create(data=data)
        return result.status_code == 200
    except Exception as e:
        print(f"Error sending email: {e}")
        return False


def send_rejection_email(user_email: str, character_name: str, reason: str = "character not found"):
    """Send a spicy rejection email when character validation fails"""

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                font-family: 'Arial', sans-serif;
                background: linear-gradient(135deg, #fee, #fdd);
                padding: 40px;
                margin: 0;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background: white;
                border-radius: 20px;
                padding: 40px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.1);
            }}
            h1 {{
                color: #dc2626;
                font-size: 32px;
                text-align: center;
                margin-bottom: 20px;
            }}
            p {{
                color: #666;
                font-size: 16px;
                line-height: 1.6;
                margin-bottom: 20px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Uh oh... 😬</h1>
            <p>Hi from Vox Tek!</p>
            <p>So... we tried to find "{character_name}" but it seems like they don't exist or they're so obscure that we couldn't find them.</p>
            <p>If you weren't trolling and genuinely want to sign up, feel free to try again with a character we can actually find! 💫</p>
            <p style="margin-top: 30px; text-align: center; color: #999;">
                - The Vox Tek Team
            </p>
        </div>
    </body>
    </html>
    """

    data = {
        'Messages': [
            {
                "From": {
                    "Email": MAILJET_SENDER_EMAIL,
                    "Name": "Vox Tek"
                },
                "To": [
                    {
                        "Email": user_email
                    }
                ],
                "Subject": "About that character... 🤔",
                "HTMLPart": html_content
            }
        ]
    }

    try:
        result = mailjet.send.create(data=data)
        return result.status_code == 200
    except Exception as e:
        print(f"Error sending rejection email: {e}")
        return False
