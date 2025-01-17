-- disable kamipay payment provider by nullifying credentials
UPDATE payment_provider
   SET kamipay_api_key = NULL,
       kamipay_api_secret = NULL,
       kamipay_signature_key = NULL,
       kamipay_wallet_address = NULL;
