"""DFE de ARCA: abrir SOLO las comunicaciones sin importancia para que queden leídas (Gaby 27/11/2026).
Réplica de la bandeja nueva (ve.cloud.afip.gob.ar): clic en el asunto -> detalle "N° de comunicación" -> VOLVER.
Uso: PYTHONPATH=. python3 robots/pruebas/test_dfe_rutinarias.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from playwright.sync_api import sync_playwright  # noqa: E402
from robots import arca, robot_dfe as d  # noqa: E402
from robots.notificaciones import rutinaria  # noqa: E402

arca.pausa = lambda *a, **k: None
ok = True


def chk(c, m):
    global ok
    ok &= bool(c)
    print(("✔ " if c else "✘ ") + m)


chk(rutinaria("Sistema Informático Malvina") and rutinaria("Emisión de Libro de Sueldos Digital")
    and rutinaria("SIM - SECOEXPO") and rutinaria("Mi PyME - Categorización y/o Beneficios Fiscales"), "reconoce los seis sistemas")
chk(not rutinaria("Sistema de Cuentas Tributarias") and not rutinaria("Monotributistas y autónomos - Intimación por falta de pago")
    and not rutinaria("Sistema Informático Malvina - Intimación de pago") and not rutinaria("Libro de sueldos - falta de presentación"),
    "nunca las importantes ni las que intiman")

FILAS = [("", "Sistema Informático Malvina", "NABAJUMA SA", "Mensajes", "20/11/2026", True),
         ("", "Sistema de Cuentas Tributarias", "NABAJUMA SA", "Notificaciones", "17/11/2026", True),
         ("", "SIM - SECOEXPO", "NABAJUMA SA", "Mensajes", "15/11/2026", True),
         ("", "SIM - SECOEXPO", "NABAJUMA SA", "Mensajes", "10/11/2026", False),
         ("", "Mi PyME - Categorización y/o Beneficios Fiscales - Intimación", "NABAJUMA SA", "Intimaciones", "09/11/2026", True)]
HTML = """<html><body><ul><li class="nav-item" id="solapa">Comunicaciones de NABAJUMA S.A. x</li></ul><div class="tab-pane active"><div id="lista"><table><thead><tr><th>Notificado</th><th>Asunto</th>
<th>Representado</th><th>Clasificación</th><th>Recibido</th></tr></thead><tbody>
""" + "".join(f"""<tr><td>{n}</td><td><a href="#" onclick="abrir(event,'{a}')" style="font-weight:{700 if nl else 400}">{a}</a></td>
<td>{r}</td><td>{c}</td><td>{f}</td></tr>""" for n, a, r, c, f, nl in FILAS) + """</tbody></table></div>
<div id="det" style="display:none"><h3 id="tit"></h3><p>N° de comunicación: 685057589</p><button onclick="volver()">VOLVER</button></div></div>
<script>window.abiertas = [];
function abrir(e, a){ e.preventDefault(); window.abiertas.push(a); document.getElementById('tit').innerText = a;
  document.getElementById('lista').style.display = 'none'; document.getElementById('det').style.display = ''; }
function volver(){ if (window.todos) document.getElementById('solapa').innerText = 'Comunicaciones de Todos tus representados (75) x';
  document.getElementById('lista').style.display = ''; document.getElementById('det').style.display = 'none'; }
</script></body></html>"""

with sync_playwright() as pw:
    b = pw.chromium.launch()
    p = b.new_page()
    p.set_content(HTML)
    filas = [{"asunto": a, "recibido": f, "representado": r, "clasificacion": c, "organismo": "", "leida_pantalla": not nl}
             for _, a, r, c, f, nl in FILAS]
    n = d.abrir_rutinarias(p, filas, "30712227571", "NABAJUMA S.A.")
    ab = p.evaluate("window.abiertas")
    chk(n == 2 and ab == ["Sistema Informático Malvina", "SIM - SECOEXPO"], f"abre solo las dos rutinarias no leídas ({ab})")
    chk(filas[0]["leida_pantalla"] and filas[0].get("abierta_por_robot") and not filas[1]["leida_pantalla"]
        and not filas[4]["leida_pantalla"], "las marca leídas; Cuentas Tributarias y la intimación quedan sin abrir")
    p.set_content(HTML)
    filas = [{"asunto": a, "recibido": f, "representado": "OTRA EMPRESA SA", "clasificacion": c, "organismo": "", "leida_pantalla": not nl}
             for _, a, r, c, f, nl in FILAS]
    chk(d.abrir_rutinarias(p, filas, "30712227571", "NABAJUMA S.A.") == 0 and p.evaluate("window.abiertas") == [],
        "si el representado es otro, no abre nada")
    p.set_content(HTML)
    p.evaluate("window.todos = true")
    filas = [{"asunto": a, "recibido": f, "representado": r, "clasificacion": c, "organismo": "", "leida_pantalla": not nl}
             for _, a, r, c, f, nl in FILAS]
    n = d.abrir_rutinarias(p, filas, "30712227571", "NABAJUMA S.A.")
    chk(n == 1 and p.evaluate("window.abiertas") == ["Sistema Informático Malvina"],
        "si al volver la pantalla pasa a 'Todos tus representados', no abre ninguna más")
    p.set_content(HTML.replace("Comunicaciones de NABAJUMA S.A. x", "Mis Comunicaciones"))
    filas = [{"asunto": a, "recibido": f, "representado": "", "clasificacion": c, "organismo": "", "leida_pantalla": not nl}
             for _, a, r, c, f, nl in FILAS]
    chk(d.abrir_rutinarias(p, filas, "30712227571", "") == 2, "con la clave del propio cliente (Mis Comunicaciones) también")
    b.close()

print("TODO OK" if ok else "FALLAS")
sys.exit(0 if ok else 1)
