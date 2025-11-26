/**
 * Swipe Gesture Handler for Mobile
 * Adds swipe support for common actions
 */

class SwipeHandler {
    constructor(element, options = {}) {
        this.element = element;
        this.options = {
            threshold: options.threshold || 50, // minimum distance for swipe
            restraint: options.restraint || 100, // maximum distance perpendicular
            allowedTime: options.allowedTime || 500, // maximum time for swipe
            ...options
        };

        this.startX = 0;
        this.startY = 0;
        this.distX = 0;
        this.distY = 0;
        this.startTime = 0;
        this.elapsedTime = 0;

        this.init();
    }

    init() {
        this.element.addEventListener('touchstart', (e) => this.handleTouchStart(e), false);
        this.element.addEventListener('touchmove', (e) => this.handleTouchMove(e), false);
        this.element.addEventListener('touchend', (e) => this.handleTouchEnd(e), false);
    }

    handleTouchStart(e) {
        const touchObj = e.changedTouches[0];
        this.startX = touchObj.pageX;
        this.startY = touchObj.pageY;
        this.startTime = new Date().getTime();
    }

    handleTouchMove(e) {
        // Prevent default behavior for horizontal swipes
        const touchObj = e.changedTouches[0];
        this.distX = touchObj.pageX - this.startX;
        this.distY = touchObj.pageY - this.startY;

        // If swiping horizontally, prevent vertical scroll
        if (Math.abs(this.distX) > Math.abs(this.distY)) {
            e.preventDefault();
        }
    }

    handleTouchEnd(e) {
        const touchObj = e.changedTouches[0];
        this.distX = touchObj.pageX - this.startX;
        this.distY = touchObj.pageY - this.startY;
        this.elapsedTime = new Date().getTime() - this.startTime;

        // Check if swipe meets criteria
        if (this.elapsedTime <= this.options.allowedTime) {
            if (Math.abs(this.distX) >= this.options.threshold && Math.abs(this.distY) <= this.options.restraint) {
                const direction = this.distX < 0 ? 'left' : 'right';
                this.triggerSwipe(direction);
            } else if (Math.abs(this.distY) >= this.options.threshold && Math.abs(this.distX) <= this.options.restraint) {
                const direction = this.distY < 0 ? 'up' : 'down';
                this.triggerSwipe(direction);
            }
        }
    }

    triggerSwipe(direction) {
        const event = new CustomEvent('swipe', {
            detail: {
                direction: direction,
                distance: direction === 'left' || direction === 'right' ? Math.abs(this.distX) : Math.abs(this.distY),
                duration: this.elapsedTime
            }
        });
        this.element.dispatchEvent(event);
    }
}

// Initialize swipe gestures for mobile
if ('ontouchstart' in window) {
    document.addEventListener('DOMContentLoaded', function() {
        // Swipe to open/close mobile menu
        const navbar = document.querySelector('.navbar');
        if (navbar) {
            const navSwipe = new SwipeHandler(navbar);
            navbar.addEventListener('swipe', (e) => {
                if (e.detail.direction === 'right') {
                    toggleMobileMenu();
                }
            });
        }

        // Swipe on notification center
        const notificationCenter = document.getElementById('notification-center');
        if (notificationCenter) {
            const notifSwipe = new SwipeHandler(notificationCenter);
            notificationCenter.addEventListener('swipe', (e) => {
                if (e.detail.direction === 'right') {
                    notificationManager.toggleCenter();
                }
            });
        }

        // Swipe on console to refresh or clear
        const consoleOutput = document.getElementById('console-output');
        if (consoleOutput) {
            const consoleSwipe = new SwipeHandler(consoleOutput, { threshold: 100 });
            consoleOutput.addEventListener('swipe', (e) => {
                if (e.detail.direction === 'down' && consoleOutput.scrollTop === 0) {
                    // Pull down to refresh logs
                    showInfo('Refreshing logs...');
                    if (typeof refreshLogs === 'function') {
                        refreshLogs(false);
                    }
                } else if (e.detail.direction === 'left') {
                    // Swipe left to clear search filter
                    const searchInput = document.getElementById('log-search');
                    if (searchInput && searchInput.value) {
                        searchInput.value = '';
                        if (enhancedConsole) {
                            enhancedConsole.filters.search = '';
                            enhancedConsole.applyFilters();
                        }
                        showSuccess('Search cleared');
                    }
                }
            });
        }

        // Swipe on file manager rows for quick actions
        const fileRows = document.querySelectorAll('tbody tr');
        fileRows.forEach(row => {
            const rowSwipe = new SwipeHandler(row);
            row.addEventListener('swipe', (e) => {
                if (e.detail.direction === 'left') {
                    // Swipe left to reveal delete button
                    const deleteBtn = row.querySelector('button[type="submit"]');
                    if (deleteBtn) {
                        deleteBtn.style.transform = 'scale(1.1)';
                        deleteBtn.style.transition = 'transform 0.3s';
                        setTimeout(() => {
                            deleteBtn.style.transform = 'scale(1)';
                        }, 300);
                    }
                } else if (e.detail.direction === 'right') {
                    // Swipe right to open file
                    const link = row.querySelector('td:nth-child(2) a');
                    if (link) {
                        window.location.href = link.href;
                    }
                }
            });
        });

        // Swipe on recent files panel
        const recentPanel = document.getElementById('recent-files-panel');
        if (recentPanel) {
            const recentSwipe = new SwipeHandler(recentPanel);
            recentPanel.addEventListener('swipe', (e) => {
                if (e.detail.direction === 'right') {
                    if (fileManager) {
                        fileManager.toggleRecentFiles();
                    }
                }
            });
        }

        // Add visual feedback for swipes
        addSwipeIndicators();
    });
}

function addSwipeIndicators() {
    const style = document.createElement('style');
    style.textContent = `
        .swipe-indicator {
            position: fixed;
            top: 50%;
            transform: translateY(-50%);
            font-size: 48px;
            color: var(--accent-blue);
            opacity: 0;
            transition: opacity 0.3s;
            pointer-events: none;
            z-index: 10000;
        }

        .swipe-indicator.left {
            left: 20px;
        }

        .swipe-indicator.right {
            right: 20px;
        }

        .swipe-indicator.show {
            opacity: 0.7;
        }

        .swipe-hint {
            position: fixed;
            bottom: 20px;
            left: 50%;
            transform: translateX(-50%);
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            padding: 12px 20px;
            border-radius: 8px;
            font-size: 13px;
            color: var(--text-secondary);
            opacity: 0;
            transition: opacity 0.3s;
            pointer-events: none;
            z-index: 10000;
        }

        .swipe-hint.show {
            opacity: 1;
        }
    `;
    document.head.appendChild(style);

    // Show swipe hints for first-time mobile users
    const hasSeenHint = localStorage.getItem('swipe_hint_seen');
    if (!hasSeenHint && 'ontouchstart' in window) {
        setTimeout(() => {
            showSwipeHint('Swipe right on menu bar to open navigation');
            localStorage.setItem('swipe_hint_seen', 'true');
        }, 2000);
    }
}

function showSwipeHint(message) {
    let hint = document.getElementById('swipe-hint');
    if (!hint) {
        hint = document.createElement('div');
        hint.id = 'swipe-hint';
        hint.className = 'swipe-hint';
        document.body.appendChild(hint);
    }

    hint.textContent = message;
    hint.classList.add('show');

    setTimeout(() => {
        hint.classList.remove('show');
    }, 3000);
}

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = SwipeHandler;
}
