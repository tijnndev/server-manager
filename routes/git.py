from flask import Blueprint, jsonify, request, render_template, url_for, redirect
from models.git import GitIntegration
from utils import find_process_by_name
from decorators import owner_or_subuser_required
from db import db

git_routes = Blueprint('git', __name__)


@git_routes.route('/<name>', methods=['GET'])
@owner_or_subuser_required()
def git(name):
    process = find_process_by_name(name)
    integrations = GitIntegration.query.filter_by(process_name=name).all()
    show_add_repo_button = len(integrations) == 0
    
    # Get status and version info for each integration
    for integration in integrations:
        integration.changes = integration.get_git_status()
        integration.current_commit = integration.get_current_commit()
        integration.ahead_behind = integration.get_ahead_behind()
    
    return render_template('git/index.html', page_title="Git", process=process, integrations=integrations, show_add_repo_button=show_add_repo_button)


@git_routes.route('/<name>/add_form', methods=['GET'])
@owner_or_subuser_required()
def add_git_form(name):
    process = find_process_by_name(name)
    return render_template('git/add_form.html', page_title="Add Git", process=process)


@git_routes.route('/<name>/add_git_integration', methods=['POST'])
@owner_or_subuser_required()
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

    return redirect(url_for("git.git", name=name))


@git_routes.route('/<name>/pull_latest/<int:integration_id>', methods=['POST'])
@owner_or_subuser_required()
def pull_latest_git(name, integration_id):
    git_integration = GitIntegration.query.get(integration_id)
    if not git_integration:
        return jsonify({"error": "Git integration not found"}), 404

    git_integration.pull_latest()
    return redirect(url_for("git.git", name=name))


@git_routes.route('/<name>/remove_git_integration/<int:integration_id>', methods=['POST'])
@owner_or_subuser_required()
def remove_git_integration(name, integration_id):
    git_integration = GitIntegration.query.get(integration_id)
    if not git_integration:
        return jsonify({"error": "Git integration not found"}), 404

    git_integration.remove_repo()
    return redirect(url_for("git.git", name=name))
