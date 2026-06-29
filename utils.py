from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import smtplib
from flask import current_app
import os
import subprocess
import string
import importlib
import re
import socket
import dns.resolver
from datetime import datetime
from models.process import Process

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__)))
ACTIVE_SERVERS_DIR = os.path.join(BASE_DIR, "active-servers")


def _runtime():
    from runtime import get_runtime

    return get_runtime()


def _get_container_id(name):
    return _runtime().get_container_id(name)


def get_process_status(name):
    process = find_process_by_name(name)
    if not process:
        return {"error": "Process not found"}
    return _runtime().get_status(name, process.type)


def is_always_running_container(name):
    return _runtime().is_always_running(name)


def check_process_running_in_container(name):
    """Check if the main process is running inside the container."""
    return get_process_status(name)


def start_process_in_container(name):
    process = find_process_by_name(name)
    ptype = process.type if process else None
    return _runtime().start(name, ptype)


def stop_process_in_container(name):
    process = find_process_by_name(name)
    ptype = process.type if process else None
    return _runtime().stop(name, ptype)


def execute_command_in_container(name, command, working_dir="/app", timeout=30):
    process = find_process_by_name(name)
    ptype = process.type if process else None
    return _runtime().execute(name, command, working_dir, timeout, ptype)


def execute_interactive_command_in_container(name, command, working_dir="/app"):
    process = find_process_by_name(name)
    ptype = process.type if process else None
    return _runtime().execute_interactive(name, command, working_dir, ptype)


def find_process_by_name(name):
    with current_app.app_context():
        return Process.query.filter_by(name=name).first()


def find_process_by_id(process_id):
    with current_app.app_context():
        return Process.query.get(process_id)


SMTP_SERVER = os.getenv("MAIL_SERVER", "")
SMTP_PORT = int(os.getenv("MAIL_PORT", "0"))
EMAIL_ADDRESS = os.getenv("MAIL_USERNAME", "")
EMAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")


def send_email(
    to: str, subject: str, body: str, type: str = "auth", attachment: str = ""
):
    message = MIMEMultipart()
    message["From"] = f"Server Manager <{type}@tijnn.dev>"
    message["To"] = to
    message["Subject"] = subject
    message.attach(MIMEText(body, "html"))

    if attachment:
        part = MIMEBase("application", "octet-stream")
        with open(attachment, "rb") as file:
            part.set_payload(file.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f"attachment; filename={attachment}")
        message.attach(part)

    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.sendmail(EMAIL_ADDRESS, to, message.as_string())
            return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False


def generate_random_string(length: int) -> str:
    """Generates a cryptographically secure random string of a specified length."""
    import secrets as _secrets
    alphabet = string.ascii_letters + string.digits
    return "".join(_secrets.choice(alphabet) for _ in range(length))


def generate_reset_email_body(reset_url):
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Password Reset Request</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background-color: #f4f4f4;
                padding: 20px;
                margin: 0;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background-color: #ffffff;
                padding: 20px;
                border-radius: 8px;
                box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
            }}
            h1 {{
                color: #333;
                font-size: 24px;
                margin-bottom: 20px;
            }}
            p {{
                font-size: 16px;
                line-height: 1.5;
                color: #555;
            }}
            .btn {{
                display: inline-block;
                padding: 12px 25px;
                margin-top: 20px;
                background-color: #007bff;
                color: #ffffff;
                text-decoration: none;
                border-radius: 5px;
                font-weight: bold;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Password Reset Request</h1>
            <p>Hello,</p>
            <p>We received a request to reset your password. You can reset your password by clicking the button below:</p>
            <a href="{reset_url}" class="btn">Reset Your Password</a>
            <p>If you did not request a password reset, you can ignore this email.</p>
            <p>Best regards,<br>Your Support Team</p>
        </div>
    </body>
    </html>
    """


def execute_handler(handler_type, function_name, *args, **kwargs):
    try:
        module_name = f"handlers.{handler_type}"
        module = importlib.import_module(module_name)
        function = getattr(module, function_name)
        return function(*args, **kwargs)
    except ModuleNotFoundError:
        raise ImportError(f"Handler '{handler_type}' not found.") from None
    except AttributeError:
        raise AttributeError(
            f"Function '{function_name}' not found in '{handler_type}'."
        ) from None


handlers_folder = os.path.join(os.getcwd(), "handlers")


def find_types():
    types = []

    for _root, _dirs, files in os.walk(handlers_folder):
        for filename in files:
            if filename.endswith(".py") and filename not in types:
                types.append(filename.split(".")[0])

    return types


# ==================== Domain Validation and DNS Health Check Functions ====================


def validate_domain_format(domain):
    """
    Validate domain format with comprehensive checks.
    Returns dict with 'valid' (bool), 'error' (str if invalid), and 'normalized' (str if valid)
    """
    if not domain or not isinstance(domain, str):
        return {"valid": False, "error": "Domain cannot be empty"}

    # Strip whitespace
    domain = domain.strip()

    # Check length (253 chars max for full domain, 63 per label)
    if len(domain) > 253:
        return {"valid": False, "error": "Domain name is too long (max 253 characters)"}

    # Convert to lowercase for consistency
    domain = domain.lower()

    # Support wildcard domains for SSL
    is_wildcard = domain.startswith("*.")
    if is_wildcard:
        domain = domain[2:]  # Remove wildcard for validation

    # Check if domain is empty after removing wildcard
    if not domain:
        return {"valid": False, "error": "Invalid wildcard domain"}

    # Basic regex pattern for domain validation
    # Allows: alphanumeric, hyphens, dots, and IDN (internationalized domain names)
    domain_pattern = re.compile(
        r"^(?:[a-z0-9\u00a1-\uffff](?:[a-z0-9\u00a1-\uffff-]{0,61}[a-z0-9\u00a1-\uffff])?\.)*"
        r"(?:[a-z0-9\u00a1-\uffff](?:[a-z0-9\u00a1-\uffff-]{0,61}[a-z0-9\u00a1-\uffff])?)$",
        re.IGNORECASE,
    )

    if not domain_pattern.match(domain):
        return {
            "valid": False,
            "error": "Invalid domain format. Use only letters, numbers, hyphens, and dots",
        }

    # Check for consecutive dots
    if ".." in domain:
        return {"valid": False, "error": "Domain cannot contain consecutive dots"}

    # Check if starts or ends with hyphen or dot
    if (
        domain.startswith("-")
        or domain.endswith("-")
        or domain.startswith(".")
        or domain.endswith(".")
    ):
        return {
            "valid": False,
            "error": "Domain cannot start or end with hyphen or dot",
        }

    # Split into labels and validate each
    labels = domain.split(".")

    # Need at least 2 labels (domain.tld) unless it's localhost
    if len(labels) < 2 and domain != "localhost":
        return {
            "valid": False,
            "error": "Domain must have at least two parts (e.g., example.com)",
        }

    # Validate each label
    for label in labels:
        if not label:
            return {"valid": False, "error": "Domain contains empty label"}
        if len(label) > 63:
            return {
                "valid": False,
                "error": f"Label '{label}' is too long (max 63 characters)",
            }
        if label.startswith("-") or label.endswith("-"):
            return {
                "valid": False,
                "error": f"Label '{label}' cannot start or end with hyphen",
            }

    # Validate TLD (last label) - should be at least 2 characters and not all numeric
    tld = labels[-1]
    if len(tld) < 2 and domain != "localhost":
        return {
            "valid": False,
            "error": "Top-level domain must be at least 2 characters",
        }

    # TLD should not be all numbers
    if tld.isdigit():
        return {"valid": False, "error": "Top-level domain cannot be all numbers"}

    # Common invalid patterns
    if domain in ["example.com", "example.org", "test.com", "localhost.localdomain"]:
        return {
            "valid": False,
            "error": "Please use a real domain name",
            "warning": True,
        }

    # Return normalized domain (with wildcard if it was present)
    normalized = ("*." + domain) if is_wildcard else domain
    return {"valid": True, "normalized": normalized}


def get_server_ip():
    """Get the server's public IP address"""
    try:
        # Try to get public IP from external service
        import urllib.request

        with urllib.request.urlopen(
            "https://api.ipify.org?format=text", timeout=5
        ) as response:
            public_ip = response.read().decode("utf-8").strip()
            return public_ip
    except Exception:
        pass

    # Fallback: get local network IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        return None


def is_cloudflare_ip(ip_address):
    """
    Check if an IP address belongs to Cloudflare.
    Cloudflare's IP ranges are documented at: https://www.cloudflare.com/ips/
    """
    import ipaddress

    # Cloudflare IPv4 ranges (as of 2024)
    cloudflare_ipv4_ranges = [
        "173.245.48.0/20",
        "103.21.244.0/22",
        "103.22.200.0/22",
        "103.31.4.0/22",
        "141.101.64.0/18",
        "108.162.192.0/18",
        "190.93.240.0/20",
        "188.114.96.0/20",
        "197.234.240.0/22",
        "198.41.128.0/17",
        "162.158.0.0/15",
        "104.16.0.0/13",
        "104.24.0.0/14",
        "172.64.0.0/13",
        "131.0.252.0/22",
    ]

    # Cloudflare IPv6 ranges
    cloudflare_ipv6_ranges = [
        "2400:cb00::/32",
        "2606:4700::/32",
        "2803:f800::/32",
        "2405:b500::/32",
        "2405:8100::/32",
        "2a06:98c0::/29",
        "2c0f:f248::/32",
    ]

    try:
        ip_obj = ipaddress.ip_address(ip_address)

        # Check IPv4 ranges
        if isinstance(ip_obj, ipaddress.IPv4Address):
            for cidr in cloudflare_ipv4_ranges:
                network = ipaddress.ip_network(cidr)
                if ip_obj in network:
                    return True
        # Check IPv6 ranges
        elif isinstance(ip_obj, ipaddress.IPv6Address):
            for cidr in cloudflare_ipv6_ranges:
                network = ipaddress.ip_network(cidr)
                if ip_obj in network:
                    return True

    except ValueError:
        # Invalid IP address format
        pass

    return False


def check_dns_health(domain, server_ip=None):
    """
    Check DNS health for a domain.
    Returns dict with 'status', 'records', 'points_to_server', 'warnings', 'errors'
    """
    if not domain:
        return {"status": "error", "error": "Domain is required"}

    # Validate domain format first
    validation = validate_domain_format(domain)
    if not validation.get("valid"):
        return {"status": "error", "error": validation.get("error")}

    domain = validation.get("normalized", domain).lstrip(
        "*."
    )  # Remove wildcard for DNS check

    # Get server IP if not provided
    if not server_ip:
        server_ip = get_server_ip()

    result = {
        "status": "unknown",
        "domain": domain,
        "server_ip": server_ip,
        "records": {"A": [], "AAAA": [], "CNAME": []},
        "points_to_server": False,
        "points_to_cloudflare": False,
        "warnings": [],
        "errors": [],
    }

    resolver = dns.resolver.Resolver()
    resolver.timeout = 5
    resolver.lifetime = 5

    # Check A records (IPv4)
    try:
        answers = resolver.resolve(domain, "A")
        for rdata in answers:
            ip_address = str(rdata)
            result["records"]["A"].append(ip_address)
            if server_ip and ip_address == server_ip:
                result["points_to_server"] = True
            if is_cloudflare_ip(ip_address):
                result["points_to_cloudflare"] = True
    except dns.resolver.NXDOMAIN:
        result["errors"].append("Domain does not exist (NXDOMAIN)")
        result["status"] = "error"
        return result
    except dns.resolver.NoAnswer:
        result["warnings"].append("No A records found")
    except dns.resolver.Timeout:
        result["errors"].append("DNS query timed out")
        result["status"] = "timeout"
        return result
    except Exception as e:
        result["warnings"].append(f"A record check failed: {str(e)}")

    # Check AAAA records (IPv6)
    try:
        answers = resolver.resolve(domain, "AAAA")
        for rdata in answers:
            ip_address = str(rdata)
            result["records"]["AAAA"].append(ip_address)
            if is_cloudflare_ip(ip_address):
                result["points_to_cloudflare"] = True
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
        pass  # AAAA records are optional
    except Exception:
        pass

    # Check CNAME records
    try:
        answers = resolver.resolve(domain, "CNAME")
        for rdata in answers:
            result["records"]["CNAME"].append(str(rdata))
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
        pass  # CNAME is optional
    except Exception:
        pass

    # Determine overall status
    if result["errors"]:
        result["status"] = "error"
    elif result["points_to_server"]:
        result["status"] = "healthy"
    elif result["points_to_cloudflare"]:
        result["status"] = "healthy"  # Cloudflare is acceptable
        result["warnings"].append(
            "Domain points to Cloudflare CDN (this is normal for proxied domains)"
        )
    elif result["records"]["A"] or result["records"]["AAAA"]:
        result["status"] = "warning"
        result["warnings"].append(
            f"Domain points to {result['records']['A'][0] if result['records']['A'] else result['records']['AAAA'][0]}, not to this server ({server_ip})"
        )
    else:
        result["status"] = "warning"
        result["warnings"].append("No DNS records found for domain")

    return result


def check_ssl_certificate(domain):
    """
    Check SSL certificate status and get expiration information.
    Returns dict with 'exists', 'valid', 'expiration_date', 'days_until_expiry', 'issuer', 'validation_type'
    """
    cert_path = f"/etc/letsencrypt/live/{domain}/fullchain.pem"

    result = {"exists": False, "valid": False, "domain": domain, "errors": []}

    # Check if certificate file exists
    if not os.path.exists(cert_path):
        result["errors"].append("Certificate file not found")
        return result

    result["exists"] = True

    try:
        # Read certificate using openssl
        cmd = [
            "openssl",
            "x509",
            "-in",
            cert_path,
            "-noout",
            "-dates",
            "-issuer",
            "-subject",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)

        output = proc.stdout

        # Parse expiration date
        for line in output.split("\n"):
            if line.startswith("notAfter="):
                date_str = line.replace("notAfter=", "").strip()
                # Parse date format: "Jan 1 00:00:00 2025 GMT"
                expiration_date = datetime.strptime(date_str, "%b %d %H:%M:%S %Y %Z")
                result["expiration_date"] = expiration_date.strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

                # Calculate days until expiry
                days_until_expiry = (expiration_date - datetime.now()).days
                result["days_until_expiry"] = days_until_expiry

                # Determine if valid
                if days_until_expiry > 0:
                    result["valid"] = True
                else:
                    result["valid"] = False
                    result["errors"].append(
                        f"Certificate expired {abs(days_until_expiry)} days ago"
                    )

                # Add warning if expiring soon
                if 0 < days_until_expiry <= 30:
                    result["warning"] = (
                        f"Certificate expires in {days_until_expiry} days"
                    )

            elif line.startswith("notBefore="):
                date_str = line.replace("notBefore=", "").strip()
                issued_date = datetime.strptime(date_str, "%b %d %H:%M:%S %Y %Z")
                result["issued_date"] = issued_date.strftime("%Y-%m-%d")

            elif line.startswith("issuer="):
                issuer = line.replace("issuer=", "").strip()
                result["issuer"] = issuer

                # Determine validation type based on issuer
                if "Let's Encrypt" in issuer or "LE" in issuer:
                    result["validation_type"] = "DV"  # Domain Validation
                    result["issuer_name"] = "Let's Encrypt"
                elif (
                    "DigiCert" in issuer or "GlobalSign" in issuer or "Comodo" in issuer
                ):
                    result["validation_type"] = (
                        "OV/EV"  # Could be Organization or Extended Validation
                    )
                    result["issuer_name"] = (
                        issuer.split("CN=")[1].split(",")[0]
                        if "CN=" in issuer
                        else "Unknown"
                    )
                else:
                    result["validation_type"] = "Unknown"
                    result["issuer_name"] = "Unknown"

        # Check if certificate is for wildcard domain
        cmd_check_cn = ["openssl", "x509", "-in", cert_path, "-noout", "-text"]
        proc_cn = subprocess.run(
            cmd_check_cn, capture_output=True, text=True, check=True
        )

        if "*.%s" % domain in proc_cn.stdout or "*." in proc_cn.stdout:
            result["is_wildcard"] = True
        else:
            result["is_wildcard"] = False

    except subprocess.CalledProcessError as e:
        result["errors"].append(f"Failed to read certificate: {e.stderr}")
    except Exception as e:
        result["errors"].append(f"Error checking certificate: {str(e)}")

    return result


def check_domain_uniqueness(domain, current_process_name=None):
    """
    Check if domain is already used by another process.
    Returns dict with 'unique', 'conflicts' (list of process names using the domain)
    """
    if not domain:
        return {"unique": True, "conflicts": []}

    with current_app.app_context():
        from models.process import Process

        # Query all processes with this domain
        processes = Process.query.filter(Process.domain == domain).all()

        # Filter out current process if specified
        conflicts = [p.name for p in processes if p.name != current_process_name]

        return {"unique": len(conflicts) == 0, "conflicts": conflicts}


def get_domain_status(domain, process_name=None):
    """
    Get comprehensive domain status including validation, DNS health, SSL status, and uniqueness.
    This is the main function to call for complete domain status.
    """
    if not domain:
        return {"status": "empty", "error": "No domain configured"}

    result = {
        "domain": domain,
        "validation": None,
        "dns": None,
        "ssl": None,
        "uniqueness": None,
        "overall_status": "unknown",
    }

    # 1. Validate domain format
    validation = validate_domain_format(domain)
    result["validation"] = validation

    if not validation.get("valid"):
        result["overall_status"] = "invalid"
        return result

    normalized_domain = validation.get("normalized", domain)

    # 2. Check domain uniqueness
    uniqueness = check_domain_uniqueness(normalized_domain, process_name)
    result["uniqueness"] = uniqueness

    # 3. Check DNS health
    dns_status = check_dns_health(normalized_domain)
    result["dns"] = dns_status

    # 4. Check SSL certificate (skip for wildcard domains in DNS)
    check_domain = normalized_domain.lstrip("*.")
    ssl_status = check_ssl_certificate(check_domain)
    result["ssl"] = ssl_status

    # Determine overall status
    if not validation.get("valid"):
        result["overall_status"] = "invalid"
    elif not uniqueness.get("unique"):
        result["overall_status"] = "conflict"
    elif dns_status.get("status") == "error":
        result["overall_status"] = "dns_error"
    elif dns_status.get("status") == "warning" and not dns_status.get(
        "points_to_cloudflare"
    ):
        result["overall_status"] = "dns_warning"
    elif ssl_status.get("exists") and ssl_status.get("valid"):
        result["overall_status"] = "healthy"
    elif ssl_status.get("exists") and not ssl_status.get("valid"):
        result["overall_status"] = "ssl_expired"
    elif dns_status.get("points_to_server") or dns_status.get("points_to_cloudflare"):
        result["overall_status"] = "no_ssl"
    else:
        result["overall_status"] = "needs_configuration"

    return result
