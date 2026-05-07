import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np
import io
import seaborn as sns
import re
import datetime

# --- PAGE CONFIG ---
st.set_page_config(page_title="Quality & Scrap Dashboard", layout="wide")
st.title("📊 Production Quality Yield & Tail Scrap Analysis")
st.markdown("---")

# --- SIDEBAR: DYNAMIC SPEC LIMITS ---
st.sidebar.header("⚙️ Spec Limits (Control)")
st.sidebar.info("Limits apply from Q4 2025 onwards. Configured per Thickness.")
GLOBAL_SPECS = {0.5: {}, 0.6: {}, 0.8: {}}
for t in [0.5, 0.6, 0.8]:
    with st.sidebar.expander(f"📏 Limits for {t}mm"):
        for feat in ['YS', 'TS', 'EL', 'YPE']:
            st.caption(f"**{feat}**")
            c1, c2, c3 = st.columns(3)
            min_v = c1.number_input("Min", value=None, key=f"{t}_{feat}_min", label_visibility="collapsed")
            max_v = c2.number_input("Max", value=None, key=f"{t}_{feat}_max", label_visibility="collapsed")
            tgt_v = c3.number_input("Tgt", value=None, key=f"{t}_{feat}_tgt", label_visibility="collapsed")
            GLOBAL_SPECS[t][feat] = {'min': min_v, 'max': max_v, 'target': tgt_v}

uploaded_file = st.file_uploader("Upload Production Data (.xlsx)", type=["xlsx"])

