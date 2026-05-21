import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np
import io
import seaborn as sns
import streamlit.components.v1 as components
from PIL import Image

# --- FIX: Tắt giới hạn pixel để tránh lỗi DecompressionBombError ---
Image.MAX_IMAGE_PIXELS = None

# --- PAGE CONFIG ---
st.set_page_config(page_title="Quality & Scrap Dashboard", layout="wide")
st.title("📊 Production Quality Yield & Tail Scrap Analysis")
st.markdown("---")

# --- FIX: Tối ưu DPI cho Web để tiết kiệm RAM (vẫn giữ 300 DPI cho tải xuống) ---
plt.rcParams['figure.dpi'] = 120
plt.rcParams['savefig.dpi'] = 300
plt.rcParams['savefig.bbox'] = 'tight'

# --- SIDEBAR: DYNAMIC SPEC LIMITS INPUT PER THICKNESS ---
st.sidebar.header("⚙️ Spec Limits (Control)")
st.sidebar.info("Limits apply from Q4 2025 onwards. Configured per Thickness.")

GLOBAL_SPECS = {0.5: {}, 0.6: {}, 0.8: {}}
target_thicks = [0.5, 0.6, 0.8]

for t in target_thicks:
    with st.sidebar.expander(f"📏 Limits for {t}mm"):
        for feat in ['YS', 'TS', 'EL', 'YPE']:
            st.caption(f"**{feat}**")
            c1, c2, c3 = st.columns(3)
            min_v = c1.number_input("Min", value=None, key=f"{t}_{feat}_min", label_visibility="collapsed", placeholder="Min")
            max_v = c2.number_input("Max", value=None, key=f"{t}_{feat}_max", label_visibility="collapsed", placeholder="Max")
            tgt_v = c3.number_input("Tgt", value=None, key=f"{t}_{feat}_tgt", label_visibility="collapsed", placeholder="Tgt")
            GLOBAL_SPECS[t][feat] = {'min': min_v, 'max': max_v, 'target': tgt_v}

uploaded_file = st.file_uploader("Upload Production Data (.xlsx)", type=["xlsx"])

