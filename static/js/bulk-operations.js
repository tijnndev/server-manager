/**
 * Bulk Operations Progress Tracker
 * Shows progress for multi-file operations
 */

class BulkOperationTracker {
    constructor() {
        this.createProgressOverlay();
    }

    createProgressOverlay() {
        const overlay = document.createElement('div');
        overlay.id = 'bulk-operation-overlay';
        overlay.className = 'progress-overlay';
        overlay.innerHTML = `
            <div class="progress-content">
                <div class="progress-title" id="bulk-operation-title">Processing...</div>
                <div class="progress-bar-container">
                    <div class="progress-bar-fill" id="bulk-operation-bar" style="width: 0%"></div>
                </div>
                <div class="progress-text" id="bulk-operation-text">0 / 0 completed</div>
                <button class="btn btn-secondary btn-sm mt-3" id="bulk-operation-cancel" style="display: none;">
                    Cancel
                </button>
            </div>
        `;
        document.body.appendChild(overlay);
    }

    start(title, total) {
        this.total = total;
        this.completed = 0;
        this.cancelled = false;
        this.errors = [];

        const overlay = document.getElementById('bulk-operation-overlay');
        const titleEl = document.getElementById('bulk-operation-title');
        const textEl = document.getElementById('bulk-operation-text');
        const bar = document.getElementById('bulk-operation-bar');
        const cancelBtn = document.getElementById('bulk-operation-cancel');

        titleEl.textContent = title;
        textEl.textContent = `0 / ${total} completed`;
        bar.style.width = '0%';
        overlay.classList.add('show');
        
        cancelBtn.style.display = 'inline-block';
        cancelBtn.onclick = () => this.cancel();
    }

    update(completed, message = '') {
        this.completed = completed;
        const percentage = Math.round((completed / this.total) * 100);

        const textEl = document.getElementById('bulk-operation-text');
        const bar = document.getElementById('bulk-operation-bar');

        textEl.textContent = message || `${completed} / ${this.total} completed`;
        bar.style.width = `${percentage}%`;
    }

    addError(item, error) {
        this.errors.push({ item, error });
    }

    cancel() {
        this.cancelled = true;
        showWarning('Operation cancelled');
        this.complete();
    }

    complete(customMessage = null) {
        const overlay = document.getElementById('bulk-operation-overlay');
        
        if (this.errors.length > 0) {
            showError(`Completed with ${this.errors.length} error(s)`);
            console.error('Bulk operation errors:', this.errors);
        } else if (!this.cancelled) {
            showSuccess(customMessage || `Successfully processed ${this.completed} item(s)`);
        }

        setTimeout(() => {
            overlay.classList.remove('show');
        }, 1000);
    }

    isCancelled() {
        return this.cancelled;
    }
}

// Global instance
const bulkOperationTracker = new BulkOperationTracker();

// Enhanced bulk file operations
async function deleteSelectedFilesWithProgress() {
    if (selectedFiles.length === 0) {
        showWarning('No files selected');
        return;
    }

    if (!confirm(`Are you sure you want to delete ${selectedFiles.length} file(s)?`)) {
        return;
    }

    bulkOperationTracker.start('Deleting files...', selectedFiles.length);

    let completed = 0;
    const errors = [];

    for (const filePath of selectedFiles) {
        if (bulkOperationTracker.isCancelled()) break;

        try {
            const response = await fetch(window.location.origin + '/files/' + processName + '/files/delete', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded'
                },
                body: new URLSearchParams({
                    'filename': filePath,
                    'location': currentLocation,
                    'permanent': 'true'
                })
            });

            const data = await response.json();
            
            if (!data.success) {
                errors.push({ file: filePath, error: data.error || 'Unknown error' });
                bulkOperationTracker.addError(filePath, data.error);
            }

            completed++;
            bulkOperationTracker.update(completed, `Deleted ${completed} / ${selectedFiles.length}`);

            // Small delay to prevent overwhelming the server
            await new Promise(resolve => setTimeout(resolve, 100));

        } catch (error) {
            errors.push({ file: filePath, error: error.message });
            bulkOperationTracker.addError(filePath, error.message);
            completed++;
            bulkOperationTracker.update(completed);
        }
    }

    bulkOperationTracker.complete();

    // Clear selection and reload page
    selectedFiles = [];
    setTimeout(() => {
        location.reload();
    }, 1500);
}

async function moveSelectedFilesWithProgress() {
    if (selectedFiles.length === 0) {
        showWarning('No files selected');
        return;
    }

    const destination = prompt('Enter destination path:');
    if (!destination) return;

    bulkOperationTracker.start('Moving files...', selectedFiles.length);

    try {
        const response = await fetch(window.location.origin + '/files/move_files/' + processName, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                files: selectedFiles,
                destination: destination
            })
        });

        const data = await response.json();

        if (data.success) {
            bulkOperationTracker.update(selectedFiles.length, 'All files moved');
            bulkOperationTracker.complete('Files moved successfully');
            
            setTimeout(() => {
                location.reload();
            }, 1500);
        } else {
            bulkOperationTracker.addError('Move operation', data.error);
            bulkOperationTracker.complete();
            showError('Error: ' + data.error);
        }
    } catch (error) {
        bulkOperationTracker.addError('Move operation', error.message);
        bulkOperationTracker.complete();
        showError('Error moving files: ' + error.message);
    }

    selectedFiles = [];
}

// File upload with progress
function uploadFileWithProgress(file, targetPath) {
    return new Promise((resolve, reject) => {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('targetPath', targetPath);

        const xhr = new XMLHttpRequest();

        xhr.upload.addEventListener('progress', (e) => {
            if (e.lengthComputable) {
                const percentage = (e.loaded / e.total) * 100;
                bulkOperationTracker.update(1, `Uploading: ${Math.round(percentage)}%`);
            }
        });

        xhr.addEventListener('load', () => {
            if (xhr.status === 200) {
                resolve(JSON.parse(xhr.responseText));
            } else {
                reject(new Error(`Upload failed: ${xhr.statusText}`));
            }
        });

        xhr.addEventListener('error', () => {
            reject(new Error('Upload failed'));
        });

        xhr.open('POST', window.location.origin + '/files/file-manager/upload');
        xhr.send(formData);
    });
}

async function uploadMultipleFilesWithProgress(files, targetPath) {
    bulkOperationTracker.start('Uploading files...', files.length);

    let completed = 0;

    for (const file of files) {
        if (bulkOperationTracker.isCancelled()) break;

        try {
            await uploadFileWithProgress(file, targetPath);
            completed++;
            bulkOperationTracker.update(completed, `Uploaded ${completed} / ${files.length}`);
        } catch (error) {
            bulkOperationTracker.addError(file.name, error.message);
            completed++;
            bulkOperationTracker.update(completed);
        }
    }

    bulkOperationTracker.complete();
    
    setTimeout(() => {
        location.reload();
    }, 1500);
}
