/**
 * Enhanced File Manager
 * - File preview
 * - File search
 * - Recent files
 * - Better file sizes
 * - Friendly dates
 * - File type icons
 * - Rename functionality
 * - Open in new tab
 */

class EnhancedFileManager {
    constructor(processName) {
        this.processName = processName;
        this.recentFiles = this.loadRecentFiles();
        this.selectedFiles = [];
        this.fileTypeIcons = {
            'js': 'bi-filetype-js text-warning',
            'py': 'bi-filetype-py text-info',
            'json': 'bi-filetype-json text-success',
            'md': 'bi-filetype-md text-primary',
            'html': 'bi-filetype-html text-danger',
            'css': 'bi-filetype-css text-primary',
            'txt': 'bi-filetype-txt text-secondary',
            'yml': 'bi-filetype-yml text-warning',
            'yaml': 'bi-filetype-yml text-warning',
            'xml': 'bi-filetype-xml text-warning',
            'jsx': 'bi-filetype-jsx text-info',
            'tsx': 'bi-filetype-tsx text-info',
            'ts': 'bi-filetype-ts text-info',
            'php': 'bi-filetype-php text-purple',
            'sql': 'bi-filetype-sql text-orange',
            'sh': 'bi-terminal text-success',
            'jpg': 'bi-filetype-jpg text-danger',
            'jpeg': 'bi-filetype-jpg text-danger',
            'png': 'bi-filetype-png text-info',
            'gif': 'bi-filetype-gif text-warning',
            'svg': 'bi-filetype-svg text-success',
            'pdf': 'bi-filetype-pdf text-danger',
            'zip': 'bi-file-zip text-warning',
            'default': 'bi-file-text text-muted'
        };
        this.initializeUI();
        this.setupEventListeners();
        this.enhanceFileRows();
    }

    initializeUI() {
        // Add file manager toolbar
        const cardHeader = document.querySelector('.card-header');
        if (!cardHeader) return;

        const toolbar = document.createElement('div');
        toolbar.className = 'file-manager-toolbar';
        toolbar.innerHTML = `
            <div class="toolbar-left">
                <input 
                    type="text" 
                    id="file-search" 
                    class="form-control form-control-sm" 
                    placeholder="Search files..."
                    style="width: 200px;"
                >
            </div>
            <div class="toolbar-right">
                <button class="btn btn-sm btn-info" id="show-recent-files" title="Recent files">
                    <i class="bi bi-clock-history"></i> Recent
                </button>
            </div>
        `;

        cardHeader.after(toolbar);

        // Add file preview modal
        this.createPreviewModal();
        
        // Add rename modal
        this.createRenameModal();

        // Add styles
        this.addStyles();
    }

