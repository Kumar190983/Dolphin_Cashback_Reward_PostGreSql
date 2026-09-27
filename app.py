from io import BytesIO
import ipaddress
import pandas as pd
import os
import socket
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import qrcode
import streamlit as st

st.set_page_config(page_title="Dolphin Cashback Reward", layout="wide", initial_sidebar_state="expanded")

from db import (
    get_app_settings,
    get_submission_count,
    init_db,
    list_submissions,
    mark_paid,
    save_submission,
    seed_demo_orders,
    update_app_settings,
    validate_order,
)

init_db()
seed_demo_orders()

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"


def get_local_network_host():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
            connection.connect(("8.8.8.8", 80))
            return connection.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def get_mobile_base_url():
    configured_url = os.environ.get("CUSTOMER_FORM_URL", "").strip()
    if configured_url:
        parts = urlsplit(configured_url)
        hostname = (parts.hostname or "").lower()
        try:
            address = ipaddress.ip_address(hostname)
            is_local_address = address.is_loopback or address.is_unspecified
        except ValueError:
            is_local_address = hostname == "localhost"

        if not is_local_address:
            return configured_url

        host = get_local_network_host()
        if host == "127.0.0.1":
            return configured_url
        netloc = host if parts.port is None else f"{host}:{parts.port}"
        return urlunsplit((parts.scheme or "http", netloc, parts.path, parts.query, parts.fragment))

    host = get_local_network_host()
    return f"http://{host}:{st.get_option('server.port')}"


def make_mobile_form_url(base_url):
    parts = urlsplit(base_url)
    query = dict(parse_qsl(parts.query))
    query["entry"] = "1"
    return urlunsplit((parts.scheme or "http", parts.netloc, parts.path, urlencode(query), parts.fragment))


@st.dialog("Already scanned")
def show_duplicate_scan_dialog():
    st.error(
        "You have already scanned this QR code.\n\n"
        "आप यह QR कोड पहले ही स्कैन कर चुके हैं।"
    )


def render_customer_flow():
    direct_entry = st.query_params.get("entry") == "1"
    settings = get_app_settings()
    cashback_amount = settings["cashback_amount"]
    st.title("Dolphin Cashback Reward")
    st.info(
        "**English**\n\n"
        "Please rate and review your purchased product in the Meesho app. "
        f"Then fill out this form to request ₹{cashback_amount:g} cashback to your UPI ID.\n\n"
        "**हिंदी**\n\n"
        "कृपया Meesho ऐप में खरीदे गए उत्पाद को रेटिंग और समीक्षा दें। "
        f"इसके बाद, ₹{cashback_amount:g} कैशबैक अपने UPI ID पर पाने के लिए यह फ़ॉर्म भरें।"
    )

    choice = "Yes" if direct_entry else st.radio(
        "Would you like to continue?", ["No", "Yes"], index=0, horizontal=True
    )

    if choice == "No":
        st.warning("Thanks for your time. Please review the product when you are ready.")
    else:
        with st.form("customer_form", clear_on_submit=True):
            st.subheader("Customer Details")
            order_number = st.text_input("Order Number")
            phone_number = st.text_input("Phone Number")
            upi_id = st.text_input("UPI ID")

            submitted = st.form_submit_button("Submit")

        if submitted:
            if not order_number or not phone_number or not upi_id:
                st.error("Please fill all the required fields.")
            elif not phone_number.isdigit() or len(phone_number) != 10:
                st.error("Phone number must contain exactly 10 digits.")
            elif settings["order_validation_enabled"] and not validate_order(order_number):
                st.error("Enter order number wrong")
            else:
                is_saved, message = save_submission(order_number, phone_number, upi_id)
                if is_saved:
                    st.success(message)
                else:
                    show_duplicate_scan_dialog()

    if not direct_entry:
        st.subheader("Open the form on your phone")
        base_url = st.text_input("Phone-accessible app URL", value=get_mobile_base_url())
        mobile_url = make_mobile_form_url(base_url)
        qr_column, help_column = st.columns([1, 2])
        with qr_column:
            st.image(qrcode.make(mobile_url).get_image(), caption="Scan to open the entry form")
        with help_column:
            st.caption("Scan this code with your phone camera. The form opens in your mobile browser.")
            st.code(mobile_url, language=None)


