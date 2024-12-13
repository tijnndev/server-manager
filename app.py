import os
import json
from flask import Flask, render_template, jsonify, request, send_from_directory
import psutil, subprocess
from routes.file_manager import file_manager_routes
from routes.service import service_routes
from routes.process import process_routes

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True

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
