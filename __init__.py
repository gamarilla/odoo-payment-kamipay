from . import controllers, models

from odoo.addons.payment import setup_provider, reset_payment_provider


def post_init_hook(env):
    setup_provider(env, 'kamipay')


def uninstall_hook(env):
    reset_payment_provider(env, 'kamipay')
