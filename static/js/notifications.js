/**
 * Notification and Toast System
 * Handles toast notifications, notification center, and undo actions
 */

class NotificationManager {
    constructor() {
        this.notifications = [];
        this.maxNotifications = 50;
        this.initializeDOM();
        this.loadNotifications();
    }

    initializeDOM() {
        // Create toast container
        if (!document.getElementById('toast-container')) {
            const toastContainer = document.createElement('div');
            toastContainer.id = 'toast-container';
            toastContainer.className = 'toast-container';
            document.body.appendChild(toastContainer);
        }

        // Create notification center
        if (!document.getElementById('notification-center')) {
            const notificationCenter = document.createElement('div');
            notificationCenter.id = 'notification-center';
            notificationCenter.className = 'notification-center';
            notificationCenter.innerHTML = `
                <div class="notification-header">
                    <h3><i class="bi bi-bell"></i> Notifications</h3>
                    <div class="notification-actions">
                        <button onclick="notificationManager.clearAll()" class="btn btn-sm btn-secondary">
                            <i class="bi bi-trash"></i> Clear All
                        </button>
                        <button onclick="notificationManager.toggleCenter()" class="btn btn-sm btn-secondary">
                            <i class="bi bi-x"></i>
                        </button>
                    </div>
                </div>
                <div class="notification-list" id="notification-list"></div>
            `;
            document.body.appendChild(notificationCenter);
        }

        // Create notification bell button
        if (!document.querySelector('.notification-bell')) {
            const bell = document.createElement('li');
            bell.innerHTML = `
                <a class="nav-link notification-bell" href="#" onclick="notificationManager.toggleCenter(); return false;">
                    <i class="bi bi-bell"></i>
                    <span class="notification-badge" id="notification-badge">0</span>
                </a>
            `;
            const navbar = document.querySelector('.navbar-nav');
            if (navbar) {
                navbar.insertBefore(bell, navbar.firstChild);
            }
        }
    }

    loadNotifications() {
        const stored = localStorage.getItem('notifications');
        if (stored) {
            this.notifications = JSON.parse(stored);
            this.renderNotifications();
            this.updateBadge();
        }
    }

    saveNotifications() {
        localStorage.setItem('notifications', JSON.stringify(this.notifications));
    }

    showToast(message, type = 'info', duration = 3000, undoCallback = null) {
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        
        // Truncate message if too long (max 200 characters for toast)
        const maxLength = 200;
        const displayMessage = message.length > maxLength 
            ? message.substring(0, maxLength) + '...' 
            : message;
        
        const icon = this.getIcon(type);
        toast.innerHTML = `
            <div class="toast-content">
                <i class="${icon}"></i>
                <span class="toast-message" title="${this.escapeHtml(message)}">${this.escapeHtml(displayMessage)}</span>
            </div>
            ${undoCallback ? '<button class="toast-undo" onclick="this.parentElement.undoAction()">Undo</button>' : ''}
            <button class="toast-close" onclick="this.parentElement.remove()">
                <i class="bi bi-x"></i>
            </button>
        `;

        if (undoCallback) {
            toast.undoAction = () => {
                undoCallback();
                toast.remove();
            };
        }

        const container = document.getElementById('toast-container');
        container.appendChild(toast);

        // Animate in
        setTimeout(() => toast.classList.add('show'), 10);

        // Auto remove
        if (duration > 0) {
            setTimeout(() => {
                toast.classList.remove('show');
                setTimeout(() => toast.remove(), 300);
            }, duration);
        }

        // Add to notification center (with full message)
        this.addNotification({
            message,
            type,
            timestamp: new Date().toISOString()
        });

        return toast;
    }

