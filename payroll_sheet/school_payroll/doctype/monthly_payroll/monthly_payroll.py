# Copyright (c) 2025, Yeshiwas Dagnaw and contributors
# For license information, please see license.txt

import math
import frappe
from frappe.model.document import Document


# --- PAYE (Rwanda, monthly brackets) ---
def _paye_rwanda(gross: float) -> float:
    g = float(gross or 0)
    if g <= 60000:
        return 0.0
    if g <= 100000:
        return 0.10 * (g - 60000)
    if g <= 200000:
        return 4000 + 0.20 * (g - 100000)
    return 24000 + 0.30 * (g - 200000)


# --- Given Gross & apply_tax, compute all amounts you want to see ---
def _calc_all(gross: float, apply_tax: bool = True) -> dict:
    g = float(gross or 0)

    paye = _paye_rwanda(g) if apply_tax else 0.0
    rssb_empr = 0.08 * g   # Employer 8%
    rssb_empl = 0.06 * g   # Employee 6%
    mat_empr  = 0.006 * g  # Employer 0.6%
    mat_empl  = 0.003 * g  # Employee 0.3%

    # NOTE: Using the user's provided rule that Net Salary subtracts ALL taxes/contribs shown here.
    net_salary = g - (paye + rssb_empr + rssb_empl + mat_empr + mat_empl)

    cbhi = 0.005 * net_salary  # 0.5% of Net Salary
    take_home_2 = net_salary - cbhi

    return {
        "paye": paye,
        "rssb_employer": rssb_empr,
        "rssb_employee": rssb_empl,
        "maternity_employer": mat_empr,
        "maternity_employee": mat_empl,
        "net_salary": net_salary,
        "cbhi": cbhi,
        "take_home_2": take_home_2,
        "gross_pay": g,
    }


@frappe.whitelist()
def rwanda_gross_for_take_home(take_home: float, apply_tax: bool = True, tolerance: float = 1.0, max_iter: int = 60) -> dict:
    """
    Find the smallest Gross Pay such that Take Home 2 >= target Take Home (T).
    Returns a dict with all computed fields (rounded to 0 dec).
    - apply_tax: whether PAYE applies
    - tolerance: acceptable absolute difference in RWF in the search
    """
    T = float(take_home or 0)
    if T <= 0:
        vals = _calc_all(0.0, apply_tax=apply_tax)
        # round outputs for consistent UI
        for k in vals:
            vals[k] = round(vals[k], 0)
        vals["gross_pay"] = 0
        return vals

    # Establish an upper bound that guarantees TH2 >= T
    lo, hi = 0.0, max(T / 0.55, 200000.0)  # heuristic start
    for _ in range(30):
        if _calc_all(hi, apply_tax=apply_tax)["take_home_2"] >= T:
            break
        hi *= 2.0

    # Binary search for minimal gross meeting the target
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        th2 = _calc_all(mid, apply_tax=apply_tax)["take_home_2"]
        if abs(th2 - T) <= tolerance:
            hi = mid  # tighten upper bound
            break
        if th2 < T:
            lo = mid
        else:
            hi = mid

    # Round up to whole RWF and ensure TH2 >= T
    g = math.ceil(hi)
    vals = _calc_all(g, apply_tax=apply_tax)
    while vals["take_home_2"] < T:
        g += 1
        vals = _calc_all(g, apply_tax=apply_tax)

    # Final rounding to integers for storage
    vals["gross_pay"] = g
    for k in ("paye", "rssb_employer", "rssb_employee", "maternity_employer",
              "maternity_employee", "net_salary", "cbhi", "take_home_2"):
        vals[k] = round(vals[k], 0)
    return vals