    addStyles() {
        if (document.getElementById('file-manager-styles')) return;

        const style = document.createElement('style');
        style.id = 'file-manager-styles';
        style.textContent = `
            .file-manager-toolbar {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 12px 20px;
                background: var(--bg-tertiary);
                border-bottom: 1px solid var(--border-color);
                flex-wrap: wrap;
                gap: 12px;
            }

            .toolbar-left, .toolbar-right {
                display: flex;
                align-items: center;
                gap: 12px;
            }

            /* Prominent breadcrumbs */
            .breadcrumb {
                background: var(--bg-secondary);
                padding: 16px 20px;
                margin: 0;
                border-radius: 0;
                border-bottom: 2px solid var(--accent-blue);
                font-size: 14px;
            }

            .breadcrumb-item {
                color: var(--text-secondary);
            }

            .breadcrumb-item.active {
                color: var(--text-primary);
                font-weight: 600;
            }

            .breadcrumb-item a {
                color: var(--accent-blue);
                text-decoration: none;
                transition: all 0.2s;
            }

            .breadcrumb-item a:hover {
                color: var(--accent-blue-hover);
                text-decoration: underline;
            }

            .breadcrumb-item + .breadcrumb-item::before {
                color: var(--text-muted);
            }

            /* File actions */
            .file-actions {
                display: flex;
                gap: 8px;
                opacity: 0;
                transition: opacity 0.2s;
            }

            tr:hover .file-actions {
                opacity: 1;
            }

            .file-icon {
                font-size: 20px;
                margin-right: 8px;
            }

            .file-size-badge {
                display: inline-block;
                padding: 2px 8px;
                background: var(--bg-tertiary);
                border-radius: 4px;
                font-size: 11px;
                font-weight: 600;
                color: var(--text-secondary);
            }

            .file-date-friendly {
                color: var(--text-secondary);
                font-size: 13px;
            }

            /* Preview modal */
            .preview-modal {
                display: none;
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: rgba(0, 0, 0, 0.9);
                z-index: 10000;
                align-items: center;
                justify-content: center;
                padding: 20px;
            }

            .preview-modal.show {
                display: flex;
            }

            .preview-content {
                background: var(--bg-secondary);
                border-radius: 12px;
                max-width: 90%;
                max-height: 90%;
                overflow: auto;
                position: relative;
            }

            .preview-header {
                padding: 20px;
                border-bottom: 1px solid var(--border-color);
                display: flex;
                justify-content: space-between;
                align-items: center;
                position: sticky;
                top: 0;
                background: var(--bg-secondary);
                z-index: 10;
            }

            .preview-body {
                padding: 20px;
                max-height: calc(90vh - 100px);
                overflow: auto;
            }

            .preview-code {
                background: #0d1117;
                color: #c9d1d9;
                padding: 20px;
                border-radius: 8px;
                font-family: 'Monaco', 'Menlo', monospace;
                font-size: 13px;
                white-space: pre;
                overflow-x: auto;
            }

            .preview-image {
                max-width: 100%;
                height: auto;
                display: block;
                margin: 0 auto;
            }

            /* Rename modal */
            .rename-modal {
                display: none;
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: rgba(0, 0, 0, 0.7);
                z-index: 10000;
                align-items: center;
                justify-content: center;
            }

            .rename-modal.show {
                display: flex;
            }

            .rename-content {
                background: var(--bg-secondary);
                border-radius: 12px;
                padding: 30px;
                min-width: 400px;
                border: 1px solid var(--border-color);
            }

            /* Recent files panel */
            .recent-files-panel {
                position: fixed;
                top: 70px;
                right: -350px;
                width: 350px;
                height: calc(100vh - 70px);
                background: var(--bg-secondary);
                border-left: 1px solid var(--border-color);
                z-index: 9999;
                transition: right 0.3s ease;
                display: flex;
                flex-direction: column;
                box-shadow: -4px 0 12px rgba(0, 0, 0, 0.3);
            }

            .recent-files-panel.show {
                right: 0;
            }

            .recent-files-header {
                padding: 20px;
                border-bottom: 1px solid var(--border-color);
                display: flex;
                justify-content: space-between;
                align-items: center;
            }

            .recent-files-list {
                flex: 1;
                overflow-y: auto;
                padding: 10px;
            }

            .recent-file-item {
                padding: 12px;
                border-radius: 8px;
                margin-bottom: 8px;
                background: var(--bg-tertiary);
                cursor: pointer;
                transition: all 0.2s;
                display: flex;
                align-items: center;
                gap: 12px;
            }

            .recent-file-item:hover {
                background: var(--bg-hover);
                transform: translateX(-4px);
            }

            .recent-file-icon {
                font-size: 20px;
            }

            .recent-file-info {
                flex: 1;
                min-width: 0;
            }

            .recent-file-name {
                font-size: 14px;
                color: var(--text-primary);
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }

            .recent-file-time {
                font-size: 11px;
                color: var(--text-muted);
            }

            @media (max-width: 768px) {
                .file-manager-toolbar {
                    flex-direction: column;
                    align-items: stretch;
                }

                .toolbar-left, .toolbar-right {
                    width: 100%;
                }

                .file-actions {
                    opacity: 1;
                }

                .recent-files-panel {
                    width: 100%;
                    right: -100%;
                }
            }
        `;
        document.head.appendChild(style);
    }

    createPreviewModal() {
        const modal = document.createElement('div');
        modal.id = 'file-preview-modal';
        modal.className = 'preview-modal';
        modal.innerHTML = `
            <div class="preview-content">
                <div class="preview-header">
                    <h3 id="preview-title">File Preview</h3>
                    <button class="btn btn-secondary btn-sm" onclick="fileManager.closePreview()">
                        <i class="bi bi-x"></i> Close
                    </button>
                </div>
                <div class="preview-body" id="preview-body"></div>
            </div>
        `;
        document.body.appendChild(modal);
    }

