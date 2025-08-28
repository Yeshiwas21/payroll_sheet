# Copyright (c) 2025, Yeshiwas Dagnaw and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class Payment(Document):
    def validate(self):
        self.check_duplicate_payment()

    def check_duplicate_payment(self):
        """
        Ensure the same employee does not have a payment in the same year and payroll month.
        """
        if not self.employee or not self.year or not self.payroll_month:
            return  # skip if any field is empty

        exists = frappe.db.exists(
            "Payment",
            {
                "employee": self.employee,
                "year": self.year,
                "payroll_month": self.payroll_month,
                "docstatus":["!=", 2], # Execlude Cancelled documents
                "name": ["!=", self.name]  # exclude current document
            }
        )
        if exists:
            frappe.throw(
                f"Employee <b>'{self.employee}' </b> already has a payment recorded for <b>{self.payroll_month} {self.year}</b>."
            )
