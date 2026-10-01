from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.payment.logging import get_payment_logger
from odoo.addons.payment_kamipay import const

_logger = get_payment_logger(__name__)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    kamipay_operation_id = fields.Char("KamiPay Operation ID", index=True, copy=False)
    kamipay_emv = fields.Char("PIX code (EMV)", copy=False, help="Código 'copia e cola' del PIX; el QR es este texto.")
    kamipay_usdt_amount = fields.Float("USDT Amount", digits='Product Price', copy=False)
    kamipay_rate = fields.Float("Exchange Rate (BRL/USDT)", digits=(12, 6), copy=False)
    kamipay_expires_at = fields.Datetime("QR expires at", copy=False)
    kamipay_is_expired = fields.Boolean(compute='_compute_kamipay_is_expired')

    @api.depends('kamipay_expires_at')
    def _compute_kamipay_is_expired(self):
        now = fields.Datetime.now()
        for tx in self:
            tx.kamipay_is_expired = bool(tx.kamipay_expires_at and tx.kamipay_expires_at <= now)

    # === FLOW: redirect form -> /payment/kamipay/process -> /payment/status (QR + polling) === #

    def _get_specific_rendering_values(self, processing_values):
        if self.provider_code != 'kamipay':
            return super()._get_specific_rendering_values(processing_values)
        return {'api_url': const.PROCESS_ROUTE, 'reference': self.reference}

    def _kamipay_create_charge(self):
        """Crea el cobro PIX dinámico en KamiPay y deja la transacción pendiente (esperando el escaneo)."""
        self.ensure_one()
        if self.kamipay_operation_id:
            return
        if self.currency_id.name not in const.SUPPORTED_CURRENCIES:
            raise ValidationError(_("KamiPay only accepts payments in BRL."))
        data = self.provider_id._send_api_request('POST', const.CHARGE_ENDPOINT, json={
            'address': self.provider_id.kamipay_wallet_address,
            'amount': self.amount,
            'external_reference': self.reference,
            'expire': const.QR_EXPIRY_SECONDS,
        }, reference=self.reference)
        if not data.get('operation_id') or not data.get('emv'):
            raise ValidationError(_("KamiPay did not return a PIX charge (%s).", data))
        self.write({
            'kamipay_operation_id': data['operation_id'],
            'kamipay_emv': data['emv'],
            'kamipay_usdt_amount': float(data.get('amount_usdt') or 0),
            'kamipay_rate': float(data.get('rate') or 0),
            'kamipay_expires_at': fields.Datetime.now() + timedelta(seconds=const.QR_EXPIRY_SECONDS),
        })
        self._set_pending(state_message=_("Waiting for the PIX payment (scan the QR code)."))

    def _kamipay_sync_status(self):
        """Consulta tx_status en KamiPay y aplica el resultado; si el QR venció y no hay pago, cancela."""
        self.ensure_one()
        if self.state not in ('draft', 'pending') or not self.kamipay_operation_id:
            return
        response = self.provider_id._send_api_request('GET', const.STATUS_ENDPOINT, params={
            'target': 'operation_id', 'type': 'charge', 'id': self.kamipay_operation_id, 'chain': 'polygon',
        }, reference=self.reference)
        status_data = (response or {}).get('data') or {}
        status = status_data.get('status')
        if status and status not in const.STATUS_MAPPING['pending']:
            self._process('kamipay', {'pix_id': self.kamipay_operation_id, 'status': status, 'data': status_data})
        elif self.kamipay_is_expired:
            self._set_canceled(state_message=_("The PIX QR code expired without payment."))

    # === PAYMENT DATA PROCESSING (webhook / tx_status) === #

    @api.model
    def _search_by_reference(self, provider_code, payment_data):
        if provider_code != 'kamipay':
            return super()._search_by_reference(provider_code, payment_data)
        operation_id = payment_data.get('pix_id') or payment_data.get('operation_id')
        tx = self.search([('kamipay_operation_id', '=', operation_id), ('provider_code', '=', 'kamipay')]) if operation_id else self
        if not tx:
            _logger.warning("KamiPay: no transaction found for operation %s.", operation_id)
        return tx

    def _extract_amount_data(self, payment_data):
        if self.provider_code != 'kamipay':
            return super()._extract_amount_data(payment_data)
        amount = (payment_data.get('data') or {}).get('amount_brl')
        if not amount:
            return None   # processing/expired/failed no traen importe: no se valida
        return {'amount': float(amount), 'currency_code': 'BRL'}

    def _apply_updates(self, payment_data):
        if self.provider_code != 'kamipay':
            return super()._apply_updates(payment_data)
        status = (payment_data.get('status') or '').lower()
        data = payment_data.get('data') or {}
        if data.get('bank_txid'):
            self.provider_reference = data['bank_txid']
        if status in const.STATUS_MAPPING['pending']:
            self._set_pending(state_message=_("Your PIX payment was received and is being processed."))
        elif status in const.STATUS_MAPPING['done']:
            self._set_done(state_message=_("Your PIX payment has been confirmed."))
        elif status in const.STATUS_MAPPING['cancel']:
            self._set_canceled(state_message=_("The PIX QR code expired without payment."))
        elif status in const.STATUS_MAPPING['error']:
            self._set_error(_("KamiPay reported the payment as failed."))
        else:
            _logger.warning("KamiPay: unknown status %r for transaction %s.", status, self.reference)
            self._set_error(_("Received data with invalid status: %s.", status))

    def _post_process(self):
        """Antes del post-proceso genérico, cerrar los QR vencidos que siguen pendientes (el cliente volvió
        a /payment/status o el cron pasó): consulta KamiPay por si pagó justo antes de vencer."""
        for tx in self.filtered(lambda t: t.provider_code == 'kamipay' and t.state == 'pending' and t.kamipay_is_expired):
            try:
                tx._kamipay_sync_status()
            except ValidationError as e:
                _logger.warning("KamiPay sync on post-process failed for %s: %s", tx.reference, e)
        return super()._post_process()
