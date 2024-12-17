# app/routes/process_routes.py
from flask import Blueprint, jsonify, request, render_template
import subprocess, psutil
from db import db
from models.process import Process

process_routes = Blueprint('process', __name__)

@process_routes.route('/create', methods=['GET', 'POST'])
def create_process():
    if request.method == 'POST':
        command = request.form.get('command')
        print(request.form)
        if not command:
            return render_template('create_process.html', error="Command is required")
        try:
            
            return render_template('create_process.html', success=f"Process '{command}' started with PID {process.pid}")
        except Exception as e:
            return render_template('create_process.html', error=str(e))
    return render_template('create_process.html')
