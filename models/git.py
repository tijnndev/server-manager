from db import db

class GitIntegration(db.Model):
    __tablename__ = 'git_integrations'

    id = db.Column(db.Integer, primary_key=True)
    repository_url = db.Column(db.String(255), nullable=False)
    directory = db.Column(db.String(255), nullable=False)
    branch = db.Column(db.String(255), nullable=True, default='main')
    status = db.Column(db.String(255), nullable=False, default='Not Cloned')

    def __init__(self, repository_url, directory, branch='main', status='Not Cloned'):
        self.repository_url = repository_url
        self.directory = directory
        self.branch = branch
        self.status = status

    def clone_repo(self):
        """Clones the repository into the server folder."""
        try:
            os.makedirs(self.directory, exist_ok=True)
            subprocess.run(["git", "clone", "-b", self.branch, self.repository_url, self.directory], check=True)
            self.status = 'Cloned'
            db.session.commit()
        except subprocess.CalledProcessError as e:
            self.status = f"Error: {str(e)}"
            db.session.commit()

    def pull_latest(self):
        """Pull the latest changes for the repository."""
        try:
            subprocess.run(["git", "-C", self.directory, "pull", "origin", self.branch], check=True)
            self.status = 'Updated'
            db.session.commit()
        except subprocess.CalledProcessError as e:
            self.status = f"Error: {str(e)}"
            db.session.commit()

    def remove_repo(self):
        """Remove the repository from the server folder."""
        try:
            shutil.rmtree(self.directory)
            self.status = 'Removed'
            db.session.commit()
        except Exception as e:
            self.status = f"Error: {str(e)}"
            db.session.commit()
