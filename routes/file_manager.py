import time, os, shutil
from flask import Blueprint, render_template, jsonify, request, send_from_directory, redirect, url_for

file_manager_routes = Blueprint('files', __name__)

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '../'))
ACTIVE_SERVERS_DIR = os.path.join(BASE_DIR, 'active-servers')
TRASH_DIR = os.path.join(BASE_DIR, '.trash')


def sanitize_path(base, target):
    """Ensure target path stays within the base directory."""
    normalized_path = os.path.abspath(os.path.normpath(os.path.join(base, target)))
    if not normalized_path.startswith(base):
        raise ValueError("Path traversal detected.")
    return normalized_path


@file_manager_routes.route('/manage', methods=['GET', 'POST'])
def file_manager():
    location_param = request.args.get('location', '')
    try:
        current_location = sanitize_path(ACTIVE_SERVERS_DIR, location_param)
    except ValueError:
        return render_template('service/file_manager.html', files=[], error="Invalid path.", current_location="/")

    if not os.path.exists(current_location):
        return render_template('service/file_manager.html', files=[], error="Location does not exist.", current_location="/")

    relative_location = os.path.relpath(current_location, ACTIVE_SERVERS_DIR)
    files = [
        {
            'name': file,
            'is_directory': os.path.isdir(os.path.join(current_location, file)),
            'path': os.path.join(relative_location, file) if relative_location != '.' else file
        }
        for file in os.listdir(current_location)
    ]

    if request.method == 'POST':
        uploaded_file = request.files.get('file')
        if uploaded_file:
            try:
                file_path = sanitize_path(current_location, uploaded_file.filename)
                uploaded_file.save(file_path)
                success_message = "File uploaded successfully!"
                return render_template(
                    'service/file_manager.html',
                    files=files,
                    success=success_message,
                    current_location=relative_location
                )
            except ValueError:
                return render_template('service/file_manager.html', files=[], error="Invalid upload path.", current_location=relative_location)

    return render_template('service/file_manager.html', files=files, current_location=relative_location, page_title="File Manager")


@file_manager_routes.route('/file-manager/delete', methods=['POST'])
def delete_file():

    if not request.form:
        return
    filename = request.form.get('filename', "").replace("\\", "/")
    location = request.args.get('location', '')
    permanent = request.args.get('permanent', 'false').lower() == 'true'

    try:
        location = sanitize_path(ACTIVE_SERVERS_DIR, location)
        file_path = sanitize_path(location, filename)
    except ValueError:
        return jsonify({"error": "Invalid path."}), 400

    trash_path = os.path.join(TRASH_DIR, f"{filename.replace('/', '_')}-{int(time.time())}")

    if os.path.exists(file_path):
        try:
            message = ""
            if os.path.isfile(file_path):
                if permanent:
                    os.remove(file_path)
                    message = f"File '{filename}' permanently deleted."
                else:
                    os.makedirs(TRASH_DIR, exist_ok=True)
                    if os.path.exists(trash_path):
                        base, ext = os.path.splitext(trash_path)
                        trash_path = f"{base}-{int(time.time())}{ext}"
                    shutil.move(file_path, trash_path)
                    message = f"File '{filename}' moved to .trash."
            elif os.path.isdir(file_path):
                if permanent:
                    shutil.rmtree(file_path)
                    message = f"Directory '{filename}' permanently deleted."
                else:
                    os.makedirs(TRASH_DIR, exist_ok=True)
                    if os.path.exists(trash_path):
                        trash_path = f"{trash_path}-{int(time.time())}"
                    shutil.move(file_path, trash_path)
                    message = f"Directory '{filename}' moved to .trash."

            return redirect(url_for('files.file_manager', location=os.path.relpath(location, ACTIVE_SERVERS_DIR), message=message))

        except Exception as e:
            return redirect(url_for('files.file_manager', location=os.path.relpath(location, ACTIVE_SERVERS_DIR), message=f"Error: {e}"))

    return jsonify({"error": "File or directory not found"}), 404


@file_manager_routes.route('/file-manager/download/<filename>', methods=['GET'])
def download_file(filename):
    try:
        file_path = sanitize_path(ACTIVE_SERVERS_DIR, filename)
    except ValueError:
        return jsonify({"error": "Invalid path."}), 400

    if os.path.exists(file_path):
        return send_from_directory(ACTIVE_SERVERS_DIR, filename, as_attachment=True)
    return jsonify({"error": "File not found"}), 404


