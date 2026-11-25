"""VEP de deuda desde Cuentas Tributarias: réplica de las pantallas relevadas con Tomás el 20/11/2026 (datos de fantasía):
Deudas (casillas) -> PAGAR SELECCIONADO -> Confirmación -> GENERAR VEP -> Seleccionar medio de pago -> cartel
"¿Querés enviar el VEP a BANELCO?" -> Aceptar -> "Enviaste el VEP a la entidad de pago. N° de VEP ...".
Uso: PYTHONPATH=. python3 robots/pruebas/test_vep_deuda.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ["ROBOTS_DATOS"] = tempfile.mkdtemp()
from playwright.sync_api import sync_playwright  # noqa: E402
from robots import arca, robot_vep_deuda as rv  # noqa: E402

arca.pausa = lambda *a, **k: None
CUIT = "30111111118"
FILAS = [  # impuesto, concepto, subconcepto, periodo, cuota, venc, saldo, int
    ("10 - GANANCIAS SOCIEDADES", "191 - ANTICIPOS", "191 - ANTICIPOS", "2024", "8", "13/01/2025", "$ 0,00", "$ 890,90"),
    ("10 - GANANCIAS SOCIEDADES", "19 - DECLARACIÓN JURADA", "19 - DECLARACIÓN JURADA", "2025", "0", "14/05/2026", "$ 230.823,55", "$ 39.355,56"),
    ("10 - GANANCIAS SOCIEDADES", "191 - ANTICIPOS", "191 - ANTICIPOS", "2026", "7", "14/12/2026", "$ 124.181,64", "$ 0,00"),
    ("30 - IVA", "19 - DECLARACIÓN JURADA", "19 - DECLARACIÓN JURADA", "202609", "0", "19/10/2026", "$ 5.885.010,61", "$ 167.232,99"),
] + [("301 - EMPLEADOR-APORTES SEG. SOCIAL", "19 - DECLARACIÓN JURADA", "19 - DECLARACIÓN JURADA", f"2025{m:02d}", "0",
      f"10/{m:02d}/2025", "$ 1.000,00", "$ 10,00") for m in range(1, 13)]   # 16 filas: la 13 y la 15 se tildan abajo
CUIT_PANTALLA = {"v": "30-11111111-8"}
HTML = r"""<html><head><style>img{display:inline-block;width:80px;height:40px;border:1px solid #888}</style></head><body>
<div role="tablist"><a role="tab">Vencimientos</a><a role="tab" onclick="ver('deudas')">$ Deudas 17</a></div>
<div id="venc" style="display:none"><table><tbody>OCULTAS</tbody></table></div>
<div id="deudas" class="tab-pane active" style="display:none">
 <p>Fecha de consulta: 11/20/2026</p><button onclick="pagar()">PAGAR SELECCIONADO</button>
 <table id="t"><thead><tr><th></th><th>Establecimiento</th><th></th><th>Impuesto</th><th>Concepto</th><th>Subconcepto</th>
 <th>Período</th><th>Ant/Cuota</th><th>Vencimiento</th><th>Saldo</th><th>Int. Resarcitorio</th></tr></thead><tbody>FILAS</tbody></table>
</div>
<div id="conf" style="display:none"><h3>Confirmación</h3><div id="tot"></div>
 <table><thead><tr><th>Impuesto</th><th>Subconcepto</th></tr></thead><tbody id="cbody"></tbody></table>
 <button onclick="ver('deudas')">VOLVER</button><button onclick="ver('medio')">GENERAR VEP</button></div>
<div id="medio" style="display:none"><h2>Seleccionar medio de pago</h2><div><p>Medios de pago</p>
 <a onclick="cartel('QR')"><img alt="Pago con QR" src="qr.png"></a><a onclick="cartel('LINK')"><img alt="" src="pagar.png"></a>
 <a onclick="cartel('BANELCO')"><img alt="" src="pagomiscuentas.png"></a><a onclick="cartel('INTERBANKING')"><img alt="" src="interbanking.png"></a>
 <a onclick="cartel('XN')"><img alt="" src="xn.png"></a></div></div>
<div id="modal" style="display:none" role="dialog"><h4>Medio de pago</h4><p id="pregunta"></p>
 <button onclick="ver('medio')">Cancelar</button><button onclick="fin()">Aceptar</button></div>
<div id="fin" style="display:none"><h3>Enviaste el VEP a la entidad de pago.</h3><p>N° de VEP : 1710611439</p>
 <p>Descripción: VCON#6</p><p>CUIT: CUITPANT</p><p id="imp"></p></div>
<p>CUIT 30-11111111-8</p>
<script>
const ids=['deudas','conf','medio','modal','fin'];
function ver(x){ids.forEach(i=>document.getElementById(i).style.display=(i==x?'block':'none'));}
function num(t){return parseFloat(t.replace('$','').replace(/\./g,'').replace(',','.'))||0}
let total=0;
function pagar(){const sel=[...document.querySelectorAll('#t tbody tr')].filter(r=>r.querySelector('input').checked);
  total=sel.reduce((a,r)=>a+num(r.cells[9].innerText)+num(r.cells[10].innerText),0);
  document.getElementById('cbody').innerHTML=sel.map(r=>'<tr><td>'+r.cells[3].innerText+'</td><td>'+r.cells[5].innerText+'</td></tr>').join('')
   +'<tr><td>Total a pagar</td><td></td></tr>';
  document.getElementById('tot').innerText='Total $ '+total.toLocaleString('es-AR',{minimumFractionDigits:2});ver('conf');}
function cartel(e){document.getElementById('pregunta').innerText='¿Querés enviar el VEP a '+e+'?';document.getElementById('modal').style.display='block';}
function fin(){document.getElementById('imp').innerText='Importe: $ '+total.toLocaleString('es-AR',{minimumFractionDigits:2});ver('fin');}
</script></body></html>"""


def pagina():
    filas = "".join(f"<tr><td><input type='checkbox'></td><td>0</td><td>!</td>" + "".join(f"<td>{x}</td>" for x in f) + "</tr>"
                    for f in FILAS)
    ocultas = "".join(f"<tr><td><input type='checkbox' disabled></td><td>oculta {i}</td></tr>" for i in range(6))
    return HTML.replace("FILAS", filas).replace("OCULTAS", ocultas).replace("CUITPANT", CUIT_PANTALLA["v"])


ok = True


def chk(c, m):
    global ok
    print(("✔ " if c else "✘ ") + m)
    ok &= bool(c)


C1 = {"impuesto": "10 - GANANCIAS SOCIEDADES", "concepto": "191 - ANTICIPOS", "subconcepto": "191 - ANTICIPOS", "periodo": "2024", "cuota": "8"}
C2 = {"impuesto": "10 - GANANCIAS SOCIEDADES", "concepto": "19 - DECLARACIÓN JURADA", "subconcepto": "19 - DECLARACIÓN JURADA", "periodo": "2025", "cuota": "0"}
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    pg.set_content(pagina())
    v = rv.generar_en_sct(pg, pg.main_frame, CUIT, [C1, C2], "Pago Mis Cuentas (Banelco)")
    chk(v["vep"] == "1710611439" and v["descripcion"] == "VCON#6", f"VEP consolidado leído ({v['vep']} {v['descripcion']})")
    chk(isinstance(v.get("_captura"), bytes) and v["_captura"][:4] == b"\x89PNG", "guarda la pantalla final del VEP (para verla en la web)")
    chk(abs(v["importe"] - (890.90 + 230823.55 + 39355.56)) < 0.01 and abs(v["total_confirmacion"] - v["importe"]) < 0.01,
        f"importe del VEP = total de la confirmación ({v['importe']})")
    marcadas = pg.evaluate("[...document.querySelectorAll('#t tbody tr')].map(r=>r.querySelector('input').checked)")
    chk(marcadas == [True, True] + [False] * 14, "tildó exactamente los conceptos pedidos")
    # 25/11/2026 (VEP de Gaby que falló): filas más abajo de la 12 con otra tabla con casillas antes en la página
    pg.set_content(pagina())
    c13 = {"impuesto": "301 - EMPLEADOR-APORTES SEG. SOCIAL", "concepto": "19 - DECLARACIÓN JURADA", "periodo": "202509", "cuota": "0"}
    c15 = dict(c13, periodo="202511")
    pg.evaluate("ver('deudas')")
    n = rv.tildar(pg.main_frame, [c13, c15])
    marcadas = pg.evaluate("[...document.querySelectorAll('#t tbody tr')].map(r=>r.querySelector('input').checked)")
    chk(n == 2 and [i for i, x in enumerate(marcadas) if x] == [12, 14], "tilda filas de más abajo aunque haya otra tabla con casillas")
    # concepto que ya no está (pagado): no genera nada
    pg.set_content(pagina())
    try:
        rv.generar_en_sct(pg, pg.main_frame, CUIT, [C1, dict(C2, periodo="2019")], "Interbanking")
        chk(False, "concepto inexistente debía frenar")
    except arca.ErrorRobot as e:
        chk("no encontré" in str(e) and pg.evaluate("document.getElementById('fin').style.display") != "block",
            "si falta un concepto no genera el VEP")
    # el cartel nombra otra entidad: cancela
    pg.set_content(pagina().replace("cartel('BANELCO')", "cartel('LINK')"))
    try:
        rv.generar_en_sct(pg, pg.main_frame, CUIT, [C1], "Pago Mis Cuentas (Banelco)")
        chk(False, "cartel de otra entidad debía frenar")
    except arca.ErrorRobot as e:
        chk("No se generó" in str(e) and pg.evaluate("document.getElementById('fin').style.display") != "block",
            "si el cartel nombra otra entidad, cancela")
    # VEP de otro CUIT
    CUIT_PANTALLA["v"] = "30-99999999-7"
    pg.set_content(pagina())
    try:
        rv.generar_en_sct(pg, pg.main_frame, CUIT, [C1], "Interbanking")
        chk(False, "otro CUIT debía frenar")
    except arca.CuitEquivocado:
        chk(True, "VEP con otro CUIT: lo informa como error")
    b.close()
# el pedido que deja la web pasa el control de la bandeja del robot
from robots import pedidos as rp  # noqa: E402
base = {"cuit": CUIT, "robot": "vep_deuda", "id": "abcdef0123456789", "medio": "Interbanking", "conceptos": [C1, C2]}
chk(rp._valido(base) and not rp._valido(dict(base, medio="Tarjeta")) and not rp._valido(dict(base, conceptos=[])),
    "pedido de VEP de deuda: valida conceptos y medio de pago")
print("OK" if ok else "FALLÓ")
sys.exit(0 if ok else 1)
