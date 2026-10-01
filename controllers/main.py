import pprint

from werkzeug.exceptions import Forbidden, NotFound

from odoo import _, http
from odoo.exceptions import ValidationError
from odoo.http import request

from odoo.addons.payment.logging import get_payment_logger
from odoo.addons.payment_kamipay import const

_logger = get_payment_logger(__name__)


class KamiPayController(http.Controller):

    @http.route(const.PROCESS_ROUTE, type='http', auth='public', methods=['POST'], csrf=False)
    def kamipay_process(self, reference, **_post):
        """Destino del formulario de redirección: crea el cobro PIX y lleva a la página de estado, donde se
        muestra el QR y Odoo hace el polling hasta que el webhook confirme."""
        tx_sudo = request.env['payment.transaction'].sudo().search([('reference', '=', reference), ('provider_code', '=', 'kamipay')], limit=1)
        if not tx_sudo:
            raise NotFound()
        try:
            tx_sudo._kamipay_create_charge()
        except ValidationError as e:
            _logger.warning("KamiPay charge creation failed for %s: %s", reference, e)
            tx_sudo._set_error(_("Could not create the PIX charge: %s", e))
        return request.redirect('/payment/status')

    @http.route(const.WEBHOOK_ROUTE, type='http', auth='public', methods=['POST'], csrf=False)
    def kamipay_webhook(self, **_kwargs):
        """Notificación firmada de KamiPay. Responde 200 con cuerpo vacío al aceptarla."""
        data = request.get_json_data()
        if isinstance(data, dict) and data.get('jsonrpc') == '2.0' and isinstance(data.get('params'), dict):
            data = data['params']
        _logger.info("KamiPay webhook received:\n%s", pprint.pformat(data))
        tx_sudo = request.env['payment.transaction'].sudo()._search_by_reference('kamipay', data)
        if not tx_sudo:
            return ''   # desconocida: se responde 200 para que KamiPay no reintente eternamente
        self._verify_signature(tx_sudo, data)
        tx_sudo._process('kamipay', data)
        return ''

    @staticmethod
    def _verify_signature(tx_sudo, data):
        received = request.httprequest.headers.get(const.SIGNATURE_HEADER)
        if not received:
            _logger.warning("KamiPay webhook without signature for %s.", tx_sudo.reference)
            raise Forbidden()
        expected = tx_sudo.provider_id._kamipay_compute_signature(data)
        if not hmac_compare(received, expected):
            if tx_sudo.provider_id.state == 'test':
                _logger.warning("KamiPay webhook with invalid signature accepted in TEST mode for %s.", tx_sudo.reference)
                return
            _logger.warning("KamiPay webhook with invalid signature for %s.", tx_sudo.reference)
            raise Forbidden()

    # === herramientas de prueba (solo proveedor en modo test) === #

    @http.route('/payment/kamipay/test/console/<int:tx_id>', type='http', auth='user', website=True)
    def kamipay_test_console(self, tx_id, **_kwargs):
        tx_sudo = request.env['payment.transaction'].sudo().browse(tx_id).exists()
        if not tx_sudo or tx_sudo.provider_code != 'kamipay' or tx_sudo.provider_id.state != 'test':
            raise NotFound()
        return request.render('payment_kamipay.test_console_page', {'tx': tx_sudo, 'title': _("KamiPay test console")})

    @http.route('/payment/kamipay/test/simulate_webhook', type='jsonrpc', auth='user')
    def kamipay_simulate_webhook(self, tx_id, status):
        """Pide al emulador de KamiPay (sandbox) que envíe el webhook con el estado elegido."""
        tx_sudo = request.env['payment.transaction'].sudo().browse(int(tx_id)).exists()
        if not tx_sudo or tx_sudo.provider_code != 'kamipay' or tx_sudo.provider_id.state != 'test':
            raise NotFound()
        payload = {'pix_id': tx_sudo.kamipay_operation_id, 'status': status, 'type': 'charge', 'tx_id': None}
        if status in ('processing', 'done'):
            payload['data'] = {'bank_txid': f'TEST-{tx_sudo.kamipay_operation_id}', 'amount_brl': str(tx_sudo.amount),
                               'amount_usdt': str(tx_sudo.kamipay_usdt_amount), 'tx_id': f'0xTEST{tx_sudo.id}' if status == 'done' else None}
        tx_sudo.provider_id._send_api_request('POST', const.EMULATOR_WEBHOOK_ENDPOINT, json=payload, reference=tx_sudo.reference)
        return {'status': 'ok'}

    @http.route('/payment/kamipay/test/sync/<int:tx_id>', type='jsonrpc', auth='user')
    def kamipay_test_sync(self, tx_id):
        tx_sudo = request.env['payment.transaction'].sudo().browse(int(tx_id)).exists()
        if not tx_sudo or tx_sudo.provider_code != 'kamipay':
            raise NotFound()
        tx_sudo._kamipay_sync_status()
        return {'state': tx_sudo.state, 'state_message': tx_sudo.state_message}


def hmac_compare(a, b):
    import hmac
    return hmac.compare_digest(str(a), str(b))
