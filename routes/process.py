from flask import Blueprint, render_template

process_routes = Blueprint('process', __name__)

@process_routes.route('/create', methods=['GET', 'POST'])
def create_process():
    return render_template('create_process.html')
