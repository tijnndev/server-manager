from flask import Blueprint, render_template, request, redirect, flash, jsonify
import subprocess
from decorators import owner_or_subuser_required
from utils import find_process_by_name

email_routes = Blueprint('email', __name__)


@email_routes.route('<name>', methods=['GET', 'POST'])
@owner_or_subuser_required()
def email(name):
    process = find_process_by_name(name)
    users = []

    if request.method == 'POST':
        action = request.form.get('action')
        email = request.form.get('email')
        password = request.form.get('password')

        if not email or not password:
            flash("Email and password are required.", "danger")
            return render_template("email/index.html", process=process, users=users)

        if action == "create":
            result = subprocess.run(
                ["docker", "exec", "mailserver", "setup", "email", "add", email, password],
                capture_output=True,
                text=True, check=False
            ) 
        elif action == "delete":
            result = subprocess.run(
                ["docker", "exec", "mailserver", "setup", "email", "del", "-y", email],
                capture_output=True,
                text=True, check=False
            )
        else:
            flash("Invalid action.", "danger")
            return render_template("email/index.html", process=process, users=users)

        if result.returncode == 0:
            flash(f"{action.title()} successful for {email}", "success")
        else:
            flash(f"{action.title()} failed: {result.stderr}", "danger")

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

    return render_template("email/index.html", process=process, users=users)


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