    escapeHtml(text) {
        const map = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#039;'
        };
        return text.replace(/[&<>"']/g, m => map[m]);
    }

    getIcon(type) {
        const icons = {
            success: 'bi bi-check-circle-fill',
            error: 'bi bi-exclamation-circle-fill',
            warning: 'bi bi-exclamation-triangle-fill',
            info: 'bi bi-info-circle-fill'
        };
        return icons[type] || icons.info;
    }

    addNotification(notification) {
        this.notifications.unshift(notification);
        if (this.notifications.length > this.maxNotifications) {
            this.notifications = this.notifications.slice(0, this.maxNotifications);
        }
        this.saveNotifications();
        this.renderNotifications();
        this.updateBadge();
    }

    renderNotifications() {
        const list = document.getElementById('notification-list');
        if (!list) return;

        if (this.notifications.length === 0) {
            list.innerHTML = '<div class="notification-empty">No notifications</div>';
            return;
        }

        list.innerHTML = this.notifications.map(notif => {
            // Truncate long messages in notification center (max 300 characters)
            const maxLength = 300;
            const displayMessage = notif.message.length > maxLength 
                ? notif.message.substring(0, maxLength) + '...' 
                : notif.message;
            
            return `
                <div class="notification-item notification-${notif.type}">
                    <i class="${this.getIcon(notif.type)}"></i>
                    <div class="notification-content">
                        <div class="notification-message" title="${this.escapeHtml(notif.message)}">${this.escapeHtml(displayMessage)}</div>
                        <div class="notification-time">${this.formatTime(notif.timestamp)}</div>
                    </div>
                </div>
            `;
        }).join('');
    }

    formatTime(timestamp) {
        const date = new Date(timestamp);
        const now = new Date();
        const diff = now - date;
        const seconds = Math.floor(diff / 1000);
        const minutes = Math.floor(seconds / 60);
        const hours = Math.floor(minutes / 60);
        const days = Math.floor(hours / 24);

        if (seconds < 60) return 'Just now';
        if (minutes < 60) return `${minutes} minute${minutes > 1 ? 's' : ''} ago`;
        if (hours < 24) return `${hours} hour${hours > 1 ? 's' : ''} ago`;
        if (days < 7) return `${days} day${days > 1 ? 's' : ''} ago`;
        return date.toLocaleDateString();
    }

    toggleCenter() {
        const center = document.getElementById('notification-center');
        center.classList.toggle('show');
    }

    clearAll() {
        if (confirm('Clear all notifications?')) {
            this.notifications = [];
            this.saveNotifications();
            this.renderNotifications();
            this.updateBadge();
        }
    }

    updateBadge() {
        const badge = document.getElementById('notification-badge');
        if (badge) {
            const count = this.notifications.length;
            badge.textContent = count > 99 ? '99+' : count;
            badge.style.display = count > 0 ? 'block' : 'none';
        }
    }
}

// Initialize global notification manager
let notificationManager = null;

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() {
        notificationManager = new NotificationManager();
    });
} else {
    // DOM already loaded
    notificationManager = new NotificationManager();
}

// Helper functions for easy access
function showToast(message, type = 'info', duration = 3000) {
    if (!notificationManager) {
        console.error('NotificationManager not initialized yet');
        return;
    }
    return notificationManager.showToast(message, type, duration);
}

function showToastWithUndo(message, undoCallback, type = 'info', duration = 5000) {
    if (!notificationManager) {
        console.error('NotificationManager not initialized yet');
        return;
    }
    return notificationManager.showToast(message, type, duration, undoCallback);
}

function showSuccess(message, duration = 3000) {
    if (!notificationManager) {
        console.error('NotificationManager not initialized yet');
        return;
    }
    return notificationManager.showToast(message, 'success', duration);
}

function showError(message, duration = 5000) {
    if (!notificationManager) {
        console.error('NotificationManager not initialized yet');
        return;
    }
    return notificationManager.showToast(message, 'error', duration);
}

function showWarning(message, duration = 4000) {
    if (!notificationManager) {
        console.error('NotificationManager not initialized yet');
        return;
    }
    return notificationManager.showToast(message, 'warning', duration);
}

function showInfo(message, duration = 3000) {
    if (!notificationManager) {
        console.error('NotificationManager not initialized yet');
        return;
    }
    return notificationManager.showToast(message, 'info', duration);
}

function showConfirmation(message, onConfirm, onCancel = null) {
    const overlay = document.createElement('div');
    overlay.className = 'confirmation-overlay';
    overlay.innerHTML = `
        <div class="confirmation-dialog">
            <div class="confirmation-message">${message}</div>
            <div class="confirmation-actions">
                <button class="btn btn-secondary" id="confirm-cancel">Cancel</button>
                <button class="btn btn-danger" id="confirm-ok">Confirm</button>
            </div>
        </div>
    `;
    
    document.body.appendChild(overlay);
    
    // Animate in
    setTimeout(() => overlay.classList.add('show'), 10);
    
    // Handle buttons
    document.getElementById('confirm-ok').onclick = () => {
        overlay.classList.remove('show');
        setTimeout(() => overlay.remove(), 300);
        if (onConfirm) onConfirm();
    };
    
    document.getElementById('confirm-cancel').onclick = () => {
        overlay.classList.remove('show');
        setTimeout(() => overlay.remove(), 300);
        if (onCancel) onCancel();
    };
}
