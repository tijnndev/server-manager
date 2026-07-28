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
        // Toast stack — keep off Bootstrap class names; pin with inline styles
        let toastContainer = document.getElementById('app-toast-root');
        if (!toastContainer) {
            toastContainer = document.createElement('div');
            toastContainer.id = 'app-toast-root';
            document.body.appendChild(toastContainer);
        }
        // Remove legacy container if present
        const legacy = document.getElementById('toast-container');
        if (legacy && legacy !== toastContainer) legacy.remove();

        toastContainer.className = 'app-toast-root';
        Object.assign(toastContainer.style, {
            position: 'fixed',
            bottom: '16px',
            right: '16px',
            top: 'auto',
            left: 'auto',
            zIndex: '2147483646',
            display: 'flex',
            flexDirection: 'column',
            gap: '8px',
            width: 'min(320px, calc(100vw - 32px))',
            maxWidth: '320px',
            margin: '0',
            padding: '0',
            pointerEvents: 'none',
            transform: 'none',
            height: 'auto',
        });

        // Create notification center
        if (!document.getElementById('notification-center')) {
            const notificationCenter = document.createElement('div');
            notificationCenter.id = 'notification-center';
            notificationCenter.className = 'notification-center';
            notificationCenter.innerHTML = `
                <div class="notification-header">
                    <span class="notification-title">Activity</span>
                    <div class="notification-actions">
                        <button type="button" class="notification-action" onclick="notificationManager.clearAll()">Clear</button>
                        <button type="button" class="notification-action" onclick="notificationManager.toggleCenter()" aria-label="Close">Close</button>
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
                <a class="nav-link nav-icon-link notification-bell" href="#" onclick="notificationManager.toggleCenter(); return false;" title="Alerts" aria-label="Alerts">
                    <svg class="nav-icon" width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                        <path d="M8 1.75a3.25 3.25 0 0 0-3.25 3.25v1.3c0 .55-.18 1.09-.5 1.54L3.2 9.3A1 1 0 0 0 4.04 10.9h7.92a1 1 0 0 0 .84-1.6l-1.05-1.46a2.75 2.75 0 0 1-.5-1.54V5A3.25 3.25 0 0 0 8 1.75Z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/>
                        <path d="M6.4 12.25a1.75 1.75 0 0 0 3.2 0" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
                    </svg>
                    <span class="nav-link-text">Alerts</span>
                    <span class="notification-dot" id="notification-badge" hidden></span>
                </a>
            `;
            const navbar = document.querySelector('.navbar-nav');
            if (navbar) {
                navbar.insertBefore(bell, navbar.firstChild);
            }
        }

        // Add click-outside-to-close functionality
        this.setupClickOutsideListener();
    }

    setupClickOutsideListener() {
        // Handle click outside to close notification center
        document.addEventListener('click', (event) => {
            const notificationCenter = document.getElementById('notification-center');
            const notificationBell = document.querySelector('.notification-bell');

            // Check if the notification center is currently open
            if (notificationCenter && notificationCenter.classList.contains('show')) {
                // Check if the click was outside the notification center and not on the bell
                const isClickInsideCenter = notificationCenter.contains(event.target);
                const isClickOnBell = notificationBell && notificationBell.contains(event.target);

                if (!isClickInsideCenter && !isClickOnBell) {
                    this.toggleCenter();
                }
            }
        });
    }

    loadNotifications() {
        const stored = localStorage.getItem('notifications');
        if (stored) {
            const parsed = JSON.parse(stored);
            // Ensure legacy notifications gain a read flag
            this.notifications = parsed.map(notif => ({
                ...notif,
                read: notif.read === undefined ? false : notif.read
            }));
            this.renderNotifications();
            this.updateBadge();
        }
    }

    saveNotifications() {
        localStorage.setItem('notifications', JSON.stringify(this.notifications));
    }

    showToast(message, type = 'info', duration = 3000, undoCallback = null) {
        const root = document.getElementById('app-toast-root');
        if (!root) return null;

        const toast = document.createElement('div');
        toast.className = `app-toast app-toast--${type}`;
        toast.setAttribute('role', 'status');

        const maxLength = 140;
        const displayMessage = message.length > maxLength
            ? message.substring(0, maxLength) + '…'
            : message;

        toast.innerHTML = `
            <div class="app-toast__body">
                <span class="app-toast__kind">${this.escapeHtml(type || 'info')}</span>
                <span class="app-toast__msg" title="${this.escapeHtml(message)}">${this.escapeHtml(displayMessage)}</span>
            </div>
            <div class="app-toast__actions">
                ${undoCallback ? '<button type="button" class="app-toast__undo">Undo</button>' : ''}
                <button type="button" class="app-toast__close" aria-label="Dismiss">×</button>
            </div>
        `;

        toast.querySelector('.app-toast__close').addEventListener('click', () => toast.remove());
        if (undoCallback) {
            toast.querySelector('.app-toast__undo').addEventListener('click', () => {
                undoCallback();
                toast.remove();
            });
        }

        root.appendChild(toast);
        requestAnimationFrame(() => toast.classList.add('is-visible'));

        if (duration > 0) {
            setTimeout(() => {
                toast.classList.remove('is-visible');
                setTimeout(() => toast.remove(), 180);
            }, duration);
        }

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
        this.notifications.unshift({ ...notification, read: false });
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

        list.innerHTML = this.notifications.map((notif, index) => {
            const maxLength = 160;
            const displayMessage = notif.message.length > maxLength
                ? notif.message.substring(0, maxLength) + '…'
                : notif.message;

            return `
                <div class="notification-item notification-${notif.type} ${notif.read ? 'notification-read' : ''}">
                    <div class="notification-content">
                        <div class="notification-message" title="${this.escapeHtml(notif.message)}">${this.escapeHtml(displayMessage)}</div>
                        <div class="notification-meta">
                            <span class="notification-kind">${notif.type || 'info'}</span>
                            <span class="notification-time">${this.formatTime(notif.timestamp)}</span>
                        </div>
                    </div>
                    <button type="button" class="notification-delete" onclick="notificationManager.deleteNotification(${index}, event)" aria-label="Dismiss">×</button>
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

        if (seconds < 60) return 'now';
        if (minutes < 60) return `${minutes}m`;
        if (hours < 24) return `${hours}h`;
        if (days < 7) return `${days}d`;
        return date.toLocaleDateString();
    }

    toggleCenter() {
        const center = document.getElementById('notification-center');
        const opening = !center.classList.contains('show');
        center.classList.toggle('show');
        if (opening) this.markAllRead();
    }

    deleteNotification(index, event = null) {
        if (event) {
            event.stopPropagation();
        }
        this.notifications.splice(index, 1);
        this.saveNotifications();
        this.renderNotifications();
        this.updateBadge();
    }

    markAllRead() {
        if (this.notifications.length === 0) return;
        this.notifications = this.notifications.map(notif => ({ ...notif, read: true }));
        this.saveNotifications();
        this.renderNotifications();
        this.updateBadge();
    }

    clearAll() {
        this.notifications = [];
        this.saveNotifications();
        this.renderNotifications();
        this.updateBadge();
    }

    updateBadge() {
        const badge = document.getElementById('notification-badge');
        if (!badge) return;
        const unreadCount = this.notifications.filter(n => !n.read).length;
        // Red indicator when there is at least one unread notification
        if (unreadCount > 0) {
            badge.hidden = false;
            badge.removeAttribute('hidden');
        } else {
            badge.hidden = true;
            badge.setAttribute('hidden', '');
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
function ensureNotificationManager(callback) {
    if (notificationManager) {
        return callback(notificationManager);
    }
    // Manager not ready yet (defer script) — wait briefly
    const start = Date.now();
    const wait = setInterval(() => {
        if (notificationManager) {
            clearInterval(wait);
            callback(notificationManager);
        } else if (Date.now() - start > 3000) {
            clearInterval(wait);
            console.error('NotificationManager not initialized');
        }
    }, 50);
}

function showToast(message, type = 'info', duration = 3000) {
    return ensureNotificationManager((nm) => nm.showToast(message, type, duration));
}

function showToastWithUndo(message, undoCallback, type = 'info', duration = 5000) {
    return ensureNotificationManager((nm) => nm.showToast(message, type, duration, undoCallback));
}

function showSuccess(message, duration = 3000) {
    return ensureNotificationManager((nm) => nm.showToast(message, 'success', duration));
}

function showError(message, duration = 5000) {
    return ensureNotificationManager((nm) => nm.showToast(message, 'error', duration));
}

function showWarning(message, duration = 4000) {
    return ensureNotificationManager((nm) => nm.showToast(message, 'warning', duration));
}

function showInfo(message, duration = 3000) {
    return ensureNotificationManager((nm) => nm.showToast(message, 'info', duration));
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
