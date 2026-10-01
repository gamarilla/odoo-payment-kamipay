{
    'name': 'Payment Provider: KamiPay',
    'version': '19.0.2.0.0',
    'category': 'Accounting/Payment Providers',
    'sequence': 350,
    'summary': "PIX payments from Brazil settled in USDT, via KamiPay",
    'description': """
KamiPay payment provider: the customer pays with PIX (BRL) scanning a QR code; the merchant receives
USDT. The QR is shown on Odoo's payment status page, the transaction is confirmed by KamiPay's signed
webhook, and a cron reconciles pending transactions against the KamiPay API (lost webhooks, closed
browser) and expires stale QR codes.
""",
    'author': 'Accudyno',
    'website': 'https://github.com/gamarilla/odoo-payment-kamipay',
    'license': 'LGPL-3',
    'depends': ['payment'],
    'data': [
        'views/payment_kamipay_templates.xml',
        'views/payment_provider_views.xml',
        'views/payment_transaction_views.xml',
        'data/payment_provider_data.xml',
        'data/ir_cron.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'payment_kamipay/static/src/interactions/kamipay_status.js',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'application': False,
}
