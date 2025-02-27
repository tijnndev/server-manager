from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib
from flask import jsonify, current_app
import os, subprocess
from docker.errors import NotFound
from models.process import Process


BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__)))
ACTIVE_SERVERS_DIR = os.path.join(BASE_DIR, 'active-servers')

def get_service_status(name):
    service = find_process_by_name(name)
    if not service:
        return {"error": "Service not found"}

    try:
        service_dir = os.path.join(ACTIVE_SERVERS_DIR, name)
        os.chdir(service_dir)

        result = subprocess.run(['docker-compose', 'ps', '-q', name], capture_output=True, text=True, check=True)
        container_id = result.stdout.strip()

        if not container_id:
            return {"service": name, "status": "Exited"}

        result = subprocess.run(['docker', 'inspect', '--format', '{{.State.Status}}', container_id], capture_output=True, text=True)

        if result.returncode != 0:
            return {"error": "Failed to get service status from docker inspect."}

        container_status = result.stdout.strip()

        if container_status == 'running':
            return {"service": name, "status": "Running"}
        else:
            return {"service": name, "status": "Exited"}

    except subprocess.CalledProcessError as e:
        return {"error": f"Failed to get service status: {e.stderr}"}
    except Exception as e:
        return {"error": str(e)}

    
def find_process_by_name(name):
    with current_app.app_context():
        return Process.query.filter_by(name=name).first()

def find_process_by_id(process_id):
    with current_app.app_context():
        return Process.query.get(process_id)

from email import encoders
from email.mime.base import MIMEBase

SMTP_SERVER = os.getenv("MAIL_SERVER", "")
SMTP_PORT = int(os.getenv("MAIL_PORT", "0"))
EMAIL_ADDRESS = os.getenv("MAIL_USERNAME", "")
EMAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")

def send_email(to: str, subject: str, body: str, type: str = 'auth', attachment: str = ""):
    message = MIMEMultipart()
    message["From"] = f"ServerMonitor {type}@tijnn.dev"
    message["To"] = to
    message["Subject"] = subject
    message.attach(MIMEText(body, "html"))

    if attachment:
        part = MIMEBase('application', 'octet-stream')
        with open(attachment, 'rb') as file:
            part.set_payload(file.read())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f'attachment; filename={attachment}')
        message.attach(part)

    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.sendmail(EMAIL_ADDRESS, to, message.as_string())
            return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False
    
import random
import string

def generate_random_string(length: int) -> str:
    """Generates a random string of a specified length."""
    characters = string.ascii_letters + string.digits  # You can add more characters if needed
    return ''.join(random.choice(characters) for _ in range(length))

def generate_reset_email_body(reset_url):
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Password Reset Request</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background-color: #f4f4f4;
                padding: 20px;
                margin: 0;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background-color: #ffffff;
                padding: 20px;
                border-radius: 8px;
                box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
            }}
            h1 {{
                color: #333;
                font-size: 24px;
                margin-bottom: 20px;
            }}
            p {{
                font-size: 16px;
                line-height: 1.5;
                color: #555;
            }}
            .btn {{
                display: inline-block;
                padding: 12px 25px;
                margin-top: 20px;
                background-color: #007bff;
                color: #ffffff;
                text-decoration: none;
                border-radius: 5px;
                font-weight: bold;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Password Reset Request</h1>
            <p>Hello,</p>
            <p>We received a request to reset your password. You can reset your password by clicking the button below:</p>
            <a href="{reset_url}" class="btn">Reset Your Password</a>
            <p>If you did not request a password reset, you can ignore this email.</p>
            <p>Best regards,<br>Your Support Team</p>
        </div>
    </body>
    </html>
    """
