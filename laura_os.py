"""
LauraOS — Agente conversacional de pendientes
Requiere: pip install streamlit groq
"""

import streamlit as st
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import json, os, uuid
from datetime import datetime, date
from groq import Groq

# ─── CONFIG ───────────────────────────────────────────────────────────────────
st.set_page_config(page_title="LauraOS", page_icon="🧠", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Space Grotesk', sans-serif; }

.task-card {
    background: #f8f9ff;
    border: 1px solid #e2e4f0;
    border-radius: 10px;
    padding: 14px 16px;
    margin-bottom: 10px;
}
.task-card.alta  { border-left: 4px solid #e74c3c; }
.task-card.media { border-left: 4px solid #f39c12; }
.task-card.baja  { border-left: 4px solid #27ae60; }
.task-card.done  { opacity: 0.45; }

.badge {
    display: inline-block;
    border-radius: 20px;
    padding: 2px 10px;
    font-size: 11px;
    font-weight: 700;
    margin-right: 4px;
}
.badge-alta  { background:#fdecea; color:#c0392b; }
.badge-media { background:#fef5e7; color:#d68910; }
.badge-baja  { background:#eafaf1; color:#1e8449; }

.chat-user {
    background: #4f46e5;
    color: white;
    border-radius: 18px 18px 4px 18px;
    padding: 10px 16px;
    margin: 6px 0 6px 60px;
    font-size: 14px;
}
.chat-agent {
    background: #f1f3ff;
    color: #1a1a2e;
    border-radius: 18px 18px 18px 4px;
    padding: 10px 16px;
    margin: 6px 60px 6px 0;
    font-size: 14px;
}
.col-header {
    font-size: 12px; font-weight: 700; letter-spacing: 1px;
    text-transform: uppercase; color: #9ca3af;
    padding-bottom: 8px; border-bottom: 2px solid #e5e7eb;
    margin-bottom: 12px;
}
</style>
""", unsafe_allow_html=True)

# ─── PERSISTENCIA ─────────────────────────────────────────────────────────────
ARCHIVO = "pendientes.json"

def cargar():
    if os.path.exists(ARCHIVO):
        with open(ARCHIVO, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [t for t in data if isinstance(t, dict)]
    return []

def guardar(tasks):
    with open(ARCHIVO, "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)


# ─── NOTIFICACIONES EMAIL ──────────────────────────────────────────────────────

ULTIMO_ENVIO = "ultimo_envio.json"

def ya_envio_hoy() -> bool:
    if os.path.exists(ULTIMO_ENVIO):
        with open(ULTIMO_ENVIO, "r") as f:
            data = json.load(f)
        return data.get("fecha") == date.today().isoformat()
    return False

def marcar_envio_hoy():
    with open(ULTIMO_ENVIO, "w") as f:
        json.dump({"fecha": date.today().isoformat()}, f)

def enviar_notificacion(tasks: list):
    hoy = date.today()
    vencidas, vencen_hoy = [], []

    for t in tasks:
        if t.get("estado") == "hecho": continue
        fl = t.get("fecha_limite")
        if not fl: continue
        try:
            d = date.fromisoformat(fl)
            if d < hoy:   vencidas.append(t)
            elif d == hoy: vencen_hoy.append(t)
        except: pass

    if not vencidas and not vencen_hoy:
        return

    # Construir cuerpo del correo
    cuerpo = "<h2>🧠 LauraOS — Resumen del día</h2>"

    if vencen_hoy:
        cuerpo += "<h3>📅 Vencen HOY</h3><ul>"
        for t in vencen_hoy:
            cuerpo += f"<li><strong>{t['descripcion']}</strong> · {t.get('contexto','—')} · {t.get('prioridad','').upper()}</li>"
        cuerpo += "</ul>"

    if vencidas:
        cuerpo += "<h3>🔴 Vencidas</h3><ul>"
        for t in vencidas:
            cuerpo += f"<li><strong>{t['descripcion']}</strong> · venció {t['fecha_limite']} · {t.get('contexto','—')}</li>"
        cuerpo += "</ul>"

    try:
        origen   = st.secrets["GMAIL_ORIGEN"]
        password = st.secrets["GMAIL_PASSWORD"]

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"🧠 LauraOS — {len(vencen_hoy)} tarea(s) vencen hoy, {len(vencidas)} vencida(s)"
        msg["From"]    = origen
        msg["To"]      = origen
        msg.attach(MIMEText(cuerpo, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(origen, password)
            server.sendmail(origen, origen, msg.as_string())

        marcar_envio_hoy()
    except Exception as e:
        st.warning(f"No se pudo enviar el correo de notificación: {e}")


# ─── GROQ ─────────────────────────────────────────────────────────────────────

SYSTEM_AGENTE = """Eres LauraOS, un asistente de gestión de tareas para Laura, que trabaja en Colgas S.A. en Colombia en transformación digital y gestión de proyectos TI.

PROYECTOS ACTUALES DE LAURA:
1. Tercerización de nómina — En cierre. Solo falta agendar reunión de entrega de acta de cierre. Deadline: antes del viernes. Prioridad alta.
2. Torre de Control de Abastecimiento — Plataforma de monitoreo de transporte operacional. En ejecución.
3. Tableros Power BI de Subsidios — Dos tableros en desarrollo/mantenimiento.
4. Intercambiabilidad de cilindros — Proyecto nuevo por iniciar.
5. Pago a proveedores con Gemini — Automatización del proceso de pagos con IA.

REGLAS DE CONTEXTO:
- Si una tarea menciona nómina, cierre, acta → contexto: "Tercerización Nómina"
- Si menciona transporte, vehículos, abastecimiento, Torre de Control → contexto: "Torre de Control"
- Si menciona subsidios, Power BI, tableros → contexto: "Tableros Subsidios"
- Si menciona cilindros, intercambiabilidad → contexto: "Intercambiabilidad Cilindros"
- Si menciona proveedores, pagos, Gemini, facturas, tesorería → contexto: "Pago Proveedores"
- Si no encaja en ninguno → pregúntale a Laura a qué proyecto pertenece

Tu trabajo es ayudar a Laura a registrar tareas de forma completa. Cada tarea necesita:
- descripcion: qué hay que hacer (obligatorio)
- responsable: quién lo hace (obligatorio)
- fecha_limite: cuándo (YYYY-MM-DD, puede ser null si no aplica)
- prioridad: alta / media / baja (obligatorio)
- contexto: proyecto o área (obligatorio)

FLUJO:
1. Cuando Laura te dé un texto, extrae todas las tareas que puedas.
2. Asigna el contexto automáticamente según las reglas de arriba cuando sea obvio.
3. Para cada tarea con campos incompletos, pregúntale exactamente lo que falta. Una sola pregunta clara a la vez.
4. Cuando una tarea esté completa, responde con un bloque JSON así (en una línea):
   TAREA_LISTA: {"descripcion":"...","responsable":"...","fecha_limite":"...","prioridad":"...","contexto":"..."}
5. Si hay varias tareas, trabájalas una por una.
6. Si ya tienes todo el contexto necesario, no preguntes de más.
7. Habla en español, tono directo y profesional.
8. Cuando hayas terminado TODAS las tareas del texto, responde exactamente: TODAS_LISTAS"""

def chat_groq(historial: list) -> str:
    client = Groq(api_key=st.secrets["GROQ_API_KEY"])
    resp = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "system", "content": SYSTEM_AGENTE}] + historial,
        max_tokens=1024,
    )
    return resp.choices[0].message.content.strip()

def parsear_tareas(texto: str) -> list:
    tareas = []
    for linea in texto.split("\n"):
        linea = linea.strip()
        if linea.startswith("TAREA_LISTA:"):
            raw = linea.replace("TAREA_LISTA:", "").strip()
            try:
                t = json.loads(raw)
                t["id"] = str(uuid.uuid4())
                t["estado"] = "pendiente"
                t["creado"] = datetime.now().isoformat()
                tareas.append(t)
            except:
                pass
    return tareas

# ─── ESTADO ───────────────────────────────────────────────────────────────────
if "tasks"         not in st.session_state: st.session_state.tasks         = cargar()
if "historial"     not in st.session_state: st.session_state.historial     = []
if "tareas_sesion" not in st.session_state: st.session_state.tareas_sesion = []
if "chat_activo"   not in st.session_state: st.session_state.chat_activo   = False

tasks = st.session_state.tasks

# Enviar notificación una vez por día si hay tareas urgentes
if not ya_envio_hoy():
    enviar_notificacion(tasks)


# ─── SIDEBAR ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🧠 LauraOS")
    st.caption("Agente de pendientes · Groq")
    st.divider()

    total   = len(tasks)
    hechas  = sum(1 for t in tasks if t.get("estado") == "hecho")
    en_prog = sum(1 for t in tasks if t.get("estado") == "en progreso")
    pend    = total - hechas - en_prog

    c1, c2, c3 = st.columns(3)
    c1.metric("⏳ Pend.",  pend)
    c2.metric("🔄 Curso",  en_prog)
    c3.metric("✅ Hechas", hechas)

    st.divider()
    filtro_estado = st.multiselect("Estado", ["pendiente","en progreso","hecho"],
                                   default=["pendiente","en progreso"])
    filtro_prio   = st.multiselect("Prioridad", ["alta","media","baja"],
                                   default=["alta","media","baja"])
    busqueda = st.text_input("🔍 Buscar")

# ─── TABS ─────────────────────────────────────────────────────────────────────
tab_chat, tab_kanban, tab_manual = st.tabs(
    ["💬 Agente", "📌 Mis Pendientes", "✏️ Agregar manual"]
)

# ════════════════════════════════════════════════════════════
# TAB 1 — CHAT AGENTE
# ════════════════════════════════════════════════════════════
with tab_chat:
    st.subheader("💬 Cuéntale al agente")
    st.caption("Pega notas de reuniones o escribe directamente. El agente te preguntará lo que falte.")

    if not st.session_state.chat_activo:
        texto_inicial = st.text_area(
            "¿Qué pasó hoy? ¿Qué quedó pendiente?",
            height=130,
            placeholder="Ej: Reunión con Giovanni: necesito enviar el charter del Torre de Control esta semana. David va a revisar el presupuesto el viernes."
        )
        if st.button("🚀 Analizar", type="primary", disabled=not texto_inicial.strip()):
            st.session_state.historial     = [{"role": "user", "content": texto_inicial}]
            st.session_state.tareas_sesion = []
            st.session_state.chat_activo   = True
            with st.spinner("El agente está analizando..."):
                respuesta = chat_groq(st.session_state.historial)
            st.session_state.historial.append({"role": "assistant", "content": respuesta})
            st.session_state.tareas_sesion.extend(parsear_tareas(respuesta))
            st.rerun()
    else:
        # Renderizar historial
        for msg in st.session_state.historial:
            texto_display = "\n".join(
                l for l in msg["content"].split("\n")
                if not l.strip().startswith("TAREA_LISTA:")
                and l.strip() != "TODAS_LISTAS"
            ).strip()
            if not texto_display:
                continue
            css = "chat-user" if msg["role"] == "user" else "chat-agent"
            st.markdown(f'<div class="{css}">{texto_display}</div>', unsafe_allow_html=True)

        # Tareas capturadas
        if st.session_state.tareas_sesion:
            st.success(f"✅ {len(st.session_state.tareas_sesion)} tarea(s) capturada(s)")
            for t in st.session_state.tareas_sesion:
                prio = t.get("prioridad","media")
                st.markdown(
                    f'<div class="task-card {prio}"><strong>{t.get("descripcion","")}</strong><br/>'
                    f'<small>👤 {t.get("responsable","—")} · 📁 {t.get("contexto","—")} · '
                    f'📅 {t.get("fecha_limite") or "Sin fecha"} · '
                    f'<span class="badge badge-{prio}">{prio.upper()}</span></small></div>',
                    unsafe_allow_html=True
                )

        ultimo = st.session_state.historial[-1]["content"] if st.session_state.historial else ""
        termino = "TODAS_LISTAS" in ultimo

        if termino:
            st.info("El agente terminó de procesar todas las tareas.")
            col_g, col_r = st.columns(2)
            if col_g.button("💾 Guardar todas", type="primary"):
                tasks.extend(st.session_state.tareas_sesion)
                guardar(tasks)
                st.session_state.tasks         = tasks
                st.session_state.historial     = []
                st.session_state.tareas_sesion = []
                st.session_state.chat_activo   = False
                st.success("¡Guardadas!")
                st.rerun()
            if col_r.button("🔄 Nueva sesión"):
                st.session_state.historial     = []
                st.session_state.tareas_sesion = []
                st.session_state.chat_activo   = False
                st.rerun()
        else:
            respuesta_usuario = st.chat_input("Responde al agente...")
            if respuesta_usuario:
                st.session_state.historial.append({"role": "user", "content": respuesta_usuario})
                with st.spinner("Pensando..."):
                    respuesta_agente = chat_groq(st.session_state.historial)
                st.session_state.historial.append({"role": "assistant", "content": respuesta_agente})
                st.session_state.tareas_sesion.extend(parsear_tareas(respuesta_agente))
                st.rerun()

            if st.button("❌ Cancelar sesión"):
                st.session_state.historial     = []
                st.session_state.tareas_sesion = []
                st.session_state.chat_activo   = False
                st.rerun()

# ════════════════════════════════════════════════════════════
# TAB 2 — KANBAN
# ════════════════════════════════════════════════════════════
with tab_kanban:

    def pasa_filtros(t):
        return (
            t.get("estado","pendiente") in filtro_estado
            and t.get("prioridad","media") in filtro_prio
            and (busqueda == ""
                 or busqueda.lower() in t.get("descripcion","").lower()
                 or busqueda.lower() in t.get("contexto","").lower())
        )

    filtradas = [t for t in tasks if pasa_filtros(t)]

    if not filtradas:
        st.info("No hay tareas que coincidan.")
    else:
        col_p, col_e, col_h = st.columns(3)

        def render(t, col):
            prio   = t.get("prioridad","media")
            estado = t.get("estado","pendiente")
            tid    = t["id"]
            done   = "done" if estado == "hecho" else ""
            with col:
                st.markdown(
                    f'<div class="task-card {prio} {done}">'
                    f'<span class="badge badge-{prio}">{prio.upper()}</span><br/><br/>'
                    f'<strong>{t.get("descripcion","")}</strong><br/>'
                    f'<small style="color:#6b7280">👤 {t.get("responsable","—")} &nbsp;|&nbsp; '
                    f'📁 {t.get("contexto","—")} &nbsp;|&nbsp; '
                    f'📅 {t.get("fecha_limite") or "Sin fecha"}</small></div>',
                    unsafe_allow_html=True,
                )
                b1, b2 = st.columns([3, 1])
                nuevo = b1.selectbox("", ["pendiente","en progreso","hecho"],
                                     index=["pendiente","en progreso","hecho"].index(estado),
                                     key=f"est_{tid}", label_visibility="collapsed")
                if nuevo != estado:
                    for t2 in tasks:
                        if t2["id"] == tid: t2["estado"] = nuevo
                    guardar(tasks); st.rerun()
                if b2.button("🗑️", key=f"del_{tid}"):
                    st.session_state.tasks = [t2 for t2 in tasks if t2["id"] != tid]
                    guardar(st.session_state.tasks); st.rerun()

        with col_p:
            st.markdown('<div class="col-header">⏳ Pendiente</div>', unsafe_allow_html=True)
            for t in filtradas:
                if t.get("estado","pendiente") == "pendiente": render(t, col_p)
        with col_e:
            st.markdown('<div class="col-header">🔄 En progreso</div>', unsafe_allow_html=True)
            for t in filtradas:
                if t.get("estado") == "en progreso": render(t, col_e)
        with col_h:
            st.markdown('<div class="col-header">✅ Hecho</div>', unsafe_allow_html=True)
            for t in filtradas:
                if t.get("estado") == "hecho": render(t, col_h)

# ════════════════════════════════════════════════════════════
# TAB 3 — MANUAL
# ════════════════════════════════════════════════════════════
with tab_manual:
    st.subheader("Agregar tarea manualmente")
    desc  = st.text_input("📝 Descripción", placeholder="¿Qué hay que hacer?")
    c1, c2, c3, c4 = st.columns(4)
    resp  = c1.text_input("👤 Responsable", value="Laura")
    prio  = c2.selectbox("🚦 Prioridad", ["alta","media","baja"], index=1)
    ctx   = c3.text_input("📁 Contexto", placeholder="Proyecto / área")
    fecha = c4.date_input("📅 Fecha límite", value=None)

    if st.button("➕ Agregar", type="primary", disabled=not desc.strip()):
        tasks.append({
            "id": str(uuid.uuid4()),
            "descripcion": desc,
            "responsable": resp,
            "prioridad": prio,
            "contexto": ctx,
            "fecha_limite": fecha.isoformat() if fecha else None,
            "estado": "pendiente",
            "creado": datetime.now().isoformat(),
        })
        guardar(tasks)
        st.session_state.tasks = tasks
        st.success("✅ Tarea agregada")
        st.rerun()
