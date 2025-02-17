import subprocess
import os
from flask import Blueprint, jsonify, request, render_template
from models.git import GitIntegration
from utils import find_process_by_name, get_service_status

git_routes = Blueprint('git', __name__)

@git_routes.route('/<name>', methods=['GET'])
def git(name):
    process = find_process_by_name(name)
    integrations = GitIntegration.query.all()
    show_add_repo_button = len(integrations) == 0  # Show the button if no integrations exist
    return render_template('git/index.html', service=process, integrations=integrations, show_add_repo_button=show_add_repo_button)

# Route to display the form for adding a new Git repository
@git_routes.route('/add_form', methods=['GET'])
def add_git_form():
    return render_template('git/add_form.html')

# Route to add a new Git repository integration
@git_routes.route('/add_git_integration', methods=['POST'])
def add_git_integration():
    data = request.form
    repository_url = data.get('repository_url')
    directory = data.get('directory')
    branch = data.get('branch', 'main')

    if not repository_url or not directory:
        return jsonify({"error": "Repository URL and directory are required"}), 400

    git_integration = GitIntegration(repository_url=repository_url, directory=directory, branch=branch)
    git_integration.clone_repo()

    return jsonify({
        "message": f"Repository {repository_url} cloned to {directory}",
        "status": git_integration.status
    })

# Route to pull the latest changes
@git_routes.route('/pull_latest/<int:integration_id>', methods=['POST'])
def pull_latest(integration_id):
    git_integration = GitIntegration.query.get(integration_id)
    if not git_integration:
        return jsonify({"error": "Git integration not found"}), 404

    git_integration.pull_latest()
    return jsonify({"message": f"Repository at {git_integration.directory} updated", "status": git_integration.status})

# Route to remove a repository integration
@git_routes.route('/remove_git_integration/<int:integration_id>', methods=['POST'])
def remove_git_integration(integration_id):
    git_integration = GitIntegration.query.get(integration_id)
    if not git_integration:
        return jsonify({"error": "Git integration not found"}), 404

    git_integration.remove_repo()
    return jsonify({"message": f"Repository at {git_integration.directory} removed", "status": git_integration.status})
