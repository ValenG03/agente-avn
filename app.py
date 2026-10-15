"""
Agente de Tráfico Web — Asociación Vecinal Nordelta (AVN)
Lee Google Analytics 4 (Data API) y, si está configurado, Microsoft Clarity,
y devuelve métricas, ranking de secciones, potencial de crecimiento y recomendaciones.

Sin credenciales corre en MODO DEMO con datos inventados (claramente señalados).
"""

import json
import re
from datetime import date, timedelta
from urllib.parse import unquote

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

# ----------------------------------------------------------------------------
# Configuración general
# ----------------------------------------------------------------------------
st.set_page_config(page_title="Agente de Tráfico AVN", page_icon="📊", layout="wide")

AZUL = "#0B4F8A"
CELESTE = "#3FA7D6"
VERDE = "#2E9E6B"
NARANJA = "#E8833A"
GRIS = "#8A94A6"

st.markdown(
    f"""
    <style>
      .block-container {{padding-top: 1.6rem;}}
      .demo-banner {{background:#FFF4E5;border-left:6px solid {NARANJA};padding:.8rem 1rem;
                     border-radius:6px;margin-bottom:1rem;color:#5a3a12;}}
      .reco {{border-left:5px solid {AZUL};background:rgba(11,79,138,.06);padding:.7rem 1rem;
              border-radius:6px;margin-bottom:.6rem;}}
      .reco.alta {{border-left-color:#D64545;}}
      .reco.media {{border-left-color:{NARANJA};}}
      .reco.baja {{border-left-color:{VERDE};}}
      .reco b {{display:block;margin-bottom:.2rem;}}
    </style>
    """,
    unsafe_allow_html=True,
)

# Secciones del sitio avnordelta.com (prefijo de URL -> nombre legible).
# El orden importa: primero los prefijos más específicos.
SECCIONES = [
    ("/servicios/trámites-online", "Trámites Online"),
    ("/servicios/información-financiera", "Información Financiera"),
    ("/servicios", "Servicios (inicio)"),
    ("/novedades/noticias", "Noticias (listado)"),
    ("/novedades/archivado", "Noticias (notas)"),
    ("/novedades", "Novedades (inicio)"),
    ("/ciudad/barrios-y-consorcios", "Barrios y Consorcios"),
    ("/ciudad/cómo-llegar", "Cómo llegar"),
    ("/ciudad/deportes-y-recreación", "Deportes y Recreación"),
    ("/ciudad/vivir-y-convivir", "Vivir y Convivir"),
    ("/ciudad/historia-de-nordelta", "Historia de Nordelta"),
    ("/ciudad", "Ciudad (inicio)"),
    ("/gestion/querés-ser-parte-de-avn", "Trabajá en AVN"),
    ("/gestion/querés-ser-proveedor-de-avn", "Ser proveedor"),
    ("/gestion", "Nosotros"),
    ("/sustentabilidad", "Sustentabilidad"),
    ("/ayuda/preguntas-frecuentes", "Preguntas frecuentes"),
    ("/ayuda/teléfonos-útiles", "Teléfonos útiles"),
    ("/ayuda", "Ayuda"),
]

DIAS = ["Domingo", "Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]


def seccion_de(path: str) -> str:
    p = unquote(str(path)).lower().split("?")[0]
    if p in ("", "/", "/index", "/inicio"):
        return "Home"
    if re.match(r"^/\d{4}-", p):
        return "Conexión (newsletter)"
    for prefijo, nombre in SECCIONES:
        if p.startswith(prefijo):
            return nombre
    return "Otras páginas"


# ----------------------------------------------------------------------------
# Lectura de secrets
# ----------------------------------------------------------------------------
def secret(key, default=None):
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


PROPERTY_ID = secret("GA4_PROPERTY_ID")
SA_INFO = secret("gcp_service_account")
CLARITY_TOKEN = secret("CLARITY_API_TOKEN")
CLARITY_PROJECT = secret("CLARITY_PROJECT_ID")
ANTHROPIC_KEY = secret("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = secret("ANTHROPIC_MODEL", "claude-sonnet-5-5")

MODO_DEMO = not (PROPERTY_ID and SA_INFO)

# ----------------------------------------------------------------------------
# Google Analytics 4
# ----------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def ga_client(sa_json: str):
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.oauth2 import service_account

    creds = service_account.Credentials.from_service_account_info(
        json.loads(sa_json),
        scopes=["https://www.googleapis.com/auth/analytics.readonly"],
    )
    return BetaAnalyticsDataClient(credentials=creds)


@st.cache_data(ttl=3600, show_spinner=False)
def ga_report(sa_json, prop, dims, mets, start, end, event_names=None, limit=10000):
    from google.analytics.data_v1beta.types import (
        DateRange, Dimension, Filter, FilterExpression, Metric, RunReportRequest,
    )

    filt = None
    if event_names:
        filt = FilterExpression(
            filter=Filter(
                field_name="eventName",
                in_list_filter=Filter.InListFilter(values=list(event_names)),
            )
        )
    req = RunReportRequest(
        property=f"properties/{prop}",
        dimensions=[Dimension(name=d) for d in dims],
        metrics=[Metric(name=m) for m in mets],
        date_ranges=[DateRange(start_date=start, end_date=end)],
        dimension_filter=filt,
        limit=limit,
    )
    resp = ga_client(sa_json).run_report(req)
    rows = [
        [dv.value for dv in r.dimension_values] + [float(mv.value) for mv in r.metric_values]
        for r in resp.rows
    ]
    return pd.DataFrame(rows, columns=list(dims) + list(mets))


def cargar_ga(click_events):
    sa_json = json.dumps(dict(SA_INFO))
    p = str(PROPERTY_ID)
    R = lambda d, m, s, e, ev=None: ga_report(sa_json, p, tuple(d), tuple(m), s, e, tuple(ev) if ev else None)

    diario = R(["date"], ["activeUsers", "newUsers", "sessions", "screenPageViews"], "30daysAgo", "yesterday")
    diario_prev = R(["date"], ["activeUsers"], "60daysAgo", "31daysAgo")
    paginas = R(["pagePath"], ["screenPageViews", "activeUsers", "userEngagementDuration", "bounceRate"],
                "30daysAgo", "yesterday")
    paginas_prev = R(["pagePath"], ["screenPageViews"], "60daysAgo", "31daysAgo")
    clics = R(["pagePath", "eventName"], ["eventCount"], "30daysAgo", "yesterday", click_events)
    dispositivos = R(["deviceCategory"], ["sessions", "engagementRate"], "30daysAgo", "yesterday")
    canales = R(["sessionDefaultChannelGroup"], ["sessions", "engagementRate"], "30daysAgo", "yesterday")
    horarios = R(["dayOfWeek", "hour"], ["sessions"], "30daysAgo", "yesterday")

    diario["date"] = pd.to_datetime(diario["date"], format="%Y%m%d")
    diario_prev["date"] = pd.to_datetime(diario_prev["date"], format="%Y%m%d")
    for df in (horarios,):
        df["dayOfWeek"] = df["dayOfWeek"].astype(int)
        df["hour"] = df["hour"].astype(int)
    return dict(diario=diario.sort_values("date"), diario_prev=diario_prev.sort_values("date"),
                paginas=paginas, paginas_prev=paginas_prev, clics=clics,
                dispositivos=dispositivos, canales=canales, horarios=horarios)


# ----------------------------------------------------------------------------
# Datos de demostración (inventados, solo para ver la interfaz)
# ----------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def cargar_demo():
    rng = np.random.default_rng(7)
    hoy = date.today()
    fechas = pd.date_range(hoy - timedelta(days=30), hoy - timedelta(days=1))
    fechas_prev = pd.date_range(hoy - timedelta(days=60), hoy - timedelta(days=31))

    def serie(fs, base):
        dow = np.array([1.15, 1.1, 1.05, 1.0, 0.95, 0.7, 0.65])[fs.dayofweek]
        v = base * dow * rng.normal(1, 0.08, len(fs))
        v[fs.day.isin([3, 4])] *= 1.45  # pico de newsletter
        return np.round(v).astype(int)

    au = serie(fechas, 1150)
    diario = pd.DataFrame({"date": fechas, "activeUsers": au, "newUsers": (au * 0.38).astype(int),
                           "sessions": (au * 1.32).astype(int), "screenPageViews": (au * 2.6).astype(int)})
    diario_prev = pd.DataFrame({"date": fechas_prev, "activeUsers": serie(fechas_prev, 1060)})

    pesos = {
        "/": 9000, "/servicios/trámites-online/": 7600, "/ayuda/teléfonos-útiles/": 4200,
        "/novedades/noticias/": 2600, "/novedades/archivado/nota-lagos/": 1300,
        "/novedades/archivado/nota-10k/": 1100, "/ciudad/barrios-y-consorcios/": 2100,
        "/servicios/información-financiera/": 1500, "/ayuda/preguntas-frecuentes/": 1700,
        "/ciudad/cómo-llegar/": 900, "/gestion/querés-ser-parte-de-avn/": 1200,
        "/gestion/quiénes-somos/": 600, "/sustentabilidad/": 450, "/2026-septiembre/": 800,
        "/ciudad/deportes-y-recreación/": 520, "/ciudad/vivir-y-convivir/": 380,
        "/gestion/querés-ser-proveedor-de-avn/": 340, "/ciudad/historia-de-nordelta/": 250,
    }
    filas, filas_prev, clic = [], [], []
    for path, v in pesos.items():
        v = int(v * rng.normal(1, 0.05))
        eng = rng.uniform(25, 95) * (1.8 if path in ("/sustentabilidad/", "/2026-septiembre/",
                                                    "/ciudad/vivir-y-convivir/") else 1)
        filas.append([path, v, int(v * 0.7), v * eng, rng.uniform(0.3, 0.72)])
        crec = 1.4 if path in ("/sustentabilidad/", "/2026-septiembre/") else rng.uniform(0.8, 1.15)
        filas_prev.append([path, int(v / crec)])
        clic.append([path, "click", int(v * rng.uniform(0.05, 0.4))])
    paginas = pd.DataFrame(filas, columns=["pagePath", "screenPageViews", "activeUsers",
                                           "userEngagementDuration", "bounceRate"])
    paginas_prev = pd.DataFrame(filas_prev, columns=["pagePath", "screenPageViews"])
    clics = pd.DataFrame(clic, columns=["pagePath", "eventName", "eventCount"])
    dispositivos = pd.DataFrame({"deviceCategory": ["mobile", "desktop", "tablet"],
                                 "sessions": [26000, 13500, 900], "engagementRate": [0.48, 0.63, 0.55]})
    canales = pd.DataFrame({"sessionDefaultChannelGroup": ["Direct", "Organic Search", "Email",
                                                           "Organic Social", "Referral"],
                            "sessions": [17000, 11000, 6500, 3600, 2300],
                            "engagementRate": [0.55, 0.61, 0.66, 0.38, 0.5]})
    h = []
    for d in range(7):
        for hr in range(24):
            base = 30 + 220 * np.exp(-((hr - 10) ** 2) / 18) + 160 * np.exp(-((hr - 20) ** 2) / 10)
            base *= [0.65, 1.15, 1.1, 1.05, 1.0, 0.95, 0.7][d]
            h.append([d, hr, int(base * rng.normal(1, 0.1))])
    horarios = pd.DataFrame(h, columns=["dayOfWeek", "hour", "sessions"])
    return dict(diario=diario, diario_prev=diario_prev, paginas=paginas, paginas_prev=paginas_prev,
                clics=clics, dispositivos=dispositivos, canales=canales, horarios=horarios)


# ----------------------------------------------------------------------------
# Análisis
# ----------------------------------------------------------------------------
def por_seccion(d, agrupar=True):
    key = "seccion" if agrupar else "pagina"
    pg = d["paginas"].copy()
    pg[key] = pg["pagePath"].map(seccion_de) if agrupar else pg["pagePath"].map(unquote)
    pg["rebote_x_vistas"] = pg["bounceRate"] * pg["screenPageViews"]
    s = pg.groupby(key).agg(vistas=("screenPageViews", "sum"), usuarios=("activeUsers", "sum"),
                            engagement=("userEngagementDuration", "sum"),
                            rxv=("rebote_x_vistas", "sum")).reset_index()
    s["tiempo_por_vista_seg"] = (s["engagement"] / s["vistas"].clip(lower=1)).round(1)
    s["rebote_%"] = (100 * s["rxv"] / s["vistas"].clip(lower=1)).round(1)

    prev = d["paginas_prev"].copy()
    prev[key] = prev["pagePath"].map(seccion_de) if agrupar else prev["pagePath"].map(unquote)
    prev = prev.groupby(key)["screenPageViews"].sum().rename("vistas_mes_anterior")
    s = s.merge(prev, on=key, how="left").fillna({"vistas_mes_anterior": 0})
    s["crecimiento_%"] = np.where(
        s["vistas_mes_anterior"] > 0,
        (100 * (s["vistas"] - s["vistas_mes_anterior"]) / s["vistas_mes_anterior"]).round(1),
        np.nan,
    )

    cl = d["clics"].copy()
    if len(cl):
        cl[key] = cl["pagePath"].map(seccion_de) if agrupar else cl["pagePath"].map(unquote)
        cl = cl.groupby(key)["eventCount"].sum().rename("clics")
        s = s.merge(cl, on=key, how="left")
    else:
        s["clics"] = 0
    s["clics"] = s["clics"].fillna(0).astype(int)

    # Índice de potencial (0-100): mucho interés por visita + poco tráfico + tendencia al alza.
    r_eng = s["tiempo_por_vista_seg"].rank(pct=True)
    r_poco_trafico = 1 - s["vistas"].rank(pct=True)
    r_crec = s["crecimiento_%"].fillna(0).rank(pct=True)
    r_bajo_rebote = 1 - s["rebote_%"].rank(pct=True)
    s["potencial"] = (100 * (0.40 * r_eng + 0.25 * r_poco_trafico + 0.20 * r_crec + 0.15 * r_bajo_rebote)).round(0)
    s = s.drop(columns=["engagement", "rxv"]).rename(columns={key: "Sección" if agrupar else "Página"})
    return s.sort_values("vistas", ascending=False).reset_index(drop=True)


def recomendaciones(d, secc, click_events):
    recos = []
    N = secc.columns[0]
    diario, prev = d["diario"], d["diario_prev"]
    total, total_prev = diario["activeUsers"].sum(), prev["activeUsers"].sum()
    if total_prev:
        var = 100 * (total - total_prev) / total_prev
        if var < -5:
            recos.append(("alta", f"El tráfico cayó {abs(var):.0f}% contra el mes anterior",
                          "Revisá si dejó de salir algún envío de Conexión o si bajaron las búsquedas en Google. "
                          "Cruzalo con el gráfico de canales."))
        elif var > 5:
            recos.append(("baja", f"El tráfico creció {var:.0f}% contra el mes anterior",
                          "Identificá qué notas o envíos lo explican (picos del gráfico de línea) y repetí ese formato."))

    top = secc.iloc[0]
    if top["rebote_%"] > 55:
        recos.append(("alta", f"«{top[N]}» es lo más visitado pero rebota un {top['rebote_%']:.0f}%",
                      "La gente entra y se va. Sumá accesos directos visibles arriba (Trámites, Teléfonos, "
                      "última noticia) y links internos a secciones relacionadas."))

    pot = secc.sort_values("potencial", ascending=False).iloc[0]
    recos.append(("media", f"«{pot[N]}» es la sección con más potencial de crecimiento",
                  f"Retiene {pot['tiempo_por_vista_seg']:.0f} s por visita pero tiene solo "
                  f"{int(pot['vistas']):,} vistas. ".replace(",", ".") +
                  "Destacala en la home, linkeala desde el newsletter Conexión y desde redes."))

    caidas = secc[(secc["crecimiento_%"] < -20) & (secc["vistas"] > secc["vistas"].median())]
    for _, r in caidas.head(2).iterrows():
        recos.append(("media", f"«{r[N]}» bajó {abs(r['crecimiento_%']):.0f}% en visitas",
                      "Chequeá que los links que llevan ahí sigan funcionando y que el contenido esté actualizado."))

    dev = d["dispositivos"].set_index("deviceCategory")
    if "mobile" in dev.index:
        share = dev.loc["mobile", "sessions"] / dev["sessions"].sum()
        if share > 0.5:
            txt = f"El {share*100:.0f}% de las sesiones llega desde el celular."
            if "desktop" in dev.index and dev.loc["mobile", "engagementRate"] < dev.loc["desktop", "engagementRate"] - 0.08:
                recos.append(("alta", "La experiencia en celular rinde peor que en computadora",
                              txt + f" Pero el engagement en mobile ({dev.loc['mobile','engagementRate']*100:.0f}%) "
                              f"está por debajo del de desktop ({dev.loc['desktop','engagementRate']*100:.0f}%). "
                              "Revisá menús desplegables, tamaño de botones y peso de las imágenes."))
            else:
                recos.append(("baja", "El sitio se usa mayormente desde el celular", txt +
                              " Diseñá cada pieza nueva pensando primero en mobile."))

    can = d["canales"].set_index("sessionDefaultChannelGroup")["sessions"]
    tot = can.sum() or 1
    org = can.get("Organic Search", 0) / tot
    soc = (can.get("Organic Social", 0) + can.get("Paid Social", 0)) / tot
    mail = can.get("Email", 0) / tot
    if org < 0.3:
        recos.append(("media", f"Solo el {org*100:.0f}% llega desde Google",
                      "Mejorá títulos y descripciones de las notas con las palabras que usa el vecino "
                      "(«expensas Nordelta», «teléfono guardia Nordelta», etc.)."))
    if soc < 0.12:
        recos.append(("media", f"Las redes aportan solo el {soc*100:.0f}% de las sesiones",
                      "Cada posteo de Instagram/Facebook con novedad debería linkear a la nota en la web, con UTM."))
    if mail < 0.05:
        recos.append(("media", "El newsletter casi no genera visitas medibles",
                      "Agregá parámetros UTM (utm_source=conexion&utm_medium=email) a todos los links del mail."))

    h = d["horarios"]
    if len(h):
        pico = h.sort_values("sessions", ascending=False).iloc[0]
        recos.append(("baja", f"El momento de más tráfico es {DIAS[int(pico['dayOfWeek'])]} a las {int(pico['hour'])} hs",
                      "Programá los envíos y posteos importantes un rato antes de ese pico."))

    if secc["clics"].sum() == 0:
        recos.append(("alta", "No se están midiendo clics",
                      f"No hay eventos {', '.join(click_events)} en GA4. Activá «Clics salientes» en la medición "
                      "mejorada de GA4 y creá en Google Tag Manager un evento para clics internos (menú, botones)."))
    return recos


def tabla_heatmap(h):
    m = h.pivot_table(index="dayOfWeek", columns="hour", values="sessions", aggfunc="sum").reindex(
        index=range(7), columns=range(24)).fillna(0)
    m.index = [DIAS[i] for i in m.index]
    return m


# ----------------------------------------------------------------------------
# Microsoft Clarity (mapas de calor reales del mouse)
# ----------------------------------------------------------------------------
@st.cache_data(ttl=6 * 3600, show_spinner=False)
def clarity_insights(token, dias=3):
    r = requests.get(
        "https://www.clarity.ms/export-data/api/v1/project-live-insights",
        params={"numOfDays": dias, "dimension1": "URL"},
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


# ----------------------------------------------------------------------------
# IA opcional (Claude)
# ----------------------------------------------------------------------------
def analisis_ia(resumen: dict) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    prompt = (
        "Sos analista de comunicación digital de la Asociación Vecinal Nordelta (AVN), que administra los "
        "servicios de la ciudad de Nordelta. Con estos datos de Google Analytics de los últimos 30 días, "
        "escribí en español rioplatense, claro y concreto:\n"
        "1) Un diagnóstico de 3 líneas.\n2) Las 5 acciones de mayor impacto, ordenadas, cada una con qué "
        "cambiar en la web y cómo medirlo.\n3) Una oportunidad de contenido para el newsletter Conexión.\n"
        "No inventes números que no estén en los datos.\n\nDATOS:\n" + json.dumps(resumen, ensure_ascii=False)
    )
    msg = client.messages.create(model=ANTHROPIC_MODEL, max_tokens=1500,
                                 messages=[{"role": "user", "content": prompt}])
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


# ----------------------------------------------------------------------------
# Interfaz
# ----------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### ⚙️ Configuración")
    agrupar = st.toggle("Agrupar por sección", value=True,
                        help="Apagalo para ver cada página por separado (por ejemplo, cada noticia).")
    click_events = st.multiselect(
        "Eventos de GA4 que cuentan como clic",
        ["click", "click_interno", "file_download", "form_submit", "cta_click"],
        default=["click", "click_interno", "file_download"],
        help="«click» es el clic saliente de la medición mejorada. Los demás dependen de cómo esté configurado GTM.",
    )
    st.divider()
    st.caption("Estado de conexiones")
    st.write(("🟢" if not MODO_DEMO else "🟠") + " Google Analytics 4" + (" (demo)" if MODO_DEMO else ""))
    st.write(("🟢" if CLARITY_TOKEN else "⚪") + " Microsoft Clarity")
    st.write(("🟢" if ANTHROPIC_KEY else "⚪") + " Análisis con IA (opcional)")
    if st.button("🔄 Actualizar datos"):
        st.cache_data.clear()
        st.rerun()

st.title("📊 Agente de Tráfico Web · AVN")
st.caption("avnordelta.com · últimos 30 días completos (hasta ayer) vs. los 30 días anteriores")

if MODO_DEMO:
    st.markdown(
        '<div class="demo-banner"><b>MODO DEMO — estos números son inventados.</b> '
        "Sirven solo para ver cómo funciona la app. Cargá las credenciales de GA4 en los Secrets "
        "(ver README) y la app pasa sola a mostrar los datos reales de la AVN.</div>",
        unsafe_allow_html=True,
    )
    datos = cargar_demo()
else:
    try:
        with st.spinner("Consultando Google Analytics…"):
            datos = cargar_ga(click_events)
    except Exception as e:
        st.error(f"No pude leer Google Analytics: {e}")
        st.info("Revisá que el ID de propiedad sea correcto y que el mail de la cuenta de servicio "
                "tenga rol «Lector» en la propiedad de GA4.")
        st.stop()

if datos["diario"].empty:
    st.warning("GA4 no devolvió datos para el período. ¿La propiedad es la correcta?")
    st.stop()

secc = por_seccion(datos, agrupar)
col_nombre = secc.columns[0]
diario = datos["diario"]

# KPIs
prom = diario["activeUsers"].mean()
prom_prev = datos["diario_prev"]["activeUsers"].mean() if len(datos["diario_prev"]) else None
ultimo = diario.iloc[-1]
mas_visitada = secc.iloc[0]
mas_potencial = secc.sort_values("potencial", ascending=False).iloc[0]

k1, k2, k3, k4 = st.columns(4)
k1.metric("Promedio de usuarios por día", f"{prom:,.0f}".replace(",", "."),
          f"{100*(prom-prom_prev)/prom_prev:+.1f}% vs mes anterior" if prom_prev else None)
k2.metric(f"Usuarios ayer ({ultimo['date']:%d/%m})", f"{int(ultimo['activeUsers']):,}".replace(",", "."))
k3.metric("Sección más visitada", mas_visitada[col_nombre], f"{int(mas_visitada['vistas']):,} vistas".replace(",", "."),
          delta_color="off")
k4.metric("Más potencial para crecer", mas_potencial[col_nombre], f"índice {int(mas_potencial['potencial'])}/100",
          delta_color="off")

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["📈 Visitas", "🏆 Top 10 secciones", "💡 Oportunidades", "🔥 Mapa de calor", "🤖 Análisis con IA"]
)

# --- Tab 1: línea de visitas y usuarios exactos por día
with tab1:
    d = diario.copy()
    d["media_7d"] = d["activeUsers"].rolling(7, min_periods=1).mean()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=d["date"], y=d["activeUsers"], mode="lines+markers", name="Usuarios",
                             line=dict(color=AZUL, width=3), marker=dict(size=6)))
    fig.add_trace(go.Scatter(x=d["date"], y=d["screenPageViews"], mode="lines", name="Vistas de página",
                             line=dict(color=CELESTE, width=2, dash="dot"), yaxis="y"))
    fig.add_trace(go.Scatter(x=d["date"], y=d["media_7d"], mode="lines", name="Usuarios (media 7 días)",
                             line=dict(color=NARANJA, width=2)))
    fig.add_hline(y=prom, line_dash="dash", line_color=GRIS,
                  annotation_text=f"Promedio {prom:,.0f}".replace(",", "."), annotation_position="top left")
    fig.update_layout(title="Visitas del último mes", height=440, hovermode="x unified",
                      legend=dict(orientation="h", y=-0.15), margin=dict(l=10, r=10, t=50, b=10),
                      xaxis=dict(tickformat="%d/%m"))
    st.plotly_chart(fig, width="stretch")

    st.markdown("#### Usuarios que entraron a la web, día por día")
    t = d[["date", "activeUsers", "newUsers", "sessions", "screenPageViews"]].sort_values("date", ascending=False)
    t["Día"] = t["date"].dt.dayofweek.map(lambda i: ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"][i])
    t = t.rename(columns={"date": "Fecha", "activeUsers": "Usuarios", "newUsers": "Usuarios nuevos",
                          "sessions": "Sesiones", "screenPageViews": "Vistas"})
    t["Fecha"] = t["Fecha"].dt.strftime("%d/%m/%Y")
    st.dataframe(t[["Fecha", "Día", "Usuarios", "Usuarios nuevos", "Sesiones", "Vistas"]],
                 hide_index=True, width="stretch")
    st.download_button("⬇️ Descargar CSV", t.to_csv(index=False).encode("utf-8"), "usuarios_por_dia.csv")

# --- Tab 2: Top 10
with tab2:
    top10 = secc.head(10).copy()
    fig = px.bar(top10.iloc[::-1], x="vistas", y=col_nombre, orientation="h", text="vistas",
                 color_discrete_sequence=[AZUL], labels={"vistas": "Vistas", col_nombre: ""})
    fig.add_trace(go.Bar(x=top10.iloc[::-1]["clics"], y=top10.iloc[::-1][col_nombre], orientation="h",
                         name="Clics", marker_color=NARANJA, text=top10.iloc[::-1]["clics"]))
    fig.update_traces(textposition="outside")
    fig.update_layout(barmode="group", height=520, title="Top 10: vistas y clics por sección",
                      legend=dict(orientation="h", y=-0.1), margin=dict(l=10, r=40, t=50, b=10))
    fig.data[0].name = "Vistas"
    fig.data[0].showlegend = True
    st.plotly_chart(fig, width="stretch")

    mostrar = top10[[col_nombre, "vistas", "clics", "usuarios", "tiempo_por_vista_seg", "rebote_%", "crecimiento_%"]]
    mostrar.index = range(1, len(mostrar) + 1)
    st.dataframe(mostrar.rename(columns={"vistas": "Vistas", "clics": "Clics", "usuarios": "Usuarios",
                                         "tiempo_por_vista_seg": "Seg. por vista", "rebote_%": "Rebote %",
                                         "crecimiento_%": "Crec. % vs mes ant."}), width="stretch")
    st.caption("«Usuarios» suma los usuarios de cada página, así que una misma persona puede contarse en varias.")

# --- Tab 3: Oportunidades y recomendaciones
with tab3:
    c1, c2 = st.columns([1.1, 1])
    with c1:
        st.markdown("#### Qué cambiar y qué aprovechar")
        for prio, titulo, det in recomendaciones(datos, secc, click_events):
            st.markdown(f'<div class="reco {prio}"><b>{titulo}</b>{det}</div>', unsafe_allow_html=True)
    with c2:
        st.markdown("#### Mapa de oportunidades")
        fig = px.scatter(secc, x="vistas", y="tiempo_por_vista_seg", size="potencial", color="potencial",
                         hover_name=col_nombre, color_continuous_scale=["#cfe3f5", AZUL],
                         labels={"vistas": "Vistas (tráfico)", "tiempo_por_vista_seg": "Segundos por vista (interés)"},
                         log_x=True)
        fig.add_hline(y=secc["tiempo_por_vista_seg"].median(), line_dash="dot", line_color=GRIS)
        fig.add_vline(x=secc["vistas"].median(), line_dash="dot", line_color=GRIS)
        fig.update_layout(height=430, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, width="stretch")
        st.caption("Arriba a la izquierda: secciones que interesan mucho pero tienen poco tráfico → son las de más potencial.")

    st.markdown("#### Ranking de potencial de crecimiento")
    st.dataframe(secc.sort_values("potencial", ascending=False)[[col_nombre, "potencial", "vistas",
                 "tiempo_por_vista_seg", "rebote_%", "crecimiento_%"]].head(10).rename(columns={
                 "potencial": "Potencial (0-100)", "vistas": "Vistas", "tiempo_por_vista_seg": "Seg. por vista",
                 "rebote_%": "Rebote %", "crecimiento_%": "Crec. % vs mes ant."}), hide_index=True,
                 width="stretch")
    with st.expander("¿Cómo se calcula el índice de potencial?"):
        st.write("Combina cuatro posiciones relativas entre secciones: 40% tiempo de lectura por vista, "
                 "25% poco tráfico actual (hay margen para crecer), 20% crecimiento contra el mes anterior "
                 "y 15% bajo rebote. Va de 0 a 100.")

    cc1, cc2 = st.columns(2)
    with cc1:
        can = datos["canales"].sort_values("sessions", ascending=False)
        st.plotly_chart(px.pie(can, names="sessionDefaultChannelGroup", values="sessions", hole=0.5,
                               title="¿De dónde llegan?",
                               color_discrete_sequence=[AZUL, CELESTE, VERDE, NARANJA, GRIS, "#B5C3D6"]),
                        width="stretch")
    with cc2:
        dev = datos["dispositivos"].sort_values("sessions", ascending=False)
        st.plotly_chart(px.pie(dev, names="deviceCategory", values="sessions", hole=0.5,
                               title="¿Desde qué dispositivo?",
                               color_discrete_sequence=[AZUL, CELESTE, NARANJA]), width="stretch")

# --- Tab 4: Mapa de calor
with tab4:
    st.markdown("#### Mapa de calor del recorrido del mouse")
    if CLARITY_TOKEN:
        try:
            ins = clarity_insights(CLARITY_TOKEN)
            metricas = {m.get("metricName"): pd.DataFrame(m.get("information", [])) for m in ins}
            elegida = st.selectbox("Métrica de comportamiento (Clarity, últimos 3 días)", list(metricas))
            st.dataframe(metricas[elegida], width="stretch", hide_index=True)
        except Exception as e:
            st.warning(f"No pude leer Clarity: {e}. La API de Clarity permite pocas consultas por día; probá más tarde.")
        url = (f"https://clarity.microsoft.com/projects/view/{CLARITY_PROJECT}/heatmaps"
               if CLARITY_PROJECT else "https://clarity.microsoft.com/")
        st.link_button("🔥 Abrir los mapas de calor de movimiento, clics y scroll en Clarity", url)
        st.caption("Las imágenes de los mapas de calor viven en Clarity: su API exporta métricas "
                   "(clics muertos, clics de frustración, profundidad de scroll), no las imágenes.")
    else:
        st.info("Para ver por dónde mueve el mouse el usuario promedio hace falta **Microsoft Clarity** (gratis). "
                "Google Analytics no registra el movimiento del mouse. Como la web ya usa Google Tag Manager, "
                "se instala desde ahí sin tocar el código. Los pasos están en el README; después pegás el token "
                "en los Secrets y esta pestaña se completa sola.")

    st.markdown("#### Mapa de calor de tráfico: ¿cuándo entra la gente?")
    m = tabla_heatmap(datos["horarios"])
    fig = px.imshow(m, aspect="auto", color_continuous_scale=["#F3F7FB", CELESTE, AZUL],
                    labels=dict(x="Hora del día", y="", color="Sesiones"))
    fig.update_layout(height=360, margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, width="stretch")
    st.caption("Este mapa muestra sesiones por día y hora (dato de GA4). No es el recorrido del mouse.")

# --- Tab 5: IA
with tab5:
    resumen = {
        "promedio_usuarios_dia": round(float(prom)),
        "promedio_usuarios_dia_mes_anterior": round(float(prom_prev)) if prom_prev else None,
        "secciones": secc.head(15).to_dict(orient="records"),
        "canales": datos["canales"].to_dict(orient="records"),
        "dispositivos": datos["dispositivos"].to_dict(orient="records"),
        "reglas_detectadas": [t for _, t, _ in recomendaciones(datos, secc, click_events)],
    }
    if ANTHROPIC_KEY:
        st.write("Genera un diagnóstico y un plan de acción escrito a partir de los datos de esta pantalla.")
        if st.button("✨ Generar análisis"):
            with st.spinner("Analizando…"):
                try:
                    st.markdown(analisis_ia(resumen))
                except Exception as e:
                    st.error(f"Falló la llamada a la IA: {e}")
        st.caption("Cada análisis consume créditos de la API de Anthropic (unos centavos de dólar).")
    else:
        st.info("Opcional. Las recomendaciones de la pestaña **Oportunidades** ya funcionan gratis con reglas. "
                "Si querés un diagnóstico redactado por IA, agregá `ANTHROPIC_API_KEY` en los Secrets "
                "(la API de Anthropic es paga, por uso).")
    with st.expander("Ver los datos que recibiría la IA"):
        st.json(resumen)
