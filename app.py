import os
from flask import Flask, render_template
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
    return render_template('dashboard.html')

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8001)