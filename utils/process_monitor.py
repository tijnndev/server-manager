"""
Process monitoring utility for detecting crashes and status changes.

This module provides background monitoring for processes to detect crashes
and send notifications.
"""

import threading
import time
from typing import Dict, Set
from models.process import Process
from models.user import User
from utils import get_process_status
from utils.discord import DiscordNotifier, get_user_discord_settings


class ProcessMonitor:
    """Monitor processes for status changes and crashes."""
    
    def __init__(self):
        self.process_statuses: Dict[str, str] = {}
        self.monitoring = False
        self.monitor_thread = None
        self.notified_crashes: Set[str] = set()  # Track which crashes we've already notified
        
    def start_monitoring(self, interval: int = 30):
        """
        Start the background monitoring thread.
        
        Args:
            interval: How often to check process status (in seconds)
        """
        if self.monitoring:
            print("Process monitoring is already running")
            return
            
        self.monitoring = True
        self.monitor_thread = threading.Thread(
            target=self._monitor_loop,
            args=(interval,),
            daemon=True
        )
        self.monitor_thread.start()
        print(f"Process monitoring started with {interval}s interval")
        
    def stop_monitoring(self):
        """Stop the background monitoring thread."""
        self.monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        print("Process monitoring stopped")
        
    def _monitor_loop(self, interval: int):
        """Main monitoring loop that runs in background thread."""
        while self.monitoring:
            try:
                self._check_all_processes()
            except Exception as e:
                print(f"Error in process monitoring loop: {e}")
            
            time.sleep(interval)
            
    def _check_all_processes(self):
        """Check all processes for status changes."""
        try:
            from db import db
            
            # Get all processes from database
            processes = Process.query.all()
            
            for process in processes:
                try:
                    self._check_process(process)
                except Exception as e:
                    print(f"Error checking process {process.name}: {e}")
                    
        except Exception as e:
            print(f"Error querying processes: {e}")
            
    def _check_process(self, process: Process):
        """
        Check a single process for status changes.
        
        Args:
            process: The Process model instance to check
        """
        process_name = process.name
        
        # Get current status
        status_response = get_process_status(process_name)
        if "error" in status_response:
            current_status = "Error"
        else:
            current_status = status_response.get("status", "Unknown")
            
        # Map statuses to simplified versions
        if current_status == "Container Not Running":
            current_status = "Exited"
            
        # Get previous status
        previous_status = self.process_statuses.get(process_name)
        
        # Update status cache
        self.process_statuses[process_name] = current_status
        
        # If this is the first check for this process, don't notify
        if previous_status is None:
            return
            
        # Detect crash: Running -> Exited/Error/Process Stopped
        crash_statuses = ["Exited", "Error", "Process Stopped"]
        if previous_status == "Running" and current_status in crash_statuses:
            self._handle_crash(process, current_status)
            
        # If process comes back up, clear it from notified crashes
        if previous_status in crash_statuses and current_status == "Running":
            crash_key = f"{process_name}:{previous_status}"
            if crash_key in self.notified_crashes:
                self.notified_crashes.remove(crash_key)
                print(f"Process {process_name} recovered from {previous_status}")
                
    def _handle_crash(self, process: Process, crash_status: str):
        """
        Handle a detected process crash.
        
        Args:
            process: The crashed process
            crash_status: The status indicating crash
        """
        process_name = process.name
        crash_key = f"{process_name}:{crash_status}"
        
        # Don't notify multiple times for the same crash
        if crash_key in self.notified_crashes:
            return
            
        self.notified_crashes.add(crash_key)
        
        print(f"CRASH DETECTED: Process '{process_name}' changed to {crash_status}")
        
        # Try to get error logs
        error_message = None
        try:
            import subprocess
            import os
            from extra import get_project_root
            
            BASE_DIR = get_project_root()
            ACTIVE_SERVERS_DIR = os.path.join(BASE_DIR, 'active-servers')
            process_dir = os.path.join(ACTIVE_SERVERS_DIR, process_name)
            
            if os.path.exists(process_dir):
                # Get last 10 lines of logs for error context
                result = subprocess.run(
                    ['docker-compose', 'logs', '--tail', '10', '--no-log-prefix'],
                    capture_output=True,
                    text=True,
                    cwd=process_dir,
                    timeout=5
                )
                if result.stdout:
                    error_message = result.stdout.strip()
        except Exception as e:
            print(f"Could not retrieve error logs for {process_name}: {e}")
            
        # Send Discord notification
        try:
            discord_settings = get_user_discord_settings(process.owner_id)
            if discord_settings and discord_settings.get('notify_crashes'):
                user = User.query.get(process.owner_id)
                
                success = DiscordNotifier.notify_process_crash(
                    webhook_url=discord_settings['webhook_url'],
                    process_name=process_name,
                    process_type=process.type,
                    user=user.username if user else 'Unknown',
                    error_message=error_message
                )
                
                if success:
                    print(f"Sent Discord crash notification for {process_name}")
                else:
                    print(f"Failed to send Discord crash notification for {process_name}")
        except Exception as e:
            print(f"Error sending Discord notification for {process_name}: {e}")


# Global monitor instance
_monitor_instance = None


def get_monitor() -> ProcessMonitor:
    """Get or create the global process monitor instance."""
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = ProcessMonitor()
    return _monitor_instance


def start_process_monitoring(interval: int = 30):
    """
    Start process monitoring in the background.
    
    Args:
        interval: Check interval in seconds (default: 30)
    """
    monitor = get_monitor()
    monitor.start_monitoring(interval)


def stop_process_monitoring():
    """Stop the background process monitoring."""
    monitor = get_monitor()
    monitor.stop_monitoring()
