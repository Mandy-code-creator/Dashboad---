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
    if 'Thickness' in df.columns:
        df.rename(columns={'Thickness': 'Actual_Thickness'}, inplace=True)
    elif '型式' in df.columns: 
        for i, c in enumerate(df.columns):
            if '型式' in c and i > 0:
                df.rename(columns={df.columns[i - 1]: 'Actual_Thickness'}, inplace=True)
                break
    
    if 'Actual_Thickness' in df.columns:
        df['Actual_Thickness'] = pd.to_numeric(df['Actual_Thickness'], errors='coerce').round(3)

    # Handle Dates & Time Grouping
    date_key = '烤三生產日期' 
    if date_key in df.columns:
        d_str = df[date_key].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
        df['Production_Date'] = pd.to_datetime(d_str, format='%Y%m%d', errors='coerce')
        
        def categorize_period(d):
            if pd.isnull(d): return "Unknown"
            y = d.year
            if y == 2024: return "2024 (Full Year)"
            if y == 2025: return f"2025 Q{(d.month-1)//3 + 1}"
            if y == 2026: return "2026 Q1"
            return "Other"
        
        df['Time_Group'] = df['Production_Date'].apply(categorize_period)
    else:
        df['Time_Group'] = "Unknown"

    # Quality Grade Mapping (Task 1 Logic)
    base_grades = ['A-B+', 'A-B', 'A-B-', 'B+', 'B']
    for g in base_grades:
        match_cols = [c for c in df.columns if c == g or str(c).startswith(f"{g}.")]
        df[g] = df[match_cols].apply(pd.to_numeric, errors='coerce').fillna(0).sum(axis=1) if match_cols else 0

    df['Total_Qty'] = df[base_grades].sum(axis=1)
    df['Severe_Bad_Qty'] = df[['B+', 'B']].sum(axis=1)
    df['Acceptable_Qty'] = df['Total_Qty'] - df['Severe_Bad_Qty']

    # --- TABS ---
    tab1, tab5 = st.tabs(["📋 Task 1: Quality Yield", "✂️ Task 5: Tail Scrap Analysis"])

    # ==========================================================
    # TASK 1: YIELD SUMMARY
    # ==========================================================
    with tab1:
        st.header("Quality Yield Summary")
        
        yield_summary = df.groupby(['Time_Group', 'Actual_Thickness'])[
            ['Total_Qty', 'Acceptable_Qty', 'Severe_Bad_Qty']
        ].sum().reset_index()
        
        yield_summary['Yield (%)'] = (yield_summary['Acceptable_Qty'] / yield_summary['Total_Qty'] * 100).round(2)
        
        st.dataframe(
            yield_summary.style.background_gradient(subset=['Yield (%)'], cmap='Greens'),
            use_container_width=True, hide_index=True
        )

        st.subheader("Yield Performance Trend")
        fig1, ax1 = plt.subplots(figsize=(10, 4))
        if not yield_summary.empty:
            pivot_yield = yield_summary.pivot(index='Time_Group', columns='Actual_Thickness', values='Yield (%)')
            pivot_yield.plot(kind='bar', ax=ax1, edgecolor='white')
        ax1.set_title("Yield (%) by Period & Thickness", fontweight='bold')
        ax1.set_ylabel("Yield Percentage")
        ax1.set_xlabel("Time Period")
        st.pyplot(fig1)

    # ==========================================================
    # TASK 5: TAIL SCRAP & MONTHLY TREND (COIL-ID AWARE)
    # ==========================================================
    with tab5:
        st.header("Tail Scrap & Monthly Rejection Trend")
        
        COIL_ID_COL = '鋼捲號碼'
        LEN_COL = '實測長度'
        SCRAP_COL = '尾料剔退'

        if LEN_COL in df.columns and SCRAP_COL in df.columns:
            # 1. Data Cleaning
            df[LEN_COL] = pd.to_numeric(df[LEN_COL], errors='coerce').fillna(0)
            df[SCRAP_COL] = pd.to_numeric(df[SCRAP_COL], errors='coerce').fillna(0)
            
            # 2. Coil-ID Aware Logic: Sum scrap all passes, count length first pass only
            scrap_totals = df.groupby(COIL_ID_COL)[SCRAP_COL].sum().reset_index()
            first_occurrence = df.sort_values('Production_Date').drop_duplicates(subset=[COIL_ID_COL])
            
            df_scrap_master = first_occurrence.merge(scrap_totals, on=COIL_ID_COL, suffixes=('_raw', ''))
            
            # 3. Monthly Trend Calculation
            df_scrap_master['Year_Month'] = df_scrap_master['Production_Date'].dt.to_period('M').astype(str)
            
            monthly_trend = df_scrap_master.groupby('Year_Month').agg(
                Input_Length=(LEN_COL, 'sum'),
                Total_Scrap=(SCRAP_COL, 'sum')
            ).reset_index()
            
            monthly_trend['Rejection_Rate (%)'] = (monthly_trend['Total_Scrap'] / monthly_trend['Input_Length'] * 100).round(2)
            monthly_trend = monthly_trend.sort_values('Year_Month')

            # --- TREND LINE CHART (Based on image_116c1b.png) ---
            st.subheader("Monthly Rejection Rate Trend (%)")
            fig_trend, ax_trend = plt.subplots(figsize=(12, 5))
            
            ax_trend.plot(monthly_trend['Year_Month'], monthly_trend['Rejection_Rate (%)'], 
                          marker='o', linestyle='-', color='#1f77b4', linewidth=2, label='Rejection Rate %')
            
            ax_trend.set_ylim(0, monthly_trend['Rejection_Rate (%)'].max() * 1.3 if not monthly_trend.empty else 10)
            ax_trend.set_title("Monthly Rejection Rate Trend", fontweight='bold', fontsize=14)
            ax_trend.set_ylabel("Rejection Rate (%)")
            ax_trend.grid(axis='y', linestyle='--', alpha=0.6)
            
            for i, val in enumerate(monthly_trend['Rejection_Rate (%)']):
                ax_trend.text(i, val + 0.1, f'{val}%', ha='center', va='bottom', fontsize=10, fontweight='bold')
            
            plt.xticks(rotation=45)
            ax_trend.legend(loc='upper center', bbox_to_anchor=(0.5, -0.15), ncol=1)
            st.pyplot(fig_trend)

            # --- PERIOD SUMMARY TABLE ---
            st.subheader("Scrap Performance by Period")
            scrap_summary = df_scrap_master.groupby('Time_Group').agg(
                Input_Length=(LEN_COL, 'sum'),
                Total_Scrap=(SCRAP_COL, 'sum'),
                Coil_Count=(COIL_ID_COL, 'count')
            ).reset_index()
            scrap_summary['Scrap_Rate (%)'] = (scrap_summary['Total_Scrap'] / scrap_summary['Input_Length'] * 100).round(3)
            
            st.dataframe(
                scrap_summary.style.background_gradient(subset=['Scrap_Rate (%)'], cmap='Reds'),
                use_container_width=True, hide_index=True
            )
        else:
            st.warning("Required columns ('實測長度' or '尾料剔退') not found in the file.")

    # --- EXPORT ---
    st.sidebar.header("Export Report")
    if st.sidebar.button("Generate Excel File"):
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            yield_summary.to_excel(writer, sheet_name='Yield_Report', index=False)
            if 'scrap_summary' in locals():
                scrap_summary.to_excel(writer, sheet_name='Period_Scrap_Report', index=False)
            if 'monthly_trend' in locals():
                monthly_trend.to_excel(writer, sheet_name='Monthly_Trend_Report', index=False)
        st.sidebar.download_button(
            label="📥 Download Excel",
            data=output.getvalue(),
            file_name="Quality_Scrap_Summary.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
