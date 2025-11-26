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
    
    # Just pass basic integration data without heavy git operations
    return render_template('git/index.html', page_title="Git", process=process, integrations=integrations, show_add_repo_button=show_add_repo_button)


@git_routes.route('/<name>/api/git-data', methods=['GET'])
@owner_or_subuser_required()
def git_data_api(name):
    """API endpoint to fetch git repository data asynchronously"""
    try:
        integrations = GitIntegration.query.filter_by(process_name=name).all()
        
        result = []
        for integration in integrations:
            local_changes = integration.get_git_status()
            current_commit = integration.get_current_commit()
            ahead_behind = integration.get_ahead_behind()
            remote_changes = integration.get_remote_changes()
            
            result.append({
                'id': integration.id,
                'repository_url': integration.repository_url,
                'directory': integration.directory,
                'branch': integration.branch,
                'current_commit': current_commit,
                'status': integration.status,
                'ahead_behind': {
                    'ahead': ahead_behind.get('ahead', 0),
                    'behind': ahead_behind.get('behind', 0)
                },
                'local_changes': local_changes,
                'remote_changes': remote_changes
            })
        
        return jsonify({'success': True, 'integrations': result})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


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
