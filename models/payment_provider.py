import logging
import requests
import pprint
from werkzeug import urls
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from datetime import timedelta

_logger = logging.getLogger(__name__)

class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    code = fields.Selection(
        selection_add=[('kamipay', 'KamiPay')],
        ondelete={'kamipay': 'set default'}
    )
    kamipay_api_key = fields.Char(
        string="API Key",
        help="The API key provided by KamiPay",
        required_if_provider='kamipay'
    )
    kamipay_api_secret = fields.Char(
        string="API Secret",
        help="The API secret provided by KamiPay",
        required_if_provider='kamipay'
    )
    kamipay_signature_key = fields.Char(
        string="Webhook Signature",
        help="The signature key to authenticate Webhook messages",
        required_if_provider='kamipay'
    )
    kamipay_wallet_address = fields.Char(
        string="USDT Wallet Address",
        help="Your USDT wallet address where funds will be received",
        required_if_provider='kamipay'
    )
    kamipay_access_token = fields.Char(string="Access Token", groups="base.group_system")
    kamipay_token_expiry = fields.Datetime(string="Token Expiry", groups="base.group_system")

    def _compute_feature_support_fields(self):
        super()._compute_feature_support_fields()
        self.filtered(lambda p: p.code == 'kamipay').update({
            'support_tokenization': False,
            'support_express_checkout': False,
            'support_refund': None,
            'support_manual_capture': None,
        })

    def _get_kamipay_access_token(self):
        """Get a valid access token for KamiPay API."""
        self.ensure_one()

        # Check if we have a valid token
        if self.kamipay_access_token and self.kamipay_token_expiry and self.kamipay_token_expiry > fields.Datetime.now():
            return self.kamipay_access_token

        # Get new token
        base_url = 'https://api2.kamipay.io'
        if self.state == 'test':
            base_url = 'https://devnakamotoapi2.kamipay.io'

        auth_url = urls.url_join(base_url, '/auth/token')
        auth_data = {
            "username": self.kamipay_api_key,
            "password": self.kamipay_api_secret
        }

        try:
            response = requests.post(auth_url, data=auth_data, timeout=10)
            response.raise_for_status()
            token_data = response.json()
            
            # Store the new token and set expiry (let's say 1 hour to be safe)
            self.sudo().write({
                'kamipay_access_token': token_data['access_token'],
                'kamipay_token_expiry': fields.Datetime.now() + timedelta(hours=1)
            })
            return token_data['access_token']

        except requests.exceptions.RequestException as e:
            _logger.error("KamiPay authentication failed: %s", e)
            raise ValidationError(_("Could not authenticate with KamiPay: %s", str(e)))

    def _kamipay_make_request(self, endpoint, query_params=None, payload=None, method='POST'):
        """ Make a request to KamiPay API.
        
        Note: self.ensure_one()
        """
        self.ensure_one()

        base_url = 'https://api2.kamipay.io'
        if self.state == 'test':
            base_url = 'https://devnakamotoapi2.kamipay.io'

        url = urls.url_join(base_url, endpoint)
        
        # Get valid access token
        access_token = self._get_kamipay_access_token()
        
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
        }

        try:
            if method == 'GET':
                response = requests.get(url, params=query_params, headers=headers, timeout=10)
            else:
                response = requests.post(url, json=payload, headers=headers, timeout=10)
                
            _logger.info(
                "KamiPay API request to %s:\nMethod: %s\nParams: %s\nPayload: %s",
                url, method, 
                pprint.pformat(query_params) if query_params else None,
                pprint.pformat(payload) if payload else None
            )
                
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            _logger.error("KamiPay API request failed: %s", e)
            raise ValidationError(_("Could not connect to KamiPay: %s", str(e)))
        
    def _get_redirect_form_view(self, is_validation=False):
        if self.code == 'kamipay':
            return self.redirect_form_view_id
        return super()._get_redirect_form_view(is_validation)
        
    def _get_default_payment_flow(self):
        if self.code == 'kamipay':
            return 'redirect'
        return super()._get_default_payment_flow()
        
        
        