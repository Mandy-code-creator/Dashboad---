# Charts
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            st.markdown("**Yield (%) by Period & Thickness**")
            fig_y, ax_y = plt.subplots(figsize=(8, 4))
            if not yield_summary.empty:
                pivot_y = yield_summary.pivot_table(index='Time_Group', columns='Actual_Thickness', values='Yield (%)', aggfunc='mean')
                # Chỉ vẽ nếu pivot table có dữ liệu
                if not pivot_y.empty:
                    pivot_y.plot(kind='bar', ax=ax_y, colormap='Greens', edgecolor='white')
            
            ax_y.set_ylim(0, 110)
            st.pyplot(fig_y)
            
        with col_c2:
            st.markdown("**Defect Rate (%) by Period & Thickness**")
            fig_d, ax_d = plt.subplots(figsize=(8, 4))
            if not yield_summary.empty:
                pivot_d = yield_summary.pivot_table(index='Time_Group', columns='Actual_Thickness', values='Defect_Rate (%)', aggfunc='mean')
                # Chỉ vẽ nếu pivot table có dữ liệu
                if not pivot_d.empty:
                    pivot_d.plot(kind='bar', ax=ax_d, colormap='Reds', edgecolor='white')
            
            st.pyplot(fig_d)
