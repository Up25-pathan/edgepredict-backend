import os
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig, MessageType
from pydantic import EmailStr
from typing import List
from dotenv import load_dotenv

load_dotenv()

# Configuration from .env file
conf = ConnectionConfig(
    MAIL_USERNAME = os.getenv("MAIL_USERNAME"),
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD"),
    MAIL_FROM = os.getenv("MAIL_FROM"),
    MAIL_PORT = int(os.getenv("MAIL_PORT", 587)),
    MAIL_SERVER = os.getenv("MAIL_SERVER"),
    MAIL_STARTTLS = True,
    MAIL_SSL_TLS = False,
    USE_CREDENTIALS = True,
    VALIDATE_CERTS = True
)

fm = FastMail(conf)

async def send_password_reset_email(recipient_email: EmailStr, reset_token: str):
    """
    Sends a password reset email to the user.
    """
    
    # This URL should point to your *frontend's* reset page
    reset_url = f"http://localhost:3000/reset-password?token={reset_token}"

    html_content = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6;">
        <div style="max-width: 600px; margin: 20px auto; padding: 20px; border: 1px solid #ddd; border-radius: 8px;">
            <h2 style="color: #333;">Password Reset Request</h2>
            <p>You are receiving this email because you (or someone else) requested a password reset for your EdgePredict account.</p>
            <p>Please click the button below to set a new password:</p>
            <p style="text-align: center; margin: 30px 0;">
                <a href="{reset_url}" style="background-color: #6366f1; color: #ffffff; padding: 12px 20px; text-decoration: none; border-radius: 5px; font-weight: bold;">
                    Reset Your Password
                </a>
            </p>
            <p>If you did not request this, please ignore this email. This link will expire in 1 hour.</p>
            <hr style="border: 0; border-top: 1px solid #eee;">
            <p style="font-size: 0.9em; color: #777;">EdgePredict Simulation Platform</p>
        </div>
    </body>
    </html>
    """

    message = MessageSchema(
        subject="Your EdgePredict Password Reset Link",
        recipients=[recipient_email],
        body=html_content,
        subtype=MessageType.html
    )

    try:
        await fm.send_message(message)
        print(f"Password reset email sent to {recipient_email}")
    except Exception as e:
        print(f"Failed to send email: {e}")
        # In a real app, you'd have more robust error logging here
        raise RuntimeError("Failed to send password reset email.")