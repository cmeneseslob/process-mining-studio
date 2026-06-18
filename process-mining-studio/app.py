"""
Process Mining Studio
Herramienta de análisis de procesos inspirada en Celonis y Fluxicon Disco.
Construida con Streamlit y PM4Py.
"""

import streamlit as st
import pandas as pd
import numpy as np
import os
import tempfile
import traceback
from datetime import datetime, timedelta

import pm4py
from pm4py.objects.log.util import dataframe_utils
from pm4py.objects.conversion.log import converter as log_converter

import plotly.express as px
import plotly.graph_objects as go

# ─────────────────────────────────────────────
# PAGE CONFIG (must be first Streamlit call)
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Process Mining Studio",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ─────────────────────────────────────────────
# CUSTOM CSS
# ─────────────────────────────────────────────
def apply_custom_css():
    st.markdown(
        """
        <style>
        /* Header */
        .main-header {
            font-size: 2.4rem; font-weight: 800;
            color: #1a3a5c; margin-bottom: 0;
        }
        .sub-header {
            font-size: 1.05rem; color: #555;
            margin-bottom: 1.5rem;
        }
        /* Metric cards via st.metric look */
        [data-testid="metric-container"] {
            background: #f4f7fb;
            border-radius: 10px;
            padding: 0.8rem 1rem;
            border-left: 4px solid #2196F3;
        }
        /* Tab styling */
        .stTabs [data-baseweb="tab"] {
            font-size: 0.95rem; font-weight: 600;
        }
        /* Table header */
        thead tr th { background-color: #1a3a5c !important; color: white !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────
def init_session_state():
    defaults = {
        "event_log": None,       # Full unfiltered PM4Py EventLog
        "filtered_log": None,    # Log after user-applied filters
        "dataframe": None,       # Full DataFrame (for display/stats)
        "case_id_col": "case:concept:name",
        "activity_col": "concept:name",
        "timestamp_col": "time:timestamp",
        "resource_col": None,
        "cost_col": None,
        "log_name": "",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ─────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────
def seconds_to_human(seconds: float) -> str:
    """Convert seconds to a human-readable string (e.g. '3d 4h 12m')."""
    if seconds < 0 or np.isnan(seconds):
        return "N/A"
    d = int(seconds // 86400)
    h = int((seconds % 86400) // 3600)
    m = int((seconds % 3600) // 60)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m or not parts:
        parts.append(f"{m}m")
    return " ".join(parts)


def find_col_index(columns: list, hints: list) -> int:
    """Return index of first column whose name contains a hint (case-insensitive)."""
    lower = [c.lower() for c in columns]
    for hint in hints:
        for i, col in enumerate(lower):
            if hint in col:
                return i
    return 0


def render_dfg_image(dfg: dict, start_activities: dict, end_activities: dict,
                     log, variant_key, caption: str) -> None:
    """
    Render a DFG (frequency or performance) as PNG via PM4Py's graphviz
    visualizer and display it with st.image.
    Gracefully falls back to a text table if graphviz is unavailable.
    """
    try:
        from pm4py.visualization.dfg import visualizer as dfg_vis

        parameters = {
            "start_activities": start_activities,
            "end_activities": end_activities,
            "format": "png",
        }

        gviz = dfg_vis.apply(dfg, log=log, variant=variant_key, parameters=parameters)

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name

        dfg_vis.save(gviz, tmp_path)
        st.image(tmp_path, use_container_width=True, caption=caption)
        os.unlink(tmp_path)

    except Exception as exc:
        st.warning(f"No se pudo renderizar el grafo (¿graphviz instalado?): {exc}")
        # Fallback: edge table
        rows = [{"Desde": s, "Hacia": t, "Valor": v} for (s, t), v in sorted(dfg.items(), key=lambda x: -x[1])]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def filter_dfg(dfg: dict, start_activities: dict, end_activities: dict,
               activities_pct: int, paths_pct: int):
    """
    Disco-style slider filtering:
      1. Keep only top `activities_pct`% of activities by total arc weight.
      2. Keep only top `paths_pct`% of arcs by weight.
    Returns (filtered_dfg, filtered_start, filtered_end).
    """
    if not dfg:
        return dfg, start_activities, end_activities

    # Aggregate weight per activity
    act_weight: dict = {}
    for (src, tgt), w in dfg.items():
        val = w if isinstance(w, (int, float)) else (w.get("mean", 0) if isinstance(w, dict) else 0)
        act_weight[src] = act_weight.get(src, 0) + val
        act_weight[tgt] = act_weight.get(tgt, 0) + val

    # Add start activities weight
    for act, cnt in start_activities.items():
        act_weight[act] = act_weight.get(act, 0) + cnt

    n_acts = len(act_weight)
    n_keep_acts = max(1, round(n_acts * activities_pct / 100))
    top_acts = set(sorted(act_weight, key=act_weight.get, reverse=True)[:n_keep_acts])

    # Filter arcs to only those between top activities
    arcs = {k: v for k, v in dfg.items() if k[0] in top_acts and k[1] in top_acts}

    # Keep top `paths_pct`% of arcs by weight
    n_keep_paths = max(1, round(len(arcs) * paths_pct / 100))
    sorted_arcs = sorted(arcs.items(),
                         key=lambda x: x[1] if isinstance(x[1], (int, float))
                         else (x[1].get("mean", 0) if isinstance(x[1], dict) else 0),
                         reverse=True)
    arcs = dict(sorted_arcs[:n_keep_paths])

    f_start = {a: c for a, c in start_activities.items() if a in top_acts}
    f_end = {a: c for a, c in end_activities.items() if a in top_acts}

    return arcs, f_start, f_end


# ─────────────────────────────────────────────
# DATA LOADING — SIDEBAR
# ─────────────────────────────────────────────
def sidebar_data_loader():
    st.sidebar.header("📂 Carga de Datos")

    uploaded = st.sidebar.file_uploader(
        "Archivo de log de eventos",
        type=["csv", "xes"],
        help="Formatos soportados: CSV (.csv) y XES (.xes)",
    )

    if uploaded is None:
        # ── Demo data button ──────────────────────────────────────────────
        st.sidebar.divider()
        if st.sidebar.button("🧪 Cargar Log de Demo", use_container_width=True):
            _load_demo_log()
        return

    ext = uploaded.name.rsplit(".", 1)[-1].lower()

    if ext == "xes":
        _load_xes(uploaded)
    elif ext == "csv":
        _load_csv_ui(uploaded)


def _load_demo_log():
    """Generate a synthetic Purchase-to-Pay log for demo purposes."""
    try:
        import random, string
        random.seed(42)

        activities = [
            "Create Purchase Requisition",
            "Approve Requisition",
            "Create Purchase Order",
            "Send Order to Supplier",
            "Receive Goods",
            "Receive Invoice",
            "Match Invoice",
            "Approve Payment",
            "Process Payment",
        ]

        # Variant definitions (index sequences)
        variants = [
            [0, 1, 2, 3, 4, 5, 6, 7, 8],        # happy path (40%)
            [0, 1, 2, 3, 5, 4, 6, 7, 8],          # goods/invoice swapped (20%)
            [0, 2, 3, 4, 5, 6, 7, 8],              # skip approval (15%)
            [0, 1, 2, 3, 4, 5, 6, 8],              # skip payment approval (10%)
            [0, 1, 2, 3, 4, 5, 7, 8],              # skip match (8%)
            [0, 1, 2, 5, 6, 7, 8],                 # short path (7%)
        ]
        weights = [40, 20, 15, 10, 8, 7]

        rows = []
        n_cases = 500
        base_time = datetime(2024, 1, 1)

        for i in range(n_cases):
            case_id = f"CASE-{i+1:04d}"
            variant = random.choices(variants, weights=weights, k=1)[0]
            t = base_time + timedelta(days=random.randint(0, 364))
            for step in variant:
                rows.append({
                    "case:concept:name": case_id,
                    "concept:name": activities[step],
                    "time:timestamp": t,
                    "org:resource": f"User-{random.randint(1,10):02d}",
                    "cost": round(random.uniform(100, 5000), 2),
                })
                t += timedelta(hours=random.randint(1, 48))

        df = pd.DataFrame(rows)
        df = pm4py.format_dataframe(
            df,
            case_id="case:concept:name",
            activity_key="concept:name",
            timestamp_key="time:timestamp",
        )
        log = pm4py.convert_to_event_log(df)

        st.session_state.event_log = log
        st.session_state.filtered_log = log
        st.session_state.dataframe = df
        st.session_state.log_name = "Demo P2P Log"

        st.sidebar.success(f"✅ Demo cargado: {len(log)} casos, {sum(len(t) for t in log)} eventos")
        st.rerun()

    except Exception as e:
        st.sidebar.error(f"Error generando demo: {e}")


def _load_xes(uploaded_file):
    try:
        with tempfile.NamedTemporaryFile(suffix=".xes", delete=False) as tmp:
            tmp.write(uploaded_file.read())
            tmp_path = tmp.name

        log = pm4py.read_xes(tmp_path)
        os.unlink(tmp_path)

        df = pm4py.convert_to_dataframe(log)

        st.session_state.event_log = log
        st.session_state.filtered_log = log
        st.session_state.dataframe = df
        st.session_state.log_name = uploaded_file.name

        n_cases = len(log)
        n_events = sum(len(t) for t in log)
        st.sidebar.success(f"✅ XES cargado: {n_cases:,} casos · {n_events:,} eventos")

    except Exception as e:
        st.sidebar.error(f"Error al cargar XES: {e}")
        with st.sidebar.expander("Detalle del error"):
            st.code(traceback.format_exc())


def _load_csv_ui(uploaded_file):
    """Render CSV column-mapping UI and process on button click."""
    try:
        df_raw = pd.read_csv(uploaded_file)
        cols = list(df_raw.columns)

        st.sidebar.subheader("Mapeo de Columnas")
        case_id_col = st.sidebar.selectbox(
            "Case ID *", cols,
            index=find_col_index(cols, ["case", "case_id", "caseid", "traceid"]),
        )
        activity_col = st.sidebar.selectbox(
            "Actividad *", cols,
            index=find_col_index(cols, ["activity", "actividad", "task", "event", "action"]),
        )
        timestamp_col = st.sidebar.selectbox(
            "Timestamp *", cols,
            index=find_col_index(cols, ["timestamp", "time", "date", "fecha", "start"]),
        )

        optional = ["(Ninguno)"] + cols
        resource_col = st.sidebar.selectbox("Recurso (opcional)", optional,
                                            index=find_col_index(optional, ["resource", "recurso", "user", "agent"]))
        cost_col = st.sidebar.selectbox("Costo (opcional)", optional,
                                        index=find_col_index(optional, ["cost", "costo", "amount", "price"]))

        if st.sidebar.button("🔄 Procesar Log", type="primary", use_container_width=True):
            _process_csv(
                df_raw, uploaded_file.name,
                case_id_col, activity_col, timestamp_col,
                None if resource_col == "(Ninguno)" else resource_col,
                None if cost_col == "(Ninguno)" else cost_col,
            )

    except Exception as e:
        st.sidebar.error(f"Error al leer CSV: {e}")


def _process_csv(df, filename, case_id_col, activity_col, timestamp_col, resource_col, cost_col):
    try:
        col_map = {
            case_id_col: "case:concept:name",
            activity_col: "concept:name",
            timestamp_col: "time:timestamp",
        }
        if resource_col:
            col_map[resource_col] = "org:resource"
        if cost_col:
            col_map[cost_col] = "case:cost"

        df = df.rename(columns=col_map)

        # Convert timestamps using PM4Py utility
        df = dataframe_utils.convert_timestamp_columns_in_df(df)

        # Sort chronologically within each case
        df = df.sort_values(["case:concept:name", "time:timestamp"])

        df_fmt = pm4py.format_dataframe(
            df,
            case_id="case:concept:name",
            activity_key="concept:name",
            timestamp_key="time:timestamp",
        )

        log = pm4py.convert_to_event_log(df_fmt)

        st.session_state.event_log = log
        st.session_state.filtered_log = log
        st.session_state.dataframe = df_fmt
        st.session_state.resource_col = resource_col
        st.session_state.cost_col = cost_col
        st.session_state.log_name = filename

        n_cases = len(log)
        n_events = sum(len(t) for t in log)
        st.sidebar.success(f"✅ Procesado: {n_cases:,} casos · {n_events:,} eventos")
        st.rerun()

    except Exception as e:
        st.sidebar.error(f"Error procesando CSV: {e}")
        with st.sidebar.expander("Detalle del error"):
            st.code(traceback.format_exc())


# ─────────────────────────────────────────────
# VISTA 1 — DISCOVERY & MAPA INTERACTIVO
# ─────────────────────────────────────────────
def view_discovery(log):
    st.subheader("🗺️ Mapa de Proceso — Directly-Follows Graph")

    # ── Controls (right column) ────────────────────────────────────────────
    ctrl_col, map_col = st.columns([1, 3])

    with ctrl_col:
        st.markdown("**Controles del Mapa**")

        activities_pct = st.slider(
            "Actividades (%)",
            min_value=10, max_value=100, value=80, step=5,
            help="Muestra solo las actividades con mayor frecuencia acumulada",
        )
        paths_pct = st.slider(
            "Caminos / Conexiones (%)",
            min_value=10, max_value=100, value=80, step=5,
            help="Muestra solo los arcos (transiciones) más frecuentes",
        )
        view_mode = st.radio(
            "Métrica del grafo",
            ["Frecuencia", "Rendimiento (tiempo)"],
            help="Frecuencia = nº de ocurrencias · Rendimiento = tiempo medio entre actividades",
        )

        st.divider()
        st.caption("*Ajusta los sliders para simplificar o ampliar el mapa, igual que en Disco.*")

    # ── Graph ──────────────────────────────────────────────────────────────
    with map_col:
        try:
            if view_mode == "Frecuencia":
                _render_frequency_dfg(log, activities_pct, paths_pct)
            else:
                _render_performance_dfg(log, activities_pct, paths_pct)
        except Exception as e:
            st.error(f"Error generando el mapa: {e}")
            with st.expander("Detalle"):
                st.code(traceback.format_exc())


def _render_frequency_dfg(log, activities_pct, paths_pct):
    from pm4py.visualization.dfg import visualizer as dfg_vis

    dfg, start_acts, end_acts = pm4py.discover_dfg(log)
    f_dfg, f_start, f_end = filter_dfg(dfg, start_acts, end_acts, activities_pct, paths_pct)

    if not f_dfg:
        st.warning("Sin arcos con los filtros actuales. Aumenta los sliders.")
        return

    visible_acts = len({a for edge in f_dfg for a in edge})
    c1, c2, c3 = st.columns(3)
    c1.metric("Actividades visibles", visible_acts)
    c2.metric("Arcos visibles", len(f_dfg))
    c3.metric("Casos", len(log))

    render_dfg_image(
        f_dfg, f_start, f_end, log,
        dfg_vis.Variants.FREQUENCY,
        f"DFG — Frecuencia  |  {activities_pct}% actividades · {paths_pct}% caminos",
    )


def _render_performance_dfg(log, activities_pct, paths_pct):
    from pm4py.visualization.dfg import visualizer as dfg_vis

    perf_dfg, start_acts, end_acts = pm4py.discover_performance_dfg(log)
    f_dfg, f_start, f_end = filter_dfg(perf_dfg, start_acts, end_acts, activities_pct, paths_pct)

    if not f_dfg:
        st.warning("Sin arcos con los filtros actuales. Aumenta los sliders.")
        return

    visible_acts = len({a for edge in f_dfg for a in edge})
    c1, c2, c3 = st.columns(3)
    c1.metric("Actividades visibles", visible_acts)
    c2.metric("Arcos visibles", len(f_dfg))
    c3.metric("Casos", len(log))

    render_dfg_image(
        f_dfg, f_start, f_end, log,
        dfg_vis.Variants.PERFORMANCE,
        f"DFG — Rendimiento (seg.)  |  {activities_pct}% actividades · {paths_pct}% caminos",
    )


# ─────────────────────────────────────────────
# VISTA 2 — ANÁLISIS DE VARIANTES
# ─────────────────────────────────────────────
def view_variants(log):
    st.subheader("🔀 Análisis de Variantes del Proceso")

    try:
        variants_dict = pm4py.get_variants(log)

        # Sort by frequency descending
        variants_sorted = sorted(variants_dict.items(), key=lambda x: len(x[1]), reverse=True)

        total_cases = len(log)
        total_variants = len(variants_sorted)
        top5_cases = sum(len(cases) for _, cases in variants_sorted[:5])
        top5_pct = top5_cases / total_cases * 100 if total_cases else 0

        # ── KPI row ───────────────────────────────────────────────────────
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Total Variantes", f"{total_variants:,}")
        k2.metric("Casos en Top 5", f"{top5_cases:,}")
        k3.metric("Top 5 cubre", f"{top5_pct:.1f}%")
        k4.metric("Total Casos", f"{total_cases:,}")

        st.divider()

        # ── Build variants DataFrame ───────────────────────────────────────
        rows = []
        cumulative = 0.0
        for i, (variant, cases) in enumerate(variants_sorted):
            count = len(cases)
            pct = count / total_cases * 100 if total_cases else 0
            cumulative += pct
            steps = variant if isinstance(variant, tuple) else (variant,)
            flow = " → ".join(steps)
            rows.append({
                "ID": i + 1,
                "Casos": count,
                "%": round(pct, 2),
                "% Acum.": round(cumulative, 2),
                "Pasos": len(steps),
                "Flujo de Actividades": flow,
            })

        df_var = pd.DataFrame(rows)

        # ── Table ─────────────────────────────────────────────────────────
        st.markdown("#### Tabla de Variantes")
        st.dataframe(
            df_var,
            column_config={
                "ID": st.column_config.NumberColumn("ID", width="small"),
                "Casos": st.column_config.NumberColumn("Casos", format="%d"),
                "%": st.column_config.ProgressColumn(
                    "Frecuencia %", min_value=0, max_value=100, format="%.2f%%"
                ),
                "% Acum.": st.column_config.NumberColumn("% Acum.", format="%.1f%%"),
                "Pasos": st.column_config.NumberColumn("Pasos", width="small"),
                "Flujo de Actividades": st.column_config.TextColumn(
                    "Flujo (actividades)", width="large"
                ),
            },
            use_container_width=True,
            hide_index=True,
            height=380,
        )

        # ── Variant isolation ─────────────────────────────────────────────
        st.markdown("#### Aislar una Variante")

        options = ["— Todas —"] + [
            f"Variante {i+1}  ({len(cases):,} casos)" for i, (_, cases) in enumerate(variants_sorted)
        ]
        sel = st.selectbox("Selecciona una variante para filtrar todo el dashboard:", options)

        c1, c2 = st.columns([1, 3])
        with c1:
            if sel != "— Todas —" and st.button("🔍 Aplicar filtro de variante", type="primary"):
                idx = int(sel.split()[1]) - 1
                chosen_variant = variants_sorted[idx][0]
                filtered = pm4py.filter_variants(log, [chosen_variant])
                st.session_state.filtered_log = filtered
                st.success(f"Filtro aplicado: {len(filtered):,} casos con esa variante.")
                st.rerun()

        with c2:
            if st.button("🔄 Quitar filtro de variante"):
                st.session_state.filtered_log = st.session_state.event_log
                st.success("Filtro de variante eliminado.")
                st.rerun()

        # ── Pareto Chart ──────────────────────────────────────────────────
        st.divider()
        st.markdown("#### Distribución de Variantes (Pareto)")

        top_n = min(30, len(df_var))
        df_plot = df_var.head(top_n)

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=df_plot["ID"].astype(str),
            y=df_plot["%"],
            name="% de Casos",
            marker_color="#2196F3",
        ))
        fig.add_trace(go.Scatter(
            x=df_plot["ID"].astype(str),
            y=df_plot["% Acum."],
            name="% Acumulado",
            yaxis="y2",
            line=dict(color="#F44336", width=2),
            marker=dict(size=5),
        ))
        fig.update_layout(
            title=f"Top {top_n} variantes por frecuencia",
            xaxis_title="Variante ID",
            yaxis=dict(title="Frecuencia (%)"),
            yaxis2=dict(title="% Acumulado", overlaying="y", side="right", range=[0, 105]),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            hovermode="x unified",
            height=380,
        )
        st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"Error calculando variantes: {e}")
        with st.expander("Detalle"):
            st.code(traceback.format_exc())


# ─────────────────────────────────────────────
# VISTA 3 — RENDIMIENTO Y KPIs
# ─────────────────────────────────────────────
def view_performance(log):
    st.subheader("📊 Rendimiento y KPIs")

    try:
        # ── Case durations ────────────────────────────────────────────────
        raw_durations = pm4py.get_all_case_durations(log, business_hours=False)
        durations_sec = list(raw_durations) if raw_durations else []
        durations_days = [d / 86400 for d in durations_sec]

        total_cases = len(log)
        total_events = sum(len(t) for t in log)
        mean_dur = float(np.mean(durations_sec)) if durations_sec else 0
        median_dur = float(np.median(durations_sec)) if durations_sec else 0
        min_dur = float(np.min(durations_sec)) if durations_sec else 0
        max_dur = float(np.max(durations_sec)) if durations_sec else 0

        # ── KPI panel ─────────────────────────────────────────────────────
        st.markdown("#### Métricas Clave del Proceso")

        k1, k2, k3, k4, k5, k6 = st.columns(6)
        k1.metric("Ciclo Promedio", seconds_to_human(mean_dur))
        k2.metric("Ciclo Mediana", seconds_to_human(median_dur))
        k3.metric("Ciclo Mínimo", seconds_to_human(min_dur))
        k4.metric("Ciclo Máximo", seconds_to_human(max_dur))
        k5.metric("Total Casos", f"{total_cases:,}")
        k6.metric("Total Eventos", f"{total_events:,}")

        st.divider()

        # ── Charts row 1 ──────────────────────────────────────────────────
        col_hist, col_work = st.columns(2)

        with col_hist:
            st.markdown("##### Distribución de Tiempo de Ciclo")
            if durations_days:
                fig_hist = px.histogram(
                    x=durations_days,
                    nbins=50,
                    labels={"x": "Duración (días)", "y": "Casos"},
                    color_discrete_sequence=["#2196F3"],
                )
                fig_hist.add_vline(x=mean_dur / 86400, line_dash="dash", line_color="#F44336",
                                   annotation_text=f"Media: {mean_dur/86400:.1f}d",
                                   annotation_position="top right")
                fig_hist.add_vline(x=median_dur / 86400, line_dash="dot", line_color="#4CAF50",
                                   annotation_text=f"Mediana: {median_dur/86400:.1f}d",
                                   annotation_position="top left")
                fig_hist.update_layout(
                    xaxis_title="Duración del caso (días)",
                    yaxis_title="Número de casos",
                    showlegend=False,
                    height=380,
                    margin=dict(t=30),
                )
                st.plotly_chart(fig_hist, use_container_width=True)
            else:
                st.info("Sin datos de duración.")

        with col_work:
            st.markdown("##### Carga de Trabajo (Casos Activos)")
            df = pm4py.convert_to_dataframe(log)
            _plot_workload(df)

        # ── Percentile table ──────────────────────────────────────────────
        st.divider()
        st.markdown("#### Percentiles de Duración")

        if durations_days:
            percentiles = [10, 25, 50, 75, 90, 95, 99]
            perc_vals = np.percentile(durations_days, percentiles)
            p_cols = st.columns(len(percentiles))
            for col, p, v in zip(p_cols, percentiles, perc_vals):
                col.metric(f"P{p}", f"{v:.2f} días")

        # ── Activity frequency bar chart ──────────────────────────────────
        st.divider()
        st.markdown("#### Frecuencia por Actividad")

        df = pm4py.convert_to_dataframe(log)
        if "concept:name" in df.columns:
            act_counts = df["concept:name"].value_counts().head(20).reset_index()
            act_counts.columns = ["Actividad", "Frecuencia"]

            fig_bar = px.bar(
                act_counts,
                x="Frecuencia",
                y="Actividad",
                orientation="h",
                color="Frecuencia",
                color_continuous_scale="Blues",
                title="Top 20 Actividades por Frecuencia de Eventos",
            )
            fig_bar.update_layout(
                yaxis=dict(categoryorder="total ascending"),
                height=480,
                coloraxis_showscale=False,
                margin=dict(t=40),
            )
            st.plotly_chart(fig_bar, use_container_width=True)

    except Exception as e:
        st.error(f"Error calculando métricas: {e}")
        with st.expander("Detalle"):
            st.code(traceback.format_exc())


def _plot_workload(df: pd.DataFrame):
    """Line chart: number of cases active (started but not finished) over time."""
    try:
        ts_col = "time:timestamp"
        case_col = "case:concept:name"

        if ts_col not in df.columns or case_col not in df.columns:
            st.info("Columnas de timestamp o case no encontradas.")
            return

        df[ts_col] = pd.to_datetime(df[ts_col], utc=True, errors="coerce")
        df = df.dropna(subset=[ts_col])

        case_range = df.groupby(case_col)[ts_col].agg(start="min", end="max").reset_index()
        if case_range.empty:
            return

        min_t = case_range["start"].min()
        max_t = case_range["end"].max()
        timeline = pd.date_range(start=min_t, end=max_t, periods=120)

        active_counts = [
            int(((case_range["start"] <= t) & (case_range["end"] >= t)).sum())
            for t in timeline
        ]

        fig = px.line(
            x=timeline,
            y=active_counts,
            labels={"x": "Fecha", "y": "Casos activos"},
        )
        fig.update_traces(line_color="#2196F3", fill="tozeroy",
                          fillcolor="rgba(33,150,243,0.15)")
        fig.update_layout(
            xaxis_title="Fecha",
            yaxis_title="Casos activos simultáneamente",
            height=380,
            margin=dict(t=30),
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.warning(f"No se pudo graficar carga de trabajo: {e}")


# ─────────────────────────────────────────────
# VISTA 4 — FILTROS AVANZADOS
# ─────────────────────────────────────────────
def view_filters(log):
    st.subheader("🔧 Filtros Avanzados de Auditoría")
    st.info("Los filtros aplicados aquí se propagan a **todas las vistas** del dashboard.")

    try:
        df = pm4py.convert_to_dataframe(log)
        ts_col = "time:timestamp"
        act_col = "concept:name"

        # Timestamp bounds
        df[ts_col] = pd.to_datetime(df[ts_col], utc=True, errors="coerce")
        ts_min = df[ts_col].min()
        ts_max = df[ts_col].max()
        activities = sorted(df[act_col].dropna().unique().tolist()) if act_col in df.columns else []

        # ── Filter panels ─────────────────────────────────────────────────
        col_left, col_right = st.columns(2)

        # LEFT COLUMN
        with col_left:
            st.markdown("##### ⏰ Rango de Tiempo")
            use_date = st.checkbox("Activar filtro de fechas", key="f_date_on")
            date_from = date_to = None
            if use_date:
                date_from = st.date_input("Desde", value=ts_min.date(), key="f_date_from")
                date_to = st.date_input("Hasta", value=ts_max.date(), key="f_date_to")

            st.markdown("##### ⚡ Duración del Caso")
            use_perf = st.checkbox("Activar filtro de duración", key="f_perf_on")
            min_days = max_days = None
            if use_perf:
                durations = pm4py.get_all_case_durations(log, business_hours=False)
                max_dur_days = max(d / 86400 for d in durations) if durations else 365.0
                min_days, max_days = st.slider(
                    "Rango de duración (días)",
                    min_value=0.0,
                    max_value=float(max_dur_days),
                    value=(0.0, float(max_dur_days)),
                    step=0.5,
                    key="f_perf_range",
                )

        # RIGHT COLUMN
        with col_right:
            st.markdown("##### 🚀 Actividad de Inicio")
            use_start = st.checkbox("Activar filtro de actividad inicial", key="f_start_on")
            start_act = None
            if use_start and activities:
                start_act = st.selectbox("Casos que comienzan con:", activities, key="f_start_act")

            st.markdown("##### 🏁 Actividad de Fin")
            use_end = st.checkbox("Activar filtro de actividad final", key="f_end_on")
            end_act = None
            if use_end and activities:
                end_act = st.selectbox("Casos que terminan con:", activities, key="f_end_act")

            st.markdown("##### 🎯 Actividades Requeridas en el Caso")
            use_req = st.checkbox("Activar filtro de actividades requeridas", key="f_req_on")
            req_acts = []
            if use_req and activities:
                req_acts = st.multiselect(
                    "El caso debe contener:", activities, key="f_req_acts"
                )

        # ── Apply / Reset ─────────────────────────────────────────────────
        st.divider()
        btn_col1, btn_col2, _ = st.columns([1, 1, 2])

        with btn_col1:
            apply = st.button("✅ Aplicar Filtros", type="primary", use_container_width=True)
        with btn_col2:
            reset = st.button("🔄 Restablecer Filtros", use_container_width=True)

        if reset:
            st.session_state.filtered_log = st.session_state.event_log
            st.success("Todos los filtros eliminados. Usando log completo.")
            st.rerun()

        if apply:
            filtered = log
            n_filters = 0

            # Date filter
            if use_date and date_from and date_to:
                try:
                    dt_min = pd.Timestamp(date_from).tz_localize("UTC")
                    dt_max = pd.Timestamp(date_to).replace(hour=23, minute=59, second=59).tz_localize("UTC")
                    filtered = pm4py.filter_time_range(filtered, dt_min, dt_max, mode="traces_contained")
                    n_filters += 1
                except Exception as ex:
                    st.warning(f"Error en filtro de fechas: {ex}")

            # Performance filter
            if use_perf and min_days is not None:
                try:
                    filtered = pm4py.filter_case_performance(
                        filtered,
                        min_performance=min_days * 86400,
                        max_performance=max_days * 86400,
                    )
                    n_filters += 1
                except Exception as ex:
                    st.warning(f"Error en filtro de duración: {ex}")

            # Start activity filter
            if use_start and start_act:
                try:
                    filtered = pm4py.filter_start_activities(filtered, [start_act])
                    n_filters += 1
                except Exception as ex:
                    st.warning(f"Error en filtro de inicio: {ex}")

            # End activity filter
            if use_end and end_act:
                try:
                    filtered = pm4py.filter_end_activities(filtered, [end_act])
                    n_filters += 1
                except Exception as ex:
                    st.warning(f"Error en filtro de fin: {ex}")

            # Required activities filter
            if use_req and req_acts:
                try:
                    filtered = pm4py.filter_event_attribute_values(
                        filtered, "concept:name", req_acts, level="case", retain=True
                    )
                    n_filters += 1
                except Exception as ex:
                    st.warning(f"Error en filtro de actividades: {ex}")

            st.session_state.filtered_log = filtered
            orig = len(st.session_state.event_log)
            kept = len(filtered)
            pct = kept / orig * 100 if orig else 0
            st.success(f"✅ {n_filters} filtro(s) aplicado(s). Casos: {orig:,} → {kept:,} ({pct:.1f}% retenido)")
            st.rerun()

        # ── Status card ───────────────────────────────────────────────────
        st.divider()
        st.markdown("#### Estado Actual del Filtrado")

        orig_log = st.session_state.event_log
        curr_log = st.session_state.filtered_log

        if orig_log and curr_log:
            orig_n = len(orig_log)
            curr_n = len(curr_log)
            orig_e = sum(len(t) for t in orig_log)
            curr_e = sum(len(t) for t in curr_log)
            s1, s2, s3, s4 = st.columns(4)
            s1.metric("Casos originales", f"{orig_n:,}")
            s2.metric("Casos filtrados", f"{curr_n:,}",
                      delta=f"{curr_n - orig_n:+,}" if curr_n != orig_n else None,
                      delta_color="off")
            s3.metric("Eventos filtrados", f"{curr_e:,}")
            s4.metric("% Retenido", f"{curr_n/orig_n*100:.1f}%" if orig_n else "—")

    except Exception as e:
        st.error(f"Error en panel de filtros: {e}")
        with st.expander("Detalle"):
            st.code(traceback.format_exc())


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    apply_custom_css()
    init_session_state()

    # ── Sidebar ──────────────────────────────────────────────────────────
    st.sidebar.markdown(
        "<h2 style='color:#1a3a5c;margin-bottom:0'>⚙️ Process Mining Studio</h2>"
        "<p style='color:#888;font-size:0.85rem;margin-top:2px'>Powered by PM4Py + Streamlit</p>",
        unsafe_allow_html=True,
    )
    st.sidebar.divider()
    sidebar_data_loader()

    # ── Main area ─────────────────────────────────────────────────────────
    if st.session_state.event_log is None:
        # Welcome screen
        st.markdown(
            "<h1 class='main-header'>⚙️ Process Mining Studio</h1>"
            "<p class='sub-header'>Análisis interactivo de procesos al estilo Celonis · Disco · Open Source</p>",
            unsafe_allow_html=True,
        )

        c1, c2, c3, c4 = st.columns(4)
        c1.info("🗺️ **Discovery**\nMapa DFG del proceso con sliders estilo Disco")
        c2.info("🔀 **Variantes**\nHappy path, excepciones y filtrado por variante")
        c3.info("📊 **Rendimiento**\nKPIs, histogramas y carga de trabajo")
        c4.info("🔧 **Filtros**\nFechas, duración, inicio/fin de actividad")

        st.markdown("---")
        st.markdown(
            "### ¿Cómo comenzar?\n"
            "1. **Carga un archivo** CSV o XES en el panel lateral izquierdo.\n"
            "2. Mapea las columnas (Case ID · Actividad · Timestamp).\n"
            "3. Haz clic en **Procesar Log** o usa **Cargar Log de Demo** para ver la app en acción."
        )

        with st.expander("📦 Fuentes de logs de ejemplo"):
            st.markdown(
                "- [PM4Py Datasets](https://pm4py.fit.fraunhofer.de/datasets)\n"
                "- [4TU Research Data – Event Logs](https://data.4tu.nl/search?q=event+log)\n"
                "- [BPI Challenge logs (IEEE TF on PM)](https://www.tf-pm.org/resources/logs)"
            )
        return

    # ── Active log ────────────────────────────────────────────────────────
    current_log = st.session_state.filtered_log or st.session_state.event_log
    orig_n = len(st.session_state.event_log)
    curr_n = len(current_log)

    # Header with log name + filter badge
    header_cols = st.columns([4, 1])
    with header_cols[0]:
        st.markdown(
            f"<h2 style='margin-bottom:0;color:#1a3a5c'>"
            f"⚙️ {st.session_state.log_name or 'Log de Eventos'}</h2>",
            unsafe_allow_html=True,
        )
    with header_cols[1]:
        if curr_n < orig_n:
            st.warning(f"🔎 {curr_n:,} / {orig_n:,} casos")
        else:
            st.success(f"✅ {orig_n:,} casos")

    # ── Tabs ──────────────────────────────────────────────────────────────
    tab1, tab2, tab3, tab4 = st.tabs(
        ["🗺️  Discovery", "🔀  Variantes", "📊  Rendimiento", "🔧  Filtros Avanzados"]
    )

    with tab1:
        view_discovery(current_log)

    with tab2:
        view_variants(current_log)

    with tab3:
        view_performance(current_log)

    with tab4:
        view_filters(current_log)


if __name__ == "__main__":
    main()
