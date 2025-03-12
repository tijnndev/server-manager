from flask import Blueprint, render_template
from utils import find_types

process_routes = Blueprint('process', __name__)


@process_routes.route('/create', methods=['GET', 'POST'])
def create_process():
    types = find_types()

    return render_template('create_process.html', types=types)
