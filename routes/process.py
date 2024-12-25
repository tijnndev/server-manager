from flask import Blueprint, render_template
from db import db
from models.process import Process

process_routes = Blueprint('process', __name__)

@process_routes.route('/create', methods=['GET', 'POST'])
def create_process():
    return render_template('create_process.html')

def update_process_id(old_id: str, new_id: str):
    try:
        process = Process.query.filter_by(id=old_id).first()

        if not process:
            return f"Process with ID '{old_id}' not found."

        process.id = new_id
        db.session.commit()

        return f"Process ID updated successfully from '{old_id}' to '{new_id}'."

    except Exception as e:
        db.session.rollback()
        return f"An error occurred while updating the process ID: {str(e)}"
