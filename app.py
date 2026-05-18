import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
import re
from scipy.stats import norm, ttest_ind, sem, t
import io
from docx import Document
from docx.shared import Inches

# ==========================================
# 1. PAGE CONFIGURATION & FONTS
# ==========================================
st.set_page_config(page_title="Line 4 Quality Analytics", layout="wide")

plt.rcParams['font.sans-serif'] = ['Arial', 'Helvetica', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False

plt.rcParams.update({
    'font.size': 12,
    'axes.labelweight': 'bold',
    'axes.titleweight': 'bold',
    'axes.titlesize': 15,
    'legend.fontsize': 10,
    'font.weight': 'bold',
    'lines.linewidth': 2.5,
    'figure.dpi': 150  
})

# ==========================================
# 2. UTILITY FUNCTIONS
# ==========================================
@st.cache_data
def load_and_clean_data(file):
    df = pd.read_csv(file) if file.name.endswith('.csv') else pd.read_excel(file)
    df.columns = [str(c).strip() for c in df.columns]
    return df

def find_data_col(df, key):
    for col in df.columns:
        if re.search(key, col, re.IGNORECASE) and not any(kw in col for kw in ["管制", "規格", "要求", "原始"]):
            return col
    return None

def get_limit(df, keyword, limit_type, category):
    col = next((c for c in df.columns if keyword in c and limit_type in c.lower() and category in c), None)
    if col:
        val = pd.to_numeric(df[col], errors='coerce').median()
        return float(val) if pd.notnull(val) and val > 0 else None
    return None

def apply_full_border(ax):
    for spine in ax.spines.values():
        spine.set_linewidth(2.5)
        spine.set_color('black')
        spine.set_visible(True)

def format_num(val):
    if val is None or pd.isna(val): return "-"
    rounded = round(float(val), 2)
    return str(int(rounded)) if rounded == int(rounded) else str(rounded)

def export_to_word(figures, titles):
    doc = Document()
    doc.add_heading('Quality Analytics Report', 0)

    for fig, title in zip(figures, titles):
        doc.add_heading(title, level=1)
        img_stream = io.BytesIO()
        fig.savefig(img_stream, format='png', dpi=300, bbox_inches='tight')
        img_stream.seek(0)
        doc.add_picture(img_stream, width=Inches(5.5))
        doc.add_paragraph("-" * 50)
    
    out_io = io.BytesIO()
    doc.save(out_io)
    out_io.seek(0)
    return out_io

# ==========================================
# 3. MAIN APP LOGIC
# ==========================================
st.sidebar.header("📂 DATA SOURCE")
uploaded_files = st.sidebar.file_uploader("Upload Excel/CSV Reports", type=["xlsx", "csv", "xls"], accept_multiple_files=True)

if uploaded_files:
    metrics_map = {"YS": "YS", "TS": "TS", "EL": "EL", "Hardness": "HRB", "YPE": "YPE"}
    zh_map_global = {"YS": "降伏強度", "TS": "抗拉強度", "EL": "伸長率", "HRB": "硬度", "YPE": "YPE"}

    file_names = [f.name for f in uploaded_files]
    
    # GLOBAL FILE ASSIGNMENT IN SIDEBAR
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🏭 ASSIGN LINE DATA")
    ma_filename = st.sidebar.selectbox("Select Galvanizing File:", file_names, key="ma_sel")
    son_filename = st.sidebar.selectbox("Select Coating File:", file_names, index=1 if len(file_names) > 1 else 0, key="son_sel")
    
    st.sidebar.markdown("---")
    view_mode = st.sidebar.radio("🔍 VIEW MODE:", [
        "Process Analytics", 
        "SPC Control Charts (I-MR)", 
        "Executive Summary", 
        "Cross-Line Comparison 🔀"
    ])

    # =========================================================================
    # MODE 1: CROSS-LINE COMPARISON
    # =========================================================================
    if view_mode == "Cross-Line Comparison 🔀":
        st.title("🔀 Statistical Process Shift & Limits Recommendation")
        
        if ma_filename == son_filename:
            st.warning("⚠️ You selected the same file for both lines. Please assign different files in the sidebar to compare.")
        else:
            file_ma = next(f for f in uploaded_files if f.name == ma_filename)
            df_ma = load_and_clean_data(file_ma)
            
            file_son = next(f for f in uploaded_files if f.name == son_filename)
            df_son = load_and_clean_data(file_son)

            common_labels = [k for k, v in metrics_map.items() if find_data_col(df_ma, v) and find_data_col(df_son, v)]

            if not common_labels:
                st.error("❌ No common mechanical property columns found between the two files.")
            else:
                st.success(f"✅ Found {len(common_labels)} common properties to analyze: {', '.join(common_labels)}")
                
                for selected_label in common_labels:
                    st.markdown(f"<hr><h2 style='color: #2E86C1;'>🔹 Analysis for Parameter: {selected_label}</h2>", unsafe_allow_html=True)
                    
                    short_key = metrics_map[selected_label]
                    zh_key = zh_map_global.get(short_key, short_key)

                    col_ma = find_data_col(df_ma, short_key)
                    col_son = find_data_col(df_son, short_key)

                    vals_ma_full = pd.to_numeric(df_ma[col_ma], errors='coerce').dropna()
                    vals_son_full = pd.to_numeric(df_son[col_son], errors='coerce').dropna()

                    def get_theoretical_mean(df, data_col):
                        df_calc = df.dropna(subset=[data_col]).copy()
                        g_col = next((c for c in df.columns if any(kw in str(c).lower() for kw in ['grade', '等级', '等級', 'cấp', 'quality', 'loại'])), None)
                        if g_col:
                            f_df = df_calc[df_calc[g_col].astype(str).str.upper().str.contains(r'A|B', regex=True, na=False)]
                            if not f_df.empty: df_calc = f_df
                        return df_calc[data_col].mean()

                    mean_ma = get_theoretical_mean(df_ma, col_ma)
                    mean_son = get_theoretical_mean(df_son, col_son)
                    delta = mean_son - mean_ma

                    lsl_son = get_limit(df_son, zh_key, "min", "管制")
                    usl_son = get_limit(df_son, zh_key, "max", "管制")

                    s_lsl = (lsl_son - delta) if lsl_son is not None else "N/A"
                    s_usl = (usl_son - delta) if usl_son is not None else "N/A"

                    st.markdown(f"#### 🔄 Optimal Limits Recommendation ({selected_label})")
                    delta_data = [{
                        "Parameter": selected_label,
                        "Galv. Mean (Theo.)": format_num(mean_ma),
                        "Coating Mean (Theo.)": format_num(mean_son),
                        "Shift (Δ)": format_num(delta),
                        "Current Coating LSL": format_num(lsl_son) if lsl_son is not None else "N/A",
                        "Current Coating USL": format_num(usl_son) if usl_son is not None else "N/A",
                        "Recommended Galv. LSL": format_num(s_lsl) if isinstance(s_lsl, (int, float)) else s_lsl,
                        "Recommended Galv. USL": format_num(s_usl) if isinstance(s_usl, (int, float)) else s_usl
                    }]
                    st.dataframe(pd.DataFrame(delta_data), hide_index=True, use_container_width=True)

                    st.markdown("#### 🔬 2-Sample T-Test")
                    t_stat, p_val = ttest_ind(vals_son_full, vals_ma_full, equal_var=False)
                    is_significant = "YES" if p_val < 0.05 else "NO"
                    
                    t_test_data = pd.DataFrame([{
                        "Metric": "T-Statistic", "Value": format_num(t_stat)
                    }, {
                        "Metric": "P-Value", "Value": f"{p_val:.4f}"
                    }, {
                        "Metric": "Significant Shift? (<0.05)", "Value": is_significant
                    }])
                    st.table(t_test_data)
                    st.caption(f"*Interpretation:* A P-Value < 0.05 proves the Coating process structurally alters the {selected_label}.")

                    st.markdown("#### 📈 Process Shift Distribution")
                    fig_comp, ax_comp = plt.subplots(figsize=(12, 6))
                    
                    for label_name, vals, color in [
                        (f"Galvanizing Line", vals_ma_full, '#1f77b4'),
                        (f"Coating Line", vals_son_full, '#ff7f0e')
                    ]:
                        if len(vals) > 1 and vals.std() > 0:
                            mu_val = vals.mean()
                            sigma_val = vals.std(ddof=1)
                            
                            x_range = np.linspace(mu_val - 4*sigma_val, mu_val + 4*sigma_val, 500)
                            bin_width = (vals.max() - vals.min()) / 20 if vals.max() > vals.min() else 1
                            y_vals = norm.pdf(x_range, mu_val, sigma_val) * len(vals) * bin_width
                            
                            ax_comp.plot(x_range, y_vals, color=color, lw=3, label=label_name)
                            ax_comp.fill_between(x_range, y_vals, alpha=0.3, color=color)
                            ax_comp.axvline(mu_val, color=color, linestyle='--', alpha=0.8) 
                    
                    ax_comp.set_ylabel("Coil Count")
                    ax_comp.set_xlabel(f"{selected_label} Value")
                    ax_comp.set_title(f"Shift Comparison: {selected_label} (Δ = {format_num(delta)})", pad=20)
                    ax_comp.legend(loc="upper right")
                    apply_full_border(ax_comp)
                    plt.tight_layout()
                    st.pyplot(fig_comp)
                    
                    buf_comp = export_to_word([fig_comp], [f"Distribution Shift Chart - {selected_label}"])
                    st.download_button(label=f"📥 Download Chart ({selected_label})", data=buf_comp, file_name=f"ShiftPlot_{selected_label}.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", key=f"dl_cross_{selected_label}")

    # =========================================================================
    # MODE 2: TABBED ANALYSIS FOR INDIVIDUAL LINES
    # =========================================================================
    else:
        st.title(f"📊 {view_mode}")
        
        if view_mode == "SPC Control Charts (I-MR)":
            st.info("⚙️ Configure global target multipliers below. The system will apply them to all available properties across both lines.")
            c_i1, c_i2 = st.columns(2)
            with c_i1: k_std = st.number_input("Target Multiplier for StdDev (Sigma):", 1.0, 6.0, 3.0, 0.1)
            with c_i2: k_iqr = st.number_input("Target Multiplier for IQR (k-factor):", 1.0, 6.0, 1.5, 0.1)
        else:
            k_std, k_iqr = 3.0, 1.5

        tab_ma, tab_son = st.tabs(["🏭 Galvanizing Line Data", "🎨 Coating Line Data"])
        
        line_configs = [
            (tab_ma, ma_filename, "Galvanizing Line"),
            (tab_son, son_filename, "Coating Line")
        ]

        for tab_obj, fname, line_label in line_configs:
            with tab_obj:
                file_obj = next((f for f in uploaded_files if f.name == fname), None)
                if not file_obj:
                    st.warning(f"File '{fname}' not found.")
                    continue
                
                df_raw = load_and_clean_data(file_obj)
                df = df_raw.copy()
                
                is_coating_line = any("原始" in str(c) for c in df.columns)
                actual_line_type = "Coating Line" if is_coating_line else "Galvanizing Line"
                
                st.info(f"📂 Analyzing File: **{fname}** | Auto-detected: **{actual_line_type}**")
                
                if "用途碼" in df.columns:
                    usage_list = sorted(df["用途碼"].dropna().unique().tolist())
                    selected_usages = st.multiselect(f"Filter Usage Code ({line_label}):", options=usage_list, default=usage_list, key=f"usage_{fname}_{view_mode}")
                    df = df[df["用途碼"].isin(selected_usages)]

                available = [k for k, v in metrics_map.items() if find_data_col(df, v)]
                if not available:
                    st.warning(f"⚠️ Mechanical property data column not found in this file.")
                    continue

                if view_mode == "Executive Summary":
                    summary_data = []
                    for selected_label in available:
                        short_key = metrics_map[selected_label]
                        data_col = find_data_col(df, short_key)
                        zh_key = zh_map_global.get(short_key, short_key)
                        
                        if data_col:
                            p_data = pd.to_numeric(df[data_col], errors='coerce').dropna()
                            if len(p_data) == 0: continue
                            mu_v = p_data.mean()
                            sig_v = p_data.std(ddof=1)
                            i_lsl = get_limit(df, zh_key, "min", "管制")
                            i_usl = get_limit(df, zh_key, "max", "管制")
                            # 👇 [THÊM MỚI TẠI ĐÂY] Ép giới hạn LSL = 4.0 cho YPE của chuyền Sơn
                            if is_coating_line and short_key == "YPE":
                                i_lsl = 4.0
                            cp, ca, cpk, formula, status = "-", "-", "-", "-", "N/A"
                            cpk_val = None
                            if sig_v > 0:
                                if i_usl is not None and i_lsl is not None:
                                    cp_v = (i_usl - i_lsl) / (6 * sig_v)
                                    cnt, half = (i_usl + i_lsl) / 2, (i_usl - i_lsl) / 2
                                    ca_v = (mu_v - cnt) / half
                                    cpk_val = cp_v * (1 - abs(ca_v))
                                    cp, ca, cpk, formula = format_num(cp_v), f"{ca_v*100:.1f}%", format_num(cpk_val), "Cp*(1-|Ca|)"
                                elif i_usl is not None:
                                    cpk_val = (i_usl - mu_v) / (3 * sig_v); cpk, formula = format_num(cpk_val), "Cpu"
                                elif i_lsl is not None:
                                    cpk_val = (mu_v - i_lsl) / (3 * sig_v); cpk, formula = format_num(cpk_val), "Cpl"
                                    
                                if cpk_val is not None:
                                    if cpk_val < 1.0: status = "🔴 Action Required"
                                    elif 1.0 <= cpk_val < 1.33: status = "🟡 Acceptable"
                                    elif 1.33 <= cpk_val <= 2.0: status = "🟢 Excellent"
                                    else: status = "🔵 Over-engineered (>2.0)"
                            
                            summary_data.append({"Parameter": selected_label, "N": len(p_data), "Mean": format_num(mu_v), "StdDev (σ)": format_num(sig_v),
                                               "Int LSL": format_num(i_lsl), "Int USL": format_num(i_usl), "Cp": cp, "Ca": ca, "Cpk": cpk, 
                                               "Cpk Formula": formula, "Status": status})
                    
                    st.dataframe(pd.DataFrame(summary_data), hide_index=True, use_container_width=True)

                else:
                    for selected_label in available:
                        st.markdown(f"<hr><h3 style='color: #2E86C1;'>🔹 Parameter: {selected_label}</h3>", unsafe_allow_html=True)
                        short_key = metrics_map[selected_label]
                        data_col = find_data_col(df, short_key) 
                        zh_key = zh_map_global.get(short_key, short_key)
                        
                        int_lsl = get_limit(df, zh_key, "min", "管制")
                        int_usl = get_limit(df, zh_key, "max", "管制")
                        cust_lsl = get_limit(df, zh_key, "min", "客戶要求")
                        cust_usl = get_limit(df, zh_key, "max", "客戶要求")
                        # 👇 CHÈN ĐOẠN NÀY VÀO ĐÂY (Khoảng dòng 167)
                        # Ép giới hạn nội bộ LSL = 4.0 cho YPE của dây chuyền Sơn phủ
                        if is_coating_line and short_key == "YPE":
                            int_lsl = 4.0
                        # 👆 -----------------------------------------------------------
                        if data_col:
                            temp_df = df.copy()
                            temp_df[data_col] = pd.to_numeric(temp_df[data_col], errors='coerce')
                            
                            plot_df = temp_df.dropna(subset=[data_col]).reset_index(drop=True)
                            plot_data = plot_df[data_col]
                            n = len(plot_data)

                            df_calc = plot_df.copy()
                            grade_col = next((c for c in df.columns if any(kw in str(c).lower() for kw in ['grade', '等级', '等級', 'cấp', 'quality', 'loại'])), None)
                            if grade_col:
                                f_df = df_calc[df_calc[grade_col].astype(str).str.upper().str.contains(r'A|B', regex=True, na=False)]
                                if not f_df.empty: df_calc = f_df
                            
                            calc_data = df_calc[data_col].dropna()
                            mu = calc_data.mean()
                            sigma_fixed = calc_data.std(ddof=1)

                            if view_mode == "Process Analytics":
                                tab_trend, tab_dist = st.tabs([f"📈 {selected_label} Trend", f"📊 {selected_label} Distribution"])
                                ucl_v1, lcl_v1 = mu + 3*sigma_fixed, mu - 3*sigma_fixed

                                with tab_trend:
                                    fig_t, ax_t = plt.subplots(figsize=(12, 6))
                                    x_coords = np.arange(1, n+1)
                                    ax_t.plot(x_coords, plot_data, marker="o", markersize=6, color="#1f77b4", label="Actual Value", zorder=1)
                                    
                                    mask_out = pd.Series([False] * len(plot_data))
                                    if int_usl is not None: mask_out = mask_out | (plot_data > int_usl)
                                    if int_lsl is not None: mask_out = mask_out | (plot_data < int_lsl)
                                    if mask_out.any():
                                        ax_t.scatter(x_coords[mask_out], plot_data[mask_out], color="red", s=80, edgecolor="black", zorder=2, label="Out of Int. Limit")

                                    ax_t.axhline(mu, color="blue", ls="-", lw=2, label=f"Theo. Mean: {mu:.1f}")
                                    if cust_lsl: ax_t.axhline(cust_lsl, color="green", ls="-", lw=3, label="Cust LSL")
                                    if cust_usl: ax_t.axhline(cust_usl, color="green", ls="-", lw=3, label="Cust USL")
                                    if int_lsl: ax_t.axhline(int_lsl, color="red", ls="--", lw=3, label="Int LSL")
                                    if int_usl: ax_t.axhline(int_usl, color="red", ls="--", lw=3, label="Int USL")
                                    ax_t.axhline(ucl_v1, color="#6A0DAD", ls=":", lw=3, label="3σ UCL")
                                    ax_t.axhline(lcl_v1, color="#6A0DAD", ls=":", lw=3, label="3σ LCL")
                                    
                                    ax_t.set_xlabel("Coil Sequence")
                                    ax_t.set_ylabel(f"{selected_label} Value")
                                    ax_t.set_title(f"{selected_label} Trend Analysis (N={n})", pad=20)
                                    ax_t.legend(loc="upper center", bbox_to_anchor=(0.5, -0.15), ncol=4, fontsize=9)
                                    apply_full_border(ax_t); plt.tight_layout(); st.pyplot(fig_t)
                                    
                                    buf_t = export_to_word([fig_t], [f"Trend Analysis - {selected_label}"])
                                    st.download_button(label=f"📥 Download Trend Chart ({selected_label})", data=buf_t, file_name=f"Trend_Report_{selected_label}.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", key=f"dl_trend_{fname}_{selected_label}")

                                with tab_dist:
                                    fig_d, ax_d = plt.subplots(figsize=(12, 6))
                                    ax_d.hist(plot_data, bins=20, density=False, alpha=0.4, color="#7FB3D5", edgecolor="black")
                                    ax_d.yaxis.set_major_locator(MaxNLocator(integer=True))
                                    ax_d.set_xlabel(f"{selected_label} Value")
                                    ax_d.set_ylabel("Coil Count")
                                    
                                    ax_pdf = ax_d.twinx()
                                    x_min_fit, x_max_fit = min(plot_data.min(), mu - 4*sigma_fixed), max(plot_data.max(), mu + 4*sigma_fixed)
                                    xs = np.linspace(x_min_fit, x_max_fit, 500)
                                    
                                    bin_w = (plot_data.max() - plot_data.min()) / 20 if plot_data.max() > plot_data.min() else 1
                                    y_vals = norm.pdf(xs, mu, sigma_fixed) * n * bin_w
                                    ax_pdf.plot(xs, y_vals, color="#1E3A8A", lw=3, label="Normal Fit")
                                    ax_pdf.set_yticks([])
                                    
                                    def add_vline_std(ax, val, color, ls, label, level=0):
                                        if val is not None:
                                            ax.axvline(val, color=color, linestyle=ls, linewidth=3, label=label)
                                            trans = ax.get_xaxis_transform()
                                            y_pos = 1.02 + (level * 0.05) 
                                            ax.text(val, y_pos, f"{val:.1f}", color=color, ha='center', va='bottom', transform=trans, fontweight='bold')

                                    # THÊM LẠI ĐẦY ĐỦ CÁC ĐƯỜNG GIỚI HẠN VÀ KIỂM SOÁT
                                    add_vline_std(ax_d, mu, "blue", "-", "Mean", 0)
                                    add_vline_std(ax_d, cust_lsl, "green", "-", "Cust LSL", 0)
                                    add_vline_std(ax_d, cust_usl, "green", "-", "Cust USL", 0)
                                    add_vline_std(ax_d, int_lsl, "red", "--", "Int LSL", 1)
                                    add_vline_std(ax_d, int_usl, "red", "--", "Int USL", 1)
                                    add_vline_std(ax_d, ucl_v1, "#6A0DAD", ":", "3σ UCL", 2) 
                                    add_vline_std(ax_d, lcl_v1, "#6A0DAD", ":", "3σ LCL", 2) 
                                    
                                    ax_d.set_title(f"{selected_label} Distribution (N={n})", pad=55)
                                    ax_d.legend(loc="upper left", bbox_to_anchor=(1, 1))
                                    apply_full_border(ax_d); plt.tight_layout(); st.pyplot(fig_d)
                                    
                                    buf_d = export_to_word([fig_d], [f"Distribution Analysis - {selected_label}"])
                                    st.download_button(label=f"📥 Download Dist Chart ({selected_label})", data=buf_d, file_name=f"Dist_Report_{selected_label}.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", key=f"dl_dist_{fname}_{selected_label}")

                            elif view_mode == "SPC Control Charts (I-MR)":
                                q1, q3 = calc_data.quantile(0.25), calc_data.quantile(0.75)
                                iqr_val = q3 - q1
                                iqr_lsl = q1 - (k_iqr * iqr_val)
                                iqr_usl = q3 + (k_iqr * iqr_val)

                                col_r1, col_r2 = st.columns(2)
                                with col_r1:
                                    st.write("**Method: Standard Deviation**")
                                    st.table(pd.DataFrame({
                                        "Metric": ["N", "Theo. Mean", "Sigma", "Prop LSL", "Prop USL"],
                                        "Value": [str(n), format_num(mu), format_num(sigma_fixed), format_num(mu - k_std*sigma_fixed), format_num(mu + k_std*sigma_fixed)]
                                    }))
                                with col_r2:
                                    st.write("**Method: IQR (Strict Standard)**")
                                    st.table(pd.DataFrame({
                                        "Metric": ["N", "IQR", "k-factor", "Prop LSL (IQR)", "Prop USL (IQR)"],
                                        "Value": [str(n), format_num(iqr_val), str(k_iqr), format_num(iqr_lsl), format_num(iqr_usl)]
                                    }))

                                fig_imr, ax_i = plt.subplots(figsize=(12, 6)) 
                                ax_i.plot(plot_data, marker="o", color="#1f77b4", label="Actual Data", alpha=0.7)
                                ax_i.axhline(mu, color="blue", ls="-", lw=2, label="Theoretical Mean")
                                
                                if int_lsl: ax_i.axhline(int_lsl, color="red", ls="--", lw=2, label="Current Int LSL")
                                if int_usl: ax_i.axhline(int_usl, color="red", ls="--", lw=2, label="Current Int USL")
                                
                                ax_i.axhline(mu + k_std*sigma_fixed, color="darkred", ls="-", label=f"Prop USL ({k_std}σ)")
                                ax_i.axhline(mu - k_std*sigma_fixed, color="darkred", ls="-", label=f"Prop LSL ({k_std}σ)")
                                ax_i.axhline(iqr_usl, color="brown", ls="--", label=f"Prop USL (IQR)")
                                ax_i.axhline(iqr_lsl, color="brown", ls="--", label=f"Prop LSL (IQR)") 
                                
                                ax_i.set_xlabel("Coil Sequence")
                                ax_i.set_ylabel(f"{selected_label} Value")
                                ax_i.set_title(f"I-Chart: Control Limit Optimization ({selected_label})", pad=20)
                                ax_i.legend(loc="upper left", bbox_to_anchor=(1, 1))
                                apply_full_border(ax_i); plt.tight_layout(); st.pyplot(fig_imr)
                                
                                buf_i = export_to_word([fig_imr], [f"SPC I-Chart Analysis - {selected_label}"])
                                st.download_button(label=f"📥 Download SPC Chart ({selected_label})", data=buf_i, file_name=f"SPC_Report_{selected_label}.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", key=f"dl_spc_{fname}_{selected_label}")
else:
    st.info("👈 Please upload the production report to start.")
