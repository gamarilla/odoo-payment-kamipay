import logging
import pprint
from odoo import _, fields, models
from odoo.exceptions import ValidationError
from odoo.http import request

_logger = logging.getLogger(__name__)

class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    kamipay_operation_id = fields.Char('KamiPay Operation ID')
    kamipay_usdt_amount = fields.Float('USDT Amount', digits='Product Price')
    kamipay_rate = fields.Float('Exchange Rate', digits=(12, 6))
    kamipay_emv = fields.Char('EMV Code')  # Add this field

    def _get_specific_rendering_values(self, processing_values):
        _logger.info("--- Generating rendering values for KamiPay")
        res = super()._get_specific_rendering_values(processing_values)
        if self.provider_code != 'kamipay':
            return res

        if not self.kamipay_operation_id:
            self._create_kamipay_payment()

        _logger.info("Generating rendering values for KamiPay transaction %s", self.reference)

        # Generate the redirect form HTML
        template = request.env.ref('payment_kamipay.redirect_form')
        values = {
            'api_url': f'/payment/kamipay/qr/{self.id}',
            'tx_id': self.id,
            'reference': self.reference,
        }
        try:
            redirect_form_html = request.env['ir.qweb']._render(template.id, values)
            _logger.info("Generated redirect form HTML: %s", redirect_form_html)
        except Exception as e:
            _logger.error("Error generating redirect form: %s", e)
            raise

        rendering_values = {
            'api_url': f'/payment/kamipay/qr/{self.id}',
            'tx_id': self.id,
            'reference': self.reference,
            'redirect_form_html': redirect_form_html,
        }
        
        _logger.info("Final rendering values: %s", rendering_values)
        return rendering_values
        
    def _get_tx_from_notification_data(self, provider_code, notification_data):
        tx = super()._get_tx_from_notification_data(provider_code, notification_data)
        if provider_code != 'kamipay':
            return tx

        operation_id = notification_data.get('pix_id')
        if not operation_id:
            raise ValidationError(
                "KamiPay: " + _("Received data with missing operation ID.")
            )

        tx = self.search([('kamipay_operation_id', '=', operation_id), ('provider_code', '=', 'kamipay')])
        if not tx:
            raise ValidationError(
                "KamiPay: " + _("No transaction found matching Operation ID %s.", operation_id)
            )
        return tx

    def _process_notification_data(self, notification_data):
        super()._process_notification_data(notification_data)
        if self.provider_code != 'kamipay':
            return

        status = notification_data.get('status')
        _logger.info("_process_notification_data status: %s", status)
            
        if status == 'processing':
            # Store additional transaction details if available 
            if notification_data.get('data'):
                self.provider_reference = notification_data['data'].get('bank_txid')
                state_message = _("Your PIX payment has been received and is being processed.")
                self._set_pending(state_message=state_message)
        elif status == 'done':
            # Store additional transaction details if available 
            if notification_data.get('data'):
                self.provider_reference = notification_data['data'].get('bank_txid')
                state_message = _("Your PIX payment has been confirmed.")
                self._set_done(state_message=state_message)
        elif status == 'expired':
            state_message = _("Payment expired after 10 minutes.")
            self._set_canceled(state_message=state_message)
        elif status == 'failed':
            self._set_error(_("Payment failed"))
        else:
            _logger.warning("Received data with invalid status: %s", status)
            self._set_error(_("Invalid payment status"))
            
    def _create_kamipay_payment(self):
        """ Create a payment request in KamiPay """
        self.ensure_one()
        
        _logger.info("KamiPay: Creating payment for tx %s", self.reference)

        payload = {
            'address': self.provider_id.kamipay_wallet_address,
            'amount': self.amount,
            'external_reference': self.reference,
            'expire': 600,  # 10 minutes expiry
        }

        tx_response = self.provider_id._kamipay_make_request(
            '/v2/charge/create_dynamic_pix_b2b', 
            payload=payload
        )
        
        self.write({
            'kamipay_operation_id': tx_response.get('operation_id'),
            'kamipay_usdt_amount': tx_response.get('amount_usdt'),
            'kamipay_rate': tx_response.get('rate'),
            'kamipay_emv': tx_response.get('emv'),  # Store the EMV code
        })

        return tx_response

    def _finalize_post_processing(self):
        """Finalize KamiPay payment post-processing"""
        super()._finalize_post_processing()
        if self.provider_code != 'kamipay':
            return

        if self.state == 'done':
            # The payment is confirmed, proceed with order confirmation 
            if hasattr(self, 'sale_order_ids'):
                # Add logging to track order states
                _logger.info(
                    "Processing order confirmation for transaction %s. Order states: %s",
                    self.reference,
                    {so.name: so.state for so in self.sale_order_ids}
                )
                
                # Only try to confirm orders that are in draft/sent state
                orders_to_confirm = self.sale_order_ids.filtered(
                    lambda so: so.state in ['draft', 'sent']
                )
                if orders_to_confirm:
                    orders_to_confirm.action_confirm()