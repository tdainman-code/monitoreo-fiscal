"""VEP de una cuota de Mis Facilidades (réplica de las pantallas que mostró Gaby el 17/11/2026)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from playwright.sync_api import sync_playwright
from robots import robot_vep_facilidades as rv, arca

arca.pausa = lambda *a, **k: None
HTML = """<html><body><div>Contribuyente: 30-71746863-1 - BH SOLUCIONES</div><p>REHABILITAR CUOTAS</p><p>Nro de plan: V311555</p>
<table><tr><th>Cuota Nro.</th><th>Capital</th><th>Int</th><th>Total</th><th>Venc</th><th>Opción</th><th>Res</th><th>Valor</th><th>Nuevo</th></tr>
<tr><td rowspan="2">11</td><td>1</td><td>1</td><td>1</td><td>16/10/2026</td><td><button onclick="window.rehab=1">Rehabilitar</button></td><td>1</td><td>1</td><td>12/11/2026</td></tr>
<tr><td><button onclick="pedir(11)">Generar Vep</button></td><td>1</td><td>1</td><td>17/11/2026</td></tr>
<tr><td rowspan="2">12</td><td>3.515,79</td><td>3.332,56</td><td>6.848,35</td><td>16/11/2026</td><td><button onclick="window.rehab=1">Rehabilitar</button></td><td>163,22</td><td>7.011,57</td><td>12/12/2026</td></tr>
<tr><td><button onclick="pedir(12)">Generar Vep</button></td><td>6,28</td><td>6.854,63</td><td>17/11/2026</td></tr></table>
<div id="m"></div><script>
let nro = 1708960299, cuota = 0;
function modal(h){ document.getElementById('m').innerHTML = '<div class="modal show" style="display:block">'+h+'</div>'; }
function pedir(c){ cuota = c; modal('<h4>ATENCION</h4><p>¿Está seguro que quiere rehabilitar la cuota N° '+c+' por un total de 6.854,63 pesos?</p><button onclick="document.getElementById(\\'m\\').innerHTML=\\'\\'">Cancelar</button><button onclick="tipos()">Aceptar</button>'); }
function tipos(){ modal('<img alt="ARCA"><p>Seleccione tipo de pago</p><img alt="pagar link" onclick="vep(\\'link\\')"><img alt="PagoMisCuentas" onclick="vep(\\'pmc\\')"><img alt="INTERbanking" onclick="vep(\\'ib\\')"><img alt="XN group" onclick="vep(\\'xn\\')"><button>Cerrar</button>'); }
function vep(m){ window.medio = m; modal('<p>Nro. VEP: '+(nro++)+'</p><p>Organismo recaudador: ARCA</p><p>Tipo de pago: MIS FACILIDADES</p><p>Nro. de plan: V311555</p><p>Cuota: '+cuota+'</p><p>Importe: 6854.63</p><p>Fecha de creación: 2026-11-17T19:03:58</p><p>Fecha de expiración: 2026-11-17</p><button onclick="document.getElementById(\\'m\\').innerHTML=\\'\\'">Cerrar</button>'); }
</script></body></html>"""
ok = True
def chk(c, m):
    global ok; print(("✔ " if c else "✘ ") + m); ok &= bool(c)

with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(); pg.set_content(HTML)
    d = rv.vep_en_pantalla(pg, "V311555", 12, "Pago Mis Cuentas (Banelco)")
    chk(d["vep"] == "1708960299" and d["cuota"] == "12" and d["vence"] == "2026-11-17" and pg.evaluate("window.medio") == "pmc",
        "Generar Vep de la cuota 12 por Pago Mis Cuentas: lee número, cuota y vencimiento")
    chk(not pg.evaluate("window.rehab"), "NUNCA toca 'Rehabilitar'")
    pg.get_by_role("button", name="Cerrar").first.click()
    d2 = rv.vep_en_pantalla(pg, "V311555", 12, "Interbanking")
    chk(d2["vep"] == "1708960300" and pg.evaluate("window.medio") == "ib", "segundo VEP por Interbanking")
    pg.get_by_role("button", name="Cerrar").first.click()
    try:
        rv.vep_en_pantalla(pg, "V311555", 13, "Interbanking"); chk(False, "cuota inexistente")
    except arca.ErrorRobot:
        chk(True, "cuota que no está en la pantalla: se detiene sin generar nada")
    try:
        rv.vep_en_pantalla(pg, "W999999", 12, "Pagar (Red Link)"); chk(False, "otro plan")
    except arca.ErrorRobot:
        chk(True, "si el VEP sale de otro plan, lo rechaza")
    b.close()
print("TODO OK" if ok else "FALLAS"); sys.exit(0 if ok else 1)
