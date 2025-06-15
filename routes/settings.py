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

        local_changes = subprocess.check_output(['git', 'status', '--porcelain']).decode('utf-8').strip()
        behind_output = subprocess.check_output(['git', 'rev-list', '--left-right', '--count', 'HEAD...@{u}']).decode('utf-8').strip()
        behind_count = int(behind_output.split()[1])

        if local_changes and behind_count > 0:
            status_msg = "You have local changes and updates are available."
            update_available = True
        elif behind_count > 0:
            status_msg = "New version available. You're behind the remote."
            update_available = True
        elif local_changes:
            status_msg = "You have uncommitted local changes."
            update_available = False
        else:
            status_msg = "You're up to date!"
            update_available = False

        return jsonify({
            "status": status_msg,
            "update_available": update_available
        })

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
