import streamlit as st
import pandas as pd
import io
import base64
from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential
from supabase import create_client
from datetime import datetime
from dateutil.parser import parse as parse_date

# --- Supabase setup ---
url = "https://smupwjlilkhxqtyeouxg.supabase.co"
key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNtdXB3amxpbGtoeHF0eWVvdXhnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTAyMzM0NjEsImV4cCI6MjA2NTgwOTQ2MX0.j4ycLGc9QrPyXcso-ahanT-oKaBqXg8qSLoHJooEzYY"
supabase = create_client(url, key)

# --- Azure Form Recognizer setup ---
form_client = DocumentAnalysisClient(
    endpoint="https://idp-recognizer.cognitiveservices.azure.com/",
    credential=AzureKeyCredential("9206ec731aff4d21864f3e98e57e3af7")
)

st.set_page_config(page_title="Invoice Analyzer", layout="centered")
st.markdown("<h1 style='text-align: center;'>Invoice Analyzer</h1>", unsafe_allow_html=True)

uploaded_file = st.file_uploader(" Upload your invoice (PDF)", type=["pdf"])

if uploaded_file:
    # --- PDF Preview ---
    base64_pdf = base64.b64encode(uploaded_file.read()).decode("utf-8")
    st.markdown(
        f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="600px"></iframe>',
        unsafe_allow_html=True
    )
    uploaded_file.seek(0)

    with st.spinner("Analyzing invoice..."):
        poller = form_client.begin_analyze_document("prebuilt-invoice", document=uploaded_file)
        result = poller.result()

    # --- Editable Summary Fields ---
    st.markdown("## Invoice Summary")
    summary_fields = ["CustomerName", "VendorName", "InvoiceDate", "DueDate", "InvoiceTotal","PurchaseOrder", "SubTotal", "TotalDiscount",
    "ShippingAddress", "ShippingAddressRecipient","VendorAddress", "VendorAddressRecipient"]
    summary_data = {}
    for doc in result.documents:
        for f in summary_fields:
            val = doc.fields.get(f)
            summary_data[f] = val.value if val and val.value else ""
    edited_summary = {f: st.text_input(f, value=summary_data.get(f, "")) for f in summary_fields}

    # --- Editable Line Items ---
    st.markdown("## Line Items")
    rows = []
    for doc in result.documents:
        items = doc.fields.get("Items")
        if items:
            for i, item in enumerate(items.value):
                row = {"ItemNo": i + 1}
                for k in ["Description", "ProductCode", "Quantity", "UnitPrice", "Amount"]:
                    fld = item.value.get(k)
                    row[k] = fld.value if fld and fld.value else ""
                rows.append(row)

    df_lines = pd.DataFrame(rows)
    edited_lines = st.data_editor(df_lines, num_rows="dynamic", use_container_width=True)

    # --- Save to Supabase ---
    if st.button("Save to Supabase"):
        try:
            summary_payload = {
                "CustomerName": edited_summary["CustomerName"],
                "VendorName": edited_summary["VendorName"],
                "InvoiceDate": parse_date(edited_summary["InvoiceDate"]).date().isoformat() if edited_summary["InvoiceDate"] else None,
                "DueDate": parse_date(edited_summary["DueDate"]).date().isoformat() if edited_summary["DueDate"] else None,
                "InvoiceTotal": float(edited_summary["InvoiceTotal"]) if edited_summary["InvoiceTotal"] else None,
                "created_at": datetime.utcnow().isoformat(),
                "PurchaseOrder": edited_summary.get("PurchaseOrder"),
    "SubTotal": float(edited_summary["SubTotal"]) if edited_summary.get("SubTotal") else None,
    "TotalDiscount": float(edited_summary["TotalDiscount"]) if edited_summary.get("TotalDiscount") else None,
    "ShippingAddress": edited_summary.get("ShippingAddress"),
    "ShippingAddressRecipient": edited_summary.get("ShippingAddressRecipient"),
    "VendorAddress": edited_summary.get("VendorAddress"),
    "VendorAddressRecipient": edited_summary.get("VendorAddressRecipient"),
    "created_at": datetime.utcnow().isoformat()
            }

            resp = supabase.table("invoice_summaries").insert(summary_payload).execute()
            summary_id = resp.data[0]["id"]

            items_payload = [dict(row, summary_id=summary_id) for _, row in edited_lines.iterrows()]
            supabase.table("invoice_items").insert(items_payload).execute()

            st.success("✅ Saved to Supabase successfully!")
        except Exception as e:
            st.error(f"❌ Failed to save to Supabase: {e}")

    # --- CSV Download ---
    combined = [{**edited_summary, **row.to_dict()} for _, row in edited_lines.iterrows()]
    csv_buf = io.StringIO()
    pd.DataFrame(combined).to_csv(csv_buf, index=False)

    st.download_button(
        "⬇️ Download Combined CSV",
        data=csv_buf.getvalue(),
        file_name="invoice_data.csv",
        mime="text/csv"
    )