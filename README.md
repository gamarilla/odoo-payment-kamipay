# Proveedor de pago KamiPay para Odoo 19 (no oficial)

[English summary below](#english-summary)

Integra [KamiPay](https://kamipay.io) con Odoo: el cliente paga con **PIX** (Brasil, BRL) escaneando un
código QR y el comercio recibe **USDT**. Pensado para operaciones cross-border Argentina ⇄ Brasil, de
acreditación inmediata y no reversible. Licencia LGPL-3. La versión para Odoo 17 está en la rama `17.0`.

## Cómo funciona (y qué cambió respecto de la versión 17)

1. El cliente elige "PIX (KamiPay)" en el pago. Odoo crea la transacción y la envía (flujo *redirect*) a
   `/payment/kamipay/process`, que crea el **cobro PIX dinámico** en KamiPay (`/v2/charge/create_dynamic_pix_b2b`)
   y deja la transacción **pendiente**.
2. El QR, el importe y el código "copia e cola" se muestran **en la propia página de estado de Odoo**
   (`/payment/status`), con cuenta regresiva de 10 minutos. No hay página propia ni polling propio: usa el
   post-procesamiento estándar de Odoo 19, que consulta el estado cada pocos segundos y continúa solo.
3. KamiPay confirma el pago con un **webhook firmado** (`X-Kamipay-Auth`, HMAC-SHA256 del cuerpo con la clave
   de firma). Odoo verifica la firma, valida el importe en BRL contra la transacción y la marca como pagada.
   El pedido se confirma y el pago contable se registra con el mecanismo estándar (`account_payment`).
4. **Red de seguridad**: un cron cada 5 minutos consulta en KamiPay (`/v2/status/tx_status`) todas las
   transacciones pendientes. Si el webhook se perdió o el cliente cerró el navegador, la transacción se
   confirma igual; si el QR venció sin pago, se cancela. Al volver a la página de estado con un QR vencido,
   el servidor también consulta KamiPay antes de cancelar, por si el pago entró en el último segundo.

Esto resuelve los defectos de la versión 17: transacciones que quedaban en borrador, QR expirados que no se
cerraban y pagos confirmados tarde que no llegaban a confirmar el pedido.

## Configuración

Contabilidad → Configuración → Proveedores de pago → **PIX (KamiPay)**:

- API Key, API Secret y Clave de firma de webhooks (las entrega KamiPay).
- Dirección de la billetera USDT donde se liquida.
- Diario contable donde registrar los cobros.
- Estado *Prueba* usa `devnakamotoapi2.kamipay.io`; *Habilitado* usa `api2.kamipay.io`.
- Moneda: solo **BRL** (el proveedor se oculta para otras monedas). Método de pago: Pix.

Configurar en KamiPay la URL del webhook: `https://<tu-dominio>/payment/kamipay/webhook`.

## Pruebas

Con el proveedor en modo *Prueba*, la página del QR muestra un enlace a la **consola de prueba**
(`/payment/kamipay/test/console/<id>`, solo usuarios internos) que pide al emulador de KamiPay que envíe
el webhook con el estado elegido (`processing`, `done`, `expired`, `failed`) y permite consultar el estado
real en KamiPay.

## Requisitos

Odoo 19 Community o Enterprise, módulo `payment` (y `account_payment` para registrar los cobros).
Sin dependencias Python adicionales.

## English summary

Unofficial KamiPay payment provider for Odoo 19: customers pay by PIX (BRL) scanning a QR code, the
merchant settles in USDT. The QR is rendered on Odoo's standard payment status page; the transaction is
confirmed by KamiPay's signed webhook, and a 5-minute cron reconciles pending transactions against the
KamiPay status API (lost webhooks, closed browsers) and expires stale QR codes. Odoo 17 version: branch `17.0`.
