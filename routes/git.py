import subprocess
import os
from flask import Blueprint, jsonify, request, render_template, url_for
from models.git import GitIntegration
from utils import find_process_by_name, get_service_status
from db import db

git_routes = Blueprint('git', __name__)

@git_routes.route('/<name>', methods=['GET'])
def git(name):
    service = find_process_by_name(name)
    integrations = GitIntegration.query.filter_by(process_name=name).all()
    show_add_repo_button = len(integrations) == 0  # Show the button if no integrations exist
    return render_template('git/index.html', service=service, integrations=integrations, show_add_repo_button=show_add_repo_button)

# Route to display the form for adding a new Git repository
@git_routes.route('/<name>/add_form', methods=['GET'])
def add_form(name):
    service = find_process_by_name(name)
    return render_template('git/add_form.html', service=service)

# Route to add a new Git repository integration
@git_routes.route('/<name>/add_git_integration', methods=['POST'])
def add_git_integration(name):
    data = request.form
    repository_url = data.get('repository_url')
    directory = data.get('directory')
    branch = data.get('branch', 'main')

    if not repository_url or not directory:
        return jsonify({"error": "Repository URL and directory are required"}), 400

    git_integration = GitIntegration(repository_url=repository_url, directory=directory, process_name=name, branch=branch)
    db.session.add(git_integration)
    db.session.commit()
    git_integration.clone_repo()

    return url_for("git.git", name=name)

@git_routes.route('/<name>/pull_latest/<int:integration_id>', methods=['POST'])
def pull_latest(name, integration_id):
    git_integration = GitIntegration.query.get(integration_id)
    if not git_integration:
        return jsonify({"error": "Git integration not found"}), 404

    git_integration.pull_latest()
    return url_for("git.git", name=name)

@git_routes.route('/<name>/remove_git_integration/<int:integration_id>', methods=['POST'])
def remove_git_integration(name, integration_id):
    git_integration = GitIntegration.query.get(integration_id)
    if not git_integration:
        return jsonify({"error": "Git integration not found"}), 404

    git_integration.remove_repo()
    return url_for("git.git", name=name)