if uploaded_file is not None:
    df_raw = pd.read_excel(uploaded_file)
    
    # --- DEDUPLICATE & CLEAN COLUMNS ---
    df_raw.columns = df_raw.columns.astype(str).str.strip()
    cols = pd.Series(df_raw.columns)
    for dup in cols[cols.duplicated()].unique():
        cols[cols[cols == dup].index.values.tolist()] = [f"{dup}.{i}" if i != 0 else dup for i in range(sum(cols == dup))]
    df_raw.columns = cols

    df = df_raw.copy()
    rename_dict = {'烤漆降伏強度': 'YS', '烤漆抗拉強度': 'TS', '伸長率': 'EL', 'Thickness': 'Actual_Thickness', '厚度': 'Actual_Thickness'}
    df.rename(columns=rename_dict, inplace=True)
    
    # Pre-process Thickness
    if 'Actual_Thickness' in df.columns:
        df['Actual_Thickness'] = pd.to_numeric(df['Actual_Thickness'], errors='coerce')
        def map_thickness(v):
            v = round(float(v), 2) if pd.notnull(v) else 0
            if v in [0.47, 0.50]: return 0.5
            if v in [0.53, 0.54, 0.57, 0.58, 0.60]: return 0.6
            if v in [0.63, 0.75, 0.76, 0.77, 0.80]: return 0.8
            return None
        df['Std_Thick'] = df['Actual_Thickness'].apply(map_thickness)
        df = df.dropna(subset=['Std_Thick'])
        df['Actual_Thickness'] = df['Std_Thick']

    # Pre-process numeric features
    for f in ['YS', 'TS', 'EL', '實測長度', '尾料剔退']:
        if f in df.columns: df[f] = pd.to_numeric(df[f], errors='coerce').fillna(0)
    
    LEN_COL, SCRAP_COL = '實測長度', '尾料剔退'

    # Date Parsing & Period Categorization
    if '烤三生產日期' in df.columns:
        def parse_date(s):
            s_str = str(s).replace('.0', '').strip()
            return pd.to_datetime(s_str, format='%Y%m%d', errors='coerce').fillna(pd.to_datetime(s_str, errors='coerce'))
        df['Production_Date'] = df['烤三生產日期'].apply(parse_date)
        
        def categorize(d):
            if pd.isnull(d): return "Unknown"
            if d.year == 2024: return "2024 (Full Year)"
            if d < pd.Timestamp(2025, 6, 29): return "2025 H1"
            if d <= pd.Timestamp(2025, 9, 30): return "2025 Q3"
            return d.strftime('%Y-%m')
        df['Time_Group'] = df['Production_Date'].apply(categorize)
        
    # Grade Processing
    base_grades = ['A-B+', 'A-B', 'A-B-', 'B+', 'B']
    for g in base_grades:
        match = [c for c in df.columns if str(c).strip().startswith(g)]
        df[g] = df[match].sum(axis=1) if match else 0
    df['Total_Qty'] = df[base_grades].sum(axis=1)
    df['Valid_Qty'] = df[['A-B+', 'A-B']].sum(axis=1)
    df['Severe_Bad'] = df[['B+', 'B']].sum(axis=1)

    def get_sort_key(x):
        if "2024" in x: return "2024-00"
        if "H1" in x: return "2025-01"
        if "Q3" in x: return "2025-02"
        return x

    def add_chart_border(ax):
        for s in ax.spines.values(): s.set_visible(True); s.set_color('#333'); s.set_linewidth(1)

    # --- TABS ---
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["📁 1. Raw", "📋 2. Yield", "📈 3. SPC", "📉 4. I-MR", "✂️ 5. Scrap", "🎯 6. End-Use"])

    with tab1:
        st.dataframe(df_raw, use_container_width=True)

    with tab2:
        st.header("2. Internal Quality & Grade Distribution")
        # Grade Distribution Chart
        grade_dist = df.groupby('Time_Group')[base_grades].sum()
        grade_pct = grade_dist.div(grade_dist.sum(axis=1), axis=0) * 100
        grade_pct = grade_pct.fillna(0).sort_index(key=lambda x: x.map(get_sort_key))
        
        fig2, ax2 = plt.subplots(figsize=(10, 4))
        grade_pct.plot(kind='bar', stacked=True, ax=ax2, color=['#2e7d32','#1f77b4','#ffa726','#ef5350','#c62828'], edgecolor='white')
        ax2.set_ylabel("Percentage (%)"); ax2.legend(bbox_to_anchor=(1,1))
        for c in ax2.containers:
            ax2.bar_label(c, labels=[f'{v.get_height():.1f}%' if v.get_height() > 5 else '' for v in c], label_type='center', color='white', fontweight='bold', fontsize=8)
        plt.xticks(rotation=45, ha='right'); add_chart_border(ax2); st.pyplot(fig2)

        yield_sum = df.groupby(['Time_Group', 'Actual_Thickness'])[['Total_Qty', 'Valid_Qty', 'Severe_Bad']].sum().reset_index()
        yield_sum['Yield (%)'] = (yield_sum['Valid_Qty'] / yield_sum['Total_Qty'] * 100).round(2)
        st.dataframe(yield_sum.sort_values('Time_Group', key=lambda x: x.map(get_sort_key)), use_container_width=True)

    with tab3:
        st.header("3. Process Capability Summary")
        cap_results = []
        for p in sorted(df['Time_Group'].unique(), key=get_sort_key):
            if any(x in p for x in ["2024", "H1", "Q3"]): continue
            df_p = df[(df['Time_Group'] == p) & (df['Valid_Qty'] > 0)]
            for t in sorted(df['Actual_Thickness'].unique()):
                df_t = df_p[df_p['Actual_Thickness'] == t]
                for f in ['YS', 'TS', 'EL']:
                    vals = df_t[f].dropna().values
                    if len(vals) >= 2:
                        mu, std = np.mean(vals), np.std(vals, ddof=1)
                        spec = GLOBAL_SPECS.get(t, {}).get(f, {})
                        lsl, usl = spec.get('min'), spec.get('max')
                        cpk = None
                        if lsl is not None and usl is not None: cpk = min((usl-mu)/(3*std), (mu-lsl)/(3*std))
                        cap_results.append({'Period': p, 'Thick': t, 'Feature': f, 'Mean': mu, 'Cpk': cpk})
        if cap_results: st.dataframe(pd.DataFrame(cap_results), use_container_width=True)

    with tab4:
        st.header("4. Post-Improvement I-MR Charts (Q4 2025+)")
        df_t4 = df[(df['Production_Date'] >= pd.Timestamp(2025, 10, 1)) & (df['Valid_Qty'] > 0)].copy()
        if not df_t4.empty:
            t4_thick = st.selectbox("Select Thickness Category:", ['Overall'] + sorted(df_t4['Actual_Thickness'].unique().tolist()))
            plot_df = df_t4 if t4_thick == 'Overall' else df_t4[df_t4['Actual_Thickness'] == t4_thick]
            for f in ['YS', 'TS', 'EL']:
                pdf = plot_df.sort_values('Production_Date').dropna(subset=[f]).reset_index(drop=True)
                if len(pdf) < 2: continue
                st.markdown(f"### 🎯 Feature: {f}")
                vals = pdf[f].values; dates = pdf['Production_Date'].dt.strftime('%Y-%m')
                m_v, mr = np.mean(vals), np.abs(np.diff(vals)); mr_m = np.mean(mr)
                ucl_i, lcl_i = m_v + 2.66*mr_m, max(0, m_v - 2.66*mr_m)
                ucl_mr = 3.267 * mr_m
                
                fig4, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), gridspec_kw={'height_ratios': [2, 1]})
                # I-Chart
                ax1.plot(vals, marker='o', alpha=0.6, color='#1f77b4')
                ax1.axhline(m_v, color='g', ls='--'); ax1.axhline(ucl_i, color='r', ls='--'); ax1.axhline(lcl_i, color='r', ls='--')
                out_i = np.where((vals > ucl_i) | (vals < lcl_i))[0]
                if len(out_i) > 0: ax1.scatter(out_i, vals[out_i], color='red', s=100, zorder=5)
                ax1.set_title(f"Individual (I) Chart - {f}")
                
                # MR-Chart
                ax2.plot(range(1, len(vals)), mr, marker='o', alpha=0.6, color='#ff7f0e')
                ax2.axhline(mr_m, color='g', ls='--'); ax2.axhline(ucl_mr, color='r', ls='--')
                out_mr = np.where(mr > ucl_mr)[0]
                if len(out_mr) > 0: ax2.scatter(out_mr + 1, mr[out_mr], color='red', s=100, zorder=5)
                ax2.set_title("Moving Range (MR) Chart")
                
                plt.xticks(range(0, len(vals)), dates, rotation=45); fig4.tight_layout(); st.pyplot(fig4)

    with tab5:
        st.header("5. Tail Scrap Trend Analysis")
        scrap_trend = df.groupby('Time_Group').agg({LEN_COL: 'sum', SCRAP_COL: 'sum'}).reset_index()
        scrap_trend['Rate (%)'] = (scrap_trend[SCRAP_COL] / scrap_trend[LEN_COL] * 100).round(2)
        scrap_trend = scrap_trend.sort_values('Time_Group', key=lambda x: x.map(get_sort_key))
        fig5, ax5 = plt.subplots(figsize=(12, 4))
        ax5.plot(scrap_trend['Time_Group'], scrap_trend['Rate (%)'], marker='o', lw=3, color='#d62728')
        for i, v in enumerate(scrap_trend['Rate (%)']): ax5.text(i, v+0.5, f'{v}%', ha='center', fontweight='bold')
        ax5.set_title("Internal Tail Scrap Rate (%) Trend"); plt.xticks(rotation=45); st.pyplot(fig5)

    with tab6:
        st.header("6. Customer End-Use & Executive Proof")
        USAGE_COL = next((c for c in ['使用日期', '使用月份', 'Usage Date'] if c in df.columns), None)
        if USAGE_COL:
            df_t6 = df[df[LEN_COL] > 0].copy()
            df_t6['Usage_Date'] = pd.to_datetime(df_t6[USAGE_COL], dayfirst=True, errors='coerce')
            df_t6 = df_t6.dropna(subset=['Usage_Date'])
            df_t6['Usage_Month'] = df_t6['Usage_Date'].dt.strftime('%Y-%m')
            
            # Executive Proof: Dual Axis
            exec_agg = df_t6.groupby('Usage_Month').agg(Scrap=(SCRAP_COL,'sum'), Len=(LEN_COL,'sum'), YS=('YS','mean'), TS=('TS','mean'), EL=('EL','mean')).reset_index()
            exec_agg['Rate'] = (exec_agg['Scrap']/exec_agg['Len']*100)
            
            st.subheader("Correlation: Customer Scrap vs Internal Material Stability")
            cols = st.columns(3)
            for i, (f, title) in enumerate([('YS','Theoretical YS'), ('TS','Theoretical TS'), ('EL','Theoretical EL')]):
                with cols[i]:
                    fig6, ax_left = plt.subplots(figsize=(6, 4))
                    ax_left.plot(exec_agg['Usage_Month'], exec_agg['Rate'], color='r', marker='o', label='Scrap %')
                    ax_right = ax_left.twinx()
                    ax_right.plot(exec_agg['Usage_Month'], exec_agg[f], color='b', ls='--', marker='s', label=title)
                    ax_left.set_title(f"Scrap vs {f}"); ax_left.set_xticklabels(exec_agg['Usage_Month'], rotation=45); st.pyplot(fig6)

            st.markdown("---")
            st.subheader("🔍 Inventory Traceability Heatmap")
            # Filter Q4 2025 onwards for Heatmap
            df_trace = df_t6[df_t6['Production_Date'] >= pd.Timestamp(2025, 10, 1)].copy()
            if not df_trace.empty:
                trace_agg = df_trace.groupby(['Usage_Month', 'Time_Group']).agg(S=(SCRAP_COL,'sum'), L=(LEN_COL,'sum')).reset_index()
                trace_agg['Rate'] = (trace_agg['S']/trace_agg['L']*100).round(2)
                pivot_trace = trace_agg.pivot(index='Usage_Month', columns='Time_Group', values='Rate')
                fig_h, ax_h = plt.subplots(figsize=(10, 5))
                sns.heatmap(pivot_trace, annot=True, cmap="Reds", fmt=".1f", ax=ax_h)
                ax_h.set_title("Scrap Rate (%) Heatmap (Usage vs Production Period)"); st.pyplot(fig_h)

                st.subheader("Customer Grading Shift (Combo Labels)")
                grade_combo = df_trace.groupby(['Usage_Month', 'Time_Group'])[base_grades].sum().reset_index()
                grade_combo['Label'] = grade_combo['Usage_Month'] + "\n(Prod: " + grade_combo['Time_Group'] + ")"
                grade_pct_c = grade_combo.set_index('Label')[base_grades].div(grade_combo[base_grades].sum(axis=1), axis=0) * 100
                fig_c, ax_c = plt.subplots(figsize=(12, 5))
                grade_pct_c.plot(kind='bar', stacked=True, ax=ax_c, color=['#2e7d32','#1f77b4','#ffa726','#ef5350','#c62828'])
                ax_c.set_title("Grade Distribution by Usage & Production Batch"); plt.xticks(rotation=45); st.pyplot(fig_c)
