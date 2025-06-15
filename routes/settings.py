import requests, subprocess
from flask import Blueprint, jsonify, render_template, current_app
from decorators import admin_required

settings_routes = Blueprint('settings', __name__)

BASE_DIR = "../"


@settings_routes.route("")
@admin_required()
def version_page():
    return render_template("settings/version.html", page_title="Version Control")


@settings_routes.route('version/git-status', methods=['POST'])
@admin_required()
def git_status():
    try:
        subprocess.check_output(['git', 'fetch'], stderr=subprocess.STDOUT)

        status_output = subprocess.check_output(['git', 'status', '-u'], stderr=subprocess.STDOUT).decode('utf-8')

        local_changes = subprocess.check_output(['git', 'status', '--porcelain']).decode('utf-8').strip()

        if "Your branch is behind" in status_output:
            if local_changes:
                msg = "You have local changes and updates are available."
            else:
                msg = "New version available. You're behind the remote."
            return jsonify({"status": msg, "update_available": True})

        if local_changes:
            return jsonify({"status": "You have uncommitted local changes.", "update_available": False, "status_output": status_output})

        if "up to date" in status_output:
            return jsonify({"status": "You're up to date!", "update_available": False})

        return jsonify({"status": "Unknown state", "update_available": False})

    except subprocess.CalledProcessError as e:
        return jsonify({'error': e.output.decode('utf-8')}), 500


@settings_routes.route('version/git-pull', methods=['POST'])
@admin_required()
def git_pull():
    try:
        result = subprocess.check_output(['git', 'pull'], stderr=subprocess.STDOUT).decode('utf-8')
        return jsonify({'message': result})
    except subprocess.CalledProcessError as e:
        return jsonify({'message': e.output.decode('utf-8')}), 500