def render_admin_dashboard():
    st.title("Admin Dashboard")

    with st.form("admin_login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")

        if submitted:
            if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
                st.session_state["admin_logged_in"] = True
            else:
                st.session_state["admin_logged_in"] = False
                st.error("Invalid credentials")

    if not st.session_state.get("admin_logged_in", False):
        st.info("Use admin credentials to access the dashboard.")
        return

    submissions_tab, config_tab = st.tabs(["Submissions", "Config"])

    with submissions_tab:
        counts = get_submission_count()
        total_col, unpaid_col, paid_col = st.columns(3)
        total_col.metric("Total submissions", counts["total"])
        unpaid_col.metric("Unpaid", counts["unpaid"], f"₹{counts['unpaid_amount']:g} owed")
        paid_col.metric("Paid", counts["paid"], f"₹{counts['paid_amount']:g} paid")

        status_options = {"All": "all", "Paid": "paid", "UnPaid": "unpaid"}
        selected_status = st.selectbox("Filter status", list(status_options))
        status_filter = status_options[selected_status]
        rows = list_submissions(status_filter)
        data_columns = [
            "id",
            "order_number",
            "phone_number",
            "upi_id",
            "cashback_amount",
            "submission_date",
            "status",
        ]
        df = pd.DataFrame(rows, columns=data_columns)
        df.columns = ["ID", "Order Number", "Phone Number", "UPI ID", "Cashback (₹)", "Date", "Status"]

        if message := st.session_state.pop("bulk_paid_message", None):
            st.success(message)

        if not rows:
            st.info("No submissions found for this filter.")
        else:
            st.subheader("Submissions")
            column_widths = [0.55, 0.45, 1.1, 1.0, 1.15, 0.8, 1.45, 0.75]
            header = st.columns(column_widths)
            for column, label in zip(header, ["Select", *df.columns.tolist()]):
                column.markdown(f"**{label}**")

            selected_ids = []
            with st.form("bulk_mark_paid", clear_on_submit=True):
                for row in rows:
                    cells = st.columns(column_widths)
                    with cells[0]:
                        selected = st.checkbox(
                            f"Select submission {row['id']}",
                            key=f"select_submission_{row['id']}",
                            disabled=row["status"] == "paid",
                            label_visibility="collapsed",
                        )
                    values = [
                        row["id"],
                        row["order_number"],
                        row["phone_number"],
                        row["upi_id"],
                        f"₹{row['cashback_amount']:g}",
                        row["submission_date"],
                        row["status"].title(),
                    ]
                    for cell, value in zip(cells[1:], values):
                        cell.write(value)
                    if selected and row["status"] == "unpaid":
                        selected_ids.append(row["id"])

                mark_selected = st.form_submit_button("Mark selected as Paid", type="primary")

            if mark_selected:
                updated_count = sum(mark_paid(submission_id) for submission_id in selected_ids)
                if updated_count:
                    st.session_state["bulk_paid_message"] = (
                        f"{updated_count} submission(s) marked Paid. Paid records cannot be changed back to UnPaid."
                    )
                    st.rerun()
                st.info("Select at least one UnPaid submission.")

        excel_buffer = BytesIO()
        with pd.ExcelWriter(excel_buffer, engine="openpyxl") as excel_writer:
            df.to_excel(excel_writer, index=False, sheet_name="Submissions")
        st.download_button(
            "Download XLSX",
            data=excel_buffer.getvalue(),
            file_name=f"submissions_{status_filter}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    with config_tab:
        settings = get_app_settings()
        if st.session_state.pop("config_saved", False):
            st.success("Configuration saved.")

        with st.form("app_config"):
            cashback_amount = st.number_input(
                "Cashback amount per eligible submission (₹)",
                min_value=0.0,
                value=settings["cashback_amount"],
                step=1.0,
                format="%.2f",
            )
            order_validation_enabled = st.checkbox(
                "Validate order numbers against the approved order list",
                value=settings["order_validation_enabled"],
            )
            st.caption(
                "When enabled, only order numbers listed in the database are accepted. "
                "When disabled, any non-empty order number is accepted."
            )
            save_config = st.form_submit_button("Save configuration")

            if save_config:
                update_app_settings(cashback_amount, order_validation_enabled)
                st.session_state["config_saved"] = True
                st.rerun()


direct_entry = st.query_params.get("entry") == "1"
menu = "Customer" if direct_entry else st.sidebar.radio("Navigation", ["Customer", "Admin"])

if menu == "Customer":
    render_customer_flow()
else:
    render_admin_dashboard()
