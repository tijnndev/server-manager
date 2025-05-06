import os
import zipfile
import shutil
import time
from decorators import owner_or_subuser_required
from flask import Blueprint, render_template, jsonify, request, send_from_directory, redirect, url_for, flash
from utils import find_process_by_name
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


@file_manager_routes.route('/manage/<name>', methods=['GET', 'POST'])
@owner_or_subuser_required()
def file_manager(name):
    process = find_process_by_name(name)
    location_param = request.args.get('location', name)

    if not location_param:
        location_param = name

    try:
        current_location = sanitize_path(ACTIVE_SERVERS_DIR, location_param)
    except ValueError:
        return render_template('files/file_manager.html', process=process, files=[], error="Invalid path.", current_location="/")
    
    if os.path.join(ACTIVE_SERVERS_DIR, name) not in current_location:
        return redirect(url_for('files.file_manager', name=process.name, location=""))

    if not os.path.exists(current_location):
        return render_template('files/file_manager.html', process=process, files=[], error="Location does not exist.", current_location="/")

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
                if uploaded_file.filename.lower().endswith('.zip'):
                    extract_path = os.path.splitext(file_path)[0]
                    with zipfile.ZipFile(file_path, 'r') as zip_ref:
                        zip_ref.extractall(extract_path)
                    os.remove(file_path)
                    flash("ZIP file extracted successfully!", "success")
                else:
                    flash("File uploaded successfully!", "success")
                
                return redirect(url_for('files.file_manager', name=process.name, location=relative_location))
            except ValueError:
                flash("Invalid upload path.", "danger")
    
    return render_template('files/file_manager.html', files=files, current_location=relative_location, page_title="File Manager", process=process)


@file_manager_routes.route('/<name>/file-manager/delete', methods=['POST'])
@owner_or_subuser_required()
def delete_file(name):
    process = find_process_by_name(name)
    filename = request.form.get('filename', "").replace("\\", "/")
    current_location = request.form.get('location', '')
    permanent = request.args.get('permanent', 'false').lower() == 'true'

    try:
        file_path = sanitize_path(ACTIVE_SERVERS_DIR, filename)
    except ValueError:
        return jsonify({"error": "Invalid path."}), 400

    trash_path = os.path.join(TRASH_DIR, f"{filename.replace('/', '_')}-{int(time.time())}")
    if os.path.exists(file_path):
        try:
            if os.path.isfile(file_path):
                os.remove(file_path) if permanent else shutil.move(file_path, trash_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path) if permanent else shutil.move(file_path, trash_path)
            return redirect(url_for('files.file_manager', name=process.name, location=current_location))
        except Exception:
            pass

    return redirect(url_for('files.file_manager', name=process.name, location=current_location))


@file_manager_routes.route('/<name>/files/delete', methods=['POST'])
@owner_or_subuser_required()
def delete_files(name):
    filename = request.form.get('filename', "").replace("\\", "/")
    permanent = request.args.get('permanent', 'false').lower() == 'true'

    try:
        file_path = sanitize_path(ACTIVE_SERVERS_DIR, filename)
    except ValueError:
        return jsonify({"error": "Invalid path."}), 400

    trash_path = os.path.join(TRASH_DIR, f"{filename.replace('/', '_')}-{int(time.time())}")
    if os.path.exists(file_path):
        try:
            if os.path.isfile(file_path):
                os.remove(file_path) if permanent else shutil.move(file_path, trash_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path) if permanent else shutil.move(file_path, trash_path)
            return jsonify({"success": True}), 200
        
        except Exception:
            pass

    return jsonify({"error": "Files not found."}), 400


@file_manager_routes.route('/<name>/file-manager/download/<filename>', methods=['GET'])
@owner_or_subuser_required()
def download_file(name, filename):
    try:
        process_path = sanitize_path(ACTIVE_SERVERS_DIR, name)
        file_path = sanitize_path(process_path, filename)
    except ValueError:
        return jsonify({"error": "Invalid path."}), 400

    if os.path.exists(file_path):
        return send_from_directory(process_path, filename, as_attachment=True)
    return jsonify({"error": "File not found"}), 404


@file_manager_routes.route('/<name>/new/file', methods=['GET', 'POST'])
@owner_or_subuser_required()
def create_file(name):
    process = find_process_by_name(name)
    location = request.args.get('location', '')
    try:
        location = sanitize_path(ACTIVE_SERVERS_DIR, location)
    except ValueError:
        return render_template('files/create_file.html', process=process, error="Invalid path.", location='/')

    if request.method == 'POST':
        file_name = request.form.get('file_name')
        file_code = request.form.get('file_code')
        if file_name and file_code:
            file_path = os.path.join(location, file_name)
            try:
                file_path = sanitize_path(location, file_name)
                with open(file_path, 'w') as f:
                    f.write(file_code)
                return redirect(url_for('files.file_manager', name=process.name, location=os.path.relpath(location, ACTIVE_SERVERS_DIR)))
            except ValueError:
                return render_template('files/create_file.html', process=process, error="Invalid file path.", location=location)

    return render_template('files/create_file.html', process=process, location=os.path.relpath(location, ACTIVE_SERVERS_DIR))


