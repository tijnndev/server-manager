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
        return redirect(url_for('files.file_manager', name=process.name, location=""))
    
    if os.path.join(ACTIVE_SERVERS_DIR, name) not in current_location:
        return redirect(url_for('files.file_manager', name=process.name, location=""))

    if not os.path.exists(current_location):
        return redirect(url_for('files.file_manager', name=process.name, location=""))

    relative_location = os.path.relpath(current_location, ACTIVE_SERVERS_DIR)
    files = []
    for file in os.listdir(current_location):
        file_full_path = os.path.join(current_location, file)
        is_dir = os.path.isdir(file_full_path)
        
        # Get file stats
        try:
            stat = os.stat(file_full_path)
            file_size = None if is_dir else stat.st_size
            modified_time = stat.st_mtime
        except OSError:
            file_size = None
            modified_time = None
        
        files.append({
            'name': file,
            'is_directory': is_dir,
            'path': os.path.join(relative_location, file) if relative_location != '.' else file,
            'size': file_size,
            'modified_time': modified_time
        })

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

    if not filename:
        return jsonify({
            "success": False,
            "error": "No filename provided. Please specify a file to delete."
        }), 400

    try:
        file_path = sanitize_path(ACTIVE_SERVERS_DIR, filename)
    except ValueError as e:
        return jsonify({
            "success": False,
            "error": f"Invalid file path: {filename}. Path must be within the server directory."
        }), 400

    if not os.path.exists(file_path):
        return jsonify({
            "success": False,
            "error": f"File not found: {filename}. It may have already been deleted."
        }), 404

    trash_path = os.path.join(TRASH_DIR, f"{filename.replace('/', '_')}-{int(time.time())}")
    
    try:
        # Ensure trash directory exists
        os.makedirs(TRASH_DIR, exist_ok=True)
        
        if os.path.isfile(file_path):
            if permanent:
                os.remove(file_path)
            else:
                shutil.move(file_path, trash_path)
        elif os.path.isdir(file_path):
            if permanent:
                shutil.rmtree(file_path)
            else:
                shutil.move(file_path, trash_path)
        
        return jsonify({
            "success": True,
            "message": f"{'Permanently deleted' if permanent else 'Moved to trash'}: {filename}",
            "trash_filename": os.path.basename(trash_path) if not permanent else None
        })
        
    except PermissionError:
        return jsonify({
            "success": False,
            "error": f"Permission denied: Cannot delete {filename}. Check if the file is in use or you have sufficient permissions."
        }), 403
    except OSError as e:
        return jsonify({
            "success": False,
            "error": f"System error while deleting {filename}: {str(e)}. Try closing any programs using this file."
        }), 500
    except shutil.Error as e:
        return jsonify({
            "success": False,
            "error": f"Failed to move {filename} to trash: {str(e)}. The file may be locked or corrupted."
        }), 500
    except Exception as e:
        return jsonify({
            "success": False,
            "error": f"Unexpected error deleting {filename}: {str(e)}. Please contact support if this persists."
        }), 500


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
        
        except (OSError, shutil.Error):
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
        return render_template('files/create_file.html', page_title="Create File", process=process, error="Invalid path.", location='/')

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
                return redirect(url_for('files.file_manager', name=process.name, location=location))

    return render_template('files/create_file.html', page_title="Create File", process=process, location=os.path.relpath(location, ACTIVE_SERVERS_DIR))


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

    return render_template('files/create_directory.html', page_title="Create Directory", process=process, current_location=os.path.relpath(location, ACTIVE_SERVERS_DIR))


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


@file_manager_routes.route('/<name>/file-manager/preview', methods=['GET'])
@owner_or_subuser_required()
def preview_file_content(name):
    """API endpoint to get file content for preview"""
    process = find_process_by_name(name)
    if not process:
        return jsonify({"success": False, "error": "Process not found"}), 404
    
    file_path_param = request.args.get('file', '')
    try:
        file_path = sanitize_path(ACTIVE_SERVERS_DIR, file_path_param)
    except ValueError:
        return jsonify({"success": False, "error": "Invalid path"}), 400

    if not os.path.exists(file_path):
        return jsonify({"success": False, "error": "File not found"}), 404
    
    if not os.path.isfile(file_path):
        return jsonify({"success": False, "error": "Not a file"}), 400
    
    try:
        # Check file size (limit to 1MB for preview)
        file_size = os.path.getsize(file_path)
        if file_size > 1024 * 1024:  # 1MB
            return jsonify({
                "success": False, 
                "error": "File too large for preview (max 1MB)"
            }), 413
        
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return jsonify({
            "success": True,
            "content": content,
            "filename": os.path.basename(file_path)
        })
    except UnicodeDecodeError:
        return jsonify({
            "success": False, 
            "error": "File is not text (binary file)"
        }), 400
    except Exception as e:
        return jsonify({
            "success": False, 
            "error": f"Error reading file: {str(e)}"
        }), 500


