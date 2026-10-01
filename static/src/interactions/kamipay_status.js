import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";

/** Cuenta regresiva y botón de copiar en la tarjeta del QR (página /payment/status).
 *  El polling y la redirección los hace el core (payment.payment_post_processing). Al vencer el QR se
 *  recarga la página: el servidor consulta KamiPay en _post_process y cancela si no hubo pago. */
export class KamiPayQr extends Interaction {
    static selector = ".o_kamipay_qr";
    dynamicContent = {
        ".o_kamipay_copy": { "t-on-click": this.copy },
    };

    start() {
        const expiresAt = this.el.dataset.expiresAt ? new Date(this.el.dataset.expiresAt + "Z") : null;
        if (!expiresAt) return;
        const tick = () => {
            const left = Math.max(0, Math.floor((expiresAt - Date.now()) / 1000));
            const mm = String(Math.floor(left / 60)).padStart(2, "0");
            const ss = String(left % 60).padStart(2, "0");
            this.el.querySelector(".o_kamipay_countdown").textContent = `${mm}:${ss}`;
            if (left <= 0) {
                window.location.reload();
            }
        };
        tick();
        this.registerCleanup(() => clearInterval(this.timer));
        this.timer = setInterval(tick, 1000);
    }

    async copy() {
        const input = this.el.querySelector(".o_kamipay_emv");
        try {
            await navigator.clipboard.writeText(input.value);
        } catch {
            input.select();
            document.execCommand("copy");
        }
        const btn = this.el.querySelector(".o_kamipay_copy");
        const old = btn.innerHTML;
        btn.innerHTML = '<i class="fa fa-check"/> Copiado';
        setTimeout(() => (btn.innerHTML = old), 2000);
    }
}

/** Consola de prueba (solo proveedor en modo test). */
export class KamiPayTestConsole extends Interaction {
    static selector = ".o_kamipay_test_console";
    dynamicContent = {
        ".o_kamipay_simulate": { "t-on-click": this.simulate },
        ".o_kamipay_sync": { "t-on-click": this.sync },
    };

    log(msg) {
        const pre = this.el.querySelector(".o_kamipay_log");
        pre.textContent = `${new Date().toLocaleTimeString()} ${msg}\n` + pre.textContent;
    }

    async simulate(ev) {
        const status = ev.currentTarget.dataset.status;
        try {
            await rpc("/payment/kamipay/test/simulate_webhook", { tx_id: this.el.dataset.txId, status });
            this.log(`webhook '${status}' pedido al emulador de KamiPay`);
            setTimeout(() => this.sync(), 2000);
        } catch (e) {
            this.log(`error: ${e.message || e}`);
        }
    }

    async sync() {
        try {
            const r = await rpc(`/payment/kamipay/test/sync/${this.el.dataset.txId}`, {});
            this.el.querySelector(".o_kamipay_state").textContent = r.state;
            this.log(`estado Odoo: ${r.state} — ${r.state_message || ""}`);
        } catch (e) {
            this.log(`error: ${e.message || e}`);
        }
    }
}

registry.category("public.interactions").add("payment_kamipay.qr", KamiPayQr);
registry.category("public.interactions").add("payment_kamipay.test_console", KamiPayTestConsole);
