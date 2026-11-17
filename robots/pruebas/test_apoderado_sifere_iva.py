"""SIFERE Web y Portal IVA con un apoderado de varias empresas (pantallas relevadas con Gaby el 17/11/2026)."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault("ROBOTS_DATOS", tempfile.mkdtemp())
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import sync_playwright
from robots import robot_sifere as sf, robot_libro_iva as li, arca

arca.pausa = lambda *a, **k: None
arca.verificar_sesion = lambda *a, **k: None
fmt = arca.cuit_fmt
YO = ("20388931311", "DAINMAN TOMAS")
EMP = [("30718086058", "CONTRIBUYENTE"), ("30717468631", "CONTRIBUYENTE"), ("30525839512", "ASOCIACION MACABI")]
S = {"sifere": YO, "iva": YO}
BS = "https://app1.comarb.gob.ar/siferewebconsultas/"
BI = "https://siapweb.cloud.afip.gob.ar/iva/"


def sifere(route):
    u = urlparse(route.request.url)
    q = parse_qs(u.query)
    if "sel" in q:
        c = q["sel"][0]
        S["sifere"] = next(e for e in EMP + [YO] if e[0] == c)
    ops = "".join(f'<option value="{c}">{n} (CUIT {fmt(c)} - Jur Sede 901)</option>' for c, n in [YO] + EMP)
    c, n = S["sifere"]
    route.fulfill(content_type="text/html", body=f"""<html><body>
      <div>{YO[1]} ({fmt(YO[0])}) representando a {n} ({fmt(c)})</div><a href="{BS}mainMenu.do">Cambiar Contribuyente</a>
      <form action="{BS}mainMenu.do"><select name="sel">{ops}</select><input type="submit" value="Seleccionar"></form></body></html>""")


def iva(route):
    route.fulfill(content_type="text/html", body=f"""<html><body><div id="cab"></div><div id="app"></div><script>
      const yo = {list(YO)}; const emp = {[list(e) for e in EMP]};
      function fm(c) {{ return c.slice(0,2)+'-'+c.slice(2,10)+'-'+c.slice(10); }}
      function pintar() {{
        const r = JSON.parse(sessionStorage.getItem('rep') || JSON.stringify(yo));
        document.getElementById('cab').innerText = yo[1]+' [CUIT '+fm(yo[0])+']\\nREPRESENTANDO A: '+r[1]+' [CUIT '+fm(r[0])+']';
        if (location.hash === '#/changeRelation') {{
          document.getElementById('app').innerHTML = '<h1>Elegí una persona para ingresar</h1>' + emp.map(e =>
            `<div class="t" data-c="${{e[0]}}"><span>${{e[1]}}</span> <span>[CUIT ${{fm(e[0])}}]</span></div>`).join('');
          document.querySelectorAll('.t').forEach(t => t.onclick = () => {{
            sessionStorage.setItem('rep', JSON.stringify(emp.find(e => e[0] === t.dataset.c))); location.hash = '#/'; }});
        }} else document.getElementById('app').innerHTML = '<h2>Portal IVA</h2>';
      }}
      window.onhashchange = pintar; pintar();</script></body></html>""")


ok = True
def chk(c, m):
    global ok; print(("✔ " if c else "✘ ") + m); ok &= bool(c)

with sync_playwright() as p:
    b = p.chromium.launch(); ctx = b.new_context()
    ctx.route(BS + "**", sifere); ctx.route(BI + "**", iva)
    pg = ctx.new_page(); pg.goto(BS + "mainMenu.do")
    sf.elegir_contribuyente(pg, "30717468631", [])
    chk(S["sifere"][0] == "30717468631", "SIFERE: elige BH en 'Contribuyentes disponibles'")
    sf.elegir_contribuyente(pg, "30525839512", [])
    chk(S["sifere"][0] == "30525839512", "SIFERE: cambia de BH a Macabi")
    try:
        sf.elegir_contribuyente(pg, "30999999993", []); chk(False, "ajena")
    except arca.SinRepresentado:
        chk(True, "SIFERE: empresa que no está en la lista -> se detiene")
    pi = ctx.new_page(); pi.goto(BI + "#/init")
    li.elegir_representado(pi, "30717468631", espera_s=5)
    li._controlar_cuit(pi, "30717468631", "Portal IVA", espera_s=5)
    chk("[CUIT 30-71746863-1]" in pi.inner_text("#cab") and "changeRelation" not in pi.url,
        "Portal IVA: elige BH en 'Elegí una persona' y el encabezado queda en BH")
    try:
        li._controlar_cuit(pi, "30525839512", "Portal IVA", espera_s=3); chk(False, "otro")
    except arca.SinRepresentado:
        chk(True, "Portal IVA: si representa a otra empresa, no lee nada")
    try:
        li.elegir_representado(pi, "30999999993", espera_s=5); chk(False, "ajena")
    except arca.SinRepresentado:
        chk(True, "Portal IVA: empresa que no puede representar -> se detiene")
    b.close()
print("TODO OK" if ok else "FALLAS"); sys.exit(0 if ok else 1)
