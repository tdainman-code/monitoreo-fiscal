"""ARCA falla al tocar el botón de un servicio (Gaby 27/11/2026): la pestaña nueva pide CUIT y clave o pide refrescar.
El robot cierra esa pestaña y vuelve a tocar el botón (hasta 3 veces) sin volver a ingresar.
Uso: PYTHONPATH=. python3 robots/pruebas/test_abrir_servicio.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from playwright.sync_api import sync_playwright  # noqa: E402
from robots import arca  # noqa: E402

arca.pausa = lambda *a, **k: None
ok = True


def chk(c, m):
    global ok
    ok &= bool(c)
    print(("✔ " if c else "✘ ") + m)


MIS = """<html><body><a role="button" title="cuenta_corriente_contrib" href="https://sct.example/app" target="_blank">
<h3>SISTEMA DE CUENTAS TRIBUTARIAS</h3></a></body></html>"""


def correr(fallas: int, refrescar: bool = False):
    estado = {"n": 0, "recargas": 0}
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context()

        def mis(route):
            route.fulfill(body=MIS, content_type="text/html; charset=utf-8")

        def sct(route):
            if "expiredSession" in route.request.url:
                return route.fulfill(body="<p>Ingresar con Clave Fiscal</p>", content_type="text/html; charset=utf-8")
            estado["n"] += 1
            if estado["n"] <= fallas:
                route.fulfill(body="<script>location.replace('https://sct.example/expiredSession')</script>", content_type="text/html; charset=utf-8")
            elif refrescar and estado["recargas"] == 0:
                estado["recargas"] += 1
                route.fulfill(body="<p>Ocurrió un error. Refrescá la pantalla con el botón de reproceso.</p>", content_type="text/html; charset=utf-8")
            else:
                route.fulfill(body="<p>Sistema de Cuentas Tributarias - 30-71222757-1</p>", content_type="text/html; charset=utf-8")

        ctx.route(arca.URL_MIS_SERVICIOS + "*", mis)
        ctx.route("https://sct.example/**", sct)
        ctx.route("https://auth.afip.gob.ar/**", lambda r: r.fulfill(body="<p>Ingresar con Clave Fiscal</p>", content_type="text/html; charset=utf-8"))
        portal = ctx.new_page()
        try:
            pag = arca.abrir_servicio(ctx, portal, "cuentas_tributarias")
            res = pag.inner_text("body")
        except arca.SesionPerdida as e:
            res = f"SesionPerdida: {e}"
        abiertas = len(ctx.pages)
        b.close()
    return res, estado["n"], abiertas


r, n, ab = correr(1)
chk("Cuentas Tributarias" in r and n == 2 and ab == 2, f"una vez pide clave: cierra la pestaña y vuelve a tocar el botón ({n} clics)")
r, n, ab = correr(2)
chk("Cuentas Tributarias" in r and n == 3, "dos veces seguidas: igual entra al tercer intento")
r, n, ab = correr(5)
chk(r.startswith("SesionPerdida") and n == 3, "si falla 3 veces, se da por sesión perdida (y el robot vuelve a ingresar)")
r, n, ab = correr(0, refrescar=True)
chk("Cuentas Tributarias" in r, f"si pide refrescar, recarga la pantalla ({r[:80]!r})")
print("TODO OK" if ok else "FALLAS")
sys.exit(0 if ok else 1)
