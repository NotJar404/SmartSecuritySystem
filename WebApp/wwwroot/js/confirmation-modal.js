/* ========================================================= */
/* SECUREVISION — TWO-STEP CONFIRMATION MODAL SYSTEM         */
/* Intercepts form submissions and shows a summary before    */
/* executing the backend action.                             */
/* ========================================================= */

(function () {
    'use strict';

    // Inject confirmation modal HTML into the page
    function injectConfirmationModal() {
        if (document.getElementById('confirmationModal')) return;

        const modalHTML = `
        <div id="confirmationModal" class="modal fade" tabindex="-1" role="dialog">
            <div class="modal-dialog modal-dialog-centered">
                <div class="modal-content">
                    <div class="modal-body">
                        <div class="confirm-icon">
                            <i id="confirmIcon" class="fas fa-check-circle"></i>
                        </div>
                        <div id="confirmTitle" class="confirm-title">Confirm Action</div>
                        <div id="confirmSummary" class="confirm-summary"></div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-light btn-sm" onclick="SecureConfirm.cancel()">Cancel</button>
                        <button type="button" id="confirmBtn" class="btn btn-primary btn-sm" onclick="SecureConfirm.execute()">Confirm</button>
                    </div>
                </div>
            </div>
        </div>`;

        document.body.insertAdjacentHTML('beforeend', modalHTML);

        // Close on backdrop click
        const modal = document.getElementById('confirmationModal');
        modal.addEventListener('click', function (e) {
            if (e.target === modal) SecureConfirm.cancel();
        });
    }

    // State
    let pendingCallback = null;
    let parentModalId = null;

    // Public API
    window.SecureConfirm = {

        /**
         * Show a confirmation modal with a summary of the action.
         *
         * @param {Object} options
         * @param {string} options.title - Confirmation title (e.g., "Confirm Add Camera")
         * @param {string} options.icon - FontAwesome icon class (default: "fas fa-check-circle")
         * @param {Array}  options.fields - Array of {label, value} for the summary
         * @param {string} options.confirmText - Text for the confirm button (default: "Confirm")
         * @param {string} options.confirmClass - CSS class for confirm button (default: "btn-primary")
         * @param {Function} options.onConfirm - Callback when confirmed
         * @param {string} options.parentModal - ID of the parent modal to re-show on cancel
         * @param {boolean} options.isDelete - Style as delete confirmation
         */
        show: function (options) {
            injectConfirmationModal();

            const modal = document.getElementById('confirmationModal');
            const icon = document.getElementById('confirmIcon');
            const title = document.getElementById('confirmTitle');
            const summary = document.getElementById('confirmSummary');
            const confirmBtn = document.getElementById('confirmBtn');

            // Set content
            title.textContent = options.title || 'Confirm Action';
            icon.className = options.icon || 'fas fa-check-circle';
            confirmBtn.textContent = options.confirmText || 'Confirm';
            confirmBtn.className = 'btn btn-sm ' + (options.confirmClass || 'btn-primary');

            // Delete styling
            if (options.isDelete) {
                modal.querySelector('.modal-content').classList.add('confirm-delete');
                icon.className = 'fas fa-exclamation-triangle';
                confirmBtn.className = 'btn btn-sm btn-danger';
            } else {
                modal.querySelector('.modal-content').classList.remove('confirm-delete');
            }

            // Build summary
            let summaryHTML = '';
            if (options.fields && options.fields.length > 0) {
                options.fields.forEach(function (field) {
                    if (field.value && field.value.toString().trim() !== '') {
                        summaryHTML += `
                            <div class="summary-row">
                                <span class="summary-label">${field.label}</span>
                                <span class="summary-value">${field.value}</span>
                            </div>`;
                    }
                });
            }
            summary.innerHTML = summaryHTML || '<p style="text-align:center;color:var(--text-dim);margin:0;">No additional details</p>';

            // Store callback and parent modal
            pendingCallback = options.onConfirm || null;
            parentModalId = options.parentModal || null;

            // Hide parent modal if specified
            if (parentModalId) {
                const parent = document.getElementById(parentModalId);
                if (parent) parent.classList.remove('show');
            }

            // Show confirmation
            modal.classList.add('show');
            document.body.style.overflow = 'hidden';
        },

        /**
         * Execute the confirmed action.
         */
        execute: function () {
            const modal = document.getElementById('confirmationModal');
            modal.classList.remove('show');
            document.body.style.overflow = 'auto';

            if (pendingCallback) {
                pendingCallback();
                pendingCallback = null;
            }
            parentModalId = null;
        },

        /**
         * Cancel the confirmation and optionally return to parent modal.
         */
        cancel: function () {
            const modal = document.getElementById('confirmationModal');
            modal.classList.remove('show');

            if (parentModalId) {
                const parent = document.getElementById(parentModalId);
                if (parent) parent.classList.add('show');
            } else {
                document.body.style.overflow = 'auto';
            }

            pendingCallback = null;
            parentModalId = null;
        },

        /**
         * Helper: Intercept a form submission with two-step confirmation.
         *
         * @param {string} formId - ID of the form element
         * @param {string} title - Confirmation title
         * @param {string} parentModal - ID of parent modal (optional)
         */
        interceptForm: function (formId, title, parentModal) {
            const form = document.getElementById(formId);
            if (!form) return;

            form.addEventListener('submit', function (e) {
                e.preventDefault();

                // Validate form first
                if (!form.checkValidity()) {
                    form.reportValidity();
                    return;
                }

                // Collect visible form fields for summary
                const fields = [];
                const inputs = form.querySelectorAll('input:not([type="hidden"]):not([type="submit"]):not([type="file"]), select, textarea');
                inputs.forEach(function (input) {
                    if (input.offsetParent === null) return; // Skip hidden
                    const label = input.closest('.form-group')?.querySelector('label')?.textContent
                        || input.name || 'Field';
                    let value = input.type === 'password' ? '••••••••' : input.value;

                    // For selects, show the selected option text
                    if (input.tagName === 'SELECT' && input.selectedIndex >= 0) {
                        value = input.options[input.selectedIndex].text;
                    }

                    if (value && value.trim()) {
                        fields.push({ label: label.trim(), value: value });
                    }
                });

                SecureConfirm.show({
                    title: title || 'Confirm Submission',
                    fields: fields,
                    parentModal: parentModal || null,
                    onConfirm: function () {
                        form.submit();
                    }
                });
            });
        },

        /**
         * Helper: Show delete confirmation.
         *
         * @param {string} itemName - Name of the item to delete
         * @param {Function} onConfirm - Callback to execute deletion
         */
        confirmDelete: function (itemName, onConfirm) {
            this.show({
                title: 'Delete ' + (itemName || 'Item') + '?',
                icon: 'fas fa-exclamation-triangle',
                isDelete: true,
                confirmText: 'Delete',
                confirmClass: 'btn-danger',
                fields: [
                    { label: 'Item', value: itemName || 'Selected item' },
                    { label: 'Action', value: 'Permanently remove from system' }
                ],
                onConfirm: onConfirm
            });
        }
    };

    // Auto-init on DOM load
    document.addEventListener('DOMContentLoaded', function () {
        injectConfirmationModal();
    });

})();
