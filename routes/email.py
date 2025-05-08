from flask import Blueprint, render_template, request, redirect, flash
import subprocess
from decorators import owner_or_subuser_required
from utils import find_process_by_name

email_routes = Blueprint('email', __name__)

@email_routes.route('<name>', methods=['GET', 'POST'])
@owner_or_subuser_required()
def email(name):
    process = find_process_by_name(name)

    if request.method == 'POST':
        action = request.form.get('action')
        email = request.form.get('email')
        password = request.form.get('password')

        if not email or not password:
            flash("Email and password are required.", "danger")
            return render_template("email/index.html", process=process)
        print(action)
        if action == "create":
            result = subprocess.run(
                ["docker", "exec", "-it", "mailserver", "setup", "email", "add", email, password],
                # ["docker", "ps"],
                capture_output=True,
                text=True
            )
            print("STDOUT:", result.stdout)
            print("STDERR:", result.stderr)
            print("Return Code:", result.returncode)

        elif action == "delete":
            result = subprocess.run(
                ["docker", "exec", "-it", "mailserver", "setup", "email", "del", email],
                capture_output=True,
                text=True
            )
        else:
            flash("Invalid action.", "danger")
            return render_template("email/index.html", process=process)

        if result.returncode == 0:
            flash(f"{action.title()} successful for {email}", "success")
        else:
            flash(f"{action.title()} failed: {result.stderr}", "danger")

        return render_template("email/index.html", process=process)

    return render_template("email/index.html", process=process)
