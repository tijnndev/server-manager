# app/routes/file_manager_routes.py
import json
import re
import time
from flask import Blueprint, render_template, jsonify, request, send_from_directory, redirect, url_for
import os, shutil, urllib.parse

file_manager_routes = Blueprint('files', __name__)

BASE_DIR = os.path.dirname(__file__)
ACTIVE_SERVERS_DIR = os.path.join(BASE_DIR, '../active-servers')
TRASH_DIR = os.path.join(BASE_DIR, '../.trash')


@file_manager_routes.route('/manage', methods=['GET', 'POST'])
def file_manager():
    current_location = ACTIVE_SERVERS_DIR

    # Get and sanitize the location parameter
    location_param = request.args.get('location')
    if location_param:
        # URL-decode the location to handle any encoding issues
        location_param = urllib.parse.unquote(location_param)
        # Ensure no traversal issues (avoid moving outside the base directory)
        location_param = os.path.normpath(location_param)  # Normalize path
        if '..' in location_param or location_param.startswith('/'):
            return render_template('file_manager.html', files=[], error="Invalid path.", current_location="/")
        current_location = os.path.join(current_location, location_param)

    # Ensure the path is absolute and normalized
    current_location = os.path.abspath(os.path.normpath(current_location))

    # Check if the location exists
    if not os.path.exists(current_location):
        return render_template('file_manager.html', files=[], error="Location does not exist.", current_location="/")

    # Prepare the relative location for display
    relative_location = os.path.relpath(current_location, ACTIVE_SERVERS_DIR)
    
    # List files in the current directory
    files = [
        {
            'name': file,
            'is_directory': os.path.isdir(os.path.join(current_location, file)),
            'path': os.path.join(relative_location, file)  # Use relative path for links
        }
        for file in os.listdir(current_location)
    ]

    # Handle file upload
    if request.method == 'POST':
        uploaded_file = request.files.get('file')
        if uploaded_file:
            file_path = os.path.join(current_location, uploaded_file.filename)
            uploaded_file.save(file_path)
            success_message = "File uploaded successfully!"
            return render_template(
                'file_manager.html',
                files=files,
                success=success_message,
                current_location=relative_location
            )

    # Render the template with the current files and location
    return render_template('file_manager.html', files=files, current_location=relative_location)


@file_manager_routes.route('/file-manager/delete', methods=['POST'])
def delete_file():
    filename = request.form.get('filename').replace("\\", "/")
    location = request.args.get('location', ACTIVE_SERVERS_DIR)
    location = os.path.abspath(os.path.normpath(location))
    permanent = request.args.get('permanent', 'false').lower() == 'true'

    file_path = os.path.abspath(os.path.normpath(os.path.join(location, filename)))
    trash_path = os.path.abspath(os.path.normpath(os.path.join(TRASH_DIR, f"{filename.replace('/', '_')}-{int(time.time())}")))
    if os.path.exists(file_path):
        directory_path, _file_name = os.path.split(file_path)
        try:
            if permanent:
                os.remove(file_path)
                message = f"File '{filename}' permanently deleted."
            else:
                if os.path.exists(TRASH_DIR):
                    if os.path.exists(trash_path):
                        _base, ext = os.path.splitext(filename.replace('/', '_'))
                        trash_path = os.path.join(TRASH_DIR, f"-{int(time.time())}{ext}")
                    shutil.move(file_path, trash_path)
                    message = f"File '{filename}' moved to .trash."
                    
                else:
                    message = "Trash directory does not exist."
            return redirect(url_for('files.file_manager', location=directory_path, message=message))
        except Exception as e:
            print(f"Error: {e}")
            message = str(e)
            return redirect(url_for('files.file_manager', location=directory_path, message=message))
    else:
        print(f"File not found at: {file_path}")
        return jsonify({"error": "File not found"}), 404


@file_manager_routes.route('/file-manager/download/<filename>', methods=['GET'])
def download_file(filename):
    file_path = os.path.join(ACTIVE_SERVERS_DIR, filename)
    if os.path.exists(file_path):
        return send_from_directory(ACTIVE_SERVERS_DIR, filename, as_attachment=True)
    else:
        return jsonify({"error": "File not found"}), 404


@file_manager_routes.route('/create-file', methods=['GET', 'POST'])
def create_file():
    location = request.args.get('location')
    print(location)
    if request.method == 'POST':
        location = os.path.join(ACTIVE_SERVERS_DIR, request.args.get('location'))
        file_name = request.form.get('file_name')
        file_code = request.form.get('file_code')

        if file_name and file_code:
            file_path = os.path.join(location, file_name)
            with open(file_path, 'w') as f:
                f.write(file_code)
            return redirect(url_for('files.file_manager', location=request.args.get('location')))
        else:
            return render_template('create_file.html', error="File name and code content are required.", location=location)

    return render_template('create_file.html', location=location)

def get_file_extension(file_type):
    if file_type == 'python':
        return '.py'
    elif file_type == 'javascript':
        return '.js'
    elif file_type == 'html':
        return '.html'
    elif file_type == 'css':
        return '.css'
    else:
        return ''
    
@file_manager_routes.route('/files/create_directory', methods=['GET', 'POST'])
def create_directory():
    location = os.path.join(ACTIVE_SERVERS_DIR, request.args.get('location'))
    if request.method == 'POST':
        new_dir_name = request.form.get('directory_name')
        if new_dir_name:
            # Create the new directory at the specified location
            new_dir_path = os.path.join(location, new_dir_name)
            try:
                os.makedirs(new_dir_path, exist_ok=True)  # Create the directory
                success = f"Directory '{new_dir_name}' created successfully."
                return redirect(url_for('files.file_manager', location=location, success=success))
            except Exception as e:
                error = f"Error creating directory: {e}"
                return redirect(url_for('files.file_manager', location=location, error=error))
    return render_template('create_directory.html', current_location=location)