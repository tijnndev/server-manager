from db import db
import os, subprocess, shutil

class GitIntegration(db.Model):
    __tablename__ = 'git_integrations'

    id = db.Column(db.Integer, primary_key=True)
    repository_url = db.Column(db.String(255), nullable=False)
    directory = db.Column(db.String(255), nullable=False)
    process_name = db.Column(db.String(255), nullable=False)
    branch = db.Column(db.String(255), nullable=True, default='main')
    status = db.Column(db.String(255), nullable=False, default='Not Cloned')

    def __init__(self, repository_url, directory, process_name, branch='main', status='Not Cloned'):
        self.repository_url = repository_url
        self.directory = directory
        self.process_name = process_name
        self.branch = branch
        self.status = status

    @property
    def server_directory(self):
        """Return the path to the server's directory."""
        return os.path.join('/etc/server-manager/active-servers', self.process_name, self.directory)

    def clone_repo(self):
        """Clones the repository into the server folder."""
        try:
            os.makedirs(self.server_directory, exist_ok=True)
            subprocess.run(["git", "clone", "-b", self.branch, self.repository_url, self.server_directory], check=True)
            self.status = 'Cloned'
            db.session.commit()
        except subprocess.CalledProcessError as e:
            self.status = f"Error: {str(e)}"
            db.session.commit()

    def pull_latest(self):
        """Pull the latest changes for the repository."""
        try:
            # Fetch the latest changes from the remote without merging
            subprocess.run(["git", "-C", self.server_directory, "fetch", "origin", self.branch], check=True)

            # Get the status of the local and remote branches
            result = subprocess.run(
                ["git", "-C", self.server_directory, "rev-parse", f"HEAD"], 
                capture_output=True, text=True, check=True
            )
            local_commit = result.stdout.strip()

            result = subprocess.run(
                ["git", "-C", self.server_directory, "rev-parse", f"origin/{self.branch}"], 
                capture_output=True, text=True, check=True
            )
            remote_commit = result.stdout.strip()

            # Compare local and remote commits
            if local_commit == remote_commit:
                self.status = 'Up to date'
            else:
                subprocess.run(["git", "-C", self.server_directory, "pull", "origin", self.branch], check=True)
                self.status = 'Updated'

            db.session.commit()

        except subprocess.CalledProcessError as e:
            self.status = f"Error: {str(e)}"
            db.session.commit()

    def remove_repo(self):
        """Remove the repository from the server folder."""
        try:
            shutil.rmtree(self.server_directory)
            self.status = 'Removed'
            db.session.delete(self)
            db.session.commit()
        except Exception as e:
            self.status = f"Error: {str(e)}"
            db.session.commit()
