import requests
from flask import Blueprint, jsonify, render_template

version_routes = Blueprint('version', __name__)


@version_routes.route("/")
def version_page():
    return render_template("version/version.html")


@version_routes.route("/check", methods=["GET"])
def check_version():
    try:
        with open("version.td") as f:
            local_version = f.read().strip()
    except FileNotFoundError:
        return jsonify({"error": "Local version file not found"}), 500
    except Exception as e:
        print(f'An error occurred: {e}')

    remote_url = "https://raw.githubusercontent.com/tijnndev/server-manager/main/version.td"
    try:
        response = requests.get(remote_url)
        response.raise_for_status()
        remote_version = response.text.strip()
    except Exception as e:
        return jsonify({"error": f"Failed to fetch remote version: {str(e)}"}), 500

    return jsonify({
        "local_version": local_version,
        "remote_version": remote_version,
        "update_available": local_version != remote_version
    })