@file_manager_routes.route('/<name>/new/dir', methods=['GET', 'POST'])
@owner_or_subuser_required()
def create_directory_file(name):
    process = find_process_by_name(name)
    current_location = request.args.get('location', '')
    try:
        location = sanitize_path(ACTIVE_SERVERS_DIR, current_location)
    except ValueError:
        return jsonify({"error": "Invalid path"}), 400

    if request.method == 'POST':
        new_dir_name = request.form.get('directory_name')
        if new_dir_name:
            new_dir_path = os.path.join(location, new_dir_name)
            try:
                new_dir_path = sanitize_path(location, new_dir_name)
                os.makedirs(new_dir_path, exist_ok=True)
                return redirect(url_for('files.file_manager', name=process.name, location=current_location))
            except Exception:
                return redirect(url_for('files.file_manager', name=process.name, location=current_location))

    return render_template('files/create_directory.html', process=process, current_location=os.path.relpath(location, ACTIVE_SERVERS_DIR))


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
            if uploaded_file.filename.lower().endswith('.zip'):
                extract_path = os.path.splitext(file_path)[0]
                with zipfile.ZipFile(file_path, 'r') as zip_ref:
                    zip_ref.extractall(extract_path)
            
            return jsonify({'success': True})
        except ValueError:
            return jsonify({'error': 'Invalid file path'}), 400

    return jsonify({'success': True})


@file_manager_routes.route('<name>/edit', methods=['GET', 'POST'])
@owner_or_subuser_required()
def edit_file(name):
    process = find_process_by_name(name)
    file_path_param = request.args.get('file', '')
    try:
        file_path = sanitize_path(ACTIVE_SERVERS_DIR, file_path_param)
    except ValueError:
        return "Invalid path", 400

    if not os.path.exists(file_path):
        return "File not found", 404

    file_name = os.path.basename(file_path)
    
    if request.method == 'POST':
        data = request.get_json()
        new_name = data['file_name']
        new_file_path = os.path.join(os.path.dirname(file_path), new_name)

        new_content = data['file_code']
        new_content = new_content.replace('\r\n', '\n').replace('\r', '\n')

        if file_path != new_file_path:
            os.remove(file_path)

        with open(new_file_path, 'w', newline='') as f:
            f.write(new_content)
        file_path = new_file_path
        with open(new_file_path) as f:
            file_content = f.read()

        return render_template('files/edit_file.html', process=process, file_path=new_file_path, file_content=file_content, file_name=new_name)

    with open(file_path) as f:
        file_content = f.read()

    return render_template('files/edit_file.html', process=process, file_path=file_path, file_content=file_content, file_name=file_name)


@file_manager_routes.route('/unzip/<name>', methods=['POST'])
@owner_or_subuser_required()
def unzip_file(name):
    zip_path = request.form.get('zip_path')
    if not zip_path or not zip_path.endswith('.zip'):
        flash("Invalid ZIP file.", "danger")
        return redirect(request.referrer)
    
    try:
        print(zip_path)
        project_dir = sanitize_path(ACTIVE_SERVERS_DIR, name)
        full_zip_path = sanitize_path(project_dir, zip_path)
        extract_dir = os.path.splitext(full_zip_path)[0]
        
        with zipfile.ZipFile(full_zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
        
        flash("ZIP file extracted successfully.", "success")
    except Exception as e:
        flash(f"Error extracting ZIP file: {str(e)}", "danger")
    
    return redirect(request.referrer)


def sanitize_path2(base_path, relative_path):
    safe_path = os.path.normpath(relative_path)

    absolute_path = os.path.join(base_path, safe_path)

    if not os.path.commonprefix([absolute_path, base_path]) == base_path:
        raise ValueError("Invalid path, path traversal detected")

    return absolute_path


@file_manager_routes.route('/move_files/<name>', methods=['POST'])
@owner_or_subuser_required()
def move_files(name):
    try:
        data = request.get_json()
        files = data.get('files', [])
        destination = data.get('destination', '')

        if not files or not destination:
            return jsonify({'error': 'Invalid request'}), 400

        server_path = os.path.join(ACTIVE_SERVERS_DIR, name)
        if not os.path.isdir(server_path):
            return jsonify({'error': f'Invalid source directory: {name}'}), 400

        for file in files:
            file_path = sanitize_path2(ACTIVE_SERVERS_DIR, file)
            if not os.path.exists(file_path):
                return jsonify({'error': f'File {file} does not exist'}), 400

            destination_dir = os.path.join(os.path.dirname(file_path), destination)
            if not os.path.abspath(destination_dir).startswith(server_path):
                return jsonify({'error': 'Cannot move file outside of the source directory'}), 400

            os.makedirs(destination_dir, exist_ok=True)

            try:
                shutil.move(file_path, os.path.join(destination_dir, os.path.basename(file_path)))
            except Exception as e:
                return jsonify({'error': f'Error moving {file}: {str(e)}'}), 500

        return jsonify({'success': True})

    except Exception as e:
        return jsonify({'error': f'Error: {str(e)}'}), 500
