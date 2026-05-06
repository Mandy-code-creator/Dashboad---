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
    df_raw.columns = df_raw.columns.astype(str).str.strip()
    df_raw = df_raw.loc[:, ~df_raw.columns.duplicated()]

    # --- 1. GLOBAL PRE-PROCESSING ---
    df = df_raw.copy()
    
    df.rename(columns={
        'Thickness': 'Actual_Thickness', '厚度': 'Actual_Thickness',
        '烤漆降伏強度': 'YS', '烤漆抗拉強度': 'TS', '伸長率': 'EL'
    }, inplace=True)
    df = df.loc[:, ~df.columns.duplicated()]

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

    # Dates
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
    df_global_grades = df[df['Total_Qty'] > 0].copy()

    # Thickness Filtering
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
    else:
        df['Actual_Thickness'] = 0.0
        df = df.iloc[0:0]

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

    # --- TABS ---
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📁 1. Raw Data", "📋 2. Quality Yield", "📈 3. Capability (SPC)", 
        "📉 4. I-MR Tracking", "✂️ 5. Tail Scrap", "🎯 6. Customer End-Use"
    ])

    # ==========================================================
    # TASK 1: RAW DATA
    # ==========================================================
    with tab1:
        st.header("1. Raw Data Inspection")
        st.info("Showing full dataset without row limitations.")
        st.dataframe(df_raw, use_container_width=True)

    # ==========================================================
    # TASK 2: YIELD
    # ==========================================================
    with tab2:
        st.header("2. Executive Quality Yield Summary")
        yield_summary = df.groupby(['Time_Group', 'Actual_Thickness', 'HR_Material'])[['Total_Qty', 'Acceptable_Qty', 'Severe_Bad_Qty']].sum().reset_index()
        yield_summary = yield_summary[yield_summary['Total_Qty'] > 0]
        
        if not yield_summary.empty:
            yield_summary['Yield (%)'] = (yield_summary['Acceptable_Qty'] / yield_summary['Total_Qty'] * 100).round(2)
            yield_summary['Defect_Rate (%)'] = (yield_summary['Severe_Bad_Qty'] / yield_summary['Total_Qty'] * 100).round(2)
            yield_summary['_sort'] = yield_summary['Time_Group'].apply(get_sort_key)
            yield_summary = yield_summary.sort_values(by=['_sort', 'Actual_Thickness']).drop(columns=['_sort'])

            st.dataframe(
                yield_summary.style.background_gradient(subset=['Yield (%)'], cmap='Greens')
                .background_gradient(subset=['Defect_Rate (%)'], cmap='Reds')
                .format({'Actual_Thickness': '{:.2f}', 'Yield (%)': '{:.2f}%', 'Defect_Rate (%)': '{:.2f}%'}),
                use_container_width=True, hide_index=True
            )
            
        st.markdown("---")
        st.subheader("Charts by Period & Thickness")
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            st.markdown("**Yield (%) by Period & Thickness**")
            fig_y, ax_y = plt.subplots(figsize=(8, 4))
            if not yield_summary.empty:
                chart_df = yield_summary[~yield_summary['Time_Group'].astype(str).str.contains("2025 \(Full Year\)", regex=True)]
                pivot_y = chart_df.pivot_table(index='Time_Group', columns='Actual_Thickness', values='Yield (%)', aggfunc='mean')
                if not pivot_y.empty:
                    pivot_y.plot(kind='bar', ax=ax_y, color=solid_colors, edgecolor='white')
                    ax_y.legend(title="Thickness", bbox_to_anchor=(1.02, 1), loc='upper left')
                    for c in ax_y.containers:
                        ax_y.bar_label(c, labels=[f"{v.get_height():.1f}%" if v.get_height() > 0 else "" for v in c], padding=3, fontsize=7, fontweight='bold', rotation=90)
            ax_y.set_ylim(0, 130)
            add_chart_border(ax_y)
            plt.xticks(rotation=30, ha='right')
            st.pyplot(fig_y)
            
        with col_c2:
            st.markdown("**Defect Rate (%) by Period & Thickness**")
            fig_d, ax_d = plt.subplots(figsize=(8, 4))
            if not yield_summary.empty:
                chart_df = yield_summary[~yield_summary['Time_Group'].astype(str).str.contains("2025 \(Full Year\)", regex=True)]
                pivot_d = chart_df.pivot_table(index='Time_Group', columns='Actual_Thickness', values='Defect_Rate (%)', aggfunc='mean')
                if not pivot_d.empty:
                    pivot_d.plot(kind='bar', ax=ax_d, color=solid_colors, edgecolor='white')
                    ax_d.legend(title="Thickness", bbox_to_anchor=(1.02, 1), loc='upper left')
                    for c in ax_d.containers:
                        ax_d.bar_label(c, labels=[f"{v.get_height():.1f}%" if v.get_height() > 0 else "" for v in c], padding=3, fontsize=7, fontweight='bold', rotation=90)
                    y_max = pivot_d.max().max() if not pivot_d.isna().all().all() else 10
                    ax_d.set_ylim(0, y_max * 1.4 + 2)
            add_chart_border(ax_d)
            plt.xticks(rotation=30, ha='right')
            st.pyplot(fig_d)

    # ==========================================================
    # TASK 3: CAPABILITY SPC
    # ==========================================================
    with tab3:
        st.header("3. Distribution & Process Capability (SPC)")
        st.info("Visualizing mechanical property distribution based on valid quality levels A and B.")
        
        # Capability helper
        def calc_capability(values, feat, period_label, thickness):
            vals = np.array(values, dtype=float)
            vals = vals[~np.isnan(vals)]
            if len(vals) < 2: return None
            mu = np.mean(vals)
            std = np.std(vals, ddof=1)
            if std == 0: return None
            spec = GLOBAL_SPECS.get(thickness, {}).get(feat, {})
            lsl, usl, tgt = spec.get('min'), spec.get('max'), spec.get('target')
            
            res = {'mean': mu, 'std': std, 'n': len(vals), 'Cp': None, 'Cpk': None, 'Ca': None, 'LSL': lsl, 'USL': usl}
            if lsl is not None and usl is not None:
                res['Cp'] = (usl - lsl) / (6 * std)
                res['Cpk'] = min((usl - mu) / (3 * std), (mu - lsl) / (3 * std))
                mid = tgt if tgt is not None else (usl + lsl) / 2
                res['Ca'] = (mu - mid) / ((usl - lsl) / 2) * 100
            elif lsl is not None:
                res['Cp'] = res['Cpk'] = (mu - lsl) / (3 * std)
            elif usl is not None:
                res['Cp'] = res['Cpk'] = (usl - mu) / (3 * std)
            return res

        ordered_periods = sorted(df['Time_Group'].unique(), key=get_sort_key)
        thickness_list = sorted(df['Actual_Thickness'].dropna().unique())
        
        cap_summary_rows = []
        for _p in ordered_periods:
            if "2025 (Full Year)" in str(_p): continue 
            _dfp_valid = df[(df['Time_Group'] == _p) & (df['Valid_Qty'] > 0)]
            for _t in thickness_list:
                _dft = _dfp_valid[_dfp_valid['Actual_Thickness'] == _t]
                if _dft.empty: continue
                for _f in ['YS', 'TS', 'EL', 'YPE']:
                    if _f in _dft.columns:
                        cap = calc_capability(_dft[_f].dropna().values, _f, _p, _t)
                        if cap:
                            cap_summary_rows.append({
                                'Period': _p, 'Thickness': _t, 'Feature': _f, 'n': cap['n'],
                                'Mean': cap['mean'], 'Std': cap['std'], 'Cpk': cap.get('Cpk')
                            })
                            
        if cap_summary_rows:
            st.dataframe(pd.DataFrame(cap_summary_rows), use_container_width=True, hide_index=True)

    # ==========================================================
    # TASK 4: I-MR TRACKING
    # ==========================================================
    with tab4:
        st.header("4. Post-Control Tracking (I-MR Charts)")
        df_t4 = df[df['Production_Date'].dt.year >= 2026].copy()
        df_t4 = df_t4[df_t4['Valid_Qty'] > 0]
        
        if df_t4.empty:
            st.warning("No valid data available for 2026 onwards.")
        else:
            t4_thick = st.selectbox("Select Thickness Category:", ['Overall'] + sorted(df_t4['Actual_Thickness'].dropna().unique().tolist()))
            plot_df_base = df_t4 if t4_thick == 'Overall' else df_t4[df_t4['Actual_Thickness'] == t4_thick]
                
            for t4_feat in ['YS', 'TS', 'EL']:
                if t4_feat not in plot_df_base.columns: continue
                plot_df = plot_df_base.sort_values('Production_Date').dropna(subset=[t4_feat])
                if len(plot_df) < 2: continue
                    
                st.markdown("---")
                st.subheader(f"Feature: {t4_feat}")
                
                dates = plot_df['Production_Date'].dt.strftime('%Y-%m-%d')
                vals = plot_df[t4_feat].values
                mean_v = np.mean(vals)
                mr = np.abs(np.diff(vals))
                mr_mean = np.mean(mr)
                
                ucl_i = mean_v + 2.66 * mr_mean
                lcl_i = max(0, mean_v - 2.66 * mr_mean)
                ucl_mr = 3.267 * mr_mean
                
                fig_imr, (ax_i, ax_mr) = plt.subplots(2, 1, figsize=(12, 8), gridspec_kw={'height_ratios': [2, 1]})
                ax_i.plot(vals, marker='o', color='#1f77b4', linestyle='-', linewidth=1.5, markersize=5)
                ax_i.axhline(mean_v, color='green', linestyle='--', label=f'Mean: {mean_v:.2f}')
                ax_i.axhline(ucl_i, color='red', linestyle='--', label=f'UCL: {ucl_i:.2f}')
                ax_i.axhline(lcl_i, color='red', linestyle='--', label=f'LCL: {lcl_i:.2f}')
                
                spec = GLOBAL_SPECS.get(t4_thick, {}).get(t4_feat, {}) if t4_thick != 'Overall' else {}
                if spec.get('min') is not None: ax_i.axhline(spec.get('min'), color='darkred', lw=2, label=f'LSL: {spec.get("min")}')
                if spec.get('max') is not None: ax_i.axhline(spec.get('max'), color='darkred', lw=2, label=f'USL: {spec.get("max")}')
                
                ax_i.set_title(f"Individual (I) Chart - {t4_feat} ({t4_thick}mm)", fontweight='bold')
                ax_i.legend(bbox_to_anchor=(1.01, 1), loc='upper left', fontsize=8)
                add_chart_border(ax_i)
                
                ax_mr.plot(range(1, len(vals)), mr, marker='o', color='#ff7f0e', linestyle='-', linewidth=1.5, markersize=5)
                ax_mr.axhline(mr_mean, color='green', linestyle='--', label=f'MR Mean: {mr_mean:.2f}')
                ax_mr.axhline(ucl_mr, color='red', linestyle='--', label=f'UCL: {ucl_mr:.2f}')
                ax_mr.set_title("Moving Range (MR) Chart", fontweight='bold')
                ax_mr.legend(bbox_to_anchor=(1.01, 1), loc='upper left', fontsize=8)
                add_chart_border(ax_mr)
                
                st.pyplot(fig_imr)

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
            first_occurrence = df_t5.sort_values(['Time_Group', 'Production_Date']).drop_duplicates(subset=['Time_Group', COIL_ID_COL], keep='first')
            df_scrap_master = first_occurrence[['Time_Group', COIL_ID_COL, LEN_COL, 'Actual_Thickness', 'HR_Material']].merge(scrap_totals, on=[COIL_ID_COL, 'Time_Group'])

            st.subheader("Scrap Rate by Time Period")
            scrap_by_period = df_scrap_master.groupby('Time_Group').agg(Total_Length=(LEN_COL, 'sum'), Total_Scrap=(SCRAP_COL, 'sum')).reset_index()
            scrap_by_period['Scrap_Rate (%)'] = np.where(scrap_by_period['Total_Length'] > 0, (scrap_by_period['Total_Scrap'] / scrap_by_period['Total_Length'] * 100), 0).round(2)
            scrap_by_period['_sort'] = scrap_by_period['Time_Group'].apply(get_sort_key)
            scrap_by_period = scrap_by_period.sort_values('_sort').drop(columns=['_sort'])
            
            fig_p, ax_p = plt.subplots(figsize=(10, 4))
            if not scrap_by_period.empty:
                ax_p.bar(scrap_by_period['Time_Group'], scrap_by_period['Scrap_Rate (%)'], color='#e74c3c', edgecolor='white')
                ax_p.set_title("Tail Scrap Rate (%) by Time Period", fontweight='bold')
                for i, val in enumerate(scrap_by_period['Scrap_Rate (%)']):
                    ax_p.annotate(f"{val:.2f}%", xy=(i, val), xytext=(0, 5), textcoords="offset points", ha='center', va='bottom', fontweight='bold')
                add_chart_border(ax_p)
                plt.xticks(rotation=30, ha='right')
                st.pyplot(fig_p)

    # ==========================================================
    # TASK 6: CUSTOMER END-USE ANALYSIS
    # ==========================================================
    with tab6:
        st.header("6. Customer End-Use Analysis & Machine Transition")
        
        USAGE_COL = '使用日期' if '使用日期' in df_global.columns else '使用月份'
        COIL_ID_COL = '鋼捲號碼'
        
        if USAGE_COL in df_global.columns and COIL_ID_COL in df_global.columns:
            df_t6 = df_global.copy()
            
            # --- BỘ LỌC KHẮT KHE ---
            df_t6 = df_t6[df_t6[LEN_COL] > 0]
            df_t6[COIL_ID_COL] = df_t6[COIL_ID_COL].astype(str).str.strip()
            df_t6 = df_t6[df_t6[COIL_ID_COL] != 'nan']
            df_t6['Parsed_Date'] = pd.to_datetime(df_t6[USAGE_COL], errors='coerce')
            df_t6 = df_t6.dropna(subset=['Parsed_Date'])
            
            # Xử lý thời gian
            df_t6['Month_Num'] = df_t6['Parsed_Date'].dt.month
            df_t6['Display_Month'] = df_t6['Month_Num'].apply(lambda x: f"Month {x}")
            df_t6['Machine_Status'] = df_t6['Month_Num'].apply(lambda x: 'New Machine (>= April)' if x >= 4 else 'Old Machine (< April)')

            st.subheader("Macro View: Customer Scrap Rate by Usage Month")
            macro_df = df_t6.groupby('Display_Month').agg({LEN_COL: 'sum', SCRAP_COL: 'sum'}).reset_index()
            macro_df['Scrap_Rate (%)'] = np.where(macro_df[LEN_COL] > 0, (macro_df[SCRAP_COL] / macro_df[LEN_COL]) * 100, 0).round(2)
            if not macro_df.empty:
                st.line_chart(macro_df.set_index('Display_Month')[['Scrap_Rate (%)']], color="#d62728")
            
            st.markdown("---")
            st.subheader("Micro View: Split-Coil Analysis")
            
            coil_status_scrap = df_t6.groupby([COIL_ID_COL, 'Machine_Status']).agg({LEN_COL: 'sum', SCRAP_COL: 'sum'}).reset_index()
            coil_status_scrap['Scrap_Rate'] = np.where(coil_status_scrap[LEN_COL] > 0, (coil_status_scrap[SCRAP_COL] / coil_status_scrap[LEN_COL]) * 100, 0)
            
            coils_before = set(coil_status_scrap[coil_status_scrap['Machine_Status'] == 'Old Machine (< April)'][COIL_ID_COL])
            coils_after = set(coil_status_scrap[coil_status_scrap['Machine_Status'] == 'New Machine (>= April)'][COIL_ID_COL])
            split_coils = coils_before.intersection(coils_after)
            
            if split_coils:
                st.info("Tracking the exact same coils run on both machines.")
                split_data = []
                for coil in split_coils:
                    df_c = coil_status_scrap[coil_status_scrap[COIL_ID_COL] == coil]
                    b_val = df_c[df_c['Machine_Status'] == 'Old Machine (< April)']['Scrap_Rate'].values[0]
                    a_val = df_c[df_c['Machine_Status'] == 'New Machine (>= April)']['Scrap_Rate'].values[0]
                    
                    props = df_t6[df_t6[COIL_ID_COL] == coil][['YS', 'TS', 'EL']].mean().to_dict()
                    
                    if b_val > 10 and a_val < 5: root = "🚨 Old Machine Issue (Proven)"
                    elif b_val > 10 and a_val >= 5: root = "⚠️ Material / Process Issue"
                    elif a_val > b_val + 5: root = "⚙️ New Machine Tuning Issue"
                    else: root = "✅ Normal / Stable"
                        
                    split_data.append({
                        'Coil ID': coil, 'Scrap (Old Machine)': b_val, 'Scrap (New Machine)': a_val,
                        'Delta (%)': b_val - a_val, 'Theoretical YS': props.get('YS', np.nan),
                        'Theoretical TS': props.get('TS', np.nan), 'Theoretical EL': props.get('EL', np.nan), 'Root Cause': root
                    })
                    
                split_report = pd.DataFrame(split_data)
                st.dataframe(
                    split_report.style.format({
                        'Scrap (Old Machine)': '{:.2f}%', 'Scrap (New Machine)': '{:.2f}%', 'Delta (%)': '{:.2f}%',
                        'Theoretical YS': '{:.1f}', 'Theoretical TS': '{:.1f}', 'Theoretical EL': '{:.1f}'
                    }).background_gradient(subset=['Scrap (Old Machine)', 'Scrap (New Machine)'], cmap='Reds'),
                    use_container_width=True, hide_index=True
                )
                split_pivot = coil_status_scrap[coil_status_scrap[COIL_ID_COL].isin(split_coils)].pivot_table(index=COIL_ID_COL, columns='Machine_Status', values='Scrap_Rate', aggfunc='mean')
                st.bar_chart(split_pivot, color=["#1f77b4", "#ff7f0e"])
                
            else:
                st.warning("No split-coils found (No single coil was processed on both the Old and New machines).")
