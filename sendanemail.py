from mailjet_rest import Client
import os
from datetime import datetime
from dotenv import load_dotenv

from PIL import Image
import io
import base64
from colorsys import rgb_to_hls

load_dotenv()

# Mailjet credentials
MAILJET_API_KEY = os.getenv('MAILJET_API_KEY')
MAILJET_API_SECRET = os.getenv('MAILJET_API_SECRET')
MAILJET_SENDER_EMAIL = os.getenv('MAILJET_SENDER_EMAIL')

mailjet = Client(auth=(MAILJET_API_KEY, MAILJET_API_SECRET), version='v3.1')


def get_average_color(image_data):
    """Get the average/dominant color from an image"""
    try:
        # Decode base64 if it's a data URL
        if 'base64,' in image_data:
            image_data = image_data.split('base64,')[1]

        img_bytes = base64.b64decode(image_data)
        img = Image.open(io.BytesIO(img_bytes))

        # Resize for faster processing
        img = img.resize((100, 100))

        # Get average color
        pixels = list(img.getdata())
        avg_color = tuple(sum(c) // len(pixels) for c in zip(*pixels))

        return avg_color
    except Exception as e:
        print(f"Error analyzing image: {e}")
        return (255, 255, 255)  # Default to white


def get_contrast_color(bg_color):
    """
    Determine if text should be black or white based on background color
    Uses relative luminance formula
    """
    r, g, b = bg_color

    # Calculate relative luminance
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255

    # If background is dark, use white text. If light, use black text
    if luminance > 0.5:
        return '#000000'  # Black text for light backgrounds
    else:
        return '#FFFFFF'  # White text for dark backgrounds


def get_custom_template(journal_entry: str, background_image: str):
    """Custom template with user-uploaded background"""

    # scan the image to determine text color
    avg_color = get_average_color(background_image)
    text_color = get_contrast_color(avg_color)

    # If text is white, add a semi transparent dark overlay for better readability
    # If text is black, add a semi transparent light overlay
    overlay_color = 'rgba(0, 0, 0, 0.5)' if text_color == '#FFFFFF' else 'rgba(255, 255, 255, 0.7)'

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                font-family: 'Arial', sans-serif;
                margin: 0;
                padding: 40px;
                background-image: url('{background_image}');
                background-size: cover;
                background-position: center;
                background-attachment: fixed;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background: {overlay_color};
                padding: 40px;
                border-radius: 20px;
                backdrop-filter: blur(10px);
            }}
            h1 {{
                color: {text_color};
                font-size: 28px;
                text-align: center;
                margin-bottom: 20px;
                text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
            }}
            .content {{
                color: {text_color};
                font-size: 16px;
                line-height: 1.8;
                white-space: pre-wrap;
                padding: 20px;
                border-radius: 10px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🎨 Your Custom Journal 🎨</h1>
            <div class="content">{journal_entry}</div>
        </div>
    </body>
    </html>
    """

def get_plain_template(journal_entry: str):
    """Simple, clean template"""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                font-family: 'Georgia', serif;
                background: #f5f5f5;
                padding: 40px;
                margin: 0;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background: white;
                padding: 40px;
                border: 1px solid #ddd;
            }}
            h1 {{
                color: #333;
                font-size: 24px;
                margin-bottom: 20px;
                border-bottom: 2px solid #333;
                padding-bottom: 10px;
            }}
            .content {{
                color: #444;
                font-size: 16px;
                line-height: 1.8;
                white-space: pre-wrap;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Journal Entry</h1>
            <div class="content">{journal_entry}</div>
        </div>
    </body>
    </html>
    """


def get_medieval_template(journal_entry: str):
    """Medieval/fantasy themed template"""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                font-family: 'Palatino', 'Book Antiqua', serif;
                background: linear-gradient(135deg, #3d2c1f, #5a4636);
                padding: 40px;
                margin: 0;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background: #f4e4c1;
                padding: 40px;
                border: 8px solid #8b6f47;
                border-radius: 5px;
                box-shadow: 0 0 20px rgba(0,0,0,0.5);
            }}
            h1 {{
                color: #5a3e2b;
                font-size: 32px;
                text-align: center;
                margin-bottom: 20px;
                font-family: 'Palatino', serif;
                text-shadow: 2px 2px 4px rgba(0,0,0,0.2);
            }}
            .content {{
                color: #3d2c1f;
                font-size: 16px;
                line-height: 1.8;
                white-space: pre-wrap;
                border-top: 2px solid #8b6f47;
                border-bottom: 2px solid #8b6f47;
                padding: 20px 0;
            }}
            .footer {{
                text-align: center;
                margin-top: 20px;
                font-style: italic;
                color: #5a3e2b;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>⚔️ Chronicle of the Day ⚔️</h1>
            <div class="content">{journal_entry}</div>
            <div class="footer">~ Thus it was written ~</div>
        </div>
    </body>
    </html>
    """


def get_angelic_template(journal_entry: str):
    """Soft, heavenly template"""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                font-family: 'Arial', sans-serif;
                background: linear-gradient(135deg, #e3f2fd, #f3e5f5, #fff9c4);
                padding: 40px;
                margin: 0;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background: rgba(255, 255, 255, 0.95);
                padding: 40px;
                border-radius: 30px;
                box-shadow: 0 10px 40px rgba(150, 150, 255, 0.3);
            }}
            h1 {{
                color: #9c27b0;
                font-size: 28px;
                text-align: center;
                margin-bottom: 20px;
                font-weight: 300;
                letter-spacing: 2px;
            }}
            .content {{
                color: #666;
                font-size: 16px;
                line-height: 2;
                white-space: pre-wrap;
                text-align: center;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>👼 Angelic and Calm 👼</h1>
            <div class="content">{journal_entry}</div>
        </div>
    </body>
    </html>
    """


def get_cozy_template(journal_entry: str):
    """Warm and cozy template"""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                font-family: 'Georgia', serif;
                background: linear-gradient(135deg, #d7ccc8, #bcaaa4);
                padding: 40px;
                margin: 0;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background: #fff8e1;
                padding: 40px;
                border-radius: 20px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            }}
            h1 {{
                color: #6d4c41;
                font-size: 28px;
                text-align: center;
                margin-bottom: 20px;
            }}
            .content {{
                color: #5d4037;
                font-size: 16px;
                line-height: 1.8;
                white-space: pre-wrap;
                background: rgba(255,255,255,0.5);
                padding: 20px;
                border-radius: 10px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>☕ Cozy Thoughts ☕</h1>
            <div class="content">{journal_entry}</div>
        </div>
    </body>
    </html>
    """


def get_cozy_pink_template(journal_entry: str):
    """Pink cozy template"""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                font-family: 'Arial', sans-serif;
                background: linear-gradient(135deg, #fce4ec, #f8bbd0, #f48fb1);
                padding: 40px;
                margin: 0;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background: white;
                padding: 40px;
                border-radius: 25px;
                box-shadow: 0 10px 30px rgba(236, 72, 153, 0.3);
            }}
            h1 {{
                color: #ec4899;
                font-size: 28px;
                text-align: center;
                margin-bottom: 20px;
            }}
            .content {{
                color: #666;
                font-size: 16px;
                line-height: 1.8;
                white-space: pre-wrap;
                background: linear-gradient(135deg, #fce4ec, #fff);
                padding: 20px;
                border-radius: 15px;
                border: 2px solid #f8bbd0;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>💕 Pink Cozy Vibes 💕</h1>
            <div class="content">{journal_entry}</div>
        </div>
    </body>
    </html>
    """


def get_night_cozy_template(journal_entry: str):
    """Dark, nighttime cozy template"""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                font-family: 'Georgia', serif;
                background: linear-gradient(135deg, #1a237e, #283593, #3f51b5);
                padding: 40px;
                margin: 0;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background: #263238;
                padding: 40px;
                border-radius: 20px;
                box-shadow: 0 10px 40px rgba(0,0,0,0.5);
            }}
            h1 {{
                color: #90caf9;
                font-size: 28px;
                text-align: center;
                margin-bottom: 20px;
            }}
            .content {{
                color: #b0bec5;
                font-size: 16px;
                line-height: 1.8;
                white-space: pre-wrap;
                background: rgba(255,255,255,0.05);
                padding: 20px;
                border-radius: 10px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🌙 Night Thoughts and ready to relax and vibe 🌙</h1>
            <div class="content">{journal_entry}</div>
        </div>
    </body>
    </html>
    """


def get_aggressive_template(journal_entry: str):
    """Bold, intense template"""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                font-family: 'Impact', 'Arial Black', sans-serif;
                background: linear-gradient(135deg, #b71c1c, #d32f2f, #f44336);
                padding: 40px;
                margin: 0;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background: #212121;
                padding: 40px;
                border: 4px solid #ff1744;
                box-shadow: 0 0 30px rgba(255, 23, 68, 0.5);
            }}
            h1 {{
                color: #ff1744;
                font-size: 32px;
                text-align: center;
                margin-bottom: 20px;
                text-transform: uppercase;
                letter-spacing: 3px;
            }}
            .content {{
                color: #fff;
                font-size: 16px;
                line-height: 1.8;
                white-space: pre-wrap;
                font-family: 'Arial', sans-serif;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🔥 I will BURN this world to the ground... 🔥</h1>
            <div class="content">{journal_entry}</div>
        </div>
    </body>
    </html>
    """


def get_sad_template(journal_entry: str):
    """Melancholic, gentle template"""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                font-family: 'Georgia', serif;
                background: linear-gradient(135deg, #b0bec5, #90a4ae, #78909c);
                padding: 40px;
                margin: 0;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background: #eceff1;
                padding: 40px;
                border-radius: 15px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.3);
            }}
            h1 {{
                color: #546e7a;
                font-size: 26px;
                text-align: center;
                margin-bottom: 20px;
                font-weight: 300;
            }}
            .content {{
                color: #607d8b;
                font-size: 16px;
                line-height: 2;
                white-space: pre-wrap;
                font-style: italic;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>💙 Sad stuff :( 💙</h1>
            <div class="content">{journal_entry}</div>
        </div>
    </body>
    </html>
    """


def get_super_happy_template(journal_entry: str):
    """Bright, cheerful template"""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                font-family: 'Comic Sans MS', 'Arial', sans-serif;
                background: linear-gradient(135deg, #fff59d, #ffee58, #fdd835);
                padding: 40px;
                margin: 0;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background: white;
                padding: 40px;
                border-radius: 30px;
                border: 5px solid #ff6f00;
                box-shadow: 0 10px 40px rgba(255, 111, 0, 0.3);
            }}
            h1 {{
                color: #ff6f00;
                font-size: 32px;
                text-align: center;
                margin-bottom: 20px;
            }}
            .content {{
                color: #333;
                font-size: 17px;
                line-height: 1.8;
                white-space: pre-wrap;
                background: linear-gradient(135deg, #fff9c4, #fff);
                padding: 20px;
                border-radius: 15px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🌈 AMAZING VIBES!!! 🌈</h1>
            <div class="content">{journal_entry}</div>
        </div>
    </body>
    </html>
    """


def send_journal_email(user_email: str, journal_entry: str, style: str,custom_background: str = None):
    """Send journal entry with the chosen style"""
    
    # Pick the template based on style
    template_map = {
        'plain': get_plain_template,
        'medieval': get_medieval_template,
        'angelic': get_angelic_template,
        'cozy': get_cozy_template,
        'cozy-pink': get_cozy_pink_template,
        'night-cozy': get_night_cozy_template,
        'aggressive': get_aggressive_template,
        'sad': get_sad_template,
        'super-happy': get_super_happy_template,
        'custom': lambda entry: get_custom_template(entry, custom_background)  # NEW
    }
    
    # Get the template function, default to plain if style not found
    template_func = template_map.get(style, get_plain_template)
    html_content = template_func(journal_entry)
    current_date = datetime.now().strftime("%B %d, %Y")  # e.g., "January 15, 2026"
    
    # Subject line based on style with the current date for tracking
    subject_map = {
        'plain': f'Journal Entry - {current_date}',
        'medieval': f'⚔️ Chronicle - {current_date}',
        'angelic': f'👼 Divine Reflections - {current_date}',
        'cozy': f'☕ Cozy Thoughts - {current_date}',
        'cozy-pink': f'💕 Pink Cozy Vibes - {current_date}',
        'night-cozy': f'🌙 Night Thoughts - {current_date}',
        'aggressive': f'🔥 Raw Thoughts - {current_date}',
        'sad': f'💙 Quiet Reflections - {current_date}',
        'super-happy': f'🌈 Amazing Vibes - {current_date}'
    }
    
    subject = subject_map.get(style, 'Your Journal Entry')
    
    data = {
        'Messages': [
            {
                "From": {
                    "Email": MAILJET_SENDER_EMAIL,
                    "Name": "Your Journal ✨"
                },
                "To": [
                    {
                        "Email": user_email
                    }
                ],
                "Subject": subject,
                "HTMLPart": html_content,
                "TextPart": f"Your journal entry:\n\n{journal_entry}"
            }
        ]
    }

    try:
        result = mailjet.send.create(data=data)
        return result.status_code == 200
    except Exception as e:
        print(f"Error sending journal email: {e}")
        return False