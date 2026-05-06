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
    
    # --- DEDUPLICATE COLUMNS ---
    df_raw.columns = df_raw.columns.astype(str).str.strip()
    cols = pd.Series(df_raw.columns)
    for dup in cols[cols.duplicated()].unique():
        cols[cols[cols == dup].index.values.tolist()] = [f"{dup}.{i}" if i != 0 else dup for i in range(sum(cols == dup))]
    df_raw.columns = cols

    # --- 1. GLOBAL PRE-PROCESSING ---
    df = df_raw.copy()
    
    rename_dict = {
        'Thickness': 'Actual_Thickness', '厚度': 'Actual_Thickness',
        '烤漆降伏強度': 'YS', '烤漆抗拉強度': 'TS', '伸長率': 'EL'
    }
    df.rename(columns=rename_dict, inplace=True)
    
    if 'Actual_Thickness' in df.columns and isinstance(df.get('Actual_Thickness'), pd.DataFrame):
        df['Temp_Thick'] = df['Actual_Thickness'].bfill(axis=1).iloc[:, 0]
        df = df.drop(columns=['Actual_Thickness'])
        df.rename(columns={'Temp_Thick': 'Actual_Thickness'}, inplace=True)

    if '熱軋材質' in df.columns:
        df['HR_Material'] = df['熱軋材質'].astype(str).str.strip().replace(['nan', ''], 'Unknown')
    else:
        df['HR_Material'] = 'Unknown'

    LEN_COL = '實測長度'
    SCRAP_COL = '尾料剔退'
    if LEN_COL in df.columns:
        df[LEN_COL] = pd.to_numeric(df[LEN_COL], errors='coerce').fillna(0)
    if SCRAP_COL in df.columns:
        df[SCRAP_COL] = pd.to_numeric(df[SCRAP_COL], errors='coerce').fillna(0)
        
    for f in ['YS', 'TS', 'EL', 'YPE', 'HARDNESS']:
        if f in df.columns:
            df[f] = pd.to_numeric(df[f], errors='coerce')

    # Date Parsing
    date_key = '烤三生產日期' 
    if date_key in df.columns:
        def parse_production_dates(s):
            if pd.api.types.is_datetime64_any_dtype(s): return s
            s_str = s.astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
            res = pd.to_datetime(s_str, format='%Y%m%d', errors='coerce')
            res = res.fillna(pd.to_datetime(s_str, errors='coerce'))
            return res
        df['Production_Date'] = parse_production_dates(df[date_key])
        
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

    # Grades
    base_grades = ['A-B+', 'A-B', 'A-B-', 'B+', 'B']
    for g in base_grades:
        match_cols = [c for c in df.columns if str(c).strip() == g or str(c).strip().startswith(f"{g}.")]
        df[g] = df[match_cols].apply(pd.to_numeric, errors='coerce').fillna(0).sum(axis=1) if match_cols else 0

    df['Total_Qty'] = df[base_grades].sum(axis=1)
    df['Severe_Bad_Qty'] = df[['B+', 'B']].sum(axis=1)
    df['Acceptable_Qty'] = df['Total_Qty'] - df['Severe_Bad_Qty']
    df['Valid_Qty'] = df[['A-B+', 'A-B']].sum(axis=1)

    df_global = df.copy()

    if 'Actual_Thickness' in df.columns:
        df['Actual_Thickness'] = pd.to_numeric(df['Actual_Thickness'], errors='coerce')
        def map_thickness(val):
            v = round(float(val), 2) if pd.notnull(val) else 0
            if v in [0.47, 0.50]: return 0.5
            if v in [0.53, 0.54, 0.57, 0.58, 0.60]: return 0.6
            if v in [0.63, 0.75, 0.76, 0.77, 0.80]: return 0.8
            return None 
        df['Standard_Thickness'] = df['Actual_Thickness'].apply(map_thickness)
        df = df.dropna(subset=['Standard_Thickness'])
        df['Actual_Thickness'] = df['Standard_Thickness']
        df = df.drop(columns=['Standard_Thickness'])
    
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

    # ==========================================================
    # GLOBAL SPC CAPABILITY FUNCTIONS
    # ==========================================================
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

    # --- TABS ---
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📁 1. Raw Data", "📋 2. Quality Yield", "📈 3. Capability (SPC)", 
        "📉 4. I-MR Tracking", "✂️ 5. Tail Scrap", "🎯 6. Customer End-Use"
    ])

    with tab1:
        st.header("1. Raw Data Inspection")
        st.dataframe(df_raw, use_container_width=True)

    with tab2:
        st.header("2. Executive Quality Yield Summary")
        yield_summary = df.groupby(['Time_Group', 'Actual_Thickness', 'HR_Material'])[['Total_Qty', 'Acceptable_Qty', 'Severe_Bad_Qty']].sum().reset_index()
        yield_summary = yield_summary[yield_summary['Total_Qty'] > 0]
        if not yield_summary.empty:
            yield_summary['Yield (%)'] = (yield_summary['Acceptable_Qty'] / yield_summary['Total_Qty'] * 100).round(2)
            yield_summary['Defect_Rate (%)'] = (yield_summary['Severe_Bad_Qty'] / yield_summary['Total_Qty'] * 100).round(2)
            yield_summary['_sort'] = yield_summary['Time_Group'].apply(get_sort_key)
            yield_summary = yield_summary.sort_values(by=['_sort', 'Actual_Thickness']).drop(columns=['_sort'])
            st.dataframe(yield_summary.style.background_gradient(subset=['Yield (%)'], cmap='Greens').background_gradient(subset=['Defect_Rate (%)'], cmap='Reds'), use_container_width=True, hide_index=True)

    with tab3:
        st.header("3. Distribution & Process Capability (SPC)")
        ordered_periods = sorted(df['Time_Group'].unique(), key=get_sort_key)
        cap_summary = []
        for p in ordered_periods:
            if "2025 (Full Year)" in str(p): continue
            df_p = df[(df['Time_Group'] == p) & (df['Valid_Qty'] > 0)]
            for t in sorted(df['Actual_Thickness'].unique()):
                df_t = df_p[df_p['Actual_Thickness'] == t]
                if df_t.empty: continue
                for f in ['YS', 'TS', 'EL', 'YPE']:
                    if f in df_t.columns:
                        c = calc_capability(df_t[f].values, f, p, t)
                        if c and c['n'] >= 2: 
                            cap_summary.append({
                                'Period': p, 'Thick': t, 'Feature': f, 'n': c['n'], 
                                'Mean': round(c['mean'],2), 'Std': round(c['std'],3), 
                                'Cpk': round(c['Cpk'],3) if c.get('Cpk') is not None else None
                            })
        if cap_summary: 
            st.dataframe(pd.DataFrame(cap_summary), use_container_width=True)

    # ==========================================================
    # TASK 4: I-MR TRACKING (SỬA TRỤC X THEO THÁNG)
    # ==========================================================
    with tab4:
        st.header("4. Post-Control Tracking (I-MR Charts)")
        
        # Bắt đầu từ Quý 4 năm 2025
        df_t4 = df[df['Production_Date'] >= pd.Timestamp(2025, 10, 1)].copy()
        df_t4 = df_t4[df_t4['Valid_Qty'] > 0]
        
        if df_t4.empty:
            st.warning("No valid data available (Grades A/B) from Q4/2025 onwards.")
        else:
            t4_thick = st.selectbox("Select Thickness Category:", ['Overall'] + sorted(df_t4['Actual_Thickness'].dropna().unique().tolist()))
            plot_df_base = df_t4 if t4_thick == 'Overall' else df_t4[df_t4['Actual_Thickness'] == t4_thick]
                
            for t4_feat in ['YS', 'TS', 'EL', 'YPE']:
                if t4_feat not in plot_df_base.columns: continue
                
                plot_df = plot_df_base.sort_values('Production_Date').dropna(subset=[t4_feat]).reset_index(drop=True)
                if len(plot_df) < 2: continue
                    
                st.markdown("---")
                st.markdown(f"### 🎯 Feature: {t4_feat}")
                
                vals = plot_df[t4_feat].values
                
                # 🚀 HIỂN THỊ NĂM-THÁNG TRÊN TRỤC X (YYYY-MM)
                dates = plot_df['Production_Date'].dt.strftime('%Y-%m')
                
                cap_data = calc_capability(vals, t4_feat, 'Q4 2025 Onwards', t4_thick)
                render_capability_badge(cap_data, t4_feat, 'Q4 2025 Onwards', t4_thick)
                
                mean_v = np.mean(vals); mr = np.abs(np.diff(vals)); mr_mean = np.mean(mr)
                ucl_i = mean_v + 2.66 * mr_mean; lcl_i = max(0, mean_v - 2.66 * mr_mean)
                
                fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 9), gridspec_kw={'height_ratios': [2, 1]})
                
                ax1.plot(vals, marker='o', color='#1f77b4', alpha=0.6, label='Actual Data')
                
                bbox_props = dict(boxstyle="round,pad=0.2", facecolor="white", alpha=0.8, edgecolor="none")
                x_max = len(vals)
                ax1.set_xlim(-1, x_max + 1) 
                
                ax1.axhline(mean_v, color='green', ls='--')
                ax1.text(x_max, mean_v, f' Mean: {mean_v:.1f}', color='green', va='center', fontweight='bold', fontsize=9, bbox=bbox_props)
                
                ax1.axhline(ucl_i, color='red', ls='--')
                ax1.text(x_max, ucl_i, f' UCL: {ucl_i:.1f}', color='red', va='center', fontweight='bold', fontsize=9, bbox=bbox_props)
                
                ax1.axhline(lcl_i, color='red', ls='--')
                ax1.text(x_max, lcl_i, f' LCL: {lcl_i:.1f}', color='red', va='center', fontweight='bold', fontsize=9, bbox=bbox_props)
                
                out_control = np.where((vals > ucl_i) | (vals < lcl_i))[0]
                if len(out_control) > 0:
                    ax1.scatter(out_control, vals[out_control], color='red', s=90, zorder=5, label='Out of Control (SPC)')
                
                spec = GLOBAL_SPECS.get(t4_thick, {}).get(t4_feat, {})
                usl, lsl = spec.get('max'), spec.get('min')
                if usl is not None: 
                    ax1.axhline(usl, color='darkred', lw=2)
                    ax1.text(-0.8, usl, f'USL: {usl} ', color='darkred', va='center', ha='left', fontweight='bold', fontsize=9, bbox=bbox_props)
                    out_usl = np.where(vals > usl)[0]
                    ax1.scatter(out_usl, vals[out_usl], marker='x', color='darkred', s=120, lw=2, zorder=6, label='Out of Spec (USL)')
                if lsl is not None: 
                    ax1.axhline(lsl, color='darkred', lw=2)
                    ax1.text(-0.8, lsl, f'LSL: {lsl} ', color='darkred', va='center', ha='left', fontweight='bold', fontsize=9, bbox=bbox_props)
                    out_lsl = np.where(vals < lsl)[0]
                    ax1.scatter(out_lsl, vals[out_lsl], marker='x', color='darkred', s=120, lw=2, zorder=6, label='Out of Spec (LSL)')

                ax1.set_title(f"Individual (I) Chart - {t4_feat}", fontsize=11, fontweight='bold')
                ax1.legend(bbox_to_anchor=(1.01, 1), loc='upper left', fontsize=8)
                
                step = max(1, len(vals) // 25)
                ax1.set_xticks(range(0, len(vals), step))
                ax1.set_xticklabels(dates.iloc[::step], rotation=45, ha='right', fontsize=9)
                add_chart_border(ax1)
                
                # MR-Chart
                ax2.plot(range(1, len(vals)), mr, marker='o', color='#ff7f0e', alpha=0.6)
                ax2.axhline(mr_mean, color='green', ls='--')
                ax2.text(len(mr), mr_mean, f' Mean MR: {mr_mean:.1f}', color='green', va='center', fontweight='bold', fontsize=9, bbox=bbox_props)
                
                ucl_mr = 3.267 * mr_mean
                ax2.axhline(ucl_mr, color='red', ls='--')
                ax2.text(len(mr), ucl_mr, f' UCL MR: {ucl_mr:.1f}', color='red', va='center', fontweight='bold', fontsize=9, bbox=bbox_props)
                
                ax2.set_title("Moving Range (MR) Chart", fontsize=10, fontweight='bold')
                ax2.set_xlim(-1, x_max + 1)
                ax2.set_xticks(range(0, len(vals)-1, step))
                ax2.set_xticklabels(dates.iloc[1::step], rotation=45, ha='right', fontsize=9)
                add_chart_border(ax2)
                
                fig.tight_layout()
                st.pyplot(fig)

    # ==========================================================
    # TASK 5: TAIL SCRAP & HYBRID TREND
    # ==========================================================
    with tab5:
        st.header("5. Tail Scrap & Length Rejection Analysis")
        COIL_ID_COL = '鋼捲號碼'

        if LEN_COL in df.columns and SCRAP_COL in df.columns:
            df_t5 = df[~df['Time_Group'].astype(str).str.contains("2025 \(Full Year\)", regex=True)].copy()
            df_t5[COIL_ID_COL] = df_t5[COIL_ID_COL].astype(str).str.strip().replace(['nan', 'None', '', 'NaN'], np.nan)
            
            missing_mask = df_t5[COIL_ID_COL].isna()
            if missing_mask.any(): df_t5.loc[missing_mask, COIL_ID_COL] = [f"UNKNOWN_{i}" for i in df_t5[missing_mask].index]

            scrap_totals = df_t5.groupby(['Time_Group', COIL_ID_COL])[SCRAP_COL].sum().reset_index()
            first_occ = df_t5.sort_values(['Time_Group', 'Production_Date']).drop_duplicates(subset=['Time_Group', COIL_ID_COL], keep='first')
            df_m = first_occ[['Time_Group', COIL_ID_COL, LEN_COL, 'Actual_Thickness', 'HR_Material']].merge(scrap_totals, on=[COIL_ID_COL, 'Time_Group'])

            # --- 1. HYBRID TREND LINE ---
            st.subheader("Rejection Rate Trend (%)")
            trend_data = df_m.groupby('Time_Group').agg(Input_Length=(LEN_COL, 'sum'), Total_Scrap=(SCRAP_COL, 'sum')).reset_index()
            trend_data = trend_data[trend_data['Time_Group'] != 'Unknown']
            trend_data['Rejection_Rate (%)'] = np.where(trend_data['Input_Length'] > 0, (trend_data['Total_Scrap'] / trend_data['Input_Length'] * 100), 0).round(2)
            trend_data['_sort'] = trend_data['Time_Group'].apply(get_sort_key)
            trend_data = trend_data.sort_values('_sort').drop(columns=['_sort'])

            fig_trend, ax_trend = plt.subplots(figsize=(14, 5))
            if not trend_data.empty:
                ax_trend.plot(trend_data['Time_Group'], trend_data['Rejection_Rate (%)'], marker='o', markersize=8, markeredgecolor='white', markeredgewidth=1.5, linestyle='-', color='#1f77b4', linewidth=3, label='Rejection Rate %')
                ax_trend.fill_between(trend_data['Time_Group'], trend_data['Rejection_Rate (%)'], color='#1f77b4', alpha=0.1)
                ax_trend.set_ylim(0, trend_data['Rejection_Rate (%)'].max() * 1.35 + 0.5)
                ax_trend.set_title("Rejection Rate Trend", fontweight='bold', fontsize=15, pad=15, color='#333')
                ax_trend.set_ylabel("Rejection Rate (%)", fontweight='bold', color='#555')
                ax_trend.grid(axis='y', linestyle='--', alpha=0.5)
                
                for i, val in enumerate(trend_data['Rejection_Rate (%)']):
                    ax_trend.annotate(f'{val:.2f}%', xy=(i, val), xytext=(0, 8), textcoords="offset points", ha='center', va='bottom', fontsize=10, fontweight='bold', color='#222', bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="none", alpha=0.8))
                
                add_chart_border(ax_trend)
                plt.xticks(rotation=40, ha='right', fontsize=10)
                fig_trend.tight_layout()
            st.pyplot(fig_trend)

            # --- 2. PERIOD SUMMARY CHART ---
            st.markdown("---")
            st.subheader("Scrap Rate by Time Period")
            scrap_p = df_m.groupby('Time_Group').agg({LEN_COL: 'sum', SCRAP_COL: 'sum'}).reset_index()
            scrap_p['Scrap_Rate (%)'] = np.where(scrap_p[LEN_COL] > 0, (scrap_p[SCRAP_COL] / scrap_p[LEN_COL] * 100), 0).round(2)
            scrap_p['_sort'] = scrap_p['Time_Group'].apply(get_sort_key)
            scrap_p = scrap_p.sort_values('_sort').drop(columns=['_sort'])
            
            fig_p, ax_p = plt.subplots(figsize=(10, 4))
            if not scrap_p.empty:
                ax_p.bar(scrap_p['Time_Group'], scrap_p['Scrap_Rate (%)'], color='#e74c3c', edgecolor='white')
                ax_p.set_title("Tail Scrap Rate (%) by Time Period", fontweight='bold')
                ax_p.set_ylabel("Scrap Rate (%)")
                ax_p.set_ylim(0, scrap_p['Scrap_Rate (%)'].max() * 1.2 + 0.1)
                for i, val in enumerate(scrap_p['Scrap_Rate (%)']):
                    ax_p.annotate(f"{val:.2f}%", xy=(i, val), xytext=(0, 5), textcoords="offset points", ha='center', va='bottom', fontweight='bold')
                add_chart_border(ax_p)
                plt.xticks(rotation=30, ha='right')
                fig_p.tight_layout()
            st.pyplot(fig_p)
            
            st.dataframe(scrap_p.style.background_gradient(subset=['Scrap_Rate (%)'], cmap='Reds').format({LEN_COL: '{:,.2f}', SCRAP_COL: '{:,.2f}', 'Scrap_Rate (%)': '{:.2f}%'}), use_container_width=True, hide_index=True)

            # --- 3. LEVEL-BY-LEVEL DRILL DOWN ---
            st.markdown("---")
            st.subheader("Deep Analysis: Scrap Rate by Period / Thickness / Material")
            scrap_detail = df_m.groupby(['Time_Group', 'Actual_Thickness', 'HR_Material']).agg({LEN_COL: 'sum', SCRAP_COL: 'sum'}).reset_index()
            scrap_detail = scrap_detail[scrap_detail[LEN_COL] > 0]
            scrap_detail['Scrap_Rate (%)'] = (scrap_detail[SCRAP_COL] / scrap_detail[LEN_COL] * 100).round(2)
            
            col_t, col_m_chart = st.columns(2)
            with col_t:
                st.markdown("**Scrap Rate by Period & Thickness**")
                fig_t, ax_t = plt.subplots(figsize=(8, 4))
                if not scrap_detail.empty:
                    pivot_t = scrap_detail.pivot_table(index='Time_Group', columns='Actual_Thickness', values='Scrap_Rate (%)', aggfunc='mean')
                    if not pivot_t.empty:
                        pivot_t.plot(kind='bar', ax=ax_t, color=solid_colors, edgecolor='white')
                        ax_t.legend(title="Thickness", bbox_to_anchor=(1.02, 1), loc='upper left')
                        for c in ax_t.containers:
                            ax_t.bar_label(c, labels=[f"{v.get_height():.1f}%" if v.get_height() > 0 else "" for v in c], padding=3, fontsize=7, fontweight='bold', rotation=90)
                    ax_t.set_ylim(0, pivot_t.max().max() * 1.4 + 2 if not pivot_t.isna().all().all() else 10)
                add_chart_border(ax_t)
                plt.xticks(rotation=30, ha='right')
                fig_t.tight_layout()
                st.pyplot(fig_t)

            with col_m_chart:
                st.markdown("**Scrap Rate by Period & Material**")
                fig_m_ch, ax_m_ch = plt.subplots(figsize=(8, 4))
                if not scrap_detail.empty:
                    pivot_m = scrap_detail.pivot_table(index='Time_Group', columns='HR_Material', values='Scrap_Rate (%)', aggfunc='mean')
                    if not pivot_m.empty:
                        pivot_m.plot(kind='bar', ax=ax_m_ch, colormap='tab10', edgecolor='white')
                        ax_m_ch.legend(title="Material", bbox_to_anchor=(1.02, 1), loc='upper left')
                        for c in ax_m_ch.containers:
                            ax_m_ch.bar_label(c, labels=[f"{v.get_height():.1f}%" if v.get_height() > 0 else "" for v in c], padding=3, fontsize=7, fontweight='bold', rotation=90)
                    ax_m_ch.set_ylim(0, pivot_m.max().max() * 1.4 + 2 if not pivot_m.isna().all().all() else 10)
                add_chart_border(ax_m_ch)
                plt.xticks(rotation=30, ha='right')
                fig_m_ch.tight_layout()
                st.pyplot(fig_m_ch)
                
            scrap_detail['_sort'] = scrap_detail['Time_Group'].apply(get_sort_key)
            scrap_detail = scrap_detail.sort_values(by=['_sort', 'Actual_Thickness']).drop(columns=['_sort'])
            st.dataframe(scrap_detail.style.background_gradient(subset=['Scrap_Rate (%)'], cmap='Oranges').format({'Actual_Thickness': '{:.2f}', LEN_COL: '{:,.2f}', SCRAP_COL: '{:,.2f}', 'Scrap_Rate (%)': '{:.2f}%'}), use_container_width=True, hide_index=True)

    # ==========================================================
    # TASK 6: CUSTOMER END-USE ANALYSIS
    # ==========================================================
    with tab6:
        st.header("6. Customer End-Use Analysis & Machine Transition")
        
        possible_usage_cols = ['使用日期', '使用月份', 'Usage Date', 'Usage Month']
        USAGE_COL = next((c for c in possible_usage_cols if c in df_global.columns), None)
        COIL_ID_COL = '鋼捲號碼'
        
        if USAGE_COL and COIL_ID_COL in df_global.columns and LEN_COL in df_global.columns and SCRAP_COL in df_global.columns:
            df_t6 = df_global[df_global[LEN_COL] > 0].copy()
            df_t6[COIL_ID_COL] = df_t6[COIL_ID_COL].astype(str).str.strip()
            df_t6 = df_t6[df_t6[COIL_ID_COL] != 'nan']
            
            def safe_parse_usage_date(s):
                if pd.api.types.is_datetime64_any_dtype(s): return s
                s_str = s.astype(str).str.strip()
                res = pd.to_datetime(s_str, dayfirst=True, errors='coerce')
                return res
                
            df_t6['Parsed_Date'] = safe_parse_usage_date(df_t6[USAGE_COL])
            df_t6 = df_t6.dropna(subset=['Parsed_Date'])
            
            cutoff_date = pd.to_datetime('2026-04-01')
            df_t6['Display_Month'] = df_t6['Parsed_Date'].dt.strftime('%Y-%m')
            df_t6['Machine_Status'] = df_t6['Parsed_Date'].apply(lambda x: 'New Machine (>= Apr 2026)' if x >= cutoff_date else 'Old Machine (< Apr 2026)')

            st.subheader("Macro View: Customer Scrap Rate by Usage Month")
            macro_df = df_t6.groupby('Display_Month').agg({LEN_COL: 'sum', SCRAP_COL: 'sum'}).reset_index()
            macro_df = macro_df.sort_values('Display_Month')
            macro_df['Scrap_Rate (%)'] = np.where(macro_df[LEN_COL] > 0, (macro_df[SCRAP_COL] / macro_df[LEN_COL]) * 100, 0).round(2)
            
            if not macro_df.empty:
                st.line_chart(macro_df.set_index('Display_Month')[['Scrap_Rate (%)']], color="#d62728")
            
            st.markdown("---")
            st.subheader("Micro View: Split-Coil Analysis")
            
            coil_status_scrap = df_t6.groupby([COIL_ID_COL, 'Machine_Status']).agg({LEN_COL: 'sum', SCRAP_COL: 'sum'}).reset_index()
            coil_status_scrap['Scrap_Rate'] = np.where(coil_status_scrap[LEN_COL] > 0, (coil_status_scrap[SCRAP_COL] / coil_status_scrap[LEN_COL]) * 100, 0)
            
            coils_before = set(coil_status_scrap[coil_status_scrap['Machine_Status'] == 'Old Machine (< Apr 2026)'][COIL_ID_COL])
            coils_after = set(coil_status_scrap[coil_status_scrap['Machine_Status'] == 'New Machine (>= Apr 2026)'][COIL_ID_COL])
            split_coils = coils_before.intersection(coils_after)
            
            if split_coils:
                st.info("Tracking coils run on both machines (Excluding perfect 0% - 0% records).")
                split_data = []
                for coil in split_coils:
                    df_c = coil_status_scrap[coil_status_scrap[COIL_ID_COL] == coil]
                    b_val = df_c[df_c['Machine_Status'] == 'Old Machine (< Apr 2026)']['Scrap_Rate'].values[0]
                    a_val = df_c[df_c['Machine_Status'] == 'New Machine (>= Apr 2026)']['Scrap_Rate'].values[0]
                    
                    if b_val == 0 and a_val == 0:
                        continue
                    
                    props = df_t6[df_t6[COIL_ID_COL] == coil][['YS', 'TS', 'EL']].mean().to_dict()
                    
                    if b_val > 10 and a_val < 5: root = "🚨 Old Machine Issue (Proven)"
                    elif b_val > 10 and a_val >= 5: root = "⚠️ Material / Process Issue"
                    elif a_val > b_val + 5: root = "⚙️ New Machine Tuning Issue"
                    elif b_val > 0 and a_val == 0: root = "✅ Improved on New Machine"
                    else: root = "✅ Normal / Stable"
                        
                    split_data.append({
                        'Coil ID': coil, 'Scrap (Old Machine)': b_val, 'Scrap (New Machine)': a_val,
                        'Delta (%)': b_val - a_val, 'Theoretical YS': props.get('YS', np.nan),
                        'Theoretical TS': props.get('TS', np.nan), 'Theoretical EL': props.get('EL', np.nan), 'Root Cause': root
                    })
                    
                if len(split_data) > 0:
                    split_report = pd.DataFrame(split_data)
                    st.dataframe(
                        split_report.style.format({
                            'Scrap (Old Machine)': '{:.2f}%', 'Scrap (New Machine)': '{:.2f}%', 'Delta (%)': '{:.2f}%',
                            'Theoretical YS': '{:.1f}', 'Theoretical TS': '{:.1f}', 'Theoretical EL': '{:.1f}'
                        }).background_gradient(subset=['Scrap (Old Machine)', 'Scrap (New Machine)'], cmap='Reds'),
                        use_container_width=True, hide_index=True
                    )
                else:
                    st.success("All coils processed across both machines achieved perfect quality (0% scrap). No defective coils to display.")
            else:
                st.warning("No split-coils found across the April 2026 transition line.")
        else:
            st.warning("Required columns for usage analysis not found.")
