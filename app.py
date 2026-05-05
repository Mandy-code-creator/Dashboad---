import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import io
import seaborn as sns

# --- PAGE CONFIG ---
st.set_page_config(page_title="Quality & Scrap Dashboard", layout="wide")
st.title("📊 Production Quality Yield & Tail Scrap Analysis")
st.markdown("---")

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
            # Group 0.5mm
            if v in [0.47, 0.50]: 
                return 0.5
            # Group 0.6mm
            if v in [0.53, 0.54, 0.57, 0.58, 0.60]: 
                return 0.6
            # Group 0.8mm
            if v in [0.63, 0.75, 0.76, 0.77, 0.80]: 
                return 0.8
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
            
            if y == 2024: 
                return "2024 (Full Year)"
            if y == 2025:
                if d < q3_s: return "2025 H1 (Until 06/28)"
                if q3_s <= d <= q3_e: return "2025 Q3 (06/29 - 09/30)"
                return d.strftime('%Y-%m')
            if y >= 2026:
                return d.strftime('%Y-%m')
            return "Other"
            
        df['Time_Group'] = df['Production_Date'].apply(categorize_period)
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

    # Pre-clean Length and Scrap Columns
    LEN_COL = '實測長度'
    SCRAP_COL = '尾料剔退'
    if LEN_COL in df.columns:
        df[LEN_COL] = pd.to_numeric(df[LEN_COL], errors='coerce').fillna(0)
    if SCRAP_COL in df.columns:
        df[SCRAP_COL] = pd.to_numeric(df[SCRAP_COL], errors='coerce').fillna(0)

    # FILTER: Prevent dropping rows that have 0 length but contain Scrap data
    df = df[(df['Total_Qty'] > 0) | (df.get(LEN_COL, 0) > 0) | (df.get(SCRAP_COL, 0) > 0)]

    # Global Style Setup for nicer Matplotlib charts
    sns.set_theme(style="whitegrid")

    # --- TABS ---
    tab0, tab1, tab5 = st.tabs(["📁 Task 0: Raw Data", "📋 Task 1: Quality Yield", "✂️ Task 5: Tail Scrap"])

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
        st.dataframe(df, use_container_width=True)

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
        st.subheader("2. Grade Distribution by Time Period (%)")
        grade_dist = df.groupby('Time_Group')[base_grades].sum()
        grade_dist['Total'] = grade_dist.sum(axis=1)
        
        grade_dist_pct = pd.DataFrame()
        for g in base_grades:
            grade_dist_pct[f'{g} (%)'] = (grade_dist[g] / grade_dist['Total'].replace(0, np.nan) * 100).fillna(0).round(2)
            
        st.dataframe(
            grade_dist_pct.style.format("{:.2f}%"), 
            use_container_width=True
        )

        col_c1, col_c2 = st.columns(2)
        with col_c1:
            st.markdown("**Yield (%) by Period & Thickness**")
            fig_y, ax_y = plt.subplots(figsize=(8, 4))
            if not yield_summary.empty:
                pivot_y = yield_summary.pivot_table(index='Time_Group', columns='Actual_Thickness', values='Yield (%)', aggfunc='mean')
                if not pivot_y.empty:
                    pivot_y.plot(kind='bar', ax=ax_y, colormap='Greens', edgecolor='white')
            ax_y.set_ylim(0, 110)
            ax_y.set_ylabel("Yield (%)")
            ax_y.spines['top'].set_visible(False)
            ax_y.spines['right'].set_visible(False)
            fig_y.tight_layout()
            st.pyplot(fig_y)
            
        with col_c2:
            st.markdown("**Defect Rate (%) by Period & Thickness**")
            fig_d, ax_d = plt.subplots(figsize=(8, 4))
            if not yield_summary.empty:
                pivot_d = yield_summary.pivot_table(index='Time_Group', columns='Actual_Thickness', values='Defect_Rate (%)', aggfunc='mean')
                if not pivot_d.empty:
                    pivot_d.plot(kind='bar', ax=ax_d, colormap='Reds', edgecolor='white')
            ax_d.set_ylabel("Defect Rate (%)")
            ax_d.spines['top'].set_visible(False)
            ax_d.spines['right'].set_visible(False)
            fig_d.tight_layout()
            st.pyplot(fig_d)

    # ==========================================================
    # TASK 5: TAIL SCRAP & HYBRID TREND
    # ==========================================================
    with tab5:
        st.header("Tail Scrap & Length Rejection Analysis")
        
        COIL_ID_COL = '鋼捲號碼'

        if LEN_COL in df.columns and SCRAP_COL in df.columns:
            df[COIL_ID_COL] = df[COIL_ID_COL].astype(str).str.strip().replace(['nan', 'None', '', 'NaN'], np.nan)
            
            missing_mask = df[COIL_ID_COL].isna()
            if missing_mask.any():
                df.loc[missing_mask, COIL_ID_COL] = [f"UNKNOWN_{i}" for i in df[missing_mask].index]

            scrap_totals = df.groupby(['Time_Group', COIL_ID_COL])[SCRAP_COL].sum().reset_index()
            first_occurrence = df.sort_values(['Time_Group', 'Production_Date']).drop_duplicates(subset=['Time_Group', COIL_ID_COL], keep='first')
            
            df_scrap_master = first_occurrence[['Time_Group', COIL_ID_COL, LEN_COL, 'Actual_Thickness', 'HR_Material', 'Production_Date']].merge(
                scrap_totals, on=[COIL_ID_COL, 'Time_Group']
            )

            # --- 1. HYBRID TREND LINE (BEAUTIFIED) ---
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
            
            trend_data = trend_data.sort_values('Time_Group')

            fig_trend, ax_trend = plt.subplots(figsize=(14, 5))
            if not trend_data.empty:
                # Plot with thicker line, bigger markers, and white edges for pop
                ax_trend.plot(trend_data['Time_Group'], trend_data['Rejection_Rate (%)'], 
                              marker='o', markersize=8, markeredgecolor='white', markeredgewidth=1.5,
                              linestyle='-', color='#1f77b4', linewidth=3, label='Rejection Rate %')
                
                # Add subtle shading under the line
                ax_trend.fill_between(trend_data['Time_Group'], trend_data['Rejection_Rate (%)'], 
                                      color='#1f77b4', alpha=0.1)

                # Set Y-axis limit with padding for annotations
                y_max = trend_data['Rejection_Rate (%)'].max()
                ax_trend.set_ylim(0, y_max * 1.35 + 0.5 if not trend_data.empty else 10)
                
                # Clean up labels and title
                ax_trend.set_title("Rejection Rate Trend", fontweight='bold', fontsize=15, pad=15, color='#333')
                ax_trend.set_ylabel("Rejection Rate (%)", fontweight='bold', color='#555')
                ax_trend.set_xlabel("")
                
                # Subtle Grid and removed spines
                ax_trend.grid(axis='y', linestyle='--', alpha=0.5)
                ax_trend.grid(axis='x', visible=False)
                ax_trend.spines['top'].set_visible(False)
                ax_trend.spines['right'].set_visible(False)
                ax_trend.spines['left'].set_color('#ddd')
                ax_trend.spines['bottom'].set_color('#ddd')
                
                # Enhanced Data Labels (Bbox with rounded corners)
                for i, val in enumerate(trend_data['Rejection_Rate (%)']):
                    ax_trend.annotate(f'{val:.2f}%', 
                                      xy=(i, val), 
                                      xytext=(0, 8), 
                                      textcoords="offset points", 
                                      ha='center', va='bottom', 
                                      fontsize=10, fontweight='bold', color='#222',
                                      bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="none", alpha=0.8))
                
                # X-axis Tick Rotation and Alignment
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
            
            scrap_by_period = scrap_by_period.sort_values('Time_Group')
            
            fig_p, ax_p = plt.subplots(figsize=(10, 4))
            if not scrap_by_period.empty:
                ax_p.bar(scrap_by_period['Time_Group'], scrap_by_period['Scrap_Rate (%)'], color='#e74c3c', edgecolor='white')
                ax_p.set_title("Tail Scrap Rate (%) by Time Period", fontweight='bold')
                ax_p.set_ylabel("Scrap Rate (%)")
                ax_p.spines['top'].set_visible(False)
                ax_p.spines['right'].set_visible(False)
                ax_p.set_ylim(0, scrap_by_period['Scrap_Rate (%)'].max() * 1.2 + 0.1)
                for i, val in enumerate(scrap_by_period['Scrap_Rate (%)']):
                    ax_p.annotate(f"{val:.2f}%", xy=(i, val), xytext=(0, 5), textcoords="offset points", ha='center', va='bottom', fontweight='bold')
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
                        pivot_t.plot(kind='bar', ax=ax_t, colormap='YlOrRd', edgecolor='white')
                ax_t.set_ylabel("Scrap Rate (%)")
                ax_t.spines['top'].set_visible(False)
                ax_t.spines['right'].set_visible(False)
                fig_t.tight_layout()
                st.pyplot(fig_t)

            with col_m:
                st.markdown("**Scrap Rate by Period & Material**")
                fig_m, ax_m = plt.subplots(figsize=(8, 4))
                if not scrap_detail.empty:
                    pivot_m = scrap_detail.pivot_table(index='Time_Group', columns='HR_Material', values='Scrap_Rate (%)', aggfunc='mean')
                    if not pivot_m.empty:
                        pivot_m.plot(kind='bar', ax=ax_m, colormap='Set2', edgecolor='white')
                ax_m.set_ylabel("Scrap Rate (%)")
                ax_m.spines['top'].set_visible(False)
                ax_m.spines['right'].set_visible(False)
                fig_m.tight_layout()
                st.pyplot(fig_m)

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
            grade_dist_pct.to_excel(writer, sheet_name='Grade_Distribution')
            if 'trend_data' in locals() and not trend_data.empty:
                trend_data.to_excel(writer, sheet_name='Trend_Data', index=False)
                scrap_by_period.to_excel(writer, sheet_name='Scrap_By_Period', index=False)
                scrap_detail.to_excel(writer, sheet_name='Scrap_Detailed', index=False)
        
        st.sidebar.download_button(
            label="📥 Download Full Excel",
            data=output.getvalue(),
            file_name="Quality_Scrap_Deep_Analysis.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
