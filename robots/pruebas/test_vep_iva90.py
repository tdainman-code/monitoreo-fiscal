"""VEP del IVA a 90 días desde "Presentación de DDJJ y Pagos" (relevado con Gaby el 26/11/2026; datos de fantasía):
VEP desde Deuda (casillas, paginado) -> Generar VEP -> VEPs a enviar -> Seleccioná medio de pago -> Seleccionar medio de
pago -> cartel "¿Querés enviar el VEP a INTERBANKING?" -> Aceptar -> N° de VEP.
También: la tabla de Mis Facilidades con el encabezado en una tabla y los renglones en otra (Obligaciones al cierre).
Uso: PYTHONPATH=. python3 robots/pruebas/test_vep_iva90.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ["ROBOTS_DATOS"] = tempfile.mkdtemp()
from playwright.sync_api import sync_playwright  # noqa: E402
from robots import arca, robot_vep_iva90 as ri, robot_situacion_fiscal as rsf  # noqa: E402

arca.pausa = lambda *a, **k: None
ok = True


def chk(c, m):
    global ok
    ok &= bool(c)
    print(("✔ " if c else "✘ ") + m)


CUIT = "20331162788"
F = [["", "202410", "30 - IVA", "19 - 19", "0", "$ 3.213.955,06", "2024-11-25"],
     ["", "202410", "30 - IVA", "19 - 51", "0", "$ 587.769,99", "2024-11-25"],
     ["", "202606", "30 - IVA", "19 - 19", "0", "$ 2.885.397,53", "2026-12-04"],
     ["", "202606", "30 - IVA", "19 - 51", "0", "$ 1.000,00", "2026-12-04"]]
chk(ri.elegir_renglon(F, "202606", "2026-12-04") == 2, "elige el IVA 19 - 19 del período y vencimiento (no los intereses 19 - 51)")
chk(ri.elegir_renglon(F, "20260600", "2026-12-04") == 2, "período de Cuentas Tributarias con 8 dígitos")
chk(ri.elegir_renglon(F, "202606", "2026-12-05") is None, "con otro vencimiento no tilda nada")
chk(ri.elegir_renglon(F + [F[2]], "202606", "2026-12-04") is None, "si hay dos iguales no tilda nada")

PAG1 = [("202409", "351 - CONTRIBUCIONES SEG. SOCIAL", "19 - 19", "$ 2.499.173,29", "2024-10-14")] * 4
PAG2 = [("202606", "30 - IVA", "19 - 51", "$ 1.000,00", "2026-12-04"), ("202606", "30 - IVA", "19 - 19", "$ 2.885.397,53", "2026-12-04")]
HTML = r"""<html><body><h1>PRESENTACIÓN DE DDJJ Y PAGOS</h1><span>GONCALVES VICENTE JUAN JOSE [20-33116278-8]</span>
<div id="deuda"><h2>VEP desde Deuda</h2><select id="c"><option>20331162788 - GONCALVES VICENTE JUAN JOSE</option></select>
<button onclick="ver()">Ver Consulta</button><div id="tab"></div>
Mostrando <select><option>5</option><option>10</option><option>100</option></select> filas | <span id="sel">0 seleccionadas</span>
<button aria-label="Siguiente" id="sig" onclick="pag(2)">&gt;</button>
<button onclick="volver()">Volver</button><button onclick="generar()">Generar VEP</button></div>
<div id="env" style="display:none"><h2>Gestión VEP</h2><a>VEPs a enviar</a>
<table><thead><tr><th><input type=checkbox></th><th>CUIT/CUIL</th><th>Descripción</th><th>Importe</th></tr></thead><tbody>
<tr><td><input type=checkbox checked></td><td>20-33116278-8</td><td>ARCA - OTROS PAGOS</td><td>$ 5.000,00</td></tr>
<tr><td><input type=checkbox id="nuevo" checked></td><td>20-33116278-8</td><td>ARCA - OTROS PAGOS</td><td>$ 2.885.397,53</td></tr>
<tr><td></td><td></td><td>Total:</td><td>$ 2.890.397,53</td></tr></tbody></table>
<button onclick="medio()">Seleccioná medio de pago</button></div>
<div id="med" style="display:none"><h2>Seleccionar medio de pago</h2><p id="tot"></p><p>Medios de pago</p>
<button><img alt="Pago con QR"></button><button><img alt="pagar"></button><button><img alt="PagoMisCuentas"></button>
<button onclick="cartel()"><img alt="interbanking"></button><button><img alt="XN group"></button>
<div id="cart" style="display:none"><span>¿Querés enviar el VEP a INTERBANKING?</span><button>Cancelar</button>
<button onclick="fin()">Aceptar</button></div></div>
<div id="fin" style="display:none">Enviaste el VEP a la entidad de pago. N° de VEP: 445566778899 CUIT: 20-33116278-8</div>
<script>
const P = {1: __PAG1__, 2: __PAG2__}; let pagina = 1;
function ver(){ pag(1); }
function pag(n){ pagina = n; document.getElementById('tab').innerHTML = '<table><thead><tr><th></th><th>Período</th><th>Impuesto</th>'
  + '<th>Concepto y Subconcepto</th><th>Anticipo/Cuota</th><th>Importe</th><th>Vencimiento</th></tr></thead><tbody>'
  + P[n].map(f => '<tr><td><input type=checkbox onchange="cuenta()"></td><td>'+f[0]+'</td><td>'+f[1]+'</td><td>'+f[2]
  + '</td><td>0</td><td>'+f[3]+'</td><td>'+f[4]+'</td></tr>').join('') + '</tbody></table>';
  document.getElementById('sig').disabled = n == 2; }
