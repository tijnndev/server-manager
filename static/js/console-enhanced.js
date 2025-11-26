/**
 * Enhanced Console Features
 * - Log filtering and search
 * - Log level badges
 * - Command history
 * - Timestamps toggle
 * - Jump to bottom
 * - Log export
 * - Command execution time tracking
 */

class EnhancedConsole {
    constructor(processName) {
        this.processName = processName;
        this.commandHistory = this.loadCommandHistory();
        this.historyIndex = -1;
        this.currentCommand = '';
        this.logBuffer = [];
        this.filteredLogs = [];
        this.filters = {
            severity: 'all',
            search: '',
            timeRange: 'all'
        };
        this.showTimestamps = this.loadTimestampPreference();
        this.autoScroll = true;
        this.commandStartTime = null;
        this.newLogsCount = 0;
        this.initializeUI();
        this.setupEventListeners();
    }

    initializeUI() {
        const consoleCard = document.querySelector('.card');
        if (!consoleCard) return;

        // Add console toolbar
        const toolbar = document.createElement('div');
        toolbar.className = 'console-toolbar';
        toolbar.innerHTML = `
            <div class="console-toolbar-left">
                <div class="filter-group">
                    <label><i class="bi bi-funnel"></i> Filter:</label>
                    <select id="severity-filter" class="form-control form-control-sm">
                        <option value="all">All Levels</option>
                        <option value="error">Errors</option>
                        <option value="warn">Warnings</option>
                        <option value="info">Info</option>
                    </select>
                </div>
                <div class="filter-group">
                    <input 
                        type="text" 
                        id="log-search" 
                        class="form-control form-control-sm" 
                        placeholder="Search logs..."
                        style="width: 200px;"
                    >
                </div>
                <button class="btn btn-sm btn-secondary" id="clear-search" title="Clear search">
                    <i class="bi bi-x"></i>
                </button>
            </div>
            <div class="console-toolbar-right">
                <button class="btn btn-sm btn-secondary" id="toggle-timestamps" title="Toggle timestamps">
                    <i class="bi bi-clock"></i> ${this.showTimestamps ? 'Hide' : 'Show'} Timestamps
                </button>
                <button class="btn btn-sm btn-info" id="export-logs" title="Export logs">
                    <i class="bi bi-download"></i> Export
                </button>
                <button class="btn btn-sm btn-warning" id="jump-to-bottom" style="display: none;" title="Jump to bottom">
                    <i class="bi bi-arrow-down"></i> New Logs
                    <span class="new-logs-badge" id="new-logs-count">0</span>
                </button>
            </div>
        `;

        const cardHeader = consoleCard.querySelector('.card-header');
        cardHeader.after(toolbar);

        // Add styles
        this.addStyles();
    }

    addStyles() {
        if (document.getElementById('console-enhanced-styles')) return;

        const style = document.createElement('style');
        style.id = 'console-enhanced-styles';
        style.textContent = `
            .console-toolbar {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 12px 20px;
                background: var(--bg-tertiary);
                border-bottom: 1px solid var(--border-color);
                flex-wrap: wrap;
                gap: 12px;
            }

            .console-toolbar-left,
            .console-toolbar-right {
                display: flex;
                align-items: center;
                gap: 12px;
                flex-wrap: wrap;
            }

            .filter-group {
                display: flex;
                align-items: center;
                gap: 8px;
            }

            .filter-group label {
                margin: 0;
                font-size: 13px;
                color: var(--text-secondary);
                white-space: nowrap;
            }

            .log-line {
                padding: 6px 0;
                border-left: 3px solid transparent;
                padding-left: 12px;
                line-height: 1.6;
                transition: all 0.2s;
            }

            .log-line:hover {
                background: rgba(255, 255, 255, 0.03);
                border-left-color: var(--accent-blue);
            }

            .log-line.log-error {
                border-left-color: var(--accent-red);
                background: rgba(239, 68, 68, 0.05);
            }

            .log-line.log-warn {
                border-left-color: var(--accent-yellow);
                background: rgba(245, 158, 11, 0.05);
            }

            .log-line.log-info {
                border-left-color: var(--accent-blue);
            }

            .log-badge {
                display: inline-block;
                padding: 2px 8px;
                border-radius: 4px;
                font-size: 10px;
                font-weight: 600;
                margin-right: 8px;
                text-transform: uppercase;
            }

            .log-badge.badge-error {
                background: var(--accent-red);
                color: white;
            }

            .log-badge.badge-warn {
                background: var(--accent-yellow);
                color: #000;
            }

            .log-badge.badge-info {
                background: var(--accent-blue);
                color: white;
            }

            .log-timestamp {
                color: var(--text-muted);
                font-size: 12px;
                margin-right: 8px;
            }

            .log-timestamp.hidden {
                display: none;
            }

            .command-time {
                display: inline-block;
                margin-left: 8px;
                color: var(--accent-green);
                font-size: 11px;
            }

            .log-highlight {
                background: rgba(59, 130, 246, 0.3);
                padding: 2px 4px;
                border-radius: 2px;
            }

            .new-logs-badge {
                display: inline-block;
                background: var(--accent-red);
                color: white;
                border-radius: 10px;
                padding: 2px 8px;
                font-size: 11px;
                font-weight: 600;
                margin-left: 8px;
                min-width: 20px;
                text-align: center;
            }

            @media (max-width: 768px) {
                .console-toolbar {
                    flex-direction: column;
                    align-items: stretch;
                }

                .console-toolbar-left,
                .console-toolbar-right {
                    width: 100%;
                    justify-content: space-between;
                }

                .filter-group {
                    flex: 1;
                }

                .filter-group input,
                .filter-group select {
                    width: 100%;
                }
            }
        `;
        document.head.appendChild(style);
    }

    setupEventListeners() {
        // Command history navigation
        const commandInput = document.getElementById('command-input');
        if (commandInput) {
            commandInput.addEventListener('keydown', (e) => {
                if (e.key === 'ArrowUp') {
                    e.preventDefault();
                    this.navigateHistory('up');
                } else if (e.key === 'ArrowDown') {
                    e.preventDefault();
                    this.navigateHistory('down');
                } else if (e.key === 'Enter') {
                    this.currentCommand = '';
                    this.historyIndex = -1;
                }
            });

            commandInput.addEventListener('input', (e) => {
                if (this.historyIndex === -1) {
                    this.currentCommand = e.target.value;
                }
            });
        }

        // Filter controls
        const severityFilter = document.getElementById('severity-filter');
        if (severityFilter) {
            severityFilter.addEventListener('change', (e) => {
                this.filters.severity = e.target.value;
                this.applyFilters();
            });
        }

        const logSearch = document.getElementById('log-search');
        if (logSearch) {
            logSearch.addEventListener('input', (e) => {
                this.filters.search = e.target.value;
                this.applyFilters();
            });
        }

        const clearSearch = document.getElementById('clear-search');
        if (clearSearch) {
            clearSearch.addEventListener('click', () => {
                logSearch.value = '';
                this.filters.search = '';
                this.applyFilters();
            });
        }

        // Timestamps toggle
        const toggleTimestamps = document.getElementById('toggle-timestamps');
        if (toggleTimestamps) {
            toggleTimestamps.addEventListener('click', () => {
                this.showTimestamps = !this.showTimestamps;
                this.saveTimestampPreference();
                this.updateTimestampDisplay();
                toggleTimestamps.innerHTML = `<i class="bi bi-clock"></i> ${this.showTimestamps ? 'Hide' : 'Show'} Timestamps`;
            });
        }

        // Export logs
        const exportBtn = document.getElementById('export-logs');
        if (exportBtn) {
            exportBtn.addEventListener('click', () => this.exportLogs());
        }

        // Jump to bottom
        const jumpBtn = document.getElementById('jump-to-bottom');
        if (jumpBtn) {
            jumpBtn.addEventListener('click', () => {
                const consoleOutput = document.getElementById('console-output');
                consoleOutput.scrollTop = consoleOutput.scrollHeight;
                jumpBtn.style.display = 'none';
                this.autoScroll = true;
                this.newLogsCount = 0;
                this.updateNewLogsCount();
            });
        }

        // Scroll detection
        const consoleOutput = document.getElementById('console-output');
        if (consoleOutput) {
            consoleOutput.addEventListener('scroll', () => {
                const isAtBottom = consoleOutput.scrollHeight - consoleOutput.scrollTop <= consoleOutput.clientHeight + 50;
                this.autoScroll = isAtBottom;
                if (jumpBtn) {
                    jumpBtn.style.display = isAtBottom ? 'none' : 'block';
                    if (isAtBottom) {
                        this.newLogsCount = 0;
                        this.updateNewLogsCount();
                    }
                }
            });
        }
    }

    updateNewLogsCount() {
        const badge = document.getElementById('new-logs-count');
        if (badge) {
            badge.textContent = this.newLogsCount;
            badge.style.display = this.newLogsCount > 0 ? 'inline-block' : 'none';
        }
    }

    incrementNewLogs() {
        if (!this.autoScroll) {
            this.newLogsCount++;
            this.updateNewLogsCount();
        }
    }

    navigateHistory(direction) {
        const commandInput = document.getElementById('command-input');
        if (!commandInput) return;

        if (direction === 'up') {
            if (this.historyIndex < this.commandHistory.length - 1) {
                if (this.historyIndex === -1) {
                    this.currentCommand = commandInput.value;
                }
                this.historyIndex++;
                commandInput.value = this.commandHistory[this.historyIndex];
            }
        } else if (direction === 'down') {
            if (this.historyIndex > 0) {
                this.historyIndex--;
                commandInput.value = this.commandHistory[this.historyIndex];
            } else if (this.historyIndex === 0) {
                this.historyIndex = -1;
                commandInput.value = this.currentCommand;
            }
        }
    }

    addCommandToHistory(command) {
        if (!command.trim()) return;
        
        // Remove if already exists
        const index = this.commandHistory.indexOf(command);
        if (index > -1) {
            this.commandHistory.splice(index, 1);
        }
        
        // Add to beginning
        this.commandHistory.unshift(command);
        
        // Limit history size
        if (this.commandHistory.length > 100) {
            this.commandHistory = this.commandHistory.slice(0, 100);
        }
        
        this.saveCommandHistory();
        this.historyIndex = -1;
    }

    loadCommandHistory() {
        const key = `console_history_${this.processName}`;
        const stored = localStorage.getItem(key);
        return stored ? JSON.parse(stored) : [];
    }

    saveCommandHistory() {
        const key = `console_history_${this.processName}`;
        localStorage.setItem(key, JSON.stringify(this.commandHistory));
    }

    loadTimestampPreference() {
        const key = `show_timestamps_${this.processName}`;
        const stored = localStorage.getItem(key);
        return stored !== 'false'; // Default to true
    }

    saveTimestampPreference() {
        const key = `show_timestamps_${this.processName}`;
        localStorage.setItem(key, this.showTimestamps.toString());
    }

    updateTimestampDisplay() {
        const timestamps = document.querySelectorAll('.log-timestamp');
        timestamps.forEach(ts => {
            ts.classList.toggle('hidden', !this.showTimestamps);
        });
    }

    parseLogLevel(line) {
        const lowerLine = line.toLowerCase();
        if (lowerLine.includes('[error]') || lowerLine.includes('error:') || lowerLine.includes('exception')) {
            return 'error';
        }
        if (lowerLine.includes('[warn]') || lowerLine.includes('warning:')) {
            return 'warn';
        }
        if (lowerLine.includes('[info]') || lowerLine.includes('info:')) {
            return 'info';
        }
        return null;
    }

    enhanceLogLine(line) {
        const level = this.parseLogLevel(line);
        
        if (!level) return line;

        const badge = `<span class="log-badge badge-${level}">${level}</span>`;
        
        // Replace level indicators with badges
        line = line.replace(/\[(ERROR|error)\]/gi, badge);
        line = line.replace(/\[(WARN|warn|WARNING|warning)\]/gi, badge);
        line = line.replace(/\[(INFO|info)\]/gi, badge);
        
        return line;
    }

    applyFilters() {
        const consoleOutput = document.getElementById('console-output');
        if (!consoleOutput) return;

        const lines = consoleOutput.querySelectorAll('.log-line');
        
        lines.forEach(line => {
            let show = true;
            
            // Severity filter
            if (this.filters.severity !== 'all') {
                const level = line.getAttribute('data-level');
                if (level !== this.filters.severity) {
                    show = false;
                }
            }
            
            // Search filter
            if (this.filters.search) {
                const text = line.textContent.toLowerCase();
                if (!text.includes(this.filters.search.toLowerCase())) {
                    show = false;
                } else if (show) {
                    // Highlight search term
                    this.highlightSearch(line, this.filters.search);
                }
            }
            
            line.style.display = show ? '' : 'none';
        });
    }

    highlightSearch(element, searchTerm) {
        const text = element.innerHTML;
        const regex = new RegExp(`(${searchTerm})`, 'gi');
        element.innerHTML = text.replace(regex, '<span class="log-highlight">$1</span>');
    }

    exportLogs() {
        const consoleOutput = document.getElementById('console-output');
        if (!consoleOutput) return;

        const lines = Array.from(consoleOutput.querySelectorAll('.log-line'))
            .filter(line => line.style.display !== 'none')
            .map(line => line.textContent)
            .join('\n');

        const blob = new Blob([lines], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${this.processName}_logs_${new Date().toISOString().split('T')[0]}.txt`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);

        showSuccess('Logs exported successfully');
    }

    trackCommandExecution(command) {
        this.commandStartTime = Date.now();
        this.addCommandToHistory(command);
    }

    showCommandExecutionTime() {
        if (this.commandStartTime) {
            const duration = Date.now() - this.commandStartTime;
            const seconds = (duration / 1000).toFixed(2);
            return `<span class="command-time">(${seconds}s)</span>`;
        }
        return '';
    }

    processLogMessage(message) {
        const level = this.parseLogLevel(message);
        const enhanced = this.enhanceLogLine(message);
        
        return {
            message: enhanced,
            level: level || 'info',
            timestamp: new Date().toISOString()
        };
    }
}

// Initialize when DOM is ready
let enhancedConsole = null;
document.addEventListener('DOMContentLoaded', function() {
    const processName = window.location.pathname.split('/')[3]; // Extract from URL
    if (processName && document.getElementById('console-output')) {
        enhancedConsole = new EnhancedConsole(processName);
    }
});
