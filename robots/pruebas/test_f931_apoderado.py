"""Declaración en línea con un apoderado de varias empresas (pantallas relevadas con Gaby el 17/11/2026)."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault("ROBOTS_DATOS", tempfile.mkdtemp())
from playwright.sync_api import sync_playwright
from robots import robot_f931 as f, arca

arca.pausa = lambda *a, **k: None
arca.verificar_sesion = lambda *a, **k: None
B = f.BASE
EMPRESAS = [("30525839512", "ASOCIACION MACABI"), ("30717468631", "BH SOLUCIONES EMPRESARIALES"),
            ("30717690326", "AMBAR ENERGROUP S. R. L.")]
ESTADO = {"cuit": None}
fmt = arca.cuit_fmt


def pagina(route):
    url = route.request.url
    if "checkIngreso" in url:
        q = url.split("cuit=")[-1] if "cuit=" in url else ""
        if q:
            ESTADO["cuit"] = q
            return route.fulfill(status=302, headers={"Location": B + "avisoInicial.aspx"})
        ops = "".join(f'<option value="{c}">{fmt(c)} - {n}</option>' for c, n in EMPRESAS)
        return route.fulfill(content_type="text/html", body=f"""<html><body><div>Usuario: TOMAS DAINMAN<br>CUIT:<br>Contribuyente:</div>
          <p>Ud. es apoderado de los siguientes CUITs , por favor seleccione uno para comenzar a operar:</p>
          <select onchange="location.href='{B}login/checkIngreso.aspx?cuit='+this.value">{ops}</select></body></html>""")
    cab = f"<div>Usuario: TOMAS DAINMAN<br>CUIT: {fmt(ESTADO['cuit']) if ESTADO['cuit'] else ''}<br></div>" \
          f"<a href='login/checkIngreso.aspx'>para cambiar el CUIT de sesión</a>"
    if "dj_generadas" in url:
        return route.fulfill(content_type="text/html", body=f"<html><body>{cab}<table><tr><td>Original (0)</td><td>10/2026</td><td>3</td></tr></table></body></html>")
    return route.fulfill(content_type="text/html", body=f"<html><body>{cab}<button>ACEPTAR</button></body></html>")


ok = True
def chk(c, m):
    global ok; print(("✔ " if c else "✘ ") + m); ok &= bool(c)

with sync_playwright() as p:
    b = p.chromium.launch(); ctx = b.new_context(); ctx.route("https://serviciossegsoc.afip.gob.ar/**", pagina)
    pg = ctx.new_page(); pg.goto(B + "login/checkIngreso.aspx")
    f.elegir_empresa(pg, "30717468631")
    chk(ESTADO["cuit"] == "30717468631", "elige BH en la lista de apoderado")
    f._ir(pg, B + "consultar/dj_generadas.aspx"); f._controlar_cuit(pg, "30717468631")
    chk(f.lista_dj(pg) == {"2026-10": 0}, "lee las DJ de BH")
    f.elegir_empresa(pg, "30717690326")
    chk(ESTADO["cuit"] == "30717690326", "sesión en BH: cambia el CUIT de sesión a AMBAR")
    pg.wait_for_load_state("load")
    pg.close(); pg = ctx.new_page(); pg.goto(B + "login/checkIngreso.aspx")
    try:
        f.elegir_empresa(pg, "30999999993"); chk(False, "empresa ajena")
    except arca.SinRepresentado:
        chk(True, "empresa que no está en la lista: se detiene (SinRepresentado)")
    b.close()
print("TODO OK" if ok else "FALLAS"); sys.exit(0 if ok else 1)
