# Server Manager Installation Guide

This guide will help you install, configure, and run the Server Manager application on your server. Please follow the steps below to ensure a smooth setup process.

## Prerequisites

Before proceeding, ensure the following are installed on your system:

- **Python 3.9** or newer
- **pip** (Python's package installer)
- **Docker** (if you're using containerized deployment)

You will also need access to the MariaDB server for database setup and configuration.

## Step 1: Clone the Repository

Option 1, install it trough my CDN:
When using this option, you can normally skip any other step, except for the database setup in the .env file and starting the service!
```bash
curl -O https://tijnn.dev/assets/server-manager/run.sh && chmod +x run.sh && sudo ./run.sh
```

Option 2, a non-automatic setup:
```bash
git clone https://your-repository-url.git
cd server-manager
```
## Step 2: Set Up the Virtual Environment

To isolate your dependencies, create a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate  # For Linux/macOS
venv\Scripts\activate     # For Windows
```

Once inside the virtual environment, you can proceed to install the necessary Python dependencies.

## Step 3: Install Required Python Packages

Install all the required Python packages listed in the `requirements.txt` file:

```bash
pip install -r requirements.txt
```

Ensure the following key packages are installed:
- `flask`
- `flask-migrate`
- `flask-sqlalchemy`

## Step 4: Configure the Database

You will need to create and configure a MariaDB database for the application.

### Create the Database

Log in to the MariaDB server:

```bash
mysql -u root -p
```

### Create a Database and User

Run the following SQL commands to create the database and assign privileges to a user:

```sql
CREATE DATABASE server_monitor;
GRANT ALL PRIVILEGES ON server_monitor.* TO 'root'@'localhost' IDENTIFIED BY 'your_password';
FLUSH PRIVILEGES;
EXIT;
```

Replace `'your_password'` with a password of your choice. If you prefer no password for the `root` user, omit the password.

### Modify Database Configuration in `app.py`

Ensure the `SQLALCHEMY_DATABASE_URI` in `app.py` points to your MariaDB server with the correct credentials:

```python
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:your_password@localhost/server_monitor'
```

## Step 5: Initialize the Database

Once the database is created, initialize it with the following command:

```bash
flask db init
```

### Running Migrations

After initializing the database, run the migrations to create the necessary tables:

```bash
flask db migrate
flask db upgrade
```

This will create the necessary tables and schema in the `server_monitor` database.

## Step 6: Set Up Docker (Optional)

If you are running the app in a Docker container, use the provided `Dockerfile` to build and run the app.

### Build the Docker Image

```bash
docker build -t server-manager .
```

### Run the Docker Container

```bash
docker run -p 8003:8003 server-manager
```

The app will be accessible at `http://localhost:8003`.

### Important Dockerfile Notes

In the provided `Dockerfile`, the port is set to `8003` using the `EXPOSE` directive:

```dockerfile
EXPOSE 8003
```

The Flask app will automatically use the port specified in the Docker container or by the environment variable `FLASK_PORT`. You can change this port by modifying the `FLASK_PORT` environment variable in the Dockerfile or when running the container.

## Step 7: Access the Application

Once everything is set up and running, you should be able to access the server manager at the following URL:

- **For Docker-based deployment**: `http://localhost:8003`
- **For local deployment**: `http://localhost:5000` (if you are not using Docker)

## Troubleshooting

### Issue: "Access Denied for User"

If you encounter the error:

```bash
sqlalchemy.exc.OperationalError: (pymysql.err.OperationalError) (1045, "Access denied for user 'root'@'localhost' (using password: NO)")
```

Make sure that the MariaDB user `root` has the appropriate privileges and password. You may need to adjust the credentials in `app.py` to match the user you've created. Also make sure the database is already created!

### Issue: Docker "Failed to start docker.service"

If you receive an error when trying to start Docker, you may need to install Docker properly by following [Docker's official installation instructions](https://docs.docker.com/engine/install/).