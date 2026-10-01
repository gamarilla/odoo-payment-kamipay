import hashlib
import hmac
import json
from datetime import timedelta

from odoo import _, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.payment.logging import get_payment_logger
from odoo.addons.payment_kamipay import const

_logger = get_payment_logger(__name__)


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    code = fields.Selection(selection_add=[('kamipay', 'KamiPay')], ondelete={'kamipay': 'set default'})
    kamipay_api_key = fields.Char("API Key", required_if_provider='kamipay', groups='base.group_system')
    kamipay_api_secret = fields.Char("API Secret", required_if_provider='kamipay', groups='base.group_system')
    kamipay_signature_key = fields.Char("Webhook Signature Key", required_if_provider='kamipay', groups='base.group_system',
                                        help="Clave con la que KamiPay firma (HMAC-SHA256) las notificaciones webhook.")
    kamipay_wallet_address = fields.Char("USDT Wallet Address", required_if_provider='kamipay',
                                         help="Billetera USDT donde KamiPay liquida los pagos PIX.")
    kamipay_access_token = fields.Char(groups='base.group_system')
    kamipay_token_expiry = fields.Datetime(groups='base.group_system')

    # === COMPUTE === #

    def _compute_feature_support_fields(self):
        super()._compute_feature_support_fields()
        self.filtered(lambda p: p.code == 'kamipay').update({
            'support_tokenization': False,
            'support_express_checkout': False,
            'support_refund': None,
            'support_manual_capture': None,
        })

    # === BUSINESS === #

    def _get_supported_currencies(self):
        supported = super()._get_supported_currencies()
        if self.code == 'kamipay':
            supported = supported.filtered(lambda c: c.name in const.SUPPORTED_CURRENCIES)
        return supported

    def _get_default_payment_method_codes(self):
        self.ensure_one()
        if self.code != 'kamipay':
            return super()._get_default_payment_method_codes()
        return const.DEFAULT_PAYMENT_METHOD_CODES

    # === REQUEST HELPERS (payment._send_api_request) === #

    def _build_request_url(self, endpoint, **kwargs):
        if self.code != 'kamipay':
            return super()._build_request_url(endpoint, **kwargs)
        base = const.API_URLS['test' if self.state == 'test' else 'enabled']
        return f"{base}{endpoint}"

    def _build_request_headers(self, method, endpoint, payload, **kwargs):
        if self.code != 'kamipay':
            return super()._build_request_headers(method, endpoint, payload, **kwargs)
        if endpoint == const.AUTH_ENDPOINT:
            return {'Content-Type': 'application/x-www-form-urlencoded'}
        return {'Authorization': f'Bearer {self._kamipay_get_access_token()}', 'Content-Type': 'application/json'}

    def _parse_response_error(self, response):
        if self.code != 'kamipay':
            return super()._parse_response_error(response)
        try:
            data = response.json()
            return data.get('detail') or data.get('message') or data.get('error') or response.text
        except ValueError:
            return response.text

    def _kamipay_get_access_token(self):
        """Token Bearer de KamiPay, cacheado en el proveedor y renovado antes de vencer."""
        self.ensure_one()
        provider = self.sudo()
        if provider.kamipay_access_token and provider.kamipay_token_expiry and provider.kamipay_token_expiry > fields.Datetime.now():
            return provider.kamipay_access_token
        data = provider._send_api_request('POST', const.AUTH_ENDPOINT, data={
            'username': provider.kamipay_api_key, 'password': provider.kamipay_api_secret})
        token = data.get('access_token')
        if not token:
            raise ValidationError(_("KamiPay did not return an access token."))
        provider.write({'kamipay_access_token': token,
                        'kamipay_token_expiry': fields.Datetime.now() + timedelta(seconds=const.TOKEN_LIFETIME_SECONDS)})
        return token

    def _kamipay_compute_signature(self, payload):
        """HMAC-SHA256 del JSON compacto (mismo criterio que KamiPay) con la clave de firma."""
        self.ensure_one()
        key = self.sudo().kamipay_signature_key or ''
        body = json.dumps(payload, sort_keys=False, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        return hmac.new(key.encode('utf-8'), body, hashlib.sha256).hexdigest()

    # === CRON === #

    def _cron_kamipay_sync_pending(self):
        """Red de seguridad: consulta en KamiPay las transacciones que siguen pendientes (webhook perdido,
        cliente que cerró el navegador) y expira los QR vencidos."""
        txs = self.env['payment.transaction'].search([
            ('provider_code', '=', 'kamipay'), ('state', 'in', ('draft', 'pending')),
            ('kamipay_operation_id', '!=', False)])
        for tx in txs:
            try:
                tx._kamipay_sync_status()
                self.env.cr.commit()
            except Exception as e:  # noqa: BLE001 - una tx no debe frenar al resto
                self.env.cr.rollback()
                _logger.warning("KamiPay sync failed for %s: %s", tx.reference, e)