    createRenameModal() {
        const modal = document.createElement('div');
        modal.id = 'rename-modal';
        modal.className = 'rename-modal';
        modal.innerHTML = `
            <div class="rename-content">
                <h4>Rename File</h4>
                <div class="form-group mt-3">
                    <label>New Name:</label>
                    <input type="text" id="rename-input" class="form-control" />
                </div>
                <div class="d-flex gap-2 mt-3">
                    <button class="btn btn-primary" onclick="fileManager.submitRename()">
                        <i class="bi bi-check"></i> Rename
                    </button>
                    <button class="btn btn-secondary" onclick="fileManager.closeRename()">
                        Cancel
                    </button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);

        // Create recent files panel
        const recentPanel = document.createElement('div');
        recentPanel.id = 'recent-files-panel';
        recentPanel.className = 'recent-files-panel';
        recentPanel.innerHTML = `
            <div class="recent-files-header">
                <h4><i class="bi bi-clock-history"></i> Recent Files</h4>
                <button class="btn btn-sm btn-secondary" onclick="fileManager.toggleRecentFiles()">
                    <i class="bi bi-x"></i>
                </button>
            </div>
            <div class="recent-files-list" id="recent-files-list"></div>
        `;
        document.body.appendChild(recentPanel);
    }

    setupEventListeners() {
        // File search
        const searchInput = document.getElementById('file-search');
        if (searchInput) {
            searchInput.addEventListener('input', (e) => {
                this.filterFiles(e.target.value);
            });
        }

        // Recent files button
        const recentBtn = document.getElementById('show-recent-files');
        if (recentBtn) {
            recentBtn.addEventListener('click', () => this.toggleRecentFiles());
        }
    }

    enhanceFileRows() {
        const rows = document.querySelectorAll('tbody tr');
        rows.forEach(row => {
            // Add file type icons
            const nameCell = row.querySelector('td:nth-child(2)');
            if (nameCell) {
                const link = nameCell.querySelector('a');
                if (link) {
                    const fileName = link.textContent.trim();
                    const extension = fileName.split('.').pop().toLowerCase();
                    const iconClass = this.fileTypeIcons[extension] || this.fileTypeIcons.default;
                    
                    const icon = link.querySelector('i');
                    if (icon && !icon.classList.contains('bi-folder-fill')) {
                        icon.className = `bi ${iconClass} file-icon`;
                    }
                }
            }

            // Enhance file sizes
            const sizeCell = row.querySelector('td:nth-child(3)');
            if (sizeCell && sizeCell.textContent.trim() !== '—') {
                const size = parseInt(sizeCell.textContent);
                if (!isNaN(size)) {
                    sizeCell.innerHTML = `<span class="file-size-badge">${this.formatFileSize(size)}</span>`;
                }
            }

            // Enhance dates
            const dateCell = row.querySelector('td:nth-child(4)');
            if (dateCell && dateCell.textContent.trim() !== '—') {
                const dateText = dateCell.textContent.trim();
                if (dateText) {
                    dateCell.innerHTML = `<span class="file-date-friendly">${this.formatFriendlyDate(dateText)}</span>`;
                }
            }

            // Add action buttons
            const actionsCell = row.querySelector('td:last-child');
            if (actionsCell && !row.querySelector('td:first-child a[href*="location="]')) { // Not a folder
                const btnGroup = actionsCell.querySelector('.btn-group');
                if (btnGroup) {
                    const fileName = row.querySelector('td:nth-child(2) a span')?.textContent || '';
                    // Get file path from data-path attribute on checkbox
                    const filePath = row.querySelector('.file-checkbox')?.dataset.path || '';
                    
                    // Add preview button
                    const previewBtn = document.createElement('button');
                    previewBtn.className = 'btn btn-outline-info btn-sm';
                    previewBtn.innerHTML = '<i class="bi bi-eye"></i>';
                    previewBtn.title = 'Preview';
                    previewBtn.onclick = () => this.previewFile(filePath, fileName);
                    
                    // Add rename button
                    const renameBtn = document.createElement('button');
                    renameBtn.className = 'btn btn-outline-warning btn-sm';
                    renameBtn.innerHTML = '<i class="bi bi-pencil"></i>';
                    renameBtn.title = 'Rename';
                    renameBtn.onclick = () => this.showRename(filePath, fileName);
                    
                    // Add open in new tab button
                    const newTabBtn = document.createElement('button');
                    newTabBtn.className = 'btn btn-outline-secondary btn-sm';
                    newTabBtn.innerHTML = '<i class="bi bi-box-arrow-up-right"></i>';
                    newTabBtn.title = 'Open in new tab';
                    newTabBtn.onclick = () => {
                        window.open(row.querySelector('td:nth-child(2) a')?.href, '_blank');
                    };
                    
                    btnGroup.insertBefore(newTabBtn, btnGroup.firstChild);
                    btnGroup.insertBefore(renameBtn, btnGroup.firstChild);
                    btnGroup.insertBefore(previewBtn, btnGroup.firstChild);
                }
            }
        });
    }

    formatFileSize(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    formatFriendlyDate(dateString) {
        const date = new Date(dateString);
        const now = new Date();
        const diffMs = now - date;
        const diffSec = Math.floor(diffMs / 1000);
        const diffMin = Math.floor(diffSec / 60);
        const diffHour = Math.floor(diffMin / 60);
        const diffDay = Math.floor(diffHour / 24);

        if (diffSec < 60) return 'Just now';
        if (diffMin < 60) return `${diffMin} minute${diffMin > 1 ? 's' : ''} ago`;
        if (diffHour < 24) return `${diffHour} hour${diffHour > 1 ? 's' : ''} ago`;
        if (diffDay === 1) return 'Yesterday';
        if (diffDay < 7) return `${diffDay} days ago`;
        return date.toLocaleDateString();
    }

    filterFiles(query) {
        const rows = document.querySelectorAll('tbody tr');
        const lowerQuery = query.toLowerCase();

        rows.forEach(row => {
            const fileName = row.querySelector('td:nth-child(2)')?.textContent.toLowerCase() || '';
            row.style.display = fileName.includes(lowerQuery) ? '' : 'none';
        });
    }

    async previewFile(filePath, fileName) {
        const modal = document.getElementById('file-preview-modal');
        const title = document.getElementById('preview-title');
        const body = document.getElementById('preview-body');

        title.textContent = fileName;
        body.innerHTML = '<div class="text-center"><div class="spinner-enhanced"></div><p>Loading preview...</p></div>';
        modal.classList.add('show');

        try {
            // Determine file type
            const extension = fileName.split('.').pop().toLowerCase();
            const imageExtensions = ['jpg', 'jpeg', 'png', 'gif', 'svg', 'webp', 'bmp', 'ico'];
            const textExtensions = ['txt', 'js', 'py', 'json', 'md', 'html', 'css', 'xml', 'yml', 'yaml', 'jsx', 'tsx', 'ts', 'php', 'sql', 'sh', 'log', 'ini', 'conf', 'env', 'properties', 'toml'];

            if (imageExtensions.includes(extension)) {
                // Show image - use download endpoint
                const imageUrl = `/files/${this.processName}/file-manager/download/${encodeURIComponent(fileName)}`;
                body.innerHTML = `<img src="${imageUrl}" class="preview-image" alt="${this.escapeHtml(fileName)}" onerror="this.parentElement.innerHTML='<p class=\\'text-center text-danger\\'>Failed to load image</p>'" />`;
            } else if (textExtensions.includes(extension)) {
                // Fetch text content via preview API
                const response = await fetch(`/files/${this.processName}/file-manager/preview?file=${encodeURIComponent(filePath)}`);
                const data = await response.json();
                
                if (data.success) {
                    body.innerHTML = `<pre class="preview-code">${this.escapeHtml(data.content)}</pre>`;
                } else {
                    body.innerHTML = `<p class="text-center text-danger">Error: ${this.escapeHtml(data.error || 'Unable to load file')}</p>`;
                }
            } else {
                body.innerHTML = '<p class="text-center text-muted">Preview not available for this file type<br><small>Supported: Images (jpg, png, gif, etc.) and Text files (txt, js, py, json, etc.)</small></p>';
            }

            // Add to recent files
            this.addToRecentFiles(filePath, fileName);
        } catch (error) {
            body.innerHTML = `<p class="text-center text-danger">Error loading preview: ${this.escapeHtml(error.message)}</p>`;
            console.error('Preview error:', error);
        }
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    closePreview() {
        document.getElementById('file-preview-modal').classList.remove('show');
    }

    showRename(filePath, currentName) {
        const modal = document.getElementById('rename-modal');
        const input = document.getElementById('rename-input');
        
        input.value = currentName;
        input.dataset.filePath = filePath;
        modal.classList.add('show');
        input.focus();
        input.select();
    }

    async submitRename() {
        const input = document.getElementById('rename-input');
        const newName = input.value.trim();
        const filePath = input.dataset.filePath;

        if (!newName) {
            showWarning('Please enter a file name');
            return;
        }

        try {
            const response = await fetch(`/files/${this.processName}/file-manager/rename`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    old_path: filePath,
                    new_name: newName
                })
            });

            const data = await response.json();

            if (data.success) {
                showSuccess(data.message || 'File renamed successfully');
                this.closeRename();
                // Reload page after short delay
                setTimeout(() => location.reload(), 1000);
            } else {
                showError(data.error || 'Failed to rename file');
            }
        } catch (error) {
            showError('Failed to rename file: ' + error.message);
            console.error('Rename error:', error);
        }
    }

    closeRename() {
        document.getElementById('rename-modal').classList.remove('show');
    }

    toggleRecentFiles() {
        const panel = document.getElementById('recent-files-panel');
        panel.classList.toggle('show');
        if (panel.classList.contains('show')) {
            this.renderRecentFiles();
        }
    }

    addToRecentFiles(filePath, fileName) {
        const entry = {
            path: filePath,
            name: fileName,
            timestamp: new Date().toISOString()
        };

        // Remove if exists
        this.recentFiles = this.recentFiles.filter(f => f.path !== filePath);
        
        // Add to beginning
        this.recentFiles.unshift(entry);
        
        // Limit to 20
        if (this.recentFiles.length > 20) {
            this.recentFiles = this.recentFiles.slice(0, 20);
        }

        this.saveRecentFiles();
    }

    renderRecentFiles() {
        const list = document.getElementById('recent-files-list');
        if (!list) return;

        if (this.recentFiles.length === 0) {
            list.innerHTML = '<div class="text-center text-muted" style="padding: 40px;">No recent files</div>';
            return;
        }

        list.innerHTML = this.recentFiles.map(file => {
            const extension = file.name.split('.').pop().toLowerCase();
            const iconClass = this.fileTypeIcons[extension] || this.fileTypeIcons.default;
            
            return `
                <div class="recent-file-item" onclick="window.location.href='/files/${this.processName}/edit?file=${encodeURIComponent(file.path)}'">
                    <i class="bi ${iconClass} recent-file-icon"></i>
                    <div class="recent-file-info">
                        <div class="recent-file-name">${file.name}</div>
                        <div class="recent-file-time">${this.formatFriendlyDate(file.timestamp)}</div>
                    </div>
                </div>
            `;
        }).join('');
    }

    loadRecentFiles() {
        const key = `recent_files_${this.processName}`;
        const stored = localStorage.getItem(key);
        return stored ? JSON.parse(stored) : [];
    }

    saveRecentFiles() {
        const key = `recent_files_${this.processName}`;
        localStorage.setItem(key, JSON.stringify(this.recentFiles));
    }
}

// Initialize when DOM is ready
let fileManager = null;
document.addEventListener('DOMContentLoaded', function() {
    const pathParts = window.location.pathname.split('/');
    // URL structure: /files/manage/<name>
    // pathParts: ['', 'files', 'manage', '<name>']
    if (pathParts.includes('files') && pathParts.includes('manage')) {
        const processName = pathParts[3]; // Process name is at index 3
        if (processName) {
            fileManager = new EnhancedFileManager(processName);
        }
    }
});
