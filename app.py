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
    # Đọc dữ liệu thô để xử lý header
    df_raw = pd.read_excel(uploaded_file)
    
    # Dọn dẹp tên cột bị trùng và khoảng trắng
    df_raw.columns = [str(c).strip() for c in df_raw.columns]
    df_raw = df_raw.loc[:, ~df_raw.columns.duplicated()]

    st.sidebar.success("File Uploaded Successfully!")
    
    # ==========================================
    # CẤU HÌNH CỘT (GIÚP TRÁNH LỖI TÌM KHÔNG THẤY MÃ)
    # ==========================================
    st.header("🔍 Data Column Mapping")
    st.info("Please confirm the columns from your Excel file to ensure accuracy.")
    
    c_map1, c_map2, c_map3 = st.columns(3)
    
    all_cols = list(df_raw.columns)
    
    # Tự động gợi ý cột
    def_coil = next((c for c in all_cols if '鋼捲' in c or 'Coil' in c), all_cols[0])
    def_date = next((c for c in all_cols if '使用' in c or 'Date' in c), all_cols[0])
    def_len = next((c for c in all_cols if '實測' in c or 'Length' in c), all_cols[0])
    
    COIL_ID_COL = c_map1.selectbox("Select Coil ID Column (鋼捲號碼):", all_cols, index=all_cols.index(def_coil))
    USAGE_DATE_COL = c_map2.selectbox("Select Usage Date Column (使用日期):", all_cols, index=all_cols.index(def_date))
    LEN_COL = c_map3.selectbox("Select Input Length Column (實測長度):", all_cols, index=all_cols.index(def_len))

    # --- 1. GLOBAL PRE-PROCESSING ---
    df = df_raw.copy()
    
    # Numeric conversions
    SCRAP_COL = '尾料剔退'
    if SCRAP_COL not in df.columns:
        df[SCRAP_COL] = 0 # Default if missing
    
    df[LEN_COL] = pd.to_numeric(df[LEN_COL], errors='coerce').fillna(0)
    df[SCRAP_COL] = pd.to_numeric(df[SCRAP_COL], errors='coerce').fillna(0)
    
    # Rename for logic consistency
    df.rename(columns={
        'Thickness': 'Actual_Thickness', '厚度': 'Actual_Thickness',
        '烤漆降伏強度': 'YS', '烤漆抗拉強度': 'TS', '伸長率': 'EL'
    }, inplace=True)
    df = df.loc[:, ~df.columns.duplicated()]

    # Production Date logic
    date_key = '烤三生產日期' 
    if date_key in df.columns:
        d_str = df[date_key].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
        df['Production_Date'] = pd.to_datetime(d_str, format='%Y%m%d', errors='coerce')
    
    # Grades logic
    base_grades = ['A-B+', 'A-B', 'A-B-', 'B+', 'B']
    for g in base_grades:
        match_cols = [c for c in df.columns if str(c).strip() == g or str(c).strip().startswith(f"{g}.")]
        df[g] = df[match_cols].apply(pd.to_numeric, errors='coerce').fillna(0).sum(axis=1) if match_cols else 0
    
    df['Total_Qty'] = df[base_grades].sum(axis=1)
    df['Valid_Qty'] = df[['A-B+', 'A-B']].sum(axis=1)
    
    # GLOBAL DF FOR CUSTOMER ANALYSIS (TASK 6)
    df_global = df.copy()

    # THICKNESS FILTERING (TASK 2-5)
    def map_thickness(val):
        v = round(float(val), 2) if pd.notnull(val) else 0
        if v in [0.47, 0.50]: return 0.5
        if v in [0.53, 0.54, 0.57, 0.58, 0.60]: return 0.6
        if v in [0.63, 0.75, 0.76, 0.77, 0.80]: return 0.8
        return None 
    
    if 'Actual_Thickness' in df.columns:
        df['Standard_Thickness'] = df['Actual_Thickness'].apply(map_thickness)
        df_filtered = df.dropna(subset=['Standard_Thickness']).copy()
        df_filtered['Actual_Thickness'] = df_filtered['Standard_Thickness']
    else:
        df_filtered = df.copy()

    # --- TABS ---
    tabs = st.tabs(["📁 1. Raw Data & Search", "📋 2. Quality Yield", "📈 3. Capability", "📉 4. I-MR", "✂️ 5. Tail Scrap", "🎯 6. Customer End-Use"])

    with tabs[0]:
        st.header("1. Data Inspector")
        st.write(f"Total rows found: {len(df_raw)}")
        
        search_query = st.text_input("🔎 Search Coil ID (Gõ mã 47B490B10 vào đây để kiểm tra dòng nào):")
        if search_query:
            # Tìm kiếm chính xác mã trong cột ID đã chọn
            res = df_raw[df_raw[COIL_ID_COL].astype(str).str.contains(search_query, na=False)]
            if not res.empty:
                st.success(f"Found {len(res)} matches!")
                st.dataframe(res)
            else:
                st.error("Mã này thực sự không tồn tại trong cột được chọn. Vui lòng kiểm tra lại Mapping ở trên.")
        
        st.markdown("### Full Data Table")
        st.dataframe(df_raw)

    # ... (Các Task 2, 3, 4, 5 giữ nguyên logic từ bản trước nhưng dùng df_filtered) ...
    # Để tiết kiệm không gian, tôi tập trung fix Task 6 cho bạn:

    with tabs[5]:
        st.header("6. Customer End-Use Analysis")
        
        # 🚀 TRIỆT TIÊU BÓNG MA DỮ LIỆU
        df_t6 = df_global[df_global[LEN_COL] > 0].copy()
        df_t6[COIL_ID_COL] = df_t6[COIL_ID_COL].astype(str).str.strip()
        
        # --- SMART DATE PARSING ---
        def extract_month_num(m_val):
            if pd.isna(m_val): return 99
            if isinstance(m_val, (pd.Timestamp, datetime.date)): return m_val.month
            m_str = str(m_val).strip()
            nums = re.findall(r'\d+', m_str)
            if nums:
                val = int(nums[0]) if len(nums)==1 else int(nums[-1])
                return val if val <= 12 else int(str(val)[-2:])
            return 99

        df_t6['Month_Num'] = df_t6[USAGE_DATE_COL].apply(extract_month_num)
        df_t6 = df_t6[df_t6['Month_Num'] <= 12].sort_values('Month_Num')
        df_t6['Display_Month'] = df_t6['Month_Num'].apply(lambda x: f"Month {x}")

        # MACRO VIEW
        macro_df = df_t6.groupby('Display_Month', sort=False).agg({LEN_COL: 'sum', SCRAP_COL: 'sum'}).reset_index()
        macro_df['Scrap_Rate (%)'] = (macro_df[SCRAP_COL] / macro_df[LEN_COL] * 100).round(2)
        st.subheader("Macro View: Customer Scrap Rate Trend")
        st.line_chart(macro_df.set_index('Display_Month')[['Scrap_Rate (%)']], color="#d62728")

        # SPLIT-COIL AI DIAGNOSIS
        st.markdown("---")
        st.subheader("🔍 AI Split-Coil Diagnosis")
        
        df_t6['Machine_Status'] = df_t6['Month_Num'].apply(lambda x: 'New Machine' if x >= 4 else 'Old Machine')
        
        coil_summary = df_t6.groupby([COIL_ID_COL, 'Machine_Status']).agg({LEN_COL: 'sum', SCRAP_COL: 'sum'}).reset_index()
        coil_summary['Scrap_Rate'] = (coil_summary[SCRAP_COL] / coil_summary[LEN_COL] * 100)
        
        coils_old = set(coil_summary[coil_summary['Machine_Status'] == 'Old Machine'][COIL_ID_COL])
        coils_new = set(coil_summary[coil_summary['Machine_Status'] == 'New Machine'][COIL_ID_COL])
        split_coils = coils_old.intersection(coils_new)

        if split_coils:
            diagnosis_data = []
            for coil in split_coils:
                d_c = coil_summary[coil_summary[COIL_ID_COL] == coil]
                old_v = d_c[d_c['Machine_Status'] == 'Old Machine']['Scrap_Rate'].values[0]
                new_v = d_c[d_c['Machine_Status'] == 'New Machine']['Scrap_Rate'].values[0]
                
                # AI Logic
                if old_v > 10 and new_v < 5: root = "🚨 Old Machine Issue (Proven)"
                elif old_v > 10 and new_v >= 5: root = "⚠️ Material / Process Issue"
                else: root = "✅ Normal / Stable"
                
                # Mech properties
                props = df_t6[df_t6[COIL_ID_COL] == coil][['YS', 'TS', 'EL']].mean().to_dict()
                
                diagnosis_data.append({
                    'Coil ID': coil, 'Scrap (Old)': f"{old_v:.2f}%", 'Scrap (New)': f"{new_v:.2f}%",
                    'AI Root Cause': root, 'YS': props.get('YS'), 'TS': props.get('TS'), 'EL': props.get('EL')
                })
            st.dataframe(pd.DataFrame(diagnosis_data), use_container_width=True)
        else:
            st.warning("No split-coils found using the selected columns.")