function cuenta(){ const n = document.querySelectorAll('#tab input:checked').length;
  document.getElementById('sel').innerText = n + (n == 1 ? ' seleccionada' : ' seleccionadas'); }
function generar(){ window.tildado = [...document.querySelectorAll('#tab tr')].filter(r => r.querySelector('input:checked')).map(r => r.innerText);
  document.getElementById('deuda').style.display = 'none'; document.getElementById('env').style.display = ''; }
function medio(){ const s = [...document.querySelectorAll('#env tbody input:checked')].map(c => c.closest('tr').innerText);
  window.enviados = s; document.getElementById('env').style.display = 'none'; document.getElementById('med').style.display = '';
  document.getElementById('tot').innerText = 'Importe Total a pagar: $ 2.885.397,53'; }
function cartel(){ document.getElementById('cart').style.display = ''; }
function fin(){ document.getElementById('med').style.display = 'none'; document.getElementById('fin').style.display = ''; }
</script></body></html>""".replace("__PAG1__", str([list(x) for x in PAG1])).replace("__PAG2__", str([list(x) for x in PAG2]))

with sync_playwright() as pw:
    b = pw.chromium.launch()
    page = b.new_page()
    page.set_content(HTML)
    ri._elegir_contribuyente(page, CUIT)
    ri._mostrar_100(page)
    imp = ri.tildar_iva(page, "202606", "2026-12-04", 2885397.53)
    chk(imp == 2885397.53, "pasa de página y tilda el IVA 19 - 19 del período")
    ri._boton(page, r"^\s*Generar\s+VEP\s*$").click()
    t = page.evaluate("window.tildado")
    chk(len(t) == 1 and "19 - 19" in t[0], "se generó con un solo renglón (sin los intereses)")
    ri.a_medio_de_pago(page, imp)
    e = page.evaluate("window.enviados")
    chk(len(e) == 1 and "2.885.397,53" in e[0], "en VEPs a enviar queda tildado solo el VEP nuevo (destilda el otro)")
    v = ri.enviar_al_medio(page, CUIT, "Interbanking")
    chk(v["vep"] == "445566778899" and v["medio"] == "Interbanking", "elige Interbanking, acepta el cartel y lee el N° de VEP")

    page.set_content(HTML)
    ri._elegir_contribuyente(page, CUIT)
    try:
        ri.tildar_iva(page, "202606", "2026-12-04", 2000000.0)
        chk(False, "importe distinto de Cuentas Tributarias: no genera")
    except arca.ErrorRobot as ex:
        chk("No se generó" in str(ex), "importe distinto de Cuentas Tributarias: no genera")

    # Mis Facilidades: encabezado fijo en una tabla y los renglones en la siguiente (26/11/2026)
    page.set_content("""<table><tr><td><table><thead><tr><th>Año</th><th>Mes</th><th>Imp.</th><th>Monto Obligación($)</th>
      <th>Saldo a Cancelar($)</th></tr></thead></table></td></tr></table>
      <div><table><tbody><tr><td>2024</td><td>10</td><td>30</td><td>1.000,00</td><td>0,00</td></tr>
      <tr><td>2024</td><td>11</td><td>30</td><td>2.000,00</td><td>0,00</td></tr></tbody></table></div>""")
    r = rsf._tabla_por_texto(page, "Saldo a Cancelar")
    chk(r["encabezados"][0] == "Año" and len(r["filas"]) == 2 and r["filas"][1]["celdas"][3] == "2.000,00",
        "Mis Facilidades: toma los renglones de la tabla que sigue al encabezado")
    page.set_content("""<table><thead><tr><th>Año</th><th>Saldo a Cancelar</th></tr></thead>
      <tbody><tr><td>2024</td><td>5,00</td></tr></tbody></table>""")
    r = rsf._tabla_por_texto(page, "Saldo a Cancelar")
    chk(len(r["filas"]) == 1, "Mis Facilidades: la tabla normal sigue igual")
    b.close()

print("TODO OK" if ok else "FALLAS")
sys.exit(0 if ok else 1)
