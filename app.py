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

# --- FIX ẢNH MỜ: ÉP CHẤT LƯỢNG RENDER 300 DPI ---
plt.rcParams['figure.dpi'] = 300
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

    # LƯU TRỮ DỮ LIỆU GỐC CHO BẢNG GRADE DISTRIBUTION (Chưa lọc độ dày)
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
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📁 1. Raw Data", 
        "📋 2. Quality Yield", 
        "📈 3. Capability (SPC)", 
        "📉 4. I-MR Tracking",
        "✂️ 5. Tail Scrap",
        "🎯 6. Customer End-Use"
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
            
        with col_c2:
            st.markdown("**Defect Rate (%) by Period & Thickness**")
            fig_d, ax_d = plt.subplots(figsize=(8, 4))
            if not yield_summary.empty:
                chart_df = yield_summary[yield_summary['Time_Group'] != "2025 (Full Year)"]
                pivot_d = chart_df.pivot_table(index='Time_Group', columns='Actual_Thickness', values='Defect_Rate (%)', aggfunc='mean')
                if not pivot_d.empty:
                    pivot_d.plot(kind='bar', ax=ax_d, color=solid_colors, edgecolor='white')
                    ax_d.legend(title="Thickness", bbox_to_anchor=(1.02, 1), loc='upper left')
                    for c in ax_d.containers:
                        labels = [f"{v.get_height():.1f}%" if v.get_height() > 0 else "" for v in c]
                        ax_d.bar_label(c, labels=labels, padding=3, fontsize=7, fontweight='bold', rotation=90)
                    y_max = pivot_d.max().max() if not pivot_d.isna().all().all() else 10
                    ax_d.set_ylim(0, y_max * 1.4 + 2)
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
        st.header("3. Distribution & Process Capability (SPC)")
        st.info("Visualizing mechanical property distribution. Capability indices (Cp, Cpk) apply from Q4 2025 onwards. Limit calculations strictly based on grades A or B (A-B+, A-B).")

        ordered_periods = sorted(df['Time_Group'].unique(), key=get_sort_key)
        thickness_list = sorted(df['Actual_Thickness'].dropna().unique())
        
        cap_summary_rows = []
        for _p in ordered_periods:
            if _p == "2025 (Full Year)": continue 
            _dfp = df[df['Time_Group'] == _p]
            _dfp_valid = _dfp[_dfp['Valid_Qty'] > 0]
            
            for _t in thickness_list:
                _dft = _dfp_valid[_dfp_valid['Actual_Thickness'] == _t]
                if _dft.empty: continue
                for _f in ['YS', 'TS', 'EL', 'YPE']:
                    if _f in _dft.columns:
                        row = build_capability_summary(_dft, _f, _p, _t)
                        if row: cap_summary_rows.append(row)

        if cap_summary_rows:
            cap_df = pd.DataFrame(cap_summary_rows)
            
            st.markdown("### 📋 Detailed Capability Log (Per Thickness - Grades A-B+, A-B Only)")
            def color_cpk_cell(val):
                if pd.isna(val) or val == 'N/A' or val == '': return ''
                try:
                    c = cpk_color(float(val))
                    return f'background-color:{c};color:white;font-weight:bold;text-align:center'
                except:
                    return ''

            fmt = {
                'Thickness': '{:.2f}',
                'Mean': '{:.2f}', 'Std': '{:.3f}', 
                'Cp': lambda v: f'{v:.3f}' if pd.notnull(v) else '—', 
                'Cpk': lambda v: f'{v:.3f}' if pd.notnull(v) else '—',
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

        for period in ordered_periods:
            if period == "2025 (Full Year)": continue
            df_p = df[df['Time_Group'] == period]
            if df_p.empty: continue
            
            st.markdown(f"## 📅 Period: **{period}**")
            
            ov_y = get_shared_y(df_p, ['YS', 'TS', 'EL', 'YPE'])
            st.markdown(f"#### 🌐 Overall Summary (All Thicknesses)")
            cols = st.columns(2)
            for idx, f in enumerate([x for x in ['YS', 'TS', 'EL', 'YPE'] if x in df_p.columns]):
                with cols[idx % 2]:
                    df_p_valid = df_p[df_p['Valid_Qty'] > 0]
                    vals_all = df_p_valid[f].dropna().values
                    render_capability_badge(calc_capability(vals_all, f, period, 'Overall'), f, period, 'Overall')
                    
                    fig, ax = plt.subplots(figsize=(8, 4.5))
                    plot_dist(ax, df_p, f, f"{f} (Overall - {period})", ov_y, period, 'Overall')
                    fig.tight_layout()
                    st.pyplot(fig)
            
            for thick in thickness_list:
                df_t = df_p[df_p['Actual_Thickness'] == thick]
                if df_t.empty: continue
                
                st.markdown(f"#### 📏 Thickness: **{thick}mm**")
                ly = get_shared_y(df_t, ['YS', 'TS', 'EL', 'YPE'])
                tcols = st.columns(2)
                
                for idx, f in enumerate([x for x in ['YS', 'TS', 'EL', 'YPE'] if x in df_t.columns]):
                    with tcols[idx % 2]:
                        df_t_valid = df_t[df_t['Valid_Qty'] > 0]
                        vals_t = df_t_valid[f].dropna().values
                        render_capability_badge(calc_capability(vals_t, f, period, thick), f, period, thick)
                        
                        fig, ax = plt.subplots(figsize=(8, 4.5))
                        plot_dist(ax, df_t, f, f"{f} (Thick:{thick} - {period})", ly, period, thick)
                        fig.tight_layout()
                        st.pyplot(fig)
            st.markdown("---")

    # ==========================================================
    # TASK 4: POST-CONTROL TRACKING (I-MR CHARTS)
    # ==========================================================
    with tab4:
        st.header("4. Post-Control Tracking (I-MR Charts)")
        st.info("Tracking process stability for production from 2026 onwards. Limits and charts calculated ONLY based on grades A or B (A-B+, A-B).")
        
        df_t4 = df[df['Production_Date'].dt.year >= 2026].copy()
        df_t4 = df_t4[df_t4['Valid_Qty'] > 0]
        
        if df_t4.empty:
            st.warning("No valid data available for 2026 onwards.")
        else:
            thicknesses = ['Overall'] + sorted(df_t4['Actual_Thickness'].dropna().unique().tolist())
            t4_thick = st.selectbox("Select Thickness Category:", thicknesses)
            
            if t4_thick != 'Overall':
                plot_df_base = df_t4[df_t4['Actual_Thickness'] == t4_thick]
            else:
                plot_df_base = df_t4
                
            for t4_feat in ['YS', 'TS', 'EL', 'YPE']:
                if t4_feat not in plot_df_base.columns:
                    continue
                    
                plot_df = plot_df_base.sort_values('Production_Date').dropna(subset=[t4_feat])
                
                if len(plot_df) < 2:
                    continue
                    
                st.markdown("---")
                st.subheader(f"Feature: {t4_feat}")
                
                vals_all = plot_df[t4_feat].values
                cap_data = calc_capability(vals_all, t4_feat, '2026-01', t4_thick)
                
                render_capability_badge(cap_data, t4_feat, '2026-01', t4_thick)
                
                dates = plot_df['Production_Date'].dt.strftime('%Y-%m-%d')
                vals = plot_df[t4_feat].values
                
                mean_v = np.mean(vals)
                mr = np.abs(np.diff(vals))
                mr_mean = np.mean(mr)
                
                ucl_i = mean_v + 2.66 * mr_mean
                lcl_i = max(0, mean_v - 2.66 * mr_mean)
                ucl_mr = 3.267 * mr_mean
                
                fig_imr, (ax_i, ax_mr) = plt.subplots(2, 1, figsize=(12, 8), gridspec_kw={'height_ratios': [2, 1]})
                
                # I-Chart
                ax_i.plot(vals, marker='o', color='#1f77b4', linestyle='-', linewidth=1.5, markersize=5)
                
                # Statistical Control Limits
                ax_i.axhline(mean_v, color='green', linestyle='--', label=f'Mean: {mean_v:.2f}')
                ax_i.axhline(ucl_i, color='red', linestyle='--', label=f'UCL: {ucl_i:.2f}')
                ax_i.axhline(lcl_i, color='red', linestyle='--', label=f'LCL: {lcl_i:.2f}')
                
                # User Input Specification Limits (USL/LSL/Target)
                spec = GLOBAL_SPECS.get(t4_thick, {}).get(t4_feat, {}) if t4_thick != 'Overall' else {}
                lsl = spec.get('min')
                usl = spec.get('max')
                tgt = spec.get('target')

                if lsl is not None:
                    ax_i.axhline(lsl, color='darkred', linestyle='-', linewidth=2, label=f'LSL (Spec Min): {lsl}')
                if usl is not None:
                    ax_i.axhline(usl, color='darkred', linestyle='-', linewidth=2, label=f'USL (Spec Max): {usl}')
                if tgt is not None:
                    ax_i.axhline(tgt, color='blue', linestyle=':', linewidth=1.5, label=f'Target: {tgt}')
                
                # Bắt lỗi vượt giới hạn (Thống kê + Kỹ thuật)
                out_condition = (vals > ucl_i) | (vals < lcl_i)
                
                if usl is not None:
                    out_condition = out_condition | (vals > usl)
                if lsl is not None:
                    out_condition = out_condition | (vals < lsl)

                out_i = np.where(out_condition)[0]
                
                if len(out_i) > 0:
                    ax_i.scatter(out_i, vals[out_i], color='red', zorder=5, s=50, label="Out of Bounds (UCL/LCL/Spec)")
                    
                all_y_vals = [v for v in [np.max(vals), np.min(vals), ucl_i, lcl_i, usl, lsl] if v is not None]
                y_max = max(all_y_vals) if all_y_vals else 10
                y_min = min(all_y_vals) if all_y_vals else 0
                y_pad = (y_max - y_min) * 0.4 if (y_max - y_min) != 0 else 1
                ax_i.set_ylim(y_min - y_pad*0.4, y_max + y_pad*1.2)
                
                ax_i.set_title(f"Individual (I) Chart - {t4_feat} ({t4_thick}mm)", fontweight='bold')
                ax_i.set_ylabel("Value")
                
                ax_i.legend(bbox_to_anchor=(1.01, 1), loc='upper left', ncol=1, fontsize=8)
                add_chart_border(ax_i)
                ax_i.set_xticks([]) 
                
                # MR-Chart
                ax_mr.plot(range(1, len(vals)), mr, marker='o', color='#ff7f0e', linestyle='-', linewidth=1.5, markersize=5)
                ax_mr.axhline(mr_mean, color='green', linestyle='--', label=f'MR Mean: {mr_mean:.2f}')
                ax_mr.axhline(ucl_mr, color='red', linestyle='--', label=f'UCL: {ucl_mr:.2f}')
                
                out_mr = np.where(mr > ucl_mr)[0]
                if len(out_mr) > 0:
                    ax_mr.scatter(out_mr + 1, mr[out_mr], color='red', zorder=5, s=50)
                    
                ax_mr.set_title("Moving Range (MR) Chart", fontweight='bold')
                ax_mr.set_ylabel("Range")
                
                ax_mr.legend(bbox_to_anchor=(1.01, 1), loc='upper left', fontsize=8)
                add_chart_border(ax_mr)
                
                step = max(1, len(vals) // 15)
                ax_mr.set_xticks(range(0, len(vals), step))
                ax_mr.set_xticklabels(dates.iloc[::step], rotation=45, ha='right')
                
                fig_imr.tight_layout()
                st.pyplot(fig_imr)

    # ==========================================================
    # TASK 5: TAIL SCRAP & HYBRID TREND
    # ==========================================================
    with tab5:
        st.header("5. Tail Scrap & Length Rejection Analysis")
        
        COIL_ID_COL = '鋼捲號碼'

        if LEN_COL in df.columns and SCRAP_COL in df.columns:
            # Loại bỏ dòng tổng kết cả năm để biểu đồ không bị nhiễu
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
            st.subheader("Rejection Rate Trend (%)")
            
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
            st.subheader("Scrap Rate by Time Period")
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

            # --- 3. LEVEL-BY-LEVEL DRILL DOWN & CHARTS (SỬA LỖI 50%) ---
            st.markdown("---")
            st.subheader("Deep Analysis: Scrap Rate by Period / Thickness / Material")
            
            # Khởi tạo bảng chi tiết cơ sở (Dùng để hiển thị ở cuối)
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
                    # Gộp tổng Length và Scrap theo Thickness trước, sau đó mới chia tỷ lệ %
                    thick_agg = scrap_detail.groupby(['Time_Group', 'Actual_Thickness']).agg(
                        T_Len=('Total_Length', 'sum'),
                        T_Scrap=('Total_Scrap', 'sum')
                    )
                    thick_agg['Rate'] = np.where(thick_agg['T_Len'] > 0, (thick_agg['T_Scrap'] / thick_agg['T_Len']) * 100, 0)
                    pivot_t = thick_agg['Rate'].unstack()
                    
                    if not pivot_t.empty:
                        pivot_t.plot(kind='bar', ax=ax_t, colormap='tab10', edgecolor='white')
                        ax_t.legend(title="Thickness", bbox_to_anchor=(1.02, 1), loc='upper left')
                        for c in ax_t.containers:
                            labels = [f"{v.get_height():.1f}%" if v.get_height() > 0 else "" for v in c]
                            ax_t.bar_label(c, labels=labels, padding=3, fontsize=7, fontweight='bold', rotation=90)
                    
                    y_max = pivot_t.max().max() if not pivot_t.isna().all().all() else 10
                    ax_t.set_ylim(0, y_max * 1.4 + 2)
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
                    # Gộp tổng Length và Scrap theo Material trước, sau đó mới chia tỷ lệ %
                    mat_agg = scrap_detail.groupby(['Time_Group', 'HR_Material']).agg(
                        M_Len=('Total_Length', 'sum'),
                        M_Scrap=('Total_Scrap', 'sum')
                    )
                    mat_agg['Rate'] = np.where(mat_agg['M_Len'] > 0, (mat_agg['M_Scrap'] / mat_agg['M_Len']) * 100, 0)
                    pivot_m = mat_agg['Rate'].unstack()
                    
                    if not pivot_m.empty:
                        pivot_m.plot(kind='bar', ax=ax_m, colormap='tab10', edgecolor='white')
                        ax_m.legend(title="Material", bbox_to_anchor=(1.02, 1), loc='upper left')
                        for c in ax_m.containers:
                            labels = [f"{v.get_height():.1f}%" if v.get_height() > 0 else "" for v in c]
                            ax_m.bar_label(c, labels=labels, padding=3, fontsize=7, fontweight='bold', rotation=90)
                    
                    y_max = pivot_m.max().max() if not pivot_m.isna().all().all() else 10
                    ax_m.set_ylim(0, y_max * 1.4 + 2)
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
            
    # ==========================================================
# TASK 6: CUSTOMER END-USE ANALYSIS & MACHINE TRANSITION
# TASK 6: CUSTOMER END-USE ANALYSIS & MACHINE TRANSITION
# ==========================================================
with tab6:
    st.header("6. Customer End-Use Analysis & Machine Transition")
    st.info("Customer End-Use Root Cause Verification System: Evaluating material stability vs. machine impact.")

    possible_usage_cols = ['使用日期', '使用月份', 'Usage Date', 'Usage Month']
    USAGE_COL = next((c for c in possible_usage_cols if c in df.columns), None) 
    COIL_ID_COL = '鋼捲號碼'

    if USAGE_COL and COIL_ID_COL in df.columns and LEN_COL in df.columns and SCRAP_COL in df.columns: 
        df_t6 = df[df[LEN_COL] > 0].copy() 
        df_t6[COIL_ID_COL] = df_t6[COIL_ID_COL].astype(str).str.strip()
        df_t6 = df_t6[df_t6[COIL_ID_COL] != 'nan']

        # Tối ưu 1: Parse ngày tháng bằng vectorized thay vì custom function
        if not pd.api.types.is_datetime64_any_dtype(df_t6[USAGE_COL]):
            df_t6['Usage_Date'] = pd.to_datetime(df_t6[USAGE_COL].astype(str).str.strip(), dayfirst=True, errors='coerce')
        else:
            df_t6['Usage_Date'] = df_t6[USAGE_COL]

        df_t6 = df_t6.dropna(subset=['Usage_Date'])
        df_t6['Usage_Month'] = df_t6['Usage_Date'].dt.strftime('%Y-%m')

        # Tách riêng dữ liệu từ Q4/2025 trở đi theo yêu cầu
        df_t6 = df_t6[df_t6['Production_Date'] >= pd.Timestamp(2025, 10, 1)].copy()

        if df_t6.empty:
            st.warning("No usage data available for materials produced from Q4/2025 onwards.")
        else:
            # 2. Machine Transition Classification (Vectorized numpy where is faster than apply)
            cutoff_date = pd.to_datetime('2026-04-01')
            df_t6['Machine_Status'] = np.where(df_t6['Usage_Date'] >= cutoff_date, 'New Machine (>= Apr 2026)', 'Old Machine (< Apr 2026)')

            # 3 & 4. Monthly Scrap & Material Stability Analysis
            st.subheader("Monthly Scrap & Material Stability Analysis")
            st.caption("Verifying if the spike in scrap correlates with material instability.")

            macro_df = df_t6.groupby('Usage_Month').agg(
                Total_Length=(LEN_COL, 'sum'), 
                Total_Scrap=(SCRAP_COL, 'sum'),
                Avg_YS=('YS', 'mean'),
                Avg_TS=('TS', 'mean'),
                Avg_EL=('EL', 'mean'),
                Avg_YPE=('YPE', 'mean')
            ).reset_index().sort_values('Usage_Month')
            
            macro_df['Scrap_Rate (%)'] = np.where(macro_df['Total_Length'] > 0, (macro_df['Total_Scrap'] / macro_df['Total_Length']) * 100, 0).round(2)

            row1_cols = st.columns(2)
            row2_cols = st.columns(2)
            cols = row1_cols + row2_cols 
            
            features = [('Avg_YS', 'Theoretical YS', '#1f77b4'), 
                        ('Avg_TS', 'Theoretical TS', '#2ca02c'), 
                        ('Avg_EL', 'Theoretical EL', '#9467bd'),
                        ('Avg_YPE', 'Theoretical YPE', '#ff7f0e')]

            for idx, (col_name, label, color) in enumerate(features):
                with cols[idx]:
                    fig_exec, ax1 = plt.subplots(figsize=(6, 4))
                    color1 = '#d62728' 
                    ax1.set_ylabel('Scrap Rate (%)', color=color1, fontweight='bold', fontsize=9)
                    ax1.plot(macro_df['Usage_Month'], macro_df['Scrap_Rate (%)'], color=color1, marker='o', linewidth=2, label='Scrap Rate')
                    ax1.tick_params(axis='y', labelcolor=color1, labelsize=8)
                    
                    max_scrap = macro_df['Scrap_Rate (%)'].max()
                    ax1.set_ylim(-0.5, max_scrap * 1.35 + 1 if max_scrap > 0 else 5)

                    ax2 = ax1.twinx()
                    if col_name in macro_df.columns:
                        feat_valid = macro_df[col_name].dropna()
                        if not feat_valid.empty:
                            ax2.set_ylabel(label, color=color, fontweight='bold', fontsize=9)
                            ax2.plot(macro_df['Usage_Month'], macro_df[col_name], color=color, marker='s', linestyle='--', linewidth=2, alpha=0.8, label=label)
                            ax2.tick_params(axis='y', labelcolor=color, labelsize=8)
                            feat_min, feat_max = feat_valid.min(), feat_valid.max()
                            padding = (feat_max - feat_min) * 0.15 if feat_max > feat_min else feat_min * 0.1
                            ax2.set_ylim(feat_min - padding, feat_max + padding)

                    plt.title(f"Scrap vs {label}", fontweight='bold', fontsize=10)
                    ax1.set_xticklabels(macro_df['Usage_Month'], rotation=45, ha='right', fontsize=8)
                    
                    if 'add_chart_border' in globals():
                        add_chart_border(ax1) 
                        
                    fig_exec.tight_layout()
                    st.pyplot(fig_exec)
                    
                    # -----------------------------------------------------------------
                    # TẢI ẢNH CHẤT LƯỢNG CAO CHO 4 BIỂU ĐỒ ĐƯỜNG (MATPLOTLIB NATIVE)
                    # -----------------------------------------------------------------
                    buf = io.BytesIO()
                    fig_exec.savefig(buf, format="png", dpi=300, bbox_inches="tight")
                    buf.seek(0)
                    st.download_button(
                        label=f"📸 Download {label} Chart (High-Res)",
                        data=buf,
                        file_name=f"Scrap_vs_{col_name}.png",
                        mime="image/png",
                        key=f"dl_chart_{idx}" 
                    )
                    
                    plt.close(fig_exec) # Giải phóng bộ nhớ matplotlib

            st.markdown("<div style='text-align: center; color: #c00000; font-weight: bold; font-size: 14px; margin-bottom: 20px;'>Logic: If Scrap increases but YS/TS/EL/YPE is stable ➡️ Issue is with the Customer's Machine.</div>", unsafe_allow_html=True)
            st.markdown("---")
            
            # 5 & 6. Production vs Usage Quality Matrix
            st.subheader("Production vs Usage Quality Matrix (Main Chart)")
            st.info("Evaluates Material Stability, Inventory Traceability, Machine Impact, and Quality Transition.")

            available_grades = [g for g in base_grades if g in df_t6.columns]
            
            agg_dict = {'Total_Length': (LEN_COL, 'sum'), 'Total_Scrap': (SCRAP_COL, 'sum'), 'Total_Coils': ('Total_Qty', 'sum')}
            matrix_data = df_t6.groupby(['Usage_Month', 'Time_Group']).agg(**agg_dict).reset_index()
            grade_data = df_t6.groupby(['Usage_Month', 'Time_Group'])[available_grades].sum().reset_index()
            matrix_data = pd.merge(matrix_data, grade_data, on=['Usage_Month', 'Time_Group'], how='left')

            matrix_data['Scrap_Rate'] = np.where(matrix_data['Total_Length'] > 0, (matrix_data['Total_Scrap'] / matrix_data['Total_Length']) * 100, 0).round(2)
            
            usage_months = sorted(matrix_data['Usage_Month'].unique())
            prod_periods = sorted(matrix_data['Time_Group'].unique(), key=get_sort_key) if 'get_sort_key' in globals() else sorted(matrix_data['Time_Group'].unique())

            def get_color(rate):
                if pd.isna(rate): return "#ffffff" 
                if rate < 2.0: return "#e8f5e9" 
                if rate < 5.0: return "#fff3e0" 
                if rate < 10.0: return "#ffcdd2" 
                return "#e57373" 

            # Tối ưu 2: Dùng Dict tra cứu O(1) thay cho filter dataframe trong vòng lặp kép
            matrix_dict = matrix_data.set_index(['Time_Group', 'Usage_Month']).to_dict('index')

            html_parts = [
                "<style>",
                ".q-matrix { width: 100%; border-collapse: collapse; font-family: sans-serif; font-size: 12px; }",
                ".q-matrix th { background-color: #1a3a5c; color: white; padding: 10px; text-align: center; border: 1px solid #ddd; }",
                ".q-matrix td { border: 1px solid #ccc; padding: 8px; vertical-align: top; }",
                ".cell-title { font-size: 14px; font-weight: bold; margin-bottom: 5px; color: #111; text-align: center; border-bottom: 1px solid rgba(0,0,0,0.1); padding-bottom: 3px;}",
                ".grade-list { list-style-type: none; padding: 0; margin: 0; line-height: 1.4; }",
                ".grade-list li { display: flex; justify-content: space-between; }",
                ".grade-name { font-weight: bold; color: #444; }",
                "</style>",
                "<table class='q-matrix'><thead><tr><th>Production \ Usage</th>"
            ]
            html_parts.extend([f"<th>{m}</th>" for m in usage_months])
            html_parts.append("</tr></thead><tbody>")

            for prod in prod_periods:
                html_parts.append(f"<tr><th style='background-color: #f1f3f5; color: #333;'>{prod}</th>")
                for usage in usage_months:
                    row = matrix_dict.get((prod, usage))
                    if not row:
                        html_parts.append("<td style='background-color: #fafafa; color: #aaa; text-align:center; vertical-align:middle;'>No Data</td>")
                    else:
                        scrap_rate = row['Scrap_Rate']
                        bg_color = get_color(scrap_rate)
                        
                        grade_html = []
                        total_coils = row.get('Total_Coils', 0)
                        if total_coils > 0:
                            for g in available_grades:
                                g_pct = (row.get(g, 0) / total_coils * 100)
                                if g_pct > 0:
                                    color = "green" if "A" in g else "red"
                                    grade_html.append(f"<li><span class='grade-name'>{g}:</span> <span style='color:{color}'>{g_pct:.0f}%</span></li>")
                        
                        html_parts.append(f"<td style='background-color: {bg_color};'><div class='cell-title'>Scrap: {scrap_rate:.1f}%</div><ul class='grade-list'>{''.join(grade_html)}</ul></td>")
                html_parts.append("</tr>")
            html_parts.append("</tbody></table>")

            # -----------------------------------------------------------------
            # NÚT CHỤP ẢNH PNG CHO BẢNG HTML (html2canvas)
            # -----------------------------------------------------------------
            matrix_html_str = "".join(html_parts)
            
            capture_component = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
                <style>
                    body {{ font-family: sans-serif; margin: 0; padding: 0; }}
                    .btn-capture {{
                        background-color: #FF4B4B; color: white; border: none; padding: 8px 15px;
                        border-radius: 5px; cursor: pointer; font-weight: bold; font-size: 13px;
                        margin-bottom: 10px; transition: 0.3s;
                    }}
                    .btn-capture:hover {{ background-color: #ff3333; }}
                </style>
            </head>
            <body>
                <button class="btn-capture" onclick="takeSnapshot()">📸 Download High-Resolution Matrix Chart Image (PNG for Report Use)</button>
                <div id="matrix-container" style="background: white; padding: 10px; display: inline-block;">
                    {matrix_html_str}
                </div>
                <script>
                    function takeSnapshot() {{
                        const target = document.getElementById('matrix-container');
                        html2canvas(target, {{ scale: 3, backgroundColor: '#ffffff' }}).then(canvas => {{
                            let link = document.createElement('a');
                            link.download = 'Quality_Matrix.png';
                            link.href = canvas.toDataURL('image/png');
                            link.click();
                        }});
                    }}
                </script>
            </body>
            </html>
            """
            components.html(capture_component, height=max(250, len(prod_periods)*65 + 100), scrolling=True)
            # ==========================================================
                                           
            st.caption("Matrix Logic: Columns = Usage Month | Rows = Production Period | Background Color = Scrap Severity | Text = Quality Grade Distribution (%)")
            st.markdown("---")
            
            # 7 & 8. Standard Heatmap & Grade Distribution Analysis
            col_h1, col_h2 = st.columns(2)

            with col_h1:
                st.subheader("7. Scrap Heatmap")
                st.caption("Identifying abnormal batches and transition impacts.")
                pivot_scrap = matrix_data.pivot(index='Usage_Month', columns='Time_Group', values='Scrap_Rate')
                fig_h1, ax_h1 = plt.subplots(figsize=(8, max(4, len(pivot_scrap) * 0.6)))
                sns.heatmap(pivot_scrap, annot=True, fmt=".1f", cmap="Reds", linewidths=1, linecolor='white', ax=ax_h1, annot_kws={"size": 10, "weight": "bold"})
                ax_h1.set_ylabel("Usage Month", fontweight='bold')
                ax_h1.set_xlabel("Production Period", fontweight='bold')
                plt.xticks(rotation=45, ha='right')
                fig_h1.tight_layout()
                st.pyplot(fig_h1)
                
                # -----------------------------------------------------------------
                # TẢI ẢNH CHẤT LƯỢNG CAO CHO HEATMAP
                # -----------------------------------------------------------------
                buf_h1 = io.BytesIO()
                fig_h1.savefig(buf_h1, format="png", dpi=300, bbox_inches="tight")
                buf_h1.seek(0)
                st.download_button(
                    label="📸 Download Heatmap (High-Res)",
                    data=buf_h1,
                    file_name="Scrap_Heatmap.png",
                    mime="image/png",
                    key="dl_heatmap"
                )
                plt.close(fig_h1) 
            
            with col_h2:
                st.subheader("8. Grade Distribution Analysis")
                st.caption("Tracking customer grade structure before and after machine transition.")
                grade_agg_usage = df_t6.groupby('Usage_Month')[available_grades].sum()
                grade_pct_usage = grade_agg_usage.div(grade_agg_usage.sum(axis=1), axis=0) * 100
                grade_pct_usage = grade_pct_usage.fillna(0)
                
                fig_g2, ax_g2 = plt.subplots(figsize=(8, max(4, len(pivot_scrap) * 0.6))) 
                color_map = {'A-B+': '#2e7d32', 'A-B': '#1f77b4', 'A-B-': '#ffa726', 'B+': '#ef5350', 'B': '#c62828'}
                plot_colors = [color_map.get(g, '#888') for g in available_grades]
                
                grade_pct_usage.plot(kind='bar', stacked=True, ax=ax_g2, color=plot_colors, width=0.8, edgecolor='white')
                ax_g2.set_ylabel("Percentage (%)", fontweight='bold')
                ax_g2.set_xlabel("Usage Month", fontweight='bold')
                ax_g2.legend(title="Quality Grade", bbox_to_anchor=(1.02, 1), loc='upper left')
                ax_g2.set_ylim(0, 105)
                
                for c in ax_g2.containers:
                    labels = [f"{v.get_height():.0f}%" if v.get_height() > 5 else "" for v in c]
                    ax_g2.bar_label(c, labels=labels, label_type='center', color='white', fontweight='bold', fontsize=9)
                    
                plt.xticks(rotation=45, ha='right')
                if 'add_chart_border' in globals():
                    add_chart_border(ax_g2)
                fig_g2.tight_layout()
                st.pyplot(fig_g2)
                
                # -----------------------------------------------------------------
                # TẢI ẢNH CHẤT LƯỢNG CAO CHO BARCHART ĐIỂM CHẤT LƯỢNG
                # -----------------------------------------------------------------
                buf_g2 = io.BytesIO()
                fig_g2.savefig(buf_g2, format="png", dpi=300, bbox_inches="tight")
                buf_g2.seek(0)
                st.download_button(
                    label="📸 Download Grade Chart (High-Res)",
                    data=buf_g2,
                    file_name="Grade_Distribution.png",
                    mime="image/png",
                    key="dl_grade"
                )
                plt.close(fig_g2)

        st.markdown("---")
        
        # 9 & 10. Split Coil Verification & Root Cause Classification
        st.subheader("9 & 10. Split Coil Verification (Strongest Evidence)")
        st.info("Identifying identical coils processed on both Old and New machines to isolate machine impact from material quality.")

        # Tối ưu 3: Vectorized Split Coils logic (Loại bỏ hoàn toàn vòng lặp FOR)
        coil_status_scrap = df_t6.groupby([COIL_ID_COL, 'Machine_Status']).agg({LEN_COL: 'sum', SCRAP_COL: 'sum'}).reset_index()
        coil_status_scrap['Scrap_Rate'] = np.where(coil_status_scrap[LEN_COL] > 0, (coil_status_scrap[SCRAP_COL] / coil_status_scrap[LEN_COL]) * 100, 0)
        
        old_machine_col = 'Old Machine (< Apr 2026)'
        new_machine_col = 'New Machine (>= Apr 2026)'
        
        # Khởi tạo Pivot để gộp scrap 2 máy trên cùng 1 hàng. Dùng dropna() để giữ lại cuộn có dùng ở cả 2 máy.
        split_pivot = coil_status_scrap.pivot(index=COIL_ID_COL, columns='Machine_Status', values='Scrap_Rate').dropna()
        
        # Bỏ qua các cuộn có scrap = 0 ở cả 2 máy (như logic cũ)
        if old_machine_col in split_pivot.columns and new_machine_col in split_pivot.columns:
            split_pivot = split_pivot[(split_pivot[old_machine_col] > 0) | (split_pivot[new_machine_col] > 0)]
        
        if not split_pivot.empty and old_machine_col in split_pivot.columns and new_machine_col in split_pivot.columns:
            split_pivot['Delta (%)'] = split_pivot[old_machine_col] - split_pivot[new_machine_col]
            
            # Logic phân loại bằng Vector
            conds = [
                (split_pivot[old_machine_col] > 10) & (split_pivot[new_machine_col] < 5),
                (split_pivot[old_machine_col] > 10) & (split_pivot[new_machine_col] >= 5),
                (split_pivot[new_machine_col] > split_pivot[old_machine_col] + 5),
                (split_pivot[old_machine_col] > 0) & (split_pivot[new_machine_col] == 0)
            ]
            choices = [
                "🚨 Old Machine Issue (Proven)",
                "⚠️ Material / Process Issue",
                "⚙️ New Machine Tuning Issue",
                "✅ Improved on New Machine"
            ]
            split_pivot['Root Cause Classification'] = np.select(conds, choices, default="✅ Normal / Stable")
            
            # Nối thuộc tính YS/TS/EL/YPE
            props_cols = [c for c in ['YS', 'TS', 'EL', 'YPE'] if c in df_t6.columns]
            if props_cols:
                coil_props = df_t6[df_t6[COIL_ID_COL].isin(split_pivot.index)].groupby(COIL_ID_COL)[props_cols].mean()
                split_pivot = split_pivot.join(coil_props)
            
            # Đổi tên cột chuẩn bị hiển thị
            rename_dict = {
                old_machine_col: 'Scrap (Old Machine)', 
                new_machine_col: 'Scrap (New Machine)',
                'YS': 'Theoretical YS', 'TS': 'Theoretical TS', 
                'EL': 'Theoretical EL', 'YPE': 'Theoretical YPE'
            }
            split_report = split_pivot.rename(columns=rename_dict).reset_index()
            
            # Cấu trúc hiển thị bảng
            format_dict = {
                'Scrap (Old Machine)': '{:.2f}%', 'Scrap (New Machine)': '{:.2f}%', 'Delta (%)': '{:.2f}%',
                'Theoretical YS': '{:.1f}', 'Theoretical TS': '{:.1f}', 'Theoretical EL': '{:.1f}', 'Theoretical YPE': '{:.1f}'
            }
            st.dataframe(
                split_report.style.format(format_dict, na_rep="N/A").background_gradient(subset=['Scrap (Old Machine)', 'Scrap (New Machine)'], cmap='Reds'),
                use_container_width=True, hide_index=True
            )
        else:
            st.success("All multi-machine coils achieved perfect quality (0% scrap) or no split-coils found transitioning across the timeline.")
    else:
        st.error("Missing required columns for Task 6 Analysis ('Usage Date', 'Coil ID', 'Length', or 'Scrap').")
    # --- GLOBAL EXPORT ---
    st.sidebar.header("Export Reports")
    if st.sidebar.button("Generate Excel File"):
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            if not yield_summary.empty:
                yield_summary.to_excel(writer, sheet_name='Yield_Detailed', index=False)
            if 'grade_dist_display' in locals() and not grade_dist_display.empty:
                grade_dist_display.to_excel(writer, sheet_name='Grade_Distribution')
            if 'cap_summary_rows' in locals() and cap_summary_rows:
                pd.DataFrame(cap_summary_rows).to_excel(writer, sheet_name='Capability_Log', index=False)
            if 'plot_df_base' in locals() and not plot_df_base.empty:
                plot_df_base.to_excel(writer, sheet_name='Task4_IMR_Data', index=False)
            if 'trend_data' in locals() and not trend_data.empty:
                trend_data.drop(columns=['_sort']).to_excel(writer, sheet_name='Trend_Data', index=False)
            if 'scrap_by_period' in locals() and not scrap_by_period.empty:
                scrap_by_period.to_excel(writer, sheet_name='Scrap_By_Period', index=False)
            if 'scrap_detail' in locals() and not scrap_detail.empty:
                scrap_detail.to_excel(writer, sheet_name='Scrap_Detailed', index=False)
        
        st.sidebar.download_button(
            label="📥 Download Full Excel",
            data=output.getvalue(),
            file_name="Quality_Scrap_Deep_Analysis.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
