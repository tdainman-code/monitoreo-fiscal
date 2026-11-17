"""Prueba del DFE con la pantalla nueva de ARCA (DFE 4.8, relevada por captura el 17/11/2026)."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault("ROBOTS_DATOS", tempfile.mkdtemp())
from playwright.sync_api import sync_playwright
from robots import robot_dfe as d, arca

arca.pausa = lambda *a, **k: None
HTML = """<html><body><h1>DOMICILIO FISCAL ELECTRONICO</h1>
<div>Bandeja de entrada (1)</div><div>Notificaciones (1)</div>
<ul class="nav"><li role="tab" class="nav-link">Mis Comunicaciones (0)</li>
<li role="tab" class="nav-link"><span>Comunicaciones de</span> <span class="chip">BH SOLUCIONES EMPRESARIALES (1) <b id="x" onclick="window.quitado=1">x</b></span></li></ul>
<div class="tab-pane card-body"><table><thead><tr><th>Notificado</th><th>Asunto</th></tr></thead><tbody><tr><td>01/01/2026</td><td>OTRO PANEL</td></tr></tbody></table></div>
<div class="tab-pane active card-body"><table><thead><tr><th>Notificado</th><th>Asunto</th><th>Organismo</th><th>Clasificación</th><th>Recibido</th></tr></thead>
<tbody><tr><td><div class="no-leido"><span title="Notificado de oficio">⚑</span> 26/10/2026</div></td><td><a class="no-leido">Intimación de pago</a></td><td>ARCA</td><td>Notificaciones</td><td>20/10/2026</td></tr>
<tr><td>28/09/2026</td><td>Comunicación informativa</td><td>ARCA</td><td>Notificaciones</td><td>21/09/2026</td></tr></tbody></table></div>
<div>Mostrar <select><option>10</option><option>50</option><option>100</option></select> registros  1 de 1</div>
<div role="dialog" id="modal"><h2>Notificaciones de oficio</h2><p>tenés 1 comunicaciones notificadas de oficio sin leer.</p>
<button onclick="document.getElementById('modal').remove()">CERRAR</button>
<button onclick="window.visualizado=1">VISUALIZAR</button></div>
</body></html>"""
ok = True
def chk(c, m):
    global ok; print(("✔ " if c else "✘ ") + m); ok &= bool(c)

with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(); pg.set_content(HTML)
    chk(d.es_pantalla_nueva(pg), "detecta pantalla nueva")
    d._cerrar_cartel(pg, 1000)
    chk(pg.locator("#modal").count() == 0, "cierra el modal con CERRAR")
    chk(not pg.evaluate("window.visualizado"), "NO toca VISUALIZAR")
    d._elegir_representado_nuevo(pg, "30717468631", "BH SOLUCIONES EMPRESARIALES S.A.")
    chk(not pg.evaluate("window.quitado"), "no quita el representado (x del chip)")
    filas, aviso = d._leer_tabla_nueva(pg)
    chk(len(filas) == 2, f"lee 2 comunicaciones ({len(filas)})")
    chk(filas[0]["leida_pantalla"] is False and filas[1]["leida_pantalla"] is True, "negrita = no leída")
    chk(filas[0]["de_oficio"] and not filas[1]["de_oficio"], "detecta notificado de oficio")
    chk(filas[0]["notificado"] == "26/10/2026" and filas[0]["asunto"] == "Intimación de pago", "columnas")
    try:
        d._elegir_representado_nuevo(pg, "30999999993", "OTRA EMPRESA SRL"); chk(False, "rechaza otro CUIT")
    except arca.CuitEquivocado:
        chk(True, "si la solapa muestra otra empresa, no lee nada (CuitEquivocado)")
    chk(d.coincide_representado("BH SOLUCIONES EMPRESARIALES (1) x", "30717468631", "B.H. Soluciones Empresariales S.R.L."),
        "razón social con puntos y S.R.L. coincide")
    chk(not d.coincide_representado("BH SOLUCIONES EMPRESARIALES (1) x", "30717468631", "BH Logística SA"),
        "otra razón social no coincide")
    chk(not d.coincide_representado("BH SOLUCIONES EMPRESARIALES (1) x", "30717468631", ""),
        "sin razón social no se da por buena")
    b.close()
print("TODO OK" if ok else "FALLAS"); sys.exit(0 if ok else 1)
