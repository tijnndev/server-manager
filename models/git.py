from db import db
import os, subprocess, shutil
import tempfile


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
        """Return the path to the server's directory, ignoring './'."""
        
        project_root = os.path.dirname(os.path.abspath(__file__))
        if self.directory == "./":
            return os.path.join(project_root, 'active-servers', self.process_name)
        return os.path.join(project_root, 'active-servers', self.process_name, self.directory)


    def clone_repo(self):
        """Clones the repository into the server folder, overriding existing files."""
        try:
            os.makedirs(self.server_directory, exist_ok=True)

            with tempfile.TemporaryDirectory() as temp_dir:
                subprocess.run(["git", "clone", "-b", self.branch, self.repository_url, temp_dir], check=True)

                for item in os.listdir(temp_dir):
                    source_path = os.path.join(temp_dir, item)
                    dest_path = os.path.join(self.server_directory, item)

                    if os.path.exists(dest_path):
                        if os.path.isdir(dest_path):
                            shutil.rmtree(dest_path)
                        else:
                            os.remove(dest_path)

                    shutil.move(source_path, dest_path)

            self.status = 'Cloned'
            db.session.commit()

        except subprocess.CalledProcessError as e:
            self.status = f"Error: {str(e)}"
            db.session.commit()


    def pull_latest(self):
        """Pull the latest changes for the repository."""
        try:
            subprocess.run(["git", "-C", self.server_directory, "stash"], check=True)
            subprocess.run(["git", "-C", self.server_directory, "fetch", "origin", self.branch], check=True)

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

            if local_commit == remote_commit:
                self.status = 'Already up to date'
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
            shutil.rmtree(os.path.join(self.server_directory, ".git"))
            self.status = 'Removed'
            db.session.delete(self)
            db.session.commit()
        except Exception as e:
            self.status = f"Error: {str(e)}"
            db.session.commit()
