import os
from flask import Blueprint, render_template

process_routes = Blueprint('process', __name__)

handlers_folder = os.path.join(os.getcwd(), 'handlers')

def find_types():
    types = []
    
    for _root, _dirs, files in os.walk(handlers_folder):
        for filename in files:
            
            if filename.endswith('.py') and filename not in types:
                types.append(filename.split('.')[0])
    
    return types

@process_routes.route('/create', methods=['GET', 'POST'])
def create_process():
    types = find_types()

    return render_template('create_process.html', types=types)
