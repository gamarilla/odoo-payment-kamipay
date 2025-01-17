{
    'name': 'Payment Provider: KamiPay',
    'version': '1.0',
    'category': 'Accounting/Payment Providers',
    'sequence': 350,
    'summary': "Payment provider for KamiPay PIX payments in Brazil",
    'description': """
        KamiPay payment provider to handle PIX payments in BRL and convert to USDT.
    """,
    'depends': ['payment'],
    'data': [
        'views/payment_kamipay_templates.xml',
        'views/payment_provider_views.xml',
        'data/payment_provider_data.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'payment_kamipay/static/src/js/payment_kamipay.js',
        ],
    },
    'application': False,
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'license': 'LGPL-3',
}
