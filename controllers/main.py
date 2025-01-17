# controllers/main.py
import logging
import pprint
from datetime import datetime
import pytz
import werkzeug
import requests
import hmac
import hashlib
import json

from odoo import http, _
from odoo.exceptions import ValidationError
from odoo.http import request

_logger = logging.getLogger(__name__)

class KamiPayController(http.Controller):
    _status_url = '/payment/kamipay/status'
    _return_url = '/payment/kamipay/return'
    _webhook_url = '/payment/kamipay/webhook'
    _simulate_webhook_url = '/payment/kamipay/test/simulate_webhook'
    _qr_url = '/payment/kamipay/qr'

    @http.route(_webhook_url, type='json', auth='public', csrf=False)
    def kamipay_webhook(self, **data):
        """ Process KamiPay webhook notifications."""
        timestamp = datetime.now(pytz.UTC).strftime('%Y-%m-%d %H:%M:%S.%f%z')
        
        _logger.info("--- KamiPay Webhook Received at %s ---", timestamp)
        
        try:
            webhook_data = request.get_json_data()
            _logger.info("Webhook Data:\n%s", pprint.pformat(webhook_data))
            
            # Verify signature
            signature = request.httprequest.headers.get('X-Kamipay-Auth')
            if not signature:
                _logger.error("No signature provided in webhook")
                return {'status': 'error', 'message': 'Missing signature'}, 403
                
            calculated_signature = self._verify_webhook_signature(webhook_data)
            if not calculated_signature:
                _logger.error("Could not calculate signature - invalid payload or missing provider")
                return {'status': 'error', 'message': 'Invalid payload'}, 403
                
            if signature != calculated_signature and not self._is_test_mode(webhook_data):
                _logger.error("Invalid signature in webhook")
                return {'status': 'error', 'message': 'Invalid signature'}, 403
            
            # Extract data from params if it's in JSON-RPC format
            if webhook_data.get('jsonrpc') == '2.0' and webhook_data.get('params'):
                webhook_data = webhook_data['params']
                
            # Process the webhook data and update transaction status
            tx_sudo = request.env['payment.transaction'].sudo()._handle_notification_data(
                'kamipay', webhook_data
            )
            _logger.info(
                "Successfully processed KamiPay webhook for transaction ref %s (ID %s)",
                tx_sudo.reference, tx_sudo.id
            )
            return {'status': 'ok'}
            
        except Exception as e:
            _logger.exception("Error processing webhook: %s", str(e))
            return {'status': 'error', 'message': str(e)}, 500

    def _is_test_mode(self, webhook_data):
        """Check if the webhook is for a test transaction."""
        try:
            operation_id = webhook_data.get('pix_id')
            if operation_id:
                tx = request.env['payment.transaction'].sudo().search([
                    ('kamipay_operation_id', '=', operation_id)
                ], limit=1)
                return tx.provider_id.state == 'test'
        except Exception:
            pass
        return False
    
    def _verify_webhook_signature(self, payload):
        """Verify the webhook signature using the provider's signature key."""
        # First, get the operation ID from the payload
        operation_id = payload.get('pix_id')
        if not operation_id:
            _logger.error("Cannot verify signature: missing operation_id in payload")
            return False
            
        # Find the corresponding transaction and provider
        tx = request.env['payment.transaction'].sudo().search([
            ('kamipay_operation_id', '=', operation_id)
        ], limit=1)
        
        if not tx or not tx.provider_id or not tx.provider_id.kamipay_signature_key:
            _logger.error("Cannot verify signature: transaction not found or missing provider signature key")
            return False
            
        # Get the signature key from the provider
        signature_key = tx.provider_id.kamipay_signature_key
        
        # Directly encode the JSON string to match the sample implementation
        payload_string = json.dumps(
            payload, 
            sort_keys=False,
            ensure_ascii=False,
            separators=(',', ':')
        ).encode('utf-8')
        
        calculated_signature = hmac.new(
            signature_key.encode('utf-8'),
            payload_string,
            hashlib.sha256
        ).hexdigest()
        
        return calculated_signature
        
    @http.route(_qr_url + '/<int:tx_id>', type='http', auth='public', website=True)
    def kamipay_qr_display(self, tx_id=None, **kwargs):
        """ Display the QR code payment page """
        _logger.info("KamiPay QR display request for tx_id: %s", tx_id)
        tx_sudo = request.env['payment.transaction'].sudo().browse(tx_id)
        if not tx_sudo or tx_sudo.provider_code != 'kamipay':
            _logger.error("Transaction not found or invalid provider: %s", tx_id)
            raise werkzeug.exceptions.NotFound()
            
        # Create KamiPay payment if not already done
        if not tx_sudo.kamipay_operation_id:
            tx_sudo._create_kamipay_payment()

        values = {
            'tx': tx_sudo,
            'qr_code': tx_sudo.kamipay_emv,  # Use EMV code from transaction
            #'qr_code': f"http://{tx_sudo.kamipay_emv}",  # Add ´http://´ to EMV code
            'title': _('PIX QR Code for Payment'),
        }
        _logger.info("Rendering QR page for transaction %s", tx_sudo.reference)
        return request.render('payment_kamipay.qr_display_page', values)

    @http.route('/payment/kamipay/test/console/<int:tx_id>', type='http', auth='public', website=True)
    def kamipay_test_console(self, tx_id=None, **kwargs):
        """Test console page for KamiPay transactions."""
        tx_sudo = request.env['payment.transaction'].sudo().browse(tx_id)
        if not tx_sudo or tx_sudo.provider_code != 'kamipay' or tx_sudo.provider_id.state != 'test':
            raise werkzeug.exceptions.NotFound()
            
        values = {
            'tx': tx_sudo,
            'amount_brl': tx_sudo.amount,
            'amount_usdt': tx_sudo.kamipay_usdt_amount,
            'operation_id': tx_sudo.kamipay_operation_id,
            'title': _('PIX KamiPay Test Console'),
        }
        return request.render('payment_kamipay.test_console_page', values)
        
    @http.route(_status_url, type='json', auth='public')
    def kamipay_status_check(self, **data):
        """ Check the status of a KamiPay transaction."""
        try:
            tx_id = data.get('tx_id')
            if not tx_id:
                return {'error': 'Missing transaction ID'}

            tx_sudo = request.env['payment.transaction'].sudo().browse(int(tx_id))
            if not tx_sudo.exists():
                return {'error': 'Transaction not found'}
                
            if tx_sudo.provider_code != 'kamipay':
                return {'error': 'Invalid payment provider'}
            
            # Ensure we have an operation ID    
            if not tx_sudo.kamipay_operation_id:
                return {'error': 'Missing operation ID'}
                
            endpoint = '/v2/status/tx_status'
            query_params = {
                'target': 'operation_id',
                'type': 'charge',
                'id': tx_sudo.kamipay_operation_id,
                'chain': 'polygon'
            }
            
            _logger.info(
                "Checking status for transaction %s with params:\n%s",
                tx_sudo.reference, 
                pprint.pformat(query_params)
            )
            
            status_response = tx_sudo.provider_id._kamipay_make_request(
                endpoint=endpoint,
                query_params=query_params,
                method='GET'
            )
            
            _logger.info(
                "Status response for transaction %s:\n%s",
                tx_sudo.reference, pprint.pformat(status_response)
            )
            
            if status_response.get('status') == 'ok':
                status_data = status_response.get('data', {})
                notification_data = {
                    'pix_id': tx_sudo.kamipay_operation_id,
                    'status': status_data.get('status', 'error'),
                    'external_reference': tx_sudo.reference,
                    'data': status_data
                }
                request.env['payment.transaction'].sudo()._handle_notification_data(
                    'kamipay', notification_data
                )
                
            return status_response

        except Exception as e:
            _logger.exception("Error checking KamiPay status: %s", str(e))
            return {'error': str(e)}

    @http.route('/payment/kamipay/poll/<int:tx_id>', type='json', auth='public')
    def poll_kamipay_status(self, tx_id, **kwargs):
        """Poll the local transaction status."""
        tx_sudo = request.env['payment.transaction'].sudo().browse(tx_id)
        if not tx_sudo.exists() or tx_sudo.provider_code != 'kamipay':
            return {'error': 'Transaction not found'}
            
        return {
            'state': tx_sudo.state,
            'state_message': tx_sudo.state_message,
        }
    
    @http.route(_simulate_webhook_url, type='json', auth='public')
    def kamipay_simulate_webhook(self, operation_id, status, amount_brl, amount_usdt, **kwargs):
        """ Simulate a webhook notification for testing."""
        simulation_start = datetime.now(pytz.UTC)
        _logger.info("Starting webhook simulation at %s", simulation_start)
        
        tx_sudo = request.env['payment.transaction'].sudo().search([
            ('kamipay_operation_id', '=', operation_id),
            ('provider_id.state', '=', 'test')
        ], limit=1)
        
        if not tx_sudo:
            raise ValidationError("Test simulation is only available in test mode")

        timestamp = datetime.now(pytz.UTC).strftime('%Y-%m-%d %H:%M:%S.%f%z')
        
        # Base webhook data that's common to all statuses
        webhook_data = {
            'pix_id': operation_id,
            'status': status,
            'tx_id': None,
            'type': 'charge',
            'timestamp': timestamp,
        }

        # Add data field for processing and done statuses
        if status in ['processing', 'done']:
            common_data = {
                'bank_txid': f'TEST-{operation_id}',
                'bank_account_nr': '00360305-2218-8041045888',
                'internal_pix_id': f'TEST-{operation_id}',
                'amount_brl': str(amount_brl),  # API expects string
                'amount_usdt': str(amount_usdt),
                'address_out': '0xca4xxxxxxxxxxxxxxx1f2fc',
                'name': 'Test User'
            }
            
            if status == 'done':
                # For 'done' status, include blockchain transaction ID
                tx_id = f'0x{operation_id[:8]}2792b5deff9440b6xxxxxxxxxxxxxxxf0c25b47739cbc3a35b16'
                webhook_data['tx_id'] = tx_id
                common_data['tx_id'] = tx_id
            else:
                # For 'processing' status, tx_id is None
                common_data['tx_id'] = None
                
            webhook_data['data'] = common_data

        _logger.info(
            "Sending webhook simulation to KamiPay emulator for operation %s with data:\n%s",
            operation_id, pprint.pformat(webhook_data)
        )

        access_token = tx_sudo.provider_id._get_kamipay_access_token()
        base_url = 'https://devnakamotoapi2.kamipay.io' if tx_sudo.provider_id.state == 'test' else 'https://api2.kamipay.io'
        url = f"{base_url}/v1/emulator/push_webhook"

        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
        }

        try:
            response = requests.post(url, json=webhook_data, headers=headers, timeout=10)
            response.raise_for_status()
            _logger.info("KamiPay emulator response at %s", datetime.now(pytz.UTC))
            _logger.info("KamiPay emulator response status code: %s", response.status_code)
            _logger.info("KamiPay emulator response content: %s", response.text)
            return {'status': 'ok', 'simulation_start': simulation_start.isoformat()}
        except requests.exceptions.RequestException as e:
            _logger.error("Failed to send webhook simulation to KamiPay: %s", str(e))
            raise ValidationError(_("Failed to simulate webhook: %s", str(e)))
            
    @http.route(_return_url, type='http', methods=['GET'], auth='public', csrf=False, save_session=False)
    def kamipay_return_from_checkout(self, **data):
        """ Handle the return from KamiPay and redirect to status page. """
        _logger.info("Handling return from KamiPay with data:\n%s", pprint.pformat(data))
        
        # Check if it's an expiry return
        if data.get('expired'):
            reference = data.get('reference')
            if reference:
                tx_sudo = request.env['payment.transaction'].sudo().search([
                    ('reference', '=', reference),
                    ('provider_code', '=', 'kamipay'),
                    ('state', '=', 'draft'),  # Only update draft transactions
                ], limit=1)
                
                if tx_sudo:
                    _logger.info("Setting expired QR transaction %s to canceled", tx_sudo.reference)
                    tx_sudo._set_canceled(state_message=_("Payment timeout - QR code expired"))

            return request.redirect('/payment/status')

        # Handle normal return flow
        tx_sudo = request.env['payment.transaction'].sudo().search([
            ('reference', '=', data.get('reference'))
        ], limit=1)

        if not tx_sudo:
            _logger.error("No transaction found for reference %s", data.get('reference'))
            return request.redirect('/payment/status')

        # Check transaction status and redirect to status page
        if tx_sudo.state not in ['done', 'error']:
            # Make a status check before redirecting
            status_response = tx_sudo.provider_id._kamipay_make_request(
                f'/v2/status/tx_status',
                payload={
                    'target': 'operation_id',
                    'type': 'charge',
                    'id': tx_sudo.kamipay_operation_id,
                    'chain': 'polygon'
                },
                method='GET'
            )
            
            if status_response.get('status') == 'ok':
                notification_data = {
                    'pix_id': tx_sudo.kamipay_operation_id,
                    'status': status_response['data'].get('status', 'error'),
                    'type': 'charge',
                    'timestamp': datetime.now(pytz.UTC).strftime('%Y-%m-%d %H:%M:%S.%f%z')
                }
                request.env['payment.transaction'].sudo()._handle_notification_data(
                    'kamipay', notification_data
                )

        return request.redirect('/payment/status')