import os
from flask import Flask, render_template, redirect, request, session, url_for
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
app.secret_key = os.getenv('SECRET_KEY')

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
    user = session.get('user', {'username': 'Guest'})
    return render_template('dashboard.html', user=user)

@app.before_request
def before_request():
    if not session.get('user') and request.endpoint not in ['login', 'static']:
        return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        session['user'] = {'username': username}
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7001)
