from flask import Blueprint, render_template, request, jsonify
import subprocess
from decorators import owner_or_subuser_required
from utils import find_process_by_name

email_routes = Blueprint('email', __name__)

_MAILSERVER_CONTAINER = "mailserver"
_MAILSERVER_MISSING = (
    "Mail server container is not running. "
    "Start the `mailserver` container to manage email accounts."
)


def _run_docker(args, timeout=35):
    return subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def _mailserver_status():
    """Return (running: bool, error: str | None) for the mailserver container."""
    inspect = _run_docker(
        ["inspect", "-f", "{{.State.Status}}", _MAILSERVER_CONTAINER],
        timeout=10,
    )
    combined = f"{inspect.stderr or ''}\n{inspect.stdout or ''}"
    if inspect.returncode != 0:
        if "No such container" in combined:
            return False, _MAILSERVER_MISSING
        return False, (inspect.stderr or inspect.stdout or "docker inspect failed").strip()

    status = (inspect.stdout or "").strip()
    if status != "running":
        return False, (
            f"Mail server container is {status or 'not running'}. "
            "IMAP will fail until `mailserver` is healthy."
        )
    return True, None


def _mailserver_error(stderr: str = "", stdout: str = "") -> str:
    combined = f"{stderr or ''}\n{stdout or ''}"
    if "No such container" in combined:
        return _MAILSERVER_MISSING
    if "is restarting" in combined:
        return (
            "Mail server container is restarting. "
            "Check SSL certs in /etc/server-manager/mail-certs and `docker logs mailserver`."
        )
    return (stderr or stdout or "Mail server command failed").strip()


def list_email_users():
    """List configured email users from the mailserver container."""
    users = []
    try:
        running, status_error = _mailserver_status()
        if not running:
            return users, status_error

        list_result = _run_docker(
            ["exec", _MAILSERVER_CONTAINER, "setup", "email", "list"],
            timeout=35,
        )

        if list_result.returncode != 0:
            return users, _mailserver_error(list_result.stderr, list_result.stdout)

        for line in list_result.stdout.strip().splitlines():
            parts = line.split()
            if len(parts) > 1:
                email = parts[1]
                if "@" in email:
                    users.append(email)

        return users, None
    except subprocess.TimeoutExpired:
        return users, "Timed out while fetching email accounts"
    except Exception as e:
        return users, _mailserver_error(str(e))


@email_routes.route('<name>', methods=['GET'])
@owner_or_subuser_required()
def email(name):
    process = find_process_by_name(name)
    return render_template("email/index.html", process=process, page_title="Email")


@email_routes.route('<name>/api/accounts', methods=['GET'])
@owner_or_subuser_required()
def list_email_accounts(name):
    process = find_process_by_name(name)
    if not process:
        return jsonify({"success": False, "error": "Process not found"}), 404

    users, error = list_email_users()
    if error:
        return jsonify({"success": False, "error": error, "users": users}), 500

    return jsonify({"success": True, "users": users})


@email_routes.route('<name>/create', methods=['POST'])
@owner_or_subuser_required()
def create_email(name):
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    running, status_error = _mailserver_status()
    if not running:
        return jsonify({"error": status_error}), 500

    result = _run_docker(
        ["exec", _MAILSERVER_CONTAINER, "setup", "email", "add", email, password],
    )

    if result.returncode == 0:
        return jsonify({"message": f"Email {email} created successfully"}), 200

    return jsonify({"error": _mailserver_error(result.stderr, result.stdout)}), 500


@email_routes.route('<name>/delete', methods=['POST'])
@owner_or_subuser_required()
def delete_email(name):
    email = request.json.get('email')

    if not email:
        return jsonify({"error": "Email is required"}), 400

    running, status_error = _mailserver_status()
    if not running:
        return jsonify({"error": status_error}), 500

    result = _run_docker(
        ["exec", _MAILSERVER_CONTAINER, "setup", "email", "del", email],
    )

    if result.returncode == 0:
        return jsonify({"message": f"Email {email} deleted successfully"}), 200

    return jsonify({"error": _mailserver_error(result.stderr, result.stdout)}), 500


@email_routes.route('<name>/update-password', methods=['POST'])
@owner_or_subuser_required()
def update_email_password(name):
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    running, status_error = _mailserver_status()
    if not running:
        return jsonify({"error": status_error}), 500

    result = _run_docker(
        ["exec", _MAILSERVER_CONTAINER, "setup", "email", "update", email, password],
    )

    if result.returncode == 0:
        return jsonify({"message": f"Password updated successfully for {email}"}), 200

    return jsonify({"error": _mailserver_error(result.stderr, result.stdout)}), 500
