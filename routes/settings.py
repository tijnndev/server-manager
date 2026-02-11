import subprocess
from flask import Blueprint, jsonify, render_template, request, session
from decorators import admin_required, auth_check
from models.user_settings import UserSettings

settings_routes = Blueprint('settings', __name__)

BASE_DIR = "../"


@settings_routes.route("")
@admin_required()
def version_page():
    return render_template("settings/version.html", page_title="Version Control")


@settings_routes.route("/preferences")
@auth_check()
def preferences_page():
    user_id = session.get("user_id")
    user_settings = UserSettings.get_or_create(user_id)
    return render_template("settings/preferences.html", page_title="Preferences", user_settings=user_settings)


@settings_routes.route("/preferences/update", methods=["POST"])
@auth_check()
def update_preferences():
    try:
        user_id = session.get("user_id")
        data = request.get_json()
        
        user_settings = UserSettings.get_or_create(user_id)
        
        # Update all settings that were provided
        user_settings.update_settings(
            remember_filters=data.get("remember_filters"),
            theme=data.get("theme"),
            compact_mode=data.get("compact_mode"),
            console_font_size=data.get("console_font_size"),
            auto_refresh_enabled=data.get("auto_refresh_enabled"),
            auto_refresh_interval=data.get("auto_refresh_interval"),
            notification_sounds=data.get("notification_sounds"),
            show_timestamps=data.get("show_timestamps"),
            console_word_wrap=data.get("console_word_wrap"),
            discord_webhook_url=data.get("discord_webhook_url"),
            discord_enabled=data.get("discord_enabled"),
            discord_notify_crashes=data.get("discord_notify_crashes"),
            discord_notify_power_actions=data.get("discord_notify_power_actions")
        )
        
        return jsonify({"success": True, "message": "Preferences updated successfully"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@settings_routes.route("/preferences/get", methods=["GET"])
@auth_check()
def get_preferences():
    try:
        user_id = session.get("user_id")
        user_settings = UserSettings.get_or_create(user_id)
        return jsonify(user_settings.as_dict())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@settings_routes.route('version/git-status', methods=['POST'])
@admin_required()
def git_status():
    try:
        subprocess.check_output(['git', 'fetch'], stderr=subprocess.STDOUT)

        status_output = subprocess.check_output(['git', 'status', '-u'], stderr=subprocess.STDOUT).decode('utf-8')

        local_changes = subprocess.check_output(['git', 'status', '--porcelain'], stderr=subprocess.STDOUT).decode().strip()
        if not local_changes:
            local_changes = ""

        if "Your branch is behind" in status_output:
            if local_changes != "":
                msg = "You have local changes and updates are available."
            else:
                msg = "New version available. You're behind the remote."
            return jsonify({"status": msg, "update_available": True})

        if local_changes != "":
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