@file_manager_routes.route('/new/file', methods=['GET', 'POST'])
def create_file():
    location = request.args.get('location', '')
    try:
        location = sanitize_path(ACTIVE_SERVERS_DIR, location)
    except ValueError:
        return render_template('create_file.html', error="Invalid path.", location='/')

    if request.method == 'POST':
        file_name = request.form.get('file_name')
        file_code = request.form.get('file_code')
        if file_name and file_code:
            file_path = os.path.join(location, file_name)
            try:
                file_path = sanitize_path(location, file_name)
                with open(file_path, 'w') as f:
                    f.write(file_code)
                return redirect(url_for('files.file_manager', location=os.path.relpath(location, ACTIVE_SERVERS_DIR)))
            except ValueError:
                return render_template('create_file.html', error="Invalid file path.", location=location)

    return render_template('create_file.html', location=os.path.relpath(location, ACTIVE_SERVERS_DIR))


@file_manager_routes.route('/new/dir', methods=['GET', 'POST'])
def create_directory():
    location = request.args.get('location', '')
    try:
        location = sanitize_path(ACTIVE_SERVERS_DIR, location)
    except ValueError:
        return jsonify({"error": "Invalid path"}), 400

    if request.method == 'POST':
        new_dir_name = request.form.get('directory_name')
        if new_dir_name:
            new_dir_path = os.path.join(location, new_dir_name)
            try:
                new_dir_path = sanitize_path(location, new_dir_name)
                os.makedirs(new_dir_path, exist_ok=True)
                return redirect(url_for('files.file_manager', location=os.path.relpath(location, ACTIVE_SERVERS_DIR), success=f"Directory '{new_dir_name}' created successfully."))
            except Exception as e:
                return redirect(url_for('files.file_manager', location=os.path.relpath(location, ACTIVE_SERVERS_DIR), error=f"Error creating directory: {e}"))

    return render_template('create_directory.html', current_location=os.path.relpath(location, ACTIVE_SERVERS_DIR))


@file_manager_routes.route('/file-manager/upload', methods=['POST'])
def upload_file():
    target_path = request.form.get('targetPath')
    try:
        target_path = sanitize_path(ACTIVE_SERVERS_DIR, target_path)
    except ValueError:
        return jsonify({'error': 'Invalid directory path'}), 400

    if not os.path.isdir(target_path):
        return jsonify({'error': 'Invalid directory path'}), 400

    uploaded_files = request.files.getlist('file')
    for uploaded_file in uploaded_files:
        file_path = os.path.join(target_path, uploaded_file.filename)
        try:
            file_path = sanitize_path(target_path, uploaded_file.filename)
            uploaded_file.save(file_path)
        except ValueError:
            return jsonify({'error': 'Invalid file path'}), 400

    return jsonify({'success': True})


@file_manager_routes.route('/edit', methods=['GET', 'POST'])
def edit_file():
    file_path_param = request.args.get('file', '')
    try:
        file_path = sanitize_path(ACTIVE_SERVERS_DIR, file_path_param)
    except ValueError:
        return "Invalid path", 400

    if not os.path.exists(file_path):
        return "File not found", 404

    file_name = os.path.basename(file_path)
    print(file_path)
    
    if request.method == 'POST':
        new_name = request.form['file_name']
        new_file_path = os.path.join(os.path.dirname(file_path), new_name)

        new_content = request.form['file_code']
        new_content = new_content.replace('\r\n', '\n').replace('\r', '\n')

        if file_path != new_file_path:
            os.remove(file_path)

        # Write the new content to the new file
        with open(new_file_path, 'w', newline='') as f:
            f.write(new_content)

        # Redirect to the file manager after saving
        return redirect(url_for('files.file_manager', location=os.path.relpath(os.path.dirname(new_file_path), ACTIVE_SERVERS_DIR)))

    # Read the file content for editing
    with open(file_path, 'r') as f:
        file_content = f.read()

    # Render the edit file template with the current file content
    return render_template('edit_file.html', file_path=file_path, file_content=file_content, file_name=file_name)
