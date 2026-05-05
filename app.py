import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np
import io
import seaborn as sns

# --- PAGE CONFIG ---
st.set_page_config(page_title="Quality & Scrap Dashboard", layout="wide")
st.title("📊 Production Quality Yield & Tail Scrap Analysis")
st.markdown("---")

# --- SIDEBAR: DYNAMIC SPEC LIMITS INPUT ---
st.sidebar.header("⚙️ Spec Limits (Control)")
st.sidebar.info("Enter limits for the SPC charts. Leave blank if not applicable.")
GLOBAL_SPECS = {}
for feat in ['YS', 'TS', 'EL', 'YPE']:
    with st.sidebar.expander(f"{feat} Configuration"):
        c1, c2 = st.columns(2)
        min_val = c1.number_input(f"Min", value=None, key=f"{feat}_min")
        max_val = c2.number_input(f"Max", value=None, key=f"{feat}_max")
        tgt_val = st.number_input(f"Target", value=None, key=f"{feat}_tgt")
        GLOBAL_SPECS[feat] = {'min': min_val, 'max': max_val, 'target': tgt_val}

uploaded_file = st.file_uploader("Upload Production Data (.xlsx)", type=["xlsx"])

if uploaded_file is not None:
    df = pd.read_excel(uploaded_file)
    df.columns = df.columns.astype(str).str.strip()

    # --- 1. DATA PRE-PROCESSING ---
    # Handle Thickness
    if 'Actual_Thickness' not in df.columns:
        if 'Thickness' in df.columns:
            df.rename(columns={'Thickness': 'Actual_Thickness'}, inplace=True)
        elif '厚度' in df.columns:
            df.rename(columns={'厚度': 'Actual_Thickness'}, inplace=True)
        else:
            for i, c in enumerate(df.columns):
                if '型式' in c and i > 0:
                    df.rename(columns={df.columns[i - 1]: 'Actual_Thickness'}, inplace=True)
                    break
    
    if 'Actual_Thickness' in df.columns:
        df['Actual_Thickness'] = pd.to_numeric(df['Actual_Thickness'], errors='coerce')
        
        # EXACT MAPPING LOGIC FOR ORDER THICKNESS
        def map_thickness(val):
            if pd.isna(val): return None
            v = round(float(val), 2)
            if v in [0.47, 0.50]: return 0.5
            if v in [0.53, 0.54, 0.57, 0.58, 0.60]: return 0.6
            if v in [0.63, 0.75, 0.76, 0.77, 0.80]: return 0.8
            return None 
            
        df['Standard_Thickness'] = df['Actual_Thickness'].apply(map_thickness)
        df = df.dropna(subset=['Standard_Thickness'])
        df['Actual_Thickness'] = df['Standard_Thickness']
        df = df.drop(columns=['Standard_Thickness'])
    else:
        df['Actual_Thickness'] = 0.0
        df = df.iloc[0:0]

    # Handle Material
    if '熱軋材質' in df.columns:
        df['HR_Material'] = df['熱軋材質'].astype(str).str.strip().replace(['nan', ''], 'Unknown')
    else:
        df['HR_Material'] = 'Unknown'

    # Handle Dates & Time Grouping
    date_key = '烤三生產日期' 
    if date_key in df.columns:
        d_str = df[date_key].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
        df['Production_Date'] = pd.to_datetime(d_str, format='%Y%m%d', errors='coerce')
        
        def categorize_period(d):
            if pd.isnull(d): return "Unknown"
            y = d.year
            q3_s, q3_e = pd.Timestamp(2025, 6, 29), pd.Timestamp(2025, 9, 30)
            
            if y == 2024: return "2024 (Full Year)"
            if y == 2025:
                if d < q3_s: return "2025 H1 (Until 06/28)"
                if q3_s <= d <= q3_e: return "2025 Q3 (06/29 - 09/30)"
                return d.strftime('%Y-%m')
            if y >= 2026: return d.strftime('%Y-%m')
            return "Other"
            
        df['Time_Group'] = df['Production_Date'].apply(categorize_period)
        df = df[df['Time_Group'] != "Other"]
        
        # Duplicate 2025 data to create a "2025 (Full Year)" summary row
        df_25 = df[df['Production_Date'].dt.year == 2025].copy()
        if not df_25.empty:
            df_25['Time_Group'] = "2025 (Full Year)"
            df = pd.concat([df, df_25], ignore_index=True)
    else:
        df['Time_Group'] = "Unknown"

    # Quality Grade Mapping
    base_grades = ['A-B+', 'A-B', 'A-B-', 'B+', 'B']
    for g in base_grades:
        match_cols = [c for c in df.columns if c == g or c == f"{g}個數" or str(c).startswith(f"{g}.")]
        df[g] = df[match_cols].apply(pd.to_numeric, errors='coerce').fillna(0).sum(axis=1) if match_cols else 0

    df['Total_Qty'] = df[base_grades].sum(axis=1)
    df['Severe_Bad_Qty'] = df[['B+', 'B']].sum(axis=1)
    df['Acceptable_Qty'] = df['Total_Qty'] - df['Severe_Bad_Qty']

    # Mechanical Properties Mapping
    df.rename(columns={'烤漆降伏強度': 'YS', '烤漆抗拉強度': 'TS', '伸長率': 'EL'}, inplace=True)
    mech_features = ['YS', 'TS', 'EL', 'YPE', 'HARDNESS']
    for f in mech_features:
        if f in df.columns:
            df[f] = pd.to_numeric(df[f], errors='coerce')

    # Pre-clean Length and Scrap Columns
    LEN_COL = '實測長度'
    SCRAP_COL = '尾料剔退'
    if LEN_COL in df.columns:
        df[LEN_COL] = pd.to_numeric(df[LEN_COL], errors='coerce').fillna(0)
    if SCRAP_COL in df.columns:
        df[SCRAP_COL] = pd.to_numeric(df[SCRAP_COL], errors='coerce').fillna(0)

    # FILTER: Prevent dropping rows that have 0 length but contain Scrap or Qty data
    df = df[(df['Total_Qty'] > 0) | (df.get(LEN_COL, 0) > 0) | (df.get(SCRAP_COL, 0) > 0)]

    # Global Style Setup for Matplotlib charts
    sns.set_theme(style="whitegrid")
    solid_colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b']

    # Custom Sorter for Time_Group to keep logical order
    def get_sort_key(x):
        if "2024 (Full Year)" in x: return "2024-00"
        if "2025 H1" in x: return "2025-00a"
        if "2025 Q3" in x: return "2025-00b"
        if "2025 (Full Year)" in x: return "2025-99" 
        return x

    # HELPER FUNCTION: Add borders to charts
    def add_chart_border(ax):
        for spine in ax.spines.values():
            spine.set_visible(True)
            spine.set_color('#333333')
            spine.set_linewidth(1.0)

    # --- TABS ---
    tab0, tab1, tab3, tab5 = st.tabs(["📁 Task 0: Raw Data", "📋 Task 1: Quality Yield", "📈 Task 3: Capability", "✂️ Task 5: Tail Scrap"])

    # ==========================================================
    # TASK 0: RAW DATA INSPECTION
    # ==========================================================
    with tab0:
        st.header("Raw Data Inspection")
        st.info("Grouped Thickness: 0.5mm (0.47, 0.50), 0.6mm (0.53-0.60), 0.8mm (0.63-0.80). Unmatched and empty rows removed.")
        
        col_m1, col_m2, col_m3 = st.columns(3)
        col_m1.metric("Valid Rows", f"{len(df):,}")
        col_m2.metric("Total Columns", len(df.columns))
        
        if 'Production_Date' in df.columns and not df['Production_Date'].isna().all():
            min_date = df['Production_Date'].min().strftime('%Y-%m-%d')
            max_date = df['Production_Date'].max().strftime('%Y-%m-%d')
            col_m3.metric("Date Range", f"{min_date} to {max_date}")
        else:
            col_m3.metric("Date Range", "N/A")
            
        st.markdown("### Filtered Data Preview")
        st.dataframe(df.head(50), use_container_width=True) # Displaying first 50 for performance

    # ==========================================================
    # TASK 1: YIELD SUMMARY
    # ==========================================================
    with tab1:
        st.header("Executive Quality Yield Summary")
        
        st.subheader("1. Detailed Yield by Thickness & Material")
        yield_summary = df.groupby(['Time_Group', 'Actual_Thickness', 'HR_Material'])[
            ['Total_Qty', 'Acceptable_Qty', 'Severe_Bad_Qty']
        ].sum().reset_index()
        
        yield_summary = yield_summary[yield_summary['Total_Qty'] > 0]
        
        if not yield_summary.empty:
            yield_summary['Yield (%)'] = (yield_summary['Acceptable_Qty'] / yield_summary['Total_Qty'] * 100).round(2)
            yield_summary['Defect_Rate (%)'] = (yield_summary['Severe_Bad_Qty'] / yield_summary['Total_Qty'] * 100).round(2)
            
            yield_summary['_sort'] = yield_summary['Time_Group'].apply(get_sort_key)
            yield_summary = yield_summary.sort_values(by=['_sort', 'Actual_Thickness']).drop(columns=['_sort'])

            st.dataframe(
                yield_summary.style
                    .background_gradient(subset=['Yield (%)'], cmap='Greens')
                    .background_gradient(subset=['Defect_Rate (%)'], cmap='Reds')
                    .format({
                        'Actual_Thickness': '{:.2f}', 'Total_Qty': '{:.0f}',
                        'Acceptable_Qty': '{:.0f}', 'Severe_Bad_Qty': '{:.0f}',
                        'Yield (%)': '{:.2f}%', 'Defect_Rate (%)': '{:.2f}%'
                    }),
                use_container_width=True, hide_index=True
            )
        else:
            st.info("No yield data available to display in this view.")

        st.markdown("---")
        st.subheader("📊 2. Grade Distribution by Time Period (%)")
        
        grade_dist = df.groupby('Time_Group')[base_grades].sum()
        grade_dist['Total'] = grade_dist.sum(axis=1)
        
        grade_dist_display = pd.DataFrame()
        for g in base_grades:
            grade_dist_display[g] = (grade_dist[g] / grade_dist['Total'].replace(0, np.nan) * 100).fillna(0).round(1)
        
        grade_dist_display['_sort'] = grade_dist_display.index.map(get_sort_key)
        grade_dist_display = grade_dist_display.sort_values('_sort').drop(columns=['_sort'])
        
        grade_dist_pct_str = grade_dist_display.map(lambda x: f"{x:.1f}%")

        header_color = "#1a3a5c"
        alt_row_color = "#dce6f1"
        html = f"""
        <style>
        .grade-table {{ width:100%; border-collapse:collapse; font-family:sans-serif; font-size:14px; margin-bottom:24px; }}
        .grade-table th {{ background-color:{header_color}; color:white; padding:10px 16px; text-align:center; }}
        .grade-table td {{ padding:9px 16px; text-align:center; border-bottom:1px solid #ccc; }}
        .grade-table tr:nth-child(odd) td {{ background-color:{alt_row_color}; }}
        .grade-table tr:nth-child(even) td {{ background-color:#ffffff; }}
        .grade-table tr:hover td {{ background-color:#b8cce4; }}
        </style>
        <table class="grade-table">
            <thead><tr><th>Time Period</th>{''.join(f'<th>{g}</th>' for g in base_grades)}</tr></thead>
            <tbody>
        """
        for period, row in grade_dist_pct_str.iterrows():
            html += "<tr>"
            html += f"<td><b>{period}</b></td>"
            for g in base_grades:
                val = float(row[g].replace('%', ''))
                if g in ['B+', 'B'] and val > 1.0:
                    html += f'<td style="color:#c00000;font-weight:bold">{row[g]}</td>'
                elif g in ['A-B+', 'A-B'] and val > 30.0:
                    html += f'<td style="color:#2e7d32;font-weight:bold">{row[g]}</td>'
                else:
                    html += f'<td>{row[g]}</td>'
            html += "</tr>"
        html += "</tbody></table>"
        
        st.markdown(html, unsafe_allow_html=True)

        st.markdown("**📈 Grade Distribution Chart**")
        fig_g, ax_g = plt.subplots(figsize=(12, 5))
        if not grade_dist_display.empty:
            grade_colors = ['#2e7d32', '#66bb6a', '#ffa726', '#ef5350', '#c62828']
            grade_dist_display.plot(kind='bar', stacked=True, ax=ax_g, color=grade_colors, edgecolor='white')
            ax_g.set_ylabel("Percentage (%)")
            ax_g.set_xlabel("")
            ax_g.set_ylim(0, 105)
            ax_g.legend(title="Quality Grade", bbox_to_anchor=(1.02, 1), loc='upper left')
            add_chart_border(ax_g)
            
            for container in ax_g.containers:
                labels = [f"{v.get_height():.1f}%" if v.get_height() > 3.0 else "" for v in container]
                ax_g.bar_label(container, labels=labels, label_type='center', color='white', fontweight='bold', fontsize=9)
            
            plt.xticks(rotation=30, ha='right')
            fig_g.tight_layout()
            st.pyplot(fig_g)

        st.markdown("---")
        st.subheader("3. Charts by Period & Thickness")
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            st.markdown("**Yield (%) by Period & Thickness**")
            fig_y, ax_y = plt.subplots(figsize=(8, 4))
            if not yield_summary.empty:
                chart_df = yield_summary[yield_summary['Time_Group'] != "2025 (Full Year)"]
                pivot_y = chart_df.pivot_table(index='Time_Group', columns='Actual_Thickness', values='Yield (%)', aggfunc='mean')
                if not pivot_y.empty:
                    pivot_y.plot(kind='bar', ax=ax_y, color=solid_colors, edgecolor='white')
                    ax_y.legend(title="Thickness", bbox_to_anchor=(1.02, 1), loc='upper left')
            ax_y.set_ylim(0, 110)
            ax_y.set_ylabel("Yield (%)")
            ax_y.set_xlabel("")
            add_chart_border(ax_y)
            plt.xticks(rotation=30, ha='right')
            fig_y.tight_layout()
            st.pyplot(fig_y)
            
        with col_c2:
            st.markdown("**Defect Rate (%) by Period & Thickness**")
            fig_d, ax_d = plt.subplots(figsize=(8, 4))
            if not yield_summary.empty:
                chart_df = yield_summary[yield_summary['Time_Group'] != "2025 (Full Year)"]
                pivot_d = chart_df.pivot_table(index='Time_Group', columns='Actual_Thickness', values='Defect_Rate (%)', aggfunc='mean')
                if not pivot_d.empty:
                    pivot_d.plot(kind='bar', ax=ax_d, color=solid_colors, edgecolor='white')
                    ax_d.legend(title="Thickness", bbox_to_anchor=(1.02, 1), loc='upper left')
            ax_d.set_ylabel("Defect Rate (%)")
            ax_d.set_xlabel("")
            add_chart_border(ax_d)
            plt.xticks(rotation=30, ha='right')
            fig_d.tight_layout()
            st.pyplot(fig_d)

    # ==========================================================
    # TASK 3: DISTRIBUTION & PROCESS CAPABILITY (SPC)
    # ==========================================================
    with tab3:
        st.header("📊 Distribution & Process Capability (SPC)")
        st.info("Visualizing mechanical property distribution and capability indices (Cp, Cpk, Ca) based on your target limits.")

        # --- CAPABILITY INDEX HELPERS ---
        def calc_capability(values, feat):
            vals = np.array(values, dtype=float)
            vals = vals[~np.isnan(vals)]
            if len(vals) < 2: return None
            
            mu  = np.mean(vals)
            std = np.std(vals, ddof=1)
            if std == 0: return None

            spec = GLOBAL_SPECS.get(feat, {})
            lsl  = spec.get('min')
            usl  = spec.get('max')
            tgt  = spec.get('target')

            result = {'mean': mu, 'std': std, 'n': len(vals),
                      'Cp': None, 'Cpk': None, 'Ca': None,
                      'LSL': lsl, 'USL': usl, 'Target': tgt}

            if lsl is not None and usl is not None:
                cp   = (usl - lsl) / (6 * std)
                cpu  = (usl - mu)  / (3 * std)
                cpl  = (mu  - lsl) / (3 * std)
                cpk  = min(cpu, cpl)
                result['Cp']  = round(cp,  3)
                result['Cpk'] = round(cpk, 3)
                if tgt is not None:
                    ca = (mu - tgt) / ((usl - lsl) / 2) * 100
                    result['Ca'] = round(ca, 2)
                else:
                    mid = (usl + lsl) / 2
                    ca  = (mu - mid) / ((usl - lsl) / 2) * 100
                    result['Ca'] = round(ca, 2)
            elif lsl is not None:
                cpl = (mu - lsl) / (3 * std)
                result['Cp']  = round(cpl, 3)
                result['Cpk'] = round(cpl, 3)
            elif usl is not None:
                cpu = (usl - mu) / (3 * std)
                result['Cp']  = round(cpu, 3)
                result['Cpk'] = round(cpu, 3)

            return result

        def cpk_color(cpk):
            if cpk is None: return '#888888'
            if cpk >= 1.67: return '#2e7d32'   
            if cpk >= 1.33: return '#66bb6a'   
            if cpk >= 1.00: return '#ffa726'   
            return '#d62728'                   

        def cpk_label(cpk):
            if cpk is None: return 'N/A'
            if cpk >= 1.67: return '✅ Excellent'
            if cpk >= 1.33: return '✅ Capable'
            if cpk >= 1.00: return '⚠️ Marginal'
            return '❌ Not Capable'

        def render_capability_badge(cap, feat):
            if cap is None: return
            cp_v   = f"{cap['Cp']:.3f}"   if cap['Cp']  is not None else 'N/A'
            cpk_v  = f"{cap['Cpk']:.3f}"  if cap['Cpk'] is not None else 'N/A'
            ca_v   = f"{cap['Ca']:.1f}%"  if cap['Ca']  is not None else 'N/A'
            mu_v   = f"{cap['mean']:.2f}"
            std_v  = f"{cap['std']:.3f}"
            clr    = cpk_color(cap['Cpk'])
            lbl    = cpk_label(cap['Cpk'])
            
            lsl_v  = str(cap['LSL']) if cap['LSL'] is not None else '—'
            usl_v  = str(cap['USL']) if cap['USL'] is not None else '—'

            html_badge = f"""
            <div style="background:#f8f9fa;border-left:5px solid {clr};
                        border-radius:6px;padding:8px 14px;margin:4px 0 10px 0;
                        font-family:monospace;font-size:13px;line-height:1.8;">
              <span style="font-size:14px;font-weight:bold;color:{clr};">{lbl}</span>
              &nbsp;&nbsp;|&nbsp;&nbsp;
              <b>LSL</b>: {lsl_v} &nbsp; <b>USL</b>: {usl_v}
              &nbsp;&nbsp;|&nbsp;&nbsp;
              <b>n</b>: {cap['n']} &nbsp;
              <b>Mean</b>: {mu_v} &nbsp;
              <b>Std</b>: {std_v}
              <br>
              <b style="color:{clr};">Cpk = {cpk_v}</b> &nbsp;&nbsp;
              <b>Cp = {cp_v}</b> &nbsp;&nbsp;
              <b>Ca = {ca_v}</b>
            </div>
            """
            st.markdown(html_badge, unsafe_allow_html=True)

        def build_capability_summary(df_src, feat, label):
            vals = df_src[feat].dropna().values if feat in df_src.columns else []
            cap = calc_capability(vals, feat)
            if cap is None: return None
            return {
                'Period': label,
                'Feature': feat,
                'n': cap['n'],
                'Mean': round(cap['mean'], 2),
                'Std': round(cap['std'], 3),
                'LSL': cap['LSL'],
                'USL': cap['USL'],
                'Ca (%)': cap['Ca'],
                'Cp': cap['Cp'],
                'Cpk': cap['Cpk'],
                'Verdict': cpk_label(cap['Cpk']).replace('✅ ', '').replace('⚠️ ', '').replace('❌ ', '')
            }

        global_x_bounds = {}
        for feat in ['YS', 'TS', 'EL', 'YPE']:
            if feat in df.columns:
                vd = df[[feat, 'Total_Qty']].dropna().copy()
                vd = vd[vd['Total_Qty'] > 0]
                if not vd.empty:
                    q1, q99 = np.percentile(vd[feat], 1), np.percentile(vd[feat], 99)
                    global_x_bounds[feat] = (q1 - (q99 - q1) * 0.25, q99 + (q99 - q1) * 0.25)

        def get_shared_y(data, features):
            max_y = 0
            for f in features:
                if f in data.columns:
                    vd = data.dropna(subset=[f])
                    if not vd.empty:
                        cnts, _ = np.histogram(vd[f], bins=15, weights=vd['Total_Qty'])
                        max_y = max(max_y, cnts.max())
            return max_y * 1.35 if max_y > 0 else 50

        def plot_dist(ax, data, feat, title, y_lim):
            c_map = {'A-B+': '#2ca02c', 'A-B': '#1f77b4', 'A-B-': '#ff7f0e', 'B+': '#9467bd', 'B': '#d62728'}
            spec = GLOBAL_SPECS.get(feat, {})
            lsl, usl, tgt = spec.get('min'), spec.get('max'), spec.get('target')

            fmin, fmax = global_x_bounds.get(feat, (data[feat].min() if not data.empty else 0, data[feat].max() if not data.empty else 100))
            if fmin == fmax: fmax += 1
            
            v_l, w_l, clrs, m_info = [], [], [], []
            for g in base_grades:
                if g in data.columns:
                    td = data[[feat, g]].dropna()
                    td = td[td[g] > 0]
                    if not td.empty:
                        v_l.append(td[feat].values)
                        w_l.append(td[g].values)
                        clrs.append(c_map[g])
                        m = np.average(td[feat].values, weights=td[g].values)
                        ax.axvline(m, color=c_map[g], ls='--', lw=1.2)
                        m_info.append({'v': m, 'c': c_map[g], 'label': g})

            if v_l:
                ax.hist(v_l, bins=np.linspace(fmin, fmax, 16), weights=w_l, color=clrs, stacked=True, edgecolor='white', alpha=0.7)
                
                # Annotation positioning to prevent overlapping
                m_info.sort(key=lambda x: x['v'])
                x_range = fmax - fmin
                min_gap = x_range * 0.045
                positions = [info['v'] for info in m_info]
                for _ in range(50):
                    moved = False
                    for i in range(1, len(positions)):
                        if positions[i] - positions[i - 1] < min_gap:
                            mid = (positions[i] + positions[i - 1]) / 2
                            positions[i - 1] = mid - min_gap / 2
                            positions[i] = mid + min_gap / 2
                            moved = True
                    if not moved: break
                
                y_levels = [y_lim * (0.92 - (i % 4) * 0.13) for i in range(len(m_info))]
                for i, info in enumerate(m_info):
                    x_pos = positions[i]
                    y_pos = y_levels[i]
                    ax.annotate(
                        f"{info['v']:.1f}",
                        xy=(info['v'], y_pos * 0.6), xytext=(x_pos, y_pos),
                        color='white', fontweight='bold', fontsize=8, ha='center', va='center',
                        bbox=dict(facecolor=info['c'], alpha=0.85, boxstyle='round,pad=0.25'),
                        arrowprops=dict(arrowstyle='-', color=info['c'], lw=1.0, alpha=0.6) if abs(x_pos - info['v']) > min_gap * 0.3 else None
                    )

            y_top = y_lim * 0.98
            if lsl is not None:
                ax.axvline(lsl, color='red', lw=2, ls='-', zorder=3)
                ax.text(lsl, y_top, f' LSL\n {lsl}', color='red', fontsize=7.5, fontweight='bold', va='top', ha='left')
            if usl is not None:
                ax.axvline(usl, color='red', lw=2, ls='-', zorder=3)
                ax.text(usl, y_top, f' USL\n {usl}', color='red', fontsize=7.5, fontweight='bold', va='top', ha='right')
            if tgt is not None:
                ax.axvline(tgt, color='#1a7abf', lw=1.5, ls=':', zorder=3)
                ax.text(tgt, y_top * 0.75, f' TGT\n {tgt}', color='#1a7abf', fontsize=7, fontweight='bold', va='top', ha='left')

            ax.legend(handles=[Patch(facecolor=c_map[g], label=g) for g in base_grades if g in data.columns],
                      loc='upper right', fontsize=7)
            ax.set_xlim(fmin, fmax)
            ax.set_ylim(0, y_lim)
            ax.set_title(title, fontsize=10, fontweight='bold')
            add_chart_border(ax)

        # Build capability summary
        ordered_periods = sorted(df['Time_Group'].unique(), key=get_sort_key)
        cap_summary_rows = []
        for _p in ordered_periods:
            _dfp = df[df['Time_Group'] == _p]
            for _f in ['YS', 'TS', 'EL', 'YPE']:
                if _f in _dfp.columns:
                    row = build_capability_summary(_dfp, _f, _p)
                    if row: cap_summary_rows.append(row)

        if cap_summary_rows:
            cap_df = pd.DataFrame(cap_summary_rows)
            
            st.markdown("### 📋 Detailed Capability Log")
            def color_cpk_cell(val):
                if pd.isna(val): return ''
                c = cpk_color(val)
                return f'background-color:{c};color:white;font-weight:bold;text-align:center'

            fmt = {
                'Mean': '{:.2f}', 'Std': '{:.3f}', 'Cp': '{:.3f}', 'Cpk': '{:.3f}',
                'Ca (%)': lambda v: f'{v:.1f}%' if pd.notnull(v) else '—',
                'LSL': lambda v: str(v) if pd.notnull(v) else '—',
                'USL': lambda v: str(v) if pd.notnull(v) else '—',
            }
            st.dataframe(
                cap_df.style
                .map(color_cpk_cell, subset=['Cpk'])
                .format(fmt, na_rep='—'),
                use_container_width=True, hide_index=True
            )
            st.markdown("---")

        # Distribution Charts
        thickness_list = sorted(df['Actual_Thickness'].dropna().unique())
        
        for period in ordered_periods:
            df_p = df[df['Time_Group'] == period]
            if df_p.empty: continue
            
            st.markdown(f"## 📅 Period: **{period}**")
            ov_y = get_shared_y(df_p, ['YS', 'TS', 'EL', 'YPE'])
            cols = st.columns(2)
            
            for idx, f in enumerate([x for x in ['YS', 'TS', 'EL', 'YPE'] if x in df_p.columns]):
                with cols[idx % 2]:
                    fig, ax = plt.subplots(figsize=(8, 4.5))
                    plot_dist(ax, df_p, f, f"{f} (Overall - {period})", ov_y)
                    fig.tight_layout()
                    st.pyplot(fig)
                    
                    vals_all = df_p[f].dropna().values
                    render_capability_badge(calc_capability(vals_all, f), f)

    # ==========================================================
    # TASK 5: TAIL SCRAP & HYBRID TREND
    # ==========================================================
    with tab5:
        st.header("Tail Scrap & Length Rejection Analysis")
        
        COIL_ID_COL = '鋼捲號碼'

        if LEN_COL in df.columns and SCRAP_COL in df.columns:
            df_t5 = df[df['Time_Group'] != "2025 (Full Year)"].copy()
            
            df_t5[COIL_ID_COL] = df_t5[COIL_ID_COL].astype(str).str.strip().replace(['nan', 'None', '', 'NaN'], np.nan)
            
            missing_mask = df_t5[COIL_ID_COL].isna()
            if missing_mask.any():
                df_t5.loc[missing_mask, COIL_ID_COL] = [f"UNKNOWN_{i}" for i in df_t5[missing_mask].index]

            scrap_totals = df_t5.groupby(['Time_Group', COIL_ID_COL])[SCRAP_COL].sum().reset_index()
            first_occurrence = df_t5.sort_values(['Time_Group', 'Production_Date']).drop_duplicates(subset=['Time_Group', COIL_ID_COL], keep='first')
            
            df_scrap_master = first_occurrence[['Time_Group', COIL_ID_COL, LEN_COL, 'Actual_Thickness', 'HR_Material', 'Production_Date']].merge(
                scrap_totals, on=[COIL_ID_COL, 'Time_Group']
            )

            # --- 1. HYBRID TREND LINE ---
            st.subheader("1. Rejection Rate Trend (%)")
            
            trend_data = df_scrap_master.groupby('Time_Group').agg(
                Input_Length=(LEN_COL, 'sum'),
                Total_Scrap=(SCRAP_COL, 'sum')
            ).reset_index()
            
            trend_data = trend_data[trend_data['Time_Group'] != 'Unknown']
            
            trend_data['Rejection_Rate (%)'] = np.where(
                trend_data['Input_Length'] > 0,
                (trend_data['Total_Scrap'] / trend_data['Input_Length'] * 100),
                0
            ).round(2)
            
            trend_data['_sort'] = trend_data['Time_Group'].apply(get_sort_key)
            trend_data = trend_data.sort_values('_sort').drop(columns=['_sort'])

            fig_trend, ax_trend = plt.subplots(figsize=(14, 5))
            if not trend_data.empty:
                ax_trend.plot(trend_data['Time_Group'], trend_data['Rejection_Rate (%)'], 
                              marker='o', markersize=8, markeredgecolor='white', markeredgewidth=1.5,
                              linestyle='-', color='#1f77b4', linewidth=3, label='Rejection Rate %')
                
                ax_trend.fill_between(trend_data['Time_Group'], trend_data['Rejection_Rate (%)'], 
                                      color='#1f77b4', alpha=0.1)

                y_max = trend_data['Rejection_Rate (%)'].max()
                ax_trend.set_ylim(0, y_max * 1.35 + 0.5 if not trend_data.empty else 10)
                
                ax_trend.set_title("Rejection Rate Trend", fontweight='bold', fontsize=15, pad=15, color='#333')
                ax_trend.set_ylabel("Rejection Rate (%)", fontweight='bold', color='#555')
                ax_trend.set_xlabel("")
                
                ax_trend.grid(axis='y', linestyle='--', alpha=0.5)
                ax_trend.grid(axis='x', visible=False)
                
                for i, val in enumerate(trend_data['Rejection_Rate (%)']):
                    ax_trend.annotate(f'{val:.2f}%', 
                                      xy=(i, val), 
                                      xytext=(0, 8), 
                                      textcoords="offset points", 
                                      ha='center', va='bottom', 
                                      fontsize=10, fontweight='bold', color='#222',
                                      bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="none", alpha=0.8))
                
                add_chart_border(ax_trend)
                plt.xticks(rotation=40, ha='right', fontsize=10)
                fig_trend.tight_layout()
                
            st.pyplot(fig_trend)

            # --- 2. PERIOD SUMMARY & CHART ---
            st.markdown("---")
            st.subheader("2. Scrap Rate by Time Period")
            scrap_by_period = df_scrap_master.groupby('Time_Group').agg(
                Total_Length=(LEN_COL, 'sum'),
                Total_Scrap=(SCRAP_COL, 'sum'),
                Coil_Count=(COIL_ID_COL, 'count')
            ).reset_index()
            
            scrap_by_period['Scrap_Rate (%)'] = np.where(
                scrap_by_period['Total_Length'] > 0,
                (scrap_by_period['Total_Scrap'] / scrap_by_period['Total_Length'] * 100),
                0
            ).round(2)
            
            scrap_by_period['_sort'] = scrap_by_period['Time_Group'].apply(get_sort_key)
            scrap_by_period = scrap_by_period.sort_values('_sort').drop(columns=['_sort'])
            
            fig_p, ax_p = plt.subplots(figsize=(10, 4))
            if not scrap_by_period.empty:
                ax_p.bar(scrap_by_period['Time_Group'], scrap_by_period['Scrap_Rate (%)'], color='#e74c3c', edgecolor='white')
                ax_p.set_title("Tail Scrap Rate (%) by Time Period", fontweight='bold')
                ax_p.set_ylabel("Scrap Rate (%)")
                ax_p.set_xlabel("")
                ax_p.set_ylim(0, scrap_by_period['Scrap_Rate (%)'].max() * 1.2 + 0.1)
                for i, val in enumerate(scrap_by_period['Scrap_Rate (%)']):
                    ax_p.annotate(f"{val:.2f}%", xy=(i, val), xytext=(0, 5), textcoords="offset points", ha='center', va='bottom', fontweight='bold')
                
                add_chart_border(ax_p)
                plt.xticks(rotation=30, ha='right')
                fig_p.tight_layout()
            st.pyplot(fig_p)

            st.dataframe(
                scrap_by_period.style.background_gradient(subset=['Scrap_Rate (%)'], cmap='Reds')
                .format({'Total_Length': '{:,.2f}', 'Total_Scrap': '{:,.2f}', 'Scrap_Rate (%)': '{:.2f}%'}),
                use_container_width=True, hide_index=True
            )

            # --- 3. LEVEL-BY-LEVEL DRILL DOWN & CHARTS ---
            st.markdown("---")
            st.subheader("3. Deep Analysis: Scrap Rate by Period / Thickness / Material")
            scrap_detail = df_scrap_master.groupby(['Time_Group', 'Actual_Thickness', 'HR_Material']).agg(
                Total_Length=(LEN_COL, 'sum'),
                Total_Scrap=(SCRAP_COL, 'sum'),
                Coil_Count=(COIL_ID_COL, 'count')
            ).reset_index()
            
            scrap_detail = scrap_detail[scrap_detail['Total_Length'] > 0]
            scrap_detail['Scrap_Rate (%)'] = (scrap_detail['Total_Scrap'] / scrap_detail['Total_Length'] * 100).round(2)
            
            col_t, col_m = st.columns(2)
            with col_t:
                st.markdown("**Scrap Rate by Period & Thickness**")
                fig_t, ax_t = plt.subplots(figsize=(8, 4))
                if not scrap_detail.empty:
                    pivot_t = scrap_detail.pivot_table(index='Time_Group', columns='Actual_Thickness', values='Scrap_Rate (%)', aggfunc='mean')
                    if not pivot_t.empty:
                        pivot_t.plot(kind='bar', ax=ax_t, color=solid_colors, edgecolor='white')
                        ax_t.legend(title="Thickness", bbox_to_anchor=(1.02, 1), loc='upper left')
                ax_t.set_ylabel("Scrap Rate (%)")
                ax_t.set_xlabel("")
                add_chart_border(ax_t)
                plt.xticks(rotation=30, ha='right')
                fig_t.tight_layout()
                st.pyplot(fig_t)

            with col_m:
                st.markdown("**Scrap Rate by Period & Material**")
                fig_m, ax_m = plt.subplots(figsize=(8, 4))
                if not scrap_detail.empty:
                    pivot_m = scrap_detail.pivot_table(index='Time_Group', columns='HR_Material', values='Scrap_Rate (%)', aggfunc='mean')
                    if not pivot_m.empty:
                        pivot_m.plot(kind='bar', ax=ax_m, colormap='tab10', edgecolor='white')
                        ax_m.legend(title="Material", bbox_to_anchor=(1.02, 1), loc='upper left')
                ax_m.set_ylabel("Scrap Rate (%)")
                ax_m.set_xlabel("")
                add_chart_border(ax_m)
                plt.xticks(rotation=30, ha='right')
                fig_m.tight_layout()
                st.pyplot(fig_m)

            scrap_detail['_sort'] = scrap_detail['Time_Group'].apply(get_sort_key)
            scrap_detail = scrap_detail.sort_values(by=['_sort', 'Actual_Thickness']).drop(columns=['_sort'])

            st.dataframe(
                scrap_detail.style.background_gradient(subset=['Scrap_Rate (%)'], cmap='Oranges')
                .format({'Actual_Thickness': '{:.2f}', 'Total_Length': '{:,.2f}', 'Total_Scrap': '{:,.2f}', 'Scrap_Rate (%)': '{:.2f}%'}),
                use_container_width=True, hide_index=True
            )

        else:
            st.warning("Required columns ('實測長度' or '尾料剔退') not found in the file.")

    # --- GLOBAL EXPORT ---
    st.sidebar.header("Export Reports")
    if st.sidebar.button("Generate Excel File"):
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            if not yield_summary.empty:
                yield_summary.to_excel(writer, sheet_name='Yield_Detailed', index=False)
            grade_dist_display.to_excel(writer, sheet_name='Grade_Distribution')
            if 'cap_summary_rows' in locals() and cap_summary_rows:
                pd.DataFrame(cap_summary_rows).to_excel(writer, sheet_name='Capability_Log', index=False)
            if 'trend_data' in locals() and not trend_data.empty:
                trend_data.drop(columns=['_sort']).to_excel(writer, sheet_name='Trend_Data', index=False)
                scrap_by_period.to_excel(writer, sheet_name='Scrap_By_Period', index=False)
                scrap_detail.to_excel(writer, sheet_name='Scrap_Detailed', index=False)
        
        st.sidebar.download_button(
            label="📥 Download Full Excel",
            data=output.getvalue(),
            file_name="Quality_Scrap_Deep_Analysis.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
