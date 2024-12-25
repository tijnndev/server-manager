import os
from flask import Flask, render_template, redirect, request, session, url_for
from flask_dance.contrib.discord import discord, make_discord_blueprint
from routes.file_manager import file_manager_routes
from routes.service import service_routes
from flask_migrate import Migrate
from routes.process import process_routes
from db import db
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URI')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Add Discord OAuth configuration
app.secret_key = os.getenv('SECRET_KEY')  # This should be in .env
app.config['DISCORD_OAUTH_CLIENT_ID'] = os.getenv('DISCORD_CLIENT_ID')
app.config['DISCORD_OAUTH_CLIENT_SECRET'] = os.getenv('DISCORD_CLIENT_SECRET')
app.config['DISCORD_OAUTH_REDIRECT_URI'] = os.getenv('DISCORD_REDIRECT_URI')

# Initialize OAuth with Discord
discord_bp = make_discord_blueprint(scope='identify')
app.register_blueprint(discord_bp, url_prefix='/discord_login')

db.init_app(app)
migrate = Migrate(app, db)

with app.app_context():
    db.create_all()

BASE_DIR = os.path.dirname(__file__)
ACTIVE_SERVERS_DIR = os.path.join(BASE_DIR, 'active-servers')
SERVICES_DIRECTORY = 'active-servers'

app.register_blueprint(process_routes, url_prefix='/process')
app.register_blueprint(service_routes, url_prefix='/services')
app.register_blueprint(file_manager_routes, url_prefix='/files')

## WEB
@app.route('/')
def dashboard():
    if not discord.authorized:
        return redirect(url_for('discord.login'))
    user = discord.get('users/@me').json()
    return render_template('dashboard.html', user=user)

@app.before_request
def before_request():
    if not discord.authorized and not request.endpoint.startswith('discord'):
        return redirect(url_for('discord.login'))

@app.route('/callback')
def discord_callback():
    if discord.authorized:
        user = discord.get('users/@me').json()
        session['discord_user'] = user
        return redirect(url_for('dashboard'))
    else:
        return redirect(url_for('discord.login'))
    
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7001)