@file_manager_routes.route('/<name>/edit', methods=['GET', 'POST'])
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

        return {"success": True, "file_path": os.path.relpath(file_path, ACTIVE_SERVERS_DIR)}

    with open(file_path) as f:
        file_content = f.read()

    return render_template('files/edit_file.html', page_title="Edit File", process=process, file_path=file_path, file_content=file_content, file_name=file_name)


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


@file_manager_routes.route('/<name>/file-manager/rename', methods=['POST'])
@owner_or_subuser_required()
def rename_file(name):
    """
    Rename a file or directory.
    Expects JSON: {"old_path": "path/to/old", "new_name": "new_filename"}
    """
    process = find_process_by_name(name)
    if not process:
        return jsonify({"success": False, "error": "Process not found"}), 404

    try:
        data = request.get_json()
        if not data or 'old_path' not in data or 'new_name' not in data:
            return jsonify({
                "success": False, 
                "error": "Missing required fields: old_path and new_name"
            }), 400

        old_path = data['old_path'].replace("\\", "/")
        new_name = data['new_name']

        # Validate new name doesn't contain path separators
        if '/' in new_name or '\\' in new_name:
            return jsonify({
                "success": False, 
                "error": "New name cannot contain path separators"
            }), 400

        # Sanitize paths
        old_file_path = sanitize_path(ACTIVE_SERVERS_DIR, old_path)
        
        if not os.path.exists(old_file_path):
            return jsonify({
                "success": False, 
                "error": f"File or directory not found: {old_path}"
            }), 404

        # Create new path in same directory
        old_dir = os.path.dirname(old_file_path)
        new_file_path = os.path.join(old_dir, new_name)

        # Check if target already exists
        if os.path.exists(new_file_path):
            return jsonify({
                "success": False, 
                "error": f"A file or directory named '{new_name}' already exists"
            }), 409

        # Perform rename
        os.rename(old_file_path, new_file_path)

        return jsonify({
            "success": True,
            "message": f"Successfully renamed to '{new_name}'",
            "new_path": os.path.relpath(new_file_path, ACTIVE_SERVERS_DIR)
        })

    except ValueError as e:
        return jsonify({"success": False, "error": f"Invalid path: {str(e)}"}), 400
    except PermissionError:
        return jsonify({
            "success": False, 
            "error": "Permission denied. Check file permissions."
        }), 403
    except Exception as e:
        return jsonify({
            "success": False, 
            "error": f"Failed to rename: {str(e)}"
        }), 500


@file_manager_routes.route('/<name>/file-manager/restore', methods=['POST'])
@owner_or_subuser_required()
def restore_file(name):
    """
    Restore a deleted file from trash.
    Expects JSON: {"trash_filename": "filename-timestamp"}
    """
    process = find_process_by_name(name)
    if not process:
        return jsonify({"success": False, "error": "Process not found"}), 404

    try:
        data = request.get_json()
        if not data or 'trash_filename' not in data:
            return jsonify({
                "success": False, 
                "error": "Missing trash_filename"
            }), 400

        trash_filename = data['trash_filename']
        trash_file_path = os.path.join(TRASH_DIR, trash_filename)

        if not os.path.exists(trash_file_path):
            return jsonify({
                "success": False, 
                "error": "File not found in trash"
            }), 404

        # Extract original path from trash filename
        # Format: original_path-timestamp
        original_name = '-'.join(trash_filename.split('-')[:-1]).replace('_', '/')
        
        restore_path = os.path.join(ACTIVE_SERVERS_DIR, original_name)
        
        # Check if original location still exists
        restore_dir = os.path.dirname(restore_path)
        if not os.path.exists(restore_dir):
            os.makedirs(restore_dir, exist_ok=True)

        # Check if file already exists at restore location
        if os.path.exists(restore_path):
            # Add timestamp to avoid collision
            base, ext = os.path.splitext(restore_path)
            restore_path = f"{base}_restored_{int(time.time())}{ext}"

        # Move from trash to original location
        shutil.move(trash_file_path, restore_path)

        return jsonify({
            "success": True,
            "message": "File restored successfully",
            "restored_path": os.path.relpath(restore_path, ACTIVE_SERVERS_DIR)
        })

    except Exception as e:
        return jsonify({
            "success": False, 
            "error": f"Failed to restore file: {str(e)}"
        }), 500
