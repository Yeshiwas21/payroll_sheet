// Copyright (c) 2025, Yeshiwas Dagnaw and contributors
// For license information, please see license.txt

frappe.ui.form.on('Monthly Payroll', {
    onload: function (frm) {
        let grid = frm.fields_dict['summary_by_type'].grid;
        let grid2 = frm.fields_dict['monthly_payroll_totals'].grid;

        // Make the table fully read-only
        frm.fields_dict['summary_by_type'].df.read_only = 1;
        frm.fields_dict['monthly_payroll_totals'].df.read_only = 1;

    }
});
