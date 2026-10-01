-- deshabilitar KamiPay en bases neutralizadas (sandbox): sin credenciales no hay llamadas a la API
UPDATE payment_provider
   SET kamipay_api_key = NULL, kamipay_api_secret = NULL, kamipay_signature_key = NULL,
       kamipay_access_token = NULL, kamipay_token_expiry = NULL
 WHERE code = 'kamipay';
