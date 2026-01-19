"""
Discord Integration Utility Module

This module provides Discord webhook integration for sending notifications
about process crashes, power actions, and other events.
"""

import requests
from datetime import datetime, timezone
from typing import Optional, Dict, Any


class DiscordNotifier:
    """Handles sending notifications to Discord via webhooks."""
    
    @staticmethod
    def send_webhook(webhook_url: str, embed: Dict[str, Any]) -> bool:
        """
        Send a Discord webhook with an embedded message.
        
        Args:
            webhook_url: The Discord webhook URL
            embed: The embed data to send
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not webhook_url or not webhook_url.strip():
            return False
            
        try:
            payload = {
                "embeds": [embed]
            }
            
            response = requests.post(
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            
            return response.status_code == 204
            
        except requests.exceptions.RequestException as e:
            print(f"Discord webhook error: {e}")
            return False
        except Exception as e:
            print(f"Unexpected error sending Discord webhook: {e}")
            return False
    
    @staticmethod
    def notify_process_crash(
        webhook_url: str,
        process_name: str,
        process_type: str,
        user: str,
        error_message: Optional[str] = None
    ) -> bool:
        """
        Send a notification about a process crash.
        
        Args:
            webhook_url: Discord webhook URL
            process_name: Name of the crashed process
            process_type: Type of process (e.g., 'nodejs', 'python')
            user: Username of the process owner
            error_message: Optional error details
            
        Returns:
            bool: True if notification sent successfully
        """
        embed = {
            "title": "🔴 Process Crashed",
            "description": f"Process **{process_name}** has crashed and stopped running.",
            "color": 15158332,  # Red color
            "fields": [
                {
                    "name": "Process Name",
                    "value": process_name,
                    "inline": True
                },
                {
                    "name": "Type",
                    "value": process_type,
                    "inline": True
                },
                {
                    "name": "Owner",
                    "value": user,
                    "inline": True
                }
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {
                "text": "Server Manager"
            }
        }
        
        if error_message:
            embed["fields"].append({
                "name": "Error Details",
                "value": f"```{error_message[:1000]}```",  # Limit to 1000 chars
                "inline": False
            })
        
        return DiscordNotifier.send_webhook(webhook_url, embed)
    
    @staticmethod
    def notify_power_action(
        webhook_url: str,
        action: str,
        process_name: str,
        process_type: str,
        user: str,
        success: bool = True,
        details: Optional[str] = None
    ) -> bool:
        """
        Send a notification about a power action (start, stop, restart).
        
        Args:
            webhook_url: Discord webhook URL
            action: The action performed ('start', 'stop', 'restart')
            process_name: Name of the process
            process_type: Type of process
            user: Username who performed the action
            success: Whether the action was successful
            details: Optional additional details
            
        Returns:
            bool: True if notification sent successfully
        """
        action_emojis = {
            "start": "▶️",
            "started": "▶️",
            "stop": "⏹️",
            "stopped": "⏹️",
            "restart": "🔄",
            "restarted": "🔄",
            "delete": "🗑️",
            "deleted": "🗑️"
        }
        
        action_colors = {
            "start": 3066993,   # Green
            "started": 3066993,
            "stop": 15844367,   # Yellow/Gold
            "stopped": 15844367,
            "restart": 3447003, # Blue
            "restarted": 3447003,
            "delete": 10038562, # Dark gray
            "deleted": 10038562
        }
        
        action_lower = action.lower()
        emoji = action_emojis.get(action_lower, "⚙️")
        color = action_colors.get(action_lower, 9807270) if success else 15158332  # Red if failed
        
        title = f"{emoji} Process {action.capitalize()}"
        if not success:
            title += " Failed"
        
        embed = {
            "title": title,
            "description": f"Process **{process_name}** was {action_lower} by {user}.",
            "color": color,
            "fields": [
                {
                    "name": "Process Name",
                    "value": process_name,
                    "inline": True
                },
                {
                    "name": "Type",
                    "value": process_type,
                    "inline": True
                },
                {
                    "name": "Action By",
                    "value": user,
                    "inline": True
                }
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {
                "text": "Server Manager"
            }
        }
        
        if details:
            embed["fields"].append({
                "name": "Details",
                "value": details[:1000],
                "inline": False
            })
        
        return DiscordNotifier.send_webhook(webhook_url, embed)
    
    @staticmethod
    def notify_process_error(
        webhook_url: str,
        process_name: str,
        process_type: str,
        user: str,
        error_type: str,
        error_message: str
    ) -> bool:
        """
        Send a notification about a process error (not necessarily a crash).
        
        Args:
            webhook_url: Discord webhook URL
            process_name: Name of the process
            process_type: Type of process
            user: Process owner
            error_type: Type/category of error
            error_message: Error message/details
            
        Returns:
            bool: True if notification sent successfully
        """
        embed = {
            "title": "⚠️ Process Error",
            "description": f"An error occurred in process **{process_name}**.",
            "color": 16776960,  # Yellow/warning color
            "fields": [
                {
                    "name": "Process Name",
                    "value": process_name,
                    "inline": True
                },
                {
                    "name": "Type",
                    "value": process_type,
                    "inline": True
                },
                {
                    "name": "Owner",
                    "value": user,
                    "inline": True
                },
                {
                    "name": "Error Type",
                    "value": error_type,
                    "inline": False
                },
                {
                    "name": "Error Message",
                    "value": f"```{error_message[:1000]}```",
                    "inline": False
                }
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {
                "text": "Server Manager"
            }
        }
        
        return DiscordNotifier.send_webhook(webhook_url, embed)


def get_user_discord_settings(user_id: int) -> Optional[Dict[str, Any]]:
    """
    Get Discord settings for a user.
    
    Args:
        user_id: The user ID
        
    Returns:
        Dict with discord settings or None if not configured
    """
    from models.user_settings import UserSettings
    
    try:
        settings = UserSettings.get_or_create(user_id)
        
        if not settings.discord_enabled or not settings.discord_webhook_url:
            return None
            
        return {
            "webhook_url": settings.discord_webhook_url,
            "notify_crashes": settings.discord_notify_crashes,
            "notify_power_actions": settings.discord_notify_power_actions
        }
    except Exception as e:
        print(f"Error getting Discord settings for user {user_id}: {e}")
        return None