if uploaded_file is not None:
    df = pd.read_excel(uploaded_file)
    df.columns = df.columns.astype(str).str.strip()

    # --- 1. DATA PRE-PROCESSING ---
    # Handle Dates & Time Grouping First
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
        
        df_25 = df[df['Production_Date'].dt.year == 2025].copy()
        if not df_25.empty:
            df_25['Time_Group'] = "2025 (Full Year)"
            df = pd.concat([df, df_25], ignore_index=True)
    else:
        df['Time_Group'] = "Unknown"

    # Robust Quality Grade Mapping
    base_grades = ['A-B+', 'A-B', 'A-B-', 'B+', 'B']
    for g in base_grades:
        match_cols = []
        for c in df.columns:
            c_str = str(c).strip()
            if c_str == g or c_str == f"{g}個數" or c_str.startswith(f"{g}."):
                match_cols.append(c)
        df[g] = df[match_cols].apply(pd.to_numeric, errors='coerce').fillna(0).sum(axis=1) if match_cols else 0

    df['Total_Qty'] = df[base_grades].sum(axis=1)
    df['Severe_Bad_Qty'] = df[['B+', 'B']].sum(axis=1)
    df['Acceptable_Qty'] = df['Total_Qty'] - df['Severe_Bad_Qty']
    
    target_grades = ['A-B+', 'A-B']
    df['Valid_Qty'] = df[target_grades].sum(axis=1)

    # STORE ORIGINAL DATA FOR GRADE DISTRIBUTION (Unfiltered by thickness)
    df_global_grades = df[df['Total_Qty'] > 0].copy()

    # Handle Thickness & Filtering for Detailed Charts
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

    if '熱軋材質' in df.columns:
        df['HR_Material'] = df['熱軋材質'].astype(str).str.strip().replace(['nan', ''], 'Unknown')
    else:
        df['HR_Material'] = 'Unknown'

    df.rename(columns={'烤漆降伏強度': 'YS', '烤漆抗拉強度': 'TS', '伸長率': 'EL'}, inplace=True)
    mech_features = ['YS', 'TS', 'EL', 'YPE', 'HARDNESS']
    for f in mech_features:
        if f in df.columns:
            df[f] = pd.to_numeric(df[f], errors='coerce')

    LEN_COL = '實測長度'
    SCRAP_COL = '尾料剔退'
    if LEN_COL in df.columns:
        df[LEN_COL] = pd.to_numeric(df[LEN_COL], errors='coerce').fillna(0)
    if SCRAP_COL in df.columns:
        df[SCRAP_COL] = pd.to_numeric(df[SCRAP_COL], errors='coerce').fillna(0)

    df = df[(df['Total_Qty'] > 0) | (df.get(LEN_COL, 0) > 0) | (df.get(SCRAP_COL, 0) > 0)]

    sns.set_theme(style="whitegrid")
    solid_colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b']

    def get_sort_key(x):
        if "2024 (Full Year)" in x: return "2024-00"
        if "2025 H1" in x: return "2025-00a"
        if "2025 Q3" in x: return "2025-00b"
        if "2025 (Full Year)" in x: return "2025-99" 
        return x

    def add_chart_border(ax):
        for spine in ax.spines.values():
            spine.set_visible(True)
            spine.set_color('#333333')
            spine.set_linewidth(1.0)

    # --- SPC & CAPABILITY HELPER FUNCTIONS ---
    def is_valid_for_control(period_label):
        if "2024" in period_label or "2025 H1" in period_label or "2025 Q3" in period_label or "2025 (Full Year)" in period_label:
            return False
        return True

    def calc_capability(values, feat, period_label, thickness):
        vals = np.array(values, dtype=float)
        vals = vals[~np.isnan(vals)]
        
        if thickness == 'Overall':
            return {'mean': np.mean(vals) if len(vals) > 0 else 0, 'std': np.std(vals, ddof=1) if len(vals) > 1 else 0, 'n': len(vals),
                    'Cp': None, 'Cpk': None, 'Ca': None, 'LSL': None, 'USL': None, 'Target': None}

        if len(vals) < 2: return None
        mu  = np.mean(vals)
        std = np.std(vals, ddof=1)
        if std == 0: return None

        spec = GLOBAL_SPECS.get(thickness, {}).get(feat, {})
        lsl  = spec.get('min')
        usl  = spec.get('max')
        tgt  = spec.get('target')

        result = {'mean': mu, 'std': std, 'n': len(vals),
                  'Cp': None, 'Cpk': None, 'Ca': None,
                  'LSL': lsl, 'USL': usl, 'Target': tgt}

        if not is_valid_for_control(period_label):
            return result

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

    def cpk_label(cpk, period_label, thickness):
        if thickness == 'Overall': return 'Mixed Specs'
        if not is_valid_for_control(period_label): return 'Not Monitored'
        if cpk is None: return 'N/A'
        if cpk >= 1.67: return '✅ Excellent'
        if cpk >= 1.33: return '✅ Capable'
        if cpk >= 1.00: return '⚠️ Marginal'
        return '❌ Not Capable'

    def render_capability_badge(cap, feat, period_label, thickness):
        if cap is None: return
        
        mu_v   = f"{cap['mean']:.2f}"
        std_v  = f"{cap['std']:.3f}"
        
        if thickness == 'Overall':
            cp_v, cpk_v, ca_v = 'N/A', 'N/A', 'N/A'
            clr, lbl = '#888888', 'Mixed Thickness (No Global Limit)'
            lsl_v, usl_v = '—', '—'
        elif is_valid_for_control(period_label):
            cp_v   = f"{cap['Cp']:.3f}"   if cap['Cp']  is not None else 'N/A'
            cpk_v  = f"{cap['Cpk']:.3f}"  if cap['Cpk'] is not None else 'N/A'
            ca_v   = f"{cap['Ca']:.1f}%"  if cap['Ca']  is not None else 'N/A'
            clr    = cpk_color(cap['Cpk'])
            lbl    = cpk_label(cap['Cpk'], period_label, thickness)
            lsl_v  = str(cap['LSL']) if cap['LSL'] is not None else '—'
            usl_v  = str(cap['USL']) if cap['USL'] is not None else '—'
        else:
            cp_v, cpk_v, ca_v = 'N/A', 'N/A', 'N/A'
            clr, lbl = '#888888', 'Pre-Q4 2025 (Not Monitored)'
            lsl_v, usl_v = '—', '—'

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

    def build_capability_summary(df_src, feat, label, thick):
        vals = df_src[feat].dropna().values if feat in df_src.columns else []
        cap = calc_capability(vals, feat, label, thick)
        if cap is None or cap['n'] < 2: return None
        
        if not is_valid_for_control(label):
            return {
                'Period': label, 'Thickness': thick, 'Feature': feat, 'n': cap['n'],
                'Mean': round(cap['mean'], 2), 'Std': round(cap['std'], 3),
                'LSL': None, 'USL': None, 'Ca (%)': None, 'Cp': None, 'Cpk': None,
                'Verdict': 'Not Monitored'
            }

        return {
            'Period': label, 'Thickness': thick, 'Feature': feat, 'n': cap['n'],
            'Mean': round(cap['mean'], 2), 'Std': round(cap['std'], 3),
            'LSL': cap['LSL'], 'USL': cap['USL'], 'Ca (%)': cap['Ca'],
            'Cp': cap['Cp'], 'Cpk': cap['Cpk'],
            'Verdict': cpk_label(cap['Cpk'], label, thick).replace('✅ ', '').replace('⚠️ ', '').replace('❌ ', '')
        }

    global_x_bounds = {}
    for feat in ['YS', 'TS', 'EL', 'YPE']:
        if feat in df.columns:
            vd = df[[feat, 'Valid_Qty']].dropna().copy()
            vd = vd[vd['Valid_Qty'] > 0]
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

    def plot_dist(ax, data, feat, title, y_lim, period_label, thickness):
        c_map = {'A-B+': '#2ca02c', 'A-B': '#1f77b4', 'A-B-': '#ff7f0e', 'B+': '#9467bd', 'B': '#d62728'}
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

        if thickness != 'Overall' and is_valid_for_control(period_label):
            spec = GLOBAL_SPECS.get(thickness, {}).get(feat, {})
            lsl, usl, tgt = spec.get('min'), spec.get('max'), spec.get('target')
            y_top = y_lim * 0.98
            if lsl is not None:
                ax.axvline(lsl, color='darkred', lw=2, ls='-', zorder=3)
                ax.text(lsl, y_top, f' LSL\n {lsl}', color='darkred', fontsize=7.5, fontweight='bold', va='top', ha='left')
            if usl is not None:
                ax.axvline(usl, color='darkred', lw=2, ls='-', zorder=3)
                ax.text(usl, y_top, f' USL\n {usl}', color='darkred', fontsize=7.5, fontweight='bold', va='top', ha='right')
            if tgt is not None:
                ax.axvline(tgt, color='#1a7abf', lw=1.5, ls=':', zorder=3)
                ax.text(tgt, y_top * 0.75, f' TGT\n {tgt}', color='#1a7abf', fontsize=7, fontweight='bold', va='top', ha='left')

        ax.legend(handles=[Patch(facecolor=c_map[g], label=g) for g in base_grades if g in data.columns],
                  loc='upper right', fontsize=7)
        ax.set_xlim(fmin, fmax)
        ax.set_ylim(0, y_lim)
        ax.set_title(title, fontsize=10, fontweight='bold')
        add_chart_border(ax)

    # --- TABS ---
    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
        "📁 1. Raw Data", 
        "📋 2. Quality Yield", 
        "📈 3. Capability (SPC)", 
        "📉 4. I-MR Tracking",
        "✂️ 5. Tail Scrap",
        "🎯 6. Customer End-Use",
        "🏭 7. Production-Based Scrap & Material Stability"
    ])

    # ==========================================================
    # TASK 1: RAW DATA INSPECTION
    # ==========================================================
    with tab1:
        st.header("1. Raw Data Inspection")
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
        st.dataframe(df.head(50), use_container_width=True)

    # ==========================================================
    # TASK 2: YIELD SUMMARY
    # ==========================================================
    with tab2:
        st.header("2. Executive Quality Yield Summary")
        
        st.subheader("Detailed Yield by Thickness & Material")
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
        st.subheader("📊 Grade Distribution by Time Period (%)")
        st.caption("Note: This summary table evaluates 100% of production data. Detailed charts below are filtered to specific thickness groups.")
        
        grade_dist = df_global_grades.groupby('Time_Group')[base_grades].sum()
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
            chart_grade_dist = grade_dist_display[grade_dist_display.index != "2025 (Full Year)"]
            
            grade_colors = ['#2e7d32', '#66bb6a', '#ffa726', '#ef5350', '#c62828']
            chart_grade_dist.plot(kind='bar', stacked=True, ax=ax_g, color=grade_colors, edgecolor='white')
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
            plt.close(fig_g)

        st.markdown("---")
        st.subheader("Charts by Period & Thickness")
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
                    for c in ax_y.containers:
                        labels = [f"{v.get_height():.1f}%" if v.get_height() > 0 else "" for v in c]
                        ax_y.bar_label(c, labels=labels, padding=3, fontsize=7, fontweight='bold', rotation=90)
            ax_y.set_ylim(0, 130) 
            ax_y.set_ylabel("Yield (%)")
            ax_y.set_xlabel("")
            add_chart_border(ax_y)
            plt.xticks(rotation=30, ha='right')
            fig_y.tight_layout()
            st.pyplot(fig_y)
            plt.close(fig_y)
            
        with col_c2:
            st.markdown("**Defect Rate (%) by Period & Thickness**")
            fig_d, ax_d = plt.subplots(figsize=(8, 4))
            if not yield_summary.empty:
                chart_df = yield_summary[yield_summary['Time_Group'] != "2025 (Full Year)"]
                pivot_d = chart_df.pivot_table(index='Time_Group', columns='Actual_Thickness', values='Defect_Rate (%)', aggfunc='mean')
                if not pivot_d.empty:
                    pivot_d.plot(kind='bar', ax=ax_d, color=solid_colors, edgecolor='white')
                    ax_d.legend(title="Thickness", bbox_to_anchor=(1.02, 1), loc
