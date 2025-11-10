import os
def get_project_root():
    current = os.path.abspath(os.path.dirname(__file__))
    while current != os.path.dirname(current):
        if os.path.exists(os.path.join(current, 'core.py')):
            return current
        current = os.path.dirname(current)
    return os.path.abspath(os.path.dirname(__file__))