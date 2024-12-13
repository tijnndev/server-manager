# app/routes/process_routes.py
from flask import Blueprint, jsonify, request, render_template
import subprocess, psutil

process_routes = Blueprint('process', __name__)

@process_routes.route('/create', methods=['GET', 'POST'])
def create_process():
    if request.method == 'POST':
        command = request.form.get('command')
        if not command:
            return render_template('create_process.html', error="Command is required")
        try:
            process = subprocess.Popen(command.split(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return render_template('create_process.html', success=f"Process '{command}' started with PID {process.pid}")
        except Exception as e:
            return render_template('create_process.html', error=str(e))
    return render_template('create_process.html')
