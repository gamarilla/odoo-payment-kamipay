API_URLS = {
    'enabled': 'https://api2.kamipay.io',
    'test': 'https://devnakamotoapi2.kamipay.io',
}
AUTH_ENDPOINT = '/auth/token'
CHARGE_ENDPOINT = '/v2/charge/create_dynamic_pix_b2b'
STATUS_ENDPOINT = '/v2/status/tx_status'
EMULATOR_WEBHOOK_ENDPOINT = '/v1/emulator/push_webhook'

PROCESS_ROUTE = '/payment/kamipay/process'
WEBHOOK_ROUTE = '/payment/kamipay/webhook'
SIGNATURE_HEADER = 'X-Kamipay-Auth'

QR_EXPIRY_SECONDS = 600          # lo que se pide a KamiPay ('expire') y lo que muestra la cuenta regresiva
TOKEN_LIFETIME_SECONDS = 3300    # el token de KamiPay dura 1 h; se renueva antes

DEFAULT_PAYMENT_METHOD_CODES = {'pix'}
SUPPORTED_CURRENCIES = {'BRL'}

# estado de KamiPay (webhook y tx_status) -> estado de la transacción de Odoo
STATUS_MAPPING = {
    'pending': ('created', 'pending', 'processing'),
    'done': ('done', 'confirmed', 'paid'),
    'cancel': ('expired', 'canceled', 'cancelled'),
    'error': ('failed', 'error', 'rejected'),
}
