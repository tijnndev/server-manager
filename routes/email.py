from flask import Blueprint, render_template, request, jsonify
import subprocess
from decorators import owner_or_subuser_required
from utils import find_process_by_name

email_routes = Blueprint('email', __name__)


@email_routes.route('<name>', methods=['GET'])
@owner_or_subuser_required()
def email(name):
    process = find_process_by_name(name)
    users = []

    list_result = subprocess.run(
        ["docker", "exec", "mailserver", "setup", "email", "list"],
        capture_output=True,
        text=True, check=False
    )

    if list_result.returncode == 0:
        users = []
        for line in list_result.stdout.strip().splitlines():
            parts = line.split()
            if parts and len(parts) > 0:
                email = parts[1]
                if "@" in email:
                    users.append(email)

    return render_template("email/index.html", process=process, users=users, page_title="Email")


@email_routes.route('<name>/create', methods=['POST'])
@owner_or_subuser_required()
def create_email(name):
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    result = subprocess.run(
        ["docker", "exec", "mailserver", "setup", "email", "add", email, password],
        capture_output=True,
        text=True,
        check=False
    )

    if result.returncode == 0:
        return jsonify({"message": f"Email {email} created successfully"}), 200

    return jsonify({"error": result.stderr}), 500


@email_routes.route('<name>/delete', methods=['POST'])
@owner_or_subuser_required()
def delete_email(name):
    email = request.json.get('email')

    if not email:
        return jsonify({"error": "Email is required"}), 400

    result = subprocess.run(
        ["docker", "exec", "mailserver", "setup", "email", "del", email],
        capture_output=True,
        text=True, check=False
    )

    if result.returncode == 0:
        return jsonify({"message": f"Email {email} deleted successfully"}), 200

    return jsonify({"error": result.stderr}), 500


@email_routes.route('<name>/update-password', methods=['POST'])
@owner_or_subuser_required()
def update_email_password(name):
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    result = subprocess.run(
        ["docker", "exec", "mailserver", "setup", "email", "update", email, password],
        capture_output=True,
        text=True,
        check=False
    )

    if result.returncode == 0:
        return jsonify({"message": f"Password updated successfully for {email}"}), 200

    return jsonify({"error": result.stderr}), 500
