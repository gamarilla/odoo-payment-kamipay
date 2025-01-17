/** @odoo-module **/

import publicWidget from '@web/legacy/js/public/public_widget';
import { _t } from "@web/core/l10n/translation";

// Test simulation widget
publicWidget.registry.KamiPayTestSimulation = publicWidget.Widget.extend({
    selector: '.kamipay-test-container',
    events: {
        'click .simulate-payment': '_onClickSimulate',
    },

    start: async function () {
        await this._super(...arguments);
        this.rpc = this.bindService("rpc");
        this.notification = this.bindService("notification");
    },

    async _onClickSimulate(ev) {
        const button = ev.currentTarget;
        const status = button.dataset.status;
        const operationId = button.dataset.operationId;
        const amountBrl = button.dataset.amountBrl;
        const amountUsdt = button.dataset.amountUsdt;
        
        try {
            await this.rpc('/payment/kamipay/test/simulate_webhook', {
                operation_id: operationId,
                status: status,
                amount_brl: amountBrl,
                amount_usdt: amountUsdt
            });
            
            // Just show notification, no redirects
            this.notification.add(_t('Webhook simulation sent'), {
                type: 'info',
                title: _t('Test Simulation'),
                sticky: false,
            });
        } catch (error) {
            this.notification.add(_t('Could not simulate payment'), {
                type: 'danger',
                title: _t('Error'),
                sticky: false,
            });
        }
    }
});

publicWidget.registry.KamiPayQRStatus = publicWidget.Widget.extend({
    selector: '.kamipay-qr-container',

    // Constants
    QR_EXPIRY_MS: 600 * 1000,  // 10 minute expiry
    POLLING_INTERVAL: 5000,    // Check every 5 seconds
    DRAFT_STATE: 'draft',

    start: async function () {
        await this._super(...arguments);
        this.rpc = this.bindService("rpc");
        this.notification = this.bindService("notification");
        this.txId = this.el.dataset.txId;
        this.reference = this.el.dataset.reference;
        
        if (this.txId) {
            this._startTimers();
        }
    },

    _startTimers() {
        // Start expiry timer
        this.expiryTimeout = setTimeout(() => {
            this._handleExpiry();
        }, this.QR_EXPIRY_MS);

        // Start polling for status changes
        this.pollingInterval = setInterval(() => {
            this._checkTransactionStatus();
        }, this.POLLING_INTERVAL);
    },

    async _checkTransactionStatus() {
		try {
			const response = await this.rpc(`/payment/kamipay/poll/${this.txId}`, {});
			
			if (response && response.state && response.state !== 'draft') {
				// Transaction state has changed, redirect to status page
				this._cleanup();
				window.location = '/payment/status';
			}
		} catch (error) {
			console.error('Error checking local transaction status:', error);
		}
	},

    async _handleExpiry() {
        try {
            // Do one final status check before expiring
            const statusData = await this.rpc('/payment/kamipay/status', {
                tx_id: this.txId
            });

            if (statusData.status === 'ok' && 
                statusData.data && 
                statusData.data.status !== this.DRAFT_STATE) {
                window.location = '/payment/status';
                return;
            }
            
            // If still in draft state, mark as expired
            window.location = `/payment/kamipay/return?expired=1&reference=${this.reference}`;

        } catch (error) {
            console.error('Error handling expiry:', error);
            window.location = '/shop/payment';
        }
    },

    _cleanup() {
        if (this.expiryTimeout) {
            clearTimeout(this.expiryTimeout);
            this.expiryTimeout = null;
        }
        if (this.pollingInterval) {
            clearInterval(this.pollingInterval);
            this.pollingInterval = null;
        }
    },

    destroy() {
        this._cleanup();
        this._super(...arguments);
    },
});

export default {
    KamiPayTestSimulation: publicWidget.registry.KamiPayTestSimulation,
    KamiPayQRStatus: publicWidget.registry.KamiPayQRStatus,
};