class MonthlyPayroll(Document):

    def validate(self):
        # Prevent duplicates based on Company + Month + Year
        self.check_unique_company_month_year()

        # Calculate every child row using gross-checking against Take Home (target TH2)
        for row in (self.payroll_detail or []):  # child table fieldname
            self.calculate_row(row)

        # No duplicate employees within the same Monthly Payroll
        self.validate_duplicates()

        self.calculate_summary()
        self.calculate_totals()

    def check_unique_company_month_year(self):
        if not self.company or not self.month or not self.year:
            return  # skip if any field is empty
        exists = frappe.db.exists(
            "Monthly Payroll",
            {
                "company": self.company,
                "month": self.month,
                "year": self.year,
                "name": ["!=", self.name],  # exclude current document
            },
        )
        if exists:
            frappe.throw(
                f"A payroll for Company '{self.company}', Month '{self.month}' and Year '{self.year}' already exists."
            )

    def calculate_row(self, row):
        target_th = float(row.take_home or 0)

        # --- CASE 1: No Take Home entered ---
        if target_th <= 0:
            row.gross_pay = 0
            row.paye = 0
            row.rssb_employer = 0
            row.rssb_employee = 0
            row.maternity_employer = 0
            row.maternity_employee = 0
            row.net_salary = 0
            row.cbhi = 0
            row.take_home_2 = 0
            return

        # --- CASE 2: Apply Tax = OFF ---
        if not bool(row.apply_tax):
            # Gross = Take Home = Take Home 2
            row.gross_pay = target_th
            row.net_salary = target_th
            row.take_home_2 = target_th

            # Zero out all deductions/taxes
            row.paye = 0
            row.rssb_employer = 0
            row.rssb_employee = 0
            row.maternity_employer = 0
            row.maternity_employee = 0
            row.cbhi = 0
            return

        # --- CASE 3: Apply Tax = ON (normal calculations) ---
        vals = rwanda_gross_for_take_home(
            take_home=target_th,
            apply_tax=True,
            tolerance=1.0,
            max_iter=60,
        )

        # Push values back to the row
        row.gross_pay = vals["gross_pay"]
        row.paye = vals["paye"]
        row.rssb_employer = vals["rssb_employer"]
        row.rssb_employee = vals["rssb_employee"]
        row.maternity_employer = vals["maternity_employer"]
        row.maternity_employee = vals["maternity_employee"]
        row.net_salary = vals["net_salary"]
        row.cbhi = vals["cbhi"]
        row.take_home_2 = vals["take_home_2"]


    def validate_duplicates(self):
        seen = set()
        for row in (self.payroll_detail or []):
            if row.employee:
                if row.employee in seen:
                    frappe.throw(f"Employee '{row.employee}' is added more than once in this Monthly Payroll.")
                seen.add(row.employee)

    def calculate_summary(self):
        summary = {}
        
        # Initialize summary for each type
        types = ["Academic", "Administrative", "Support"]
        for t in types:
            summary[t] = {
                "employee_type": t,
                "employee_count": 0,
                "advance_pay": 0,
                "net_salary": 0,
                "net_minus_advance": 0,
                "cost_to_company": 0
            }

        # Aggregate data from payroll_detail
        for row in self.payroll_detail:
            t = row.employee_type
            if t in summary:
                summary[t]["employee_count"] += 1
                summary[t]["advance_pay"] += row.take_home or 0
                summary[t]["net_salary"] += row.net_salary or 0
                summary[t]["cost_to_company"] += (
                    row.gross_pay or 0
                ) + (row.rssb_employer or 0) + (row.maternity_employer or 0)

        # Calculate Net - Advance and total row
        total = {
            "employee_type": "Total",
            "employee_count": 0,
            "advance_pay": 0,
            "net_salary": 0,
            "net_minus_advance": 0,
            "cost_to_company": 0
        }

        self.summary_by_type = []  # child table field

        for t, data in summary.items():
            data["net_minus_advance"] = data["net_salary"] - data["advance_pay"]
            self.append("summary_by_type", data)
            for key in total:
                if key in data and isinstance(data[key], (int, float)):
                    total[key] += data[key]

        total["net_minus_advance"] = total["net_salary"] - total["advance_pay"]
        self.append("summary_by_type", total)
    def calculate_totals(self):
        """
        Calculate totals for the entire payroll month.
        """
        total_cost = 0
        advance_pay = 0
        net_salary = 0
        net_minus_advance = 0
        total_paye = 0
        total_rssb = 0
        total_maternity = 0
        total_cbhi = 0

        for row in self.payroll_detail:
            total_cost += row.gross_pay or 0
            advance_pay += row.take_home or 0
            net_salary += row.net_salary or 0
            total_paye += row.paye or 0
            total_rssb += (row.rssb_employee or 0) + (row.rssb_employer or 0)
            total_maternity += (row.maternity_employee or 0) + (row.maternity_employer or 0)
            total_cbhi += row.cbhi or 0

        net_minus_advance = net_salary - advance_pay
        total_taxes = total_paye + total_rssb + total_maternity + total_cbhi

        # Clear and append to the child table
        self.monthly_payroll_totals = []
        self.append("monthly_payroll_totals", {
            "total_cost": total_cost,
            "advance_pay": advance_pay,
            "net_salary": net_salary,
            "net_minus_advance": net_minus_advance,
            "total_paye": total_paye,
            "total_rssb": total_rssb,
            "total_maternity": total_maternity,
            "total_cbhi": total_cbhi,
            "total_taxes": total_taxes
        })
