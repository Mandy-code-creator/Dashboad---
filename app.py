            actions.append(
                "Compare scrap changes against YS / TS / EL / YPE stability "
                "before attributing customer-end failure to material."
            )

        if 'matrix_data' in globals() and not matrix_data.empty:
            actions.append(
                "Use the Production-vs-Usage matrix to trace whether high-scrap "
                "events are concentrated in specific production periods, usage months, "
                "or machine-transition windows."
            )

        actions.append(
            "After corrective action, use I-MR monitoring to confirm whether the "
            "process remains stable over time."
        )

        for item in actions:
            p = doc.add_paragraph(
                style='List Bullet'
            )
            p.add_run(item)

        # ======================================================
        # 7. I-MR TRACKING -- LAST SECTION
        # ======================================================
        doc.add_heading(
            "7. I-MR Tracking (Post-Control Monitoring)",
            level=1
        )

        doc.add_paragraph(
            "I-MR is placed at the end because it is used to verify ongoing "
            "process stability after corrective actions or process-control decisions."
        )

        imr_source = df[
            df['Production_Date'].dt.year >= 2026
        ].copy()

        if 'Valid_Qty' in imr_source.columns:
            imr_source = imr_source[
                imr_source['Valid_Qty'] > 0
            ].copy()

        imr_features = [
            ('YS', 'Yield Strength'),
            ('TS', 'Tensile Strength'),
            ('EL', 'Elongation'),
            ('YPE', 'YPE'),
        ]

        imr_count = 0

        for feature, label in imr_features:
            if feature not in imr_source.columns:
                continue

            fig = _make_imr_report_figure(
                imr_source,
                feature,
                label
            )

            if fig is not None:
                doc.add_paragraph(
                    label,
                    style=None
                ).runs[0].bold = True

                _doc_add_figure(
                    doc,
                    fig,
                    width=6.8
                )
                imr_count += 1

        if imr_count == 0:
            doc.add_paragraph(
                "Insufficient 2026+ data for I-MR chart generation."
            )

        report_buffer = io.BytesIO()
        doc.save(report_buffer)
        report_buffer.seek(0)
        return report_buffer


    if st.sidebar.button(
        "Generate Full Management Report (.docx)",
        key="generate_management_word"
    ):
        try:
            management_report = build_full_management_report()

            st.sidebar.download_button(
                label="📄 Download Full Management Report",
                data=management_report.getvalue(),
                file_name="Quality_Scrap_Management_Report.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key="download_management_word",
            )

            st.sidebar.success(
                "Management report generated. SPC is excluded and I-MR is the final section."
            )
        except Exception as e:
            st.sidebar.error(
                f"Could not generate management report: {e}"
            )
