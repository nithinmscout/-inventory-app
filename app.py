
#git config --global user.name "nithinmscout"
#git config --global user.email "nithinm.pitchside@gmail.com"

#git add .
#git commit -m "Add home tab with location card grid and locations table"
#git push origin main

#SUPABASE_URL = "https://qfboehwxfliabbrzdvls.supabase.co"
#SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFmYm9laHd4ZmxpYWJicnpkdmxzIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzI5MDk3NDQsImV4cCI6MjA4ODQ4NTc0NH0.Zh6vHvsg7eUxayBqCjfNMu2X_Pwa9pZd9ZcWPsCbK1U"

# =============================================================================
# app.py  —  Multi-Tenant Inventory Management System
# Stack   : Streamlit (frontend) + Supabase PostgreSQL (backend)
# Auth    : Supabase Auth (JWT-based) + RLS for data isolation
# Deploys : Streamlit Community Cloud (free tier)
# =============================================================================

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

import altair as alt
import pandas as pd
import plotly.express as px
import streamlit as st
from supabase import Client, create_client


# ─────────────────────────────────────────────────────────────────────────────
# 1.  PAGE CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Inventory Manager",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ─────────────────────────────────────────────────────────────────────────────
# 2.  CUSTOM CSS
# ─────────────────────────────────────────────────────────────────────────────
CUSTOM_CSS = """
<style>
/* ── Metric Cards ────────────────────────────────────────────────────────── */
div[data-testid="metric-container"] {
    background-color: #f8f9fa;
    border-radius: 8px;
    padding: 15px 20px;
    box-shadow: 0 2px 10px rgba(0,0,0,0.07);
    border-left: 4px solid #4A90D9;
    margin-bottom: 10px;
    transition: box-shadow 0.2s ease;
}
div[data-testid="metric-container"]:hover {
    box-shadow: 0 4px 18px rgba(74,144,217,0.18);
}
div[data-testid="metric-container"] label {
    color: #6c757d !important;
    font-size: 0.82rem !important;
    font-weight: 600 !important;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}

/* ── Sidebar ─────────────────────────────────────────────────────────────── */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%);
}
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] span,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] div {
    color: #cbd5e1 !important;
}
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 {
    color: #f1f5f9 !important;
}

/* ── Tab strip ───────────────────────────────────────────────────────────── */
div[data-testid="stTabs"] button[role="tab"] {
    font-weight: 600;
    font-size: 0.93rem;
    padding: 8px 18px;
}

/* ── Dataframe ───────────────────────────────────────────────────────────── */
div[data-testid="stDataFrameContainer"] {
    border-radius: 8px;
    overflow: hidden;
    box-shadow: 0 1px 6px rgba(0,0,0,0.06);
}

/* ── Location Cards hover lift ───────────────────────────────────────────── */
div[data-testid="stVerticalBlock"]
div[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 14px !important;
    transition: box-shadow 0.2s ease, transform 0.15s ease;
}
div[data-testid="stVerticalBlock"]
div[data-testid="stVerticalBlockBorderWrapper"]:hover {
    box-shadow: 0 6px 22px rgba(0,0,0,0.11) !important;
    transform: translateY(-2px);
}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# 3.  SUPABASE CLIENT
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def _init_supabase_client() -> Client:
    url: str = st.secrets["SUPABASE_URL"]
    key: str = st.secrets["SUPABASE_ANON_KEY"]
    return create_client(url, key)


supabase: Client = _init_supabase_client()


# ─────────────────────────────────────────────────────────────────────────────
# 4.  SESSION STATE BOOTSTRAP
# ─────────────────────────────────────────────────────────────────────────────
_SESSION_DEFAULTS: dict = {
    "auth_token":      None,
    "user_id":         None,
    "user_email":      None,
    "chart_selection": None,
}

for _k, _v in _SESSION_DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ─────────────────────────────────────────────────────────────────────────────
# 5.  AUTHENTICATION HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def _clear_session() -> None:
    for key in ("auth_token", "user_id", "user_email"):
        st.session_state[key] = None


def verify_session() -> bool:
    token: Optional[str] = st.session_state.get("auth_token")
    if not token:
        return False
    try:
        resp = supabase.auth.get_user(token)
        if resp and resp.user:
            st.session_state["user_id"]    = resp.user.id
            st.session_state["user_email"] = resp.user.email
            return True
        _clear_session()
        return False
    except Exception:
        _clear_session()
        return False


def _set_postgrest_auth() -> None:
    token: Optional[str] = st.session_state.get("auth_token")
    if token:
        supabase.postgrest.auth(token)


# ─────────────────────────────────────────────────────────────────────────────
# 6.  AUTH PAGE
# ─────────────────────────────────────────────────────────────────────────────
def render_auth_page() -> None:
    _, centre, _ = st.columns([1, 2, 1])
    with centre:
        st.markdown("## 📦 Inventory Manager")
        st.caption("Multi-tenant · Free Tier · Powered by Supabase + Streamlit")
        st.divider()

        tab_login, tab_register = st.tabs(["🔑 Sign In", "📝 Create Account"])

        with tab_login:
            with st.form("login_form"):
                email    = st.text_input("Email address", placeholder="you@example.com")
                password = st.text_input("Password", type="password")
                submitted = st.form_submit_button(
                    "Sign In", use_container_width=True, type="primary"
                )

            if submitted:
                if not email.strip() or not password:
                    st.error("Please enter both email and password.")
                else:
                    try:
                        resp = supabase.auth.sign_in_with_password(
                            {"email": email.strip(), "password": password}
                        )
                        if resp.session:
                            st.session_state["auth_token"] = resp.session.access_token
                            st.session_state["user_id"]    = resp.user.id
                            st.session_state["user_email"] = resp.user.email
                            st.success("✅ Signed in! Loading your dashboard…")
                            st.rerun()
                        else:
                            st.error("Sign-in failed. Please check your credentials.")
                    except Exception as exc:
                        st.error(f"Sign-in error: {exc}")

        with tab_register:
            with st.form("register_form"):
                reg_email   = st.text_input("Email address", placeholder="you@example.com", key="reg_email")
                reg_pass    = st.text_input("Password (min 6 chars)", type="password", key="reg_pass")
                reg_confirm = st.text_input("Confirm password", type="password", key="reg_confirm")
                reg_submitted = st.form_submit_button(
                    "Create Account", use_container_width=True, type="primary"
                )

            if reg_submitted:
                if not reg_email.strip() or not reg_pass:
                    st.error("All fields are required.")
                elif reg_pass != reg_confirm:
                    st.error("Passwords do not match.")
                elif len(reg_pass) < 6:
                    st.error("Password must be at least 6 characters.")
                else:
                    try:
                        resp = supabase.auth.sign_up(
                            {"email": reg_email.strip(), "password": reg_pass}
                        )
                        if resp.user:
                            # Seed default household locations for new accounts
                            _seed_default_locations(resp.user.id)
                            st.success(
                                "🎉 Account created! "
                                "Check your email to confirm, then sign in."
                            )
                        else:
                            st.error("Registration failed. Try a different email.")
                    except Exception as exc:
                        st.error(f"Registration error: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# 7.  DATA ACCESS LAYER
# ─────────────────────────────────────────────────────────────────────────────
def fetch_inventory() -> pd.DataFrame:
    try:
        _set_postgrest_auth()
        resp = (
            supabase.table("inventory")
            .select(
                "id, item_name, category, quantity, custom_unit, description, "
                "expiry_date, estimated_value, warranty_until, "
                "location_id, created_at, updated_at"
            )
            .order("created_at", desc=True)
            .execute()
        )
        if resp.data:
            df = pd.DataFrame(resp.data)
            df["quantity"]         = pd.to_numeric(df["quantity"],         errors="coerce").fillna(0)
            df["estimated_value"]  = pd.to_numeric(df["estimated_value"],  errors="coerce")
            df["expiry_date"]      = pd.to_datetime(df["expiry_date"],     errors="coerce")
            df["warranty_until"]   = pd.to_datetime(df["warranty_until"],  errors="coerce")
            return df
        return pd.DataFrame(columns=[
            "id", "item_name", "category", "quantity", "custom_unit",
            "description", "expiry_date", "estimated_value",
            "warranty_until", "location_id", "created_at", "updated_at",
        ])
    except Exception as exc:
        st.error(f"Failed to load inventory: {exc}")
        return pd.DataFrame()


def fetch_locations() -> pd.DataFrame:
    """Returns all location rows for the authenticated user."""
    try:
        _set_postgrest_auth()
        resp = (
            supabase.table("locations")
            .select("id, name, icon, color, description, created_at")
            .order("created_at", desc=False)
            .execute()
        )
        if resp.data:
            return pd.DataFrame(resp.data)
        return pd.DataFrame(
            columns=["id", "name", "icon", "color", "description", "created_at"]
        )
    except Exception as exc:
        st.error(f"Failed to load locations: {exc}")
        return pd.DataFrame()


def fetch_preferences() -> dict:
    _default_layout: dict = {
        "show_total_items":    True,
        "show_total_quantity": True,
        "show_low_stock":      True,
    }
    try:
        _set_postgrest_auth()
        resp = (
            supabase.table("user_preferences")
            .select("*")
            .eq("user_id", st.session_state["user_id"])
            .maybe_single()
            .execute()
        )
        if resp.data:
            layout = resp.data.get("dashboard_layout", _default_layout)
            if isinstance(layout, str):
                layout = json.loads(layout)
            resp.data["dashboard_layout"] = layout
            return resp.data
        return {"theme": "system", "dashboard_layout": _default_layout}
    except Exception as exc:
        st.toast(f"Could not load preferences: {exc}", icon="⚠️")
        return {"theme": "system", "dashboard_layout": _default_layout}


def upsert_preferences(prefs: dict) -> bool:
    try:
        _set_postgrest_auth()
        supabase.table("user_preferences").upsert(
            {
                "user_id":          st.session_state["user_id"],
                "theme":            prefs.get("theme", "system"),
                "dashboard_layout": prefs.get("dashboard_layout", {}),
            },
            on_conflict="user_id",
        ).execute()
        return True
    except Exception as exc:
        st.error(f"Failed to save preferences: {exc}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 8.  LOCATION COLOUR PALETTE
# ─────────────────────────────────────────────────────────────────────────────
_CARD_COLOURS: dict[str, str] = {
    "Teal":   "#ccfbf1",
    "Blue":   "#dbeafe",
    "Green":  "#dcfce7",
    "Purple": "#ede9fe",
    "Yellow": "#fef9c3",
    "Pink":   "#fce7f3",
    "Orange": "#ffedd5",
    "Grey":   "#f1f5f9",
}

# ── Item category taxonomy ────────────────────────────────────────────────────
_CATEGORIES = [
    "Consumables",
    "Toiletries",
    "Electronics",
    "Appliances",
    "Valuables",
    "Furniture",
    "Clothing",
    "Other",
]
_EXPIRY_CATS   = {"Consumables", "Toiletries"}
_WARRANTY_CATS = {"Electronics", "Appliances", "Valuables"}

# ── Default locations seeded for every new user ───────────────────────────────
_DEFAULT_LOCATIONS = [
    {"name": "Kitchen",        "icon": "🍳", "color": "#fef9c3"},
    {"name": "Living Room",    "icon": "🛋️", "color": "#dbeafe"},
    {"name": "Master Bedroom", "icon": "🛏️", "color": "#ede9fe"},
    {"name": "Guest Bathroom", "icon": "🚿", "color": "#ccfbf1"},
    {"name": "Garage",         "icon": "🚗", "color": "#f1f5f9"},
    {"name": "Attic",          "icon": "📦", "color": "#ffedd5"},
]

def _seed_default_locations(user_id: str) -> None:
    """
    Writes the standard household location set for a brand-new user.
    Called immediately after supabase.auth.sign_up() succeeds.
    Uses a service-role-style insert; the RLS INSERT policy allows it
    because we pass the user's own ID.
    """
    try:
        rows = [
            {
                "user_id":     user_id,
                "name":        loc["name"],
                "icon":        loc["icon"],
                "color":       loc["color"],
                "description": None,
            }
            for loc in _DEFAULT_LOCATIONS
        ]
        supabase.table("locations").insert(rows).execute()
    except Exception:
        pass  # Non-fatal — user can add locations manually


# ─────────────────────────────────────────────────────────────────────────────
# 9.  LOCATION DIALOGS
# ─────────────────────────────────────────────────────────────────────────────
@st.dialog("📍 Add Location", width="large")
def dialog_add_location() -> None:
    st.caption("Locations are rooms or storage areas — e.g. Kitchen Shelf 1, Wardrobe.")

    col_a, col_b = st.columns(2)
    with col_a:
        name = st.text_input("Location Name *", placeholder="e.g. Kitchen Shelf 1")
    with col_b:
        icon = st.text_input(
            "Icon (emoji)", value="📦", max_chars=4,
            help="Paste a single emoji as the card icon."
        )

    colour_label = st.selectbox("Card Colour", options=list(_CARD_COLOURS.keys()), index=0)
    description  = st.text_area("Description (optional)", height=80)

    chosen_hex = _CARD_COLOURS[colour_label]
    st.markdown(
        f"""
        <div style="background:{chosen_hex};border-radius:12px;padding:16px 20px;
                    border:1px solid rgba(0,0,0,0.06);margin-top:8px;">
            <span style="font-size:1.5rem">{icon or '📦'}</span>
            <span style="font-weight:700;font-size:1.1rem;margin-left:10px;">
                {name or 'Location Name'}
            </span>
            <p style="color:#64748b;font-size:0.85rem;margin:4px 0 0 0;">
                {description or 'No description'}
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.divider()
    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button("💾 Save Location", type="primary", use_container_width=True):
            if not name.strip():
                st.error("Location Name is required.")
                return
            try:
                _set_postgrest_auth()
                supabase.table("locations").insert({
                    "user_id":     st.session_state["user_id"],
                    "name":        name.strip(),
                    "icon":        icon.strip() or "📦",
                    "color":       chosen_hex,
                    "description": description.strip() or None,
                }).execute()
                st.toast("📍 Location added!", icon="✅")
                st.rerun()
            except Exception as exc:
                st.error(f"Failed to add location: {exc}")
    with col_cancel:
        if st.button("Cancel", use_container_width=True):
            st.rerun()


@st.dialog("✏️ Edit Location", width="large")
def dialog_edit_location(loc: dict) -> None:
    col_a, col_b = st.columns(2)
    with col_a:
        name = st.text_input("Location Name *", value=loc.get("name", ""))
    with col_b:
        icon = st.text_input("Icon (emoji)", value=loc.get("icon", "📦"), max_chars=4)

    stored_hex    = loc.get("color", "#ccfbf1")
    hex_to_label  = {v: k for k, v in _CARD_COLOURS.items()}
    current_label = hex_to_label.get(stored_hex, "Teal")
    colour_label  = st.selectbox(
        "Card Colour",
        options=list(_CARD_COLOURS.keys()),
        index=list(_CARD_COLOURS.keys()).index(current_label),
    )
    description = st.text_area(
        "Description (optional)", value=loc.get("description") or "", height=80
    )

    st.divider()
    col_update, col_cancel = st.columns(2)
    with col_update:
        if st.button("💾 Update", type="primary", use_container_width=True):
            if not name.strip():
                st.error("Location Name is required.")
                return
            try:
                _set_postgrest_auth()
                supabase.table("locations").update({
                    "name":        name.strip(),
                    "icon":        icon.strip() or "📦",
                    "color":       _CARD_COLOURS[colour_label],
                    "description": description.strip() or None,
                }).eq("id", loc["id"]).execute()
                st.toast("✅ Location updated!", icon="✏️")
                st.rerun()
            except Exception as exc:
                st.error(f"Update failed: {exc}")
    with col_cancel:
        if st.button("Cancel", use_container_width=True):
            st.rerun()


@st.dialog("🗑️ Delete Location")
def dialog_delete_location(loc_id: str, loc_name: str) -> None:
    st.warning(
        f"Delete **{loc_name}**? Items assigned here become **Unassigned** "
        "(not deleted). This cannot be undone."
    )
    col_del, col_cancel = st.columns(2)
    with col_del:
        if st.button("🗑️ Yes, Delete", type="primary", use_container_width=True):
            try:
                _set_postgrest_auth()
                supabase.table("locations").delete().eq("id", loc_id).execute()
                st.toast(f"🗑️ '{loc_name}' removed.", icon="✅")
                st.rerun()
            except Exception as exc:
                st.error(f"Deletion failed: {exc}")
    with col_cancel:
        if st.button("Cancel", use_container_width=True):
            st.rerun()

@st.dialog("⚠️ Delete Account")
def dialog_delete_account() -> None:
    st.error(
        "**This is permanent and cannot be undone.**\n\n"
        "Deleting your account will remove:\n"
        "- All inventory items\n"
        "- All locations\n"
        "- Your preferences\n"
        "- Your login credentials"
    )
    st.divider()
    st.caption("Type **DELETE** below to confirm.")
    confirmation = st.text_input("Confirmation", placeholder="Type DELETE here", label_visibility="collapsed")

    col_del, col_cancel = st.columns(2)
    with col_del:
        if st.button("🗑️ Permanently Delete Account", type="primary", use_container_width=True):
            if confirmation.strip() != "DELETE":
                st.error("You must type DELETE exactly to confirm.")
                return
            try:
                _set_postgrest_auth()
                supabase.rpc("delete_user_account").execute()
                _clear_session()
                st.toast("Account deleted.", icon="🗑️")
                st.rerun()
            except Exception as exc:
                st.error(f"Deletion failed: {exc}")
    with col_cancel:
        if st.button("Cancel", use_container_width=True):
            st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# 10.  INVENTORY ITEM DIALOGS  (Add / Edit / Delete)
# ─────────────────────────────────────────────────────────────────────────────
@st.dialog("➕ Add Inventory Item", width="large")
def dialog_add_item() -> None:
    st.caption("All fields marked * are required.")

    locs_df     = fetch_locations()
    loc_options = {"— None —": None}
    if not locs_df.empty:
        for _, r in locs_df.iterrows():
            loc_options[f"{r['icon']} {r['name']}"] = r["id"]

    col_a, col_b = st.columns(2)
    with col_a:
        item_name = st.text_input("Item Name *", placeholder="e.g. Rice Bag")
    with col_b:
        category = st.selectbox("Category *", options=_CATEGORIES)

    col_c, col_d = st.columns(2)
    with col_c:
        quantity = st.number_input("Quantity *", min_value=0.0, step=1.0, value=1.0)
    with col_d:
        custom_unit = st.text_input("Unit", placeholder="e.g. pcs, kg")

    col_e, col_f = st.columns(2)
    with col_e:
        loc_label   = st.selectbox("Location", options=list(loc_options.keys()))
        location_id = loc_options[loc_label]
    with col_f:
        st.empty()

    # ── Conditional fields based on category ─────────────────────────────
    expiry_date     = None
    estimated_value = None
    warranty_until  = None

    if category in _EXPIRY_CATS:
        st.divider()
        st.caption("🗓️ Perishable fields")
        expiry_date = st.date_input(
            "Expiry Date",
            value=None,
            min_value=datetime.now(timezone.utc).date(),
            help="Leave blank if not applicable.",
        )

    if category in _WARRANTY_CATS:
        st.divider()
        st.caption("💰 Asset fields")
        col_v, col_w = st.columns(2)
        with col_v:
            estimated_value = st.number_input(
                "Estimated Value (£)", min_value=0.0, step=1.0, value=0.0,
                help="Used for insurance ledger calculations."
            )
            if estimated_value == 0.0:
                estimated_value = None
        with col_w:
            warranty_until = st.date_input(
                "Warranty Until",
                value=None,
                min_value=datetime.now(timezone.utc).date(),
            )

    description = st.text_area("Description / Notes", placeholder="Optional…", height=80)

    st.divider()
    col_save, col_cancel = st.columns(2)

    with col_save:
        if st.button("💾 Save Item", type="primary", use_container_width=True):
            if not item_name.strip():
                st.error("Item Name is required.")
                return
            try:
                _set_postgrest_auth()
                supabase.table("inventory").insert({
                    "user_id":          st.session_state["user_id"],
                    "item_name":        item_name.strip(),
                    "category":         category,
                    "quantity":         float(quantity),
                    "custom_unit":      custom_unit.strip() or None,
                    "description":      description.strip() or None,
                    "location_id":      location_id,
                    "expiry_date":      expiry_date.isoformat() if expiry_date else None,
                    "estimated_value":  estimated_value,
                    "warranty_until":   warranty_until.isoformat() if warranty_until else None,
                }).execute()
                st.toast("✅ Item added!", icon="📦")
                st.rerun()
            except Exception as exc:
                st.error(f"Failed to add item: {exc}")

    with col_cancel:
        if st.button("Cancel", use_container_width=True):
            st.rerun()


@st.dialog("✏️ Edit Inventory Item", width="large")
def dialog_edit_item(row: dict) -> None:
    st.caption(f"Editing item: **{row.get('item_name', '')}**")

    locs_df     = fetch_locations()
    loc_options = {"— None —": None}
    if not locs_df.empty:
        for _, r in locs_df.iterrows():
            loc_options[f"{r['icon']} {r['name']}"] = r["id"]

    current_loc_id    = row.get("location_id")
    loc_id_to_label   = {v: k for k, v in loc_options.items()}
    current_loc_label = loc_id_to_label.get(current_loc_id, "— None —")
    loc_keys          = list(loc_options.keys())
    loc_index         = loc_keys.index(current_loc_label) if current_loc_label in loc_keys else 0

    current_cat = row.get("category") or _CATEGORIES[0]
    cat_index   = _CATEGORIES.index(current_cat) if current_cat in _CATEGORIES else 0

    col_a, col_b = st.columns(2)
    with col_a:
        item_name = st.text_input("Item Name *", value=row.get("item_name", ""))
    with col_b:
        category = st.selectbox("Category *", options=_CATEGORIES, index=cat_index)

    col_c, col_d = st.columns(2)
    with col_c:
        quantity = st.number_input(
            "Quantity *", min_value=0.0, step=1.0,
            value=float(row.get("quantity", 0)),
        )
    with col_d:
        custom_unit = st.text_input("Unit", value=row.get("custom_unit") or "")

    col_e, col_f = st.columns(2)
    with col_e:
        loc_label   = st.selectbox("Location", options=loc_keys, index=loc_index)
        location_id = loc_options[loc_label]
    with col_f:
        st.empty()

    # ── Conditional fields ────────────────────────────────────────────────
    expiry_date     = None
    estimated_value = None
    warranty_until  = None

    if category in _EXPIRY_CATS:
        st.divider()
        st.caption("🗓️ Perishable fields")
        existing_expiry = row.get("expiry_date")
        if isinstance(existing_expiry, str):
            try:
                existing_expiry = datetime.fromisoformat(existing_expiry).date()
            except Exception:
                existing_expiry = None
        elif hasattr(existing_expiry, "date"):
            existing_expiry = existing_expiry.date()
        expiry_date = st.date_input("Expiry Date", value=existing_expiry)

    if category in _WARRANTY_CATS:
        st.divider()
        st.caption("💰 Asset fields")
        existing_warranty = row.get("warranty_until")
        if isinstance(existing_warranty, str):
            try:
                existing_warranty = datetime.fromisoformat(existing_warranty).date()
            except Exception:
                existing_warranty = None
        elif hasattr(existing_warranty, "date"):
            existing_warranty = existing_warranty.date()

        col_v, col_w = st.columns(2)
        with col_v:
            estimated_value = st.number_input(
                "Estimated Value (£)", min_value=0.0, step=1.0,
                value=float(row.get("estimated_value") or 0.0),
            )
            if estimated_value == 0.0:
                estimated_value = None
        with col_w:
            warranty_until = st.date_input("Warranty Until", value=existing_warranty)

    description = st.text_area(
        "Description / Notes", value=row.get("description") or "", height=80
    )

    st.divider()
    col_update, col_cancel = st.columns(2)

    with col_update:
        if st.button("💾 Update Item", type="primary", use_container_width=True):
            if not item_name.strip():
                st.error("Item Name is required.")
                return
            try:
                _set_postgrest_auth()
                supabase.table("inventory").update({
                    "item_name":        item_name.strip(),
                    "category":         category,
                    "quantity":         float(quantity),
                    "custom_unit":      custom_unit.strip() or None,
                    "description":      description.strip() or None,
                    "location_id":      location_id,
                    "expiry_date":      expiry_date.isoformat() if expiry_date else None,
                    "estimated_value":  estimated_value,
                    "warranty_until":   warranty_until.isoformat() if warranty_until else None,
                    "updated_at":       datetime.now(timezone.utc).isoformat(),
                }).eq("id", row["id"]).execute()
                st.toast("✅ Item updated!", icon="✏️")
                st.rerun()
            except Exception as exc:
                st.error(f"Update failed: {exc}")

    with col_cancel:
        if st.button("Cancel", use_container_width=True):
            st.rerun()



@st.dialog("🗑️ Confirm Deletion")
def dialog_confirm_delete(ids: list[str], names: list[str]) -> None:
    st.warning(
        f"You are about to **permanently delete {len(ids)} item(s)**. "
        "This cannot be undone."
    )
    for name in names[:10]:
        st.markdown(f"- `{name}`")
    if len(names) > 10:
        st.markdown(f"_…and {len(names) - 10} more._")

    st.divider()
    col_del, col_cancel = st.columns(2)

    with col_del:
        if st.button("🗑️ Yes, Delete", type="primary", use_container_width=True):
            try:
                _set_postgrest_auth()
                supabase.table("inventory").delete().in_("id", ids).execute()
                st.toast(f"🗑️ Deleted {len(ids)} item(s).", icon="✅")
                st.rerun()
            except Exception as exc:
                st.error(f"Deletion failed: {exc}")

    with col_cancel:
        if st.button("Cancel", use_container_width=True):
            st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# 11.  SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────
def render_sidebar(prefs: dict, df: pd.DataFrame) -> None:
    with st.sidebar:
        st.markdown("## 📦 Inventory Manager")
        st.caption("Multi-tenant · Free Tier")
        st.divider()

        email: str = st.session_state.get("user_email", "")
        uid: str   = st.session_state.get("user_id", "")

        st.markdown("**Signed in as**")
        st.markdown(f"📧 `{email}`")
        st.markdown(f"🔑 `{uid[:8]}…`" if uid else "")

        st.divider()

        # ── Dashboard Settings ─────────────────────────────────────────────
        with st.expander("⚙️ Dashboard Settings", expanded=False):
            layout: dict = prefs.get("dashboard_layout", {})

            show_items = st.toggle(
                "Total Distinct Items",
                value=layout.get("show_total_items", True),
                key="s_show_items",
            )
            show_qty = st.toggle(
                "Total Aggregate Quantity",
                value=layout.get("show_total_quantity", True),
                key="s_show_qty",
            )
            show_low = st.toggle(
                "Low Stock Alerts",
                value=layout.get("show_low_stock", True),
                key="s_show_low",
            )

            theme_options = ["system", "light", "dark"]
            current_theme = prefs.get("theme", "system")
            theme_index   = theme_options.index(current_theme) if current_theme in theme_options else 0
            theme = st.selectbox(
                "Theme", options=theme_options, index=theme_index, key="s_theme"
            )

            if st.button("💾 Save Settings", type="primary", use_container_width=True):
                new_prefs = {
                    "theme": theme,
                    "dashboard_layout": {
                        "show_total_items":    show_items,
                        "show_total_quantity": show_qty,
                        "show_low_stock":      show_low,
                    },
                }
                if upsert_preferences(new_prefs):
                    st.toast("✅ Settings saved!", icon="💾")
                    st.rerun()

        st.divider()

        # ── Account ────────────────────────────────────────────────────────
        with st.expander("👤 Account", expanded=False):
            st.markdown("**Email:**")
            st.code(email, language=None)
            st.markdown("**User ID:**")
            st.code(uid, language=None)
            st.caption("Your UUID is the RLS isolation key at the database level.")

            st.divider()

            # ── Export CSV ─────────────────────────────────────────────────
            if not df.empty:
                export_df = df.drop(columns=["id", "location_id"], errors="ignore").copy()
                # Format dates for readability
                for col in ["expiry_date", "warranty_until", "created_at", "updated_at"]:
                    if col in export_df.columns:
                        export_df[col] = pd.to_datetime(export_df[col], errors="coerce").dt.strftime("%d/%m/%Y")
                csv_bytes = export_df.to_csv(index=False).encode("utf-8")
                st.download_button(
                    label="📥 Export Inventory as CSV",
                    data=csv_bytes,
                    file_name=f"inventory_export_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
            else:
                st.caption("No data to export yet.")

            st.divider()

            # ── Delete Account ─────────────────────────────────────────────
            if st.button(
                "🗑️ Delete My Account",
                use_container_width=True,
                type="primary",
                help="Permanently deletes your account and all data.",
            ):
                dialog_delete_account()

        st.divider()

        if st.button("🚪 Sign Out", use_container_width=True, type="primary"):
            try:
                supabase.auth.sign_out()
            except Exception:
                pass
            _clear_session()
            st.rerun()

        st.divider()
        st.caption("Built with Streamlit + Supabase")

# ─────────────────────────────────────────────────────────────────────────────
# 12.  HOME TAB  —  Location Card Grid
# ─────────────────────────────────────────────────────────────────────────────
_CARDS_PER_ROW = 4


def _location_card(col, loc: dict, loc_items: pd.DataFrame) -> None:
    """Renders a single location card with an expandable item list."""
    with col:
        bg    = loc.get("color", "#e0f2fe")
        icon  = loc.get("icon",  "📦")
        name  = loc.get("name",  "Location")
        count = len(loc_items)

        if not loc_items.empty:
            preview = ", ".join(loc_items["item_name"].head(3).tolist())
            if count > 3:
                preview += f" +{count - 3} more"
        else:
            preview = "No items yet"

        # Coloured card header
        st.markdown(
            f"""
            <div style="
                background:{bg};
                border-radius:12px 12px 0 0;
                padding:14px 16px 10px 16px;
                border:1px solid rgba(0,0,0,0.07);
                border-bottom:none;">
                <div style="display:flex;justify-content:space-between;
                            align-items:center;">
                    <span style="font-size:1.4rem">{icon}</span>
                    <span style="font-size:0.75rem;color:#64748b;
                                 background:rgba(255,255,255,0.65);
                                 border-radius:20px;padding:2px 8px;">
                        {count} item{'s' if count != 1 else ''}
                    </span>
                </div>
                <p style="font-weight:700;font-size:1rem;
                          margin:6px 0 2px 0;color:#0f172a;">{name}</p>
                <p style="color:#64748b;font-size:0.82rem;margin:0;
                          white-space:nowrap;overflow:hidden;
                          text-overflow:ellipsis;">{preview}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Expandable item list
        with st.container(border=True):
            with st.expander("▾ View items", expanded=False):
                if loc_items.empty:
                    st.caption("No items assigned to this location.")
                else:
                    for _, item in loc_items.iterrows():
                        unit = item.get("custom_unit") or ""
                        qty  = (
                            f"{item['quantity']:.0f}"
                            if item["quantity"] == int(item["quantity"])
                            else f"{item['quantity']:.2f}"
                        )
                        st.markdown(f"• **{item['item_name']}** — {qty} {unit}".strip())

                st.divider()
                btn_edit, btn_del = st.columns(2)
                with btn_edit:
                    if st.button(
                        "✏️ Edit", key=f"edit_loc_{loc['id']}",
                        use_container_width=True,
                    ):
                        dialog_edit_location(loc)
                with btn_del:
                    if st.button(
                        "🗑️ Delete", key=f"del_loc_{loc['id']}",
                        use_container_width=True,
                    ):
                        dialog_delete_location(loc["id"], loc["name"])


def render_home_tab(df: pd.DataFrame, locations_df: pd.DataFrame) -> None:
    """
    Card-grid home overview.
    Each card = one location; clicking ▾ expands the item list in place.
    Below the grid: flat summary table of all items across all locations.
    """
    col_hdr, col_add = st.columns([5, 1])
    with col_hdr:
        st.subheader("🏠 Home Overview")
    with col_add:
        if st.button("📍 Add Location", type="primary", use_container_width=True):
            dialog_add_location()

    if locations_df.empty:
        st.info(
            "No locations yet. Click **📍 Add Location** to create rooms or "
            "storage areas (e.g. Kitchen Shelf 1, Wardrobe)."
        )
        return

    locs = locations_df.to_dict("records")

    # Card grid
    for row_start in range(0, len(locs), _CARDS_PER_ROW):
        row_locs = locs[row_start : row_start + _CARDS_PER_ROW]
        cols     = st.columns(_CARDS_PER_ROW)

        for col, loc in zip(cols, row_locs):
            if not df.empty and "location_id" in df.columns:
                loc_items = df[df["location_id"] == loc["id"]].copy()
            else:
                loc_items = pd.DataFrame()
            _location_card(col, loc, loc_items)

        st.write("")  # Row spacing

    # Unassigned items
    if not df.empty and "location_id" in df.columns:
        unassigned = df[df["location_id"].isna()].copy()
        if not unassigned.empty:
            st.divider()
            with st.expander(
                f"📦 Unassigned Items ({len(unassigned)})", expanded=False
            ):
                for _, item in unassigned.iterrows():
                    unit = item.get("custom_unit") or ""
                    qty  = f"{item['quantity']:.0f}"
                    st.markdown(f"• **{item['item_name']}** — {qty} {unit}".strip())

    # Summary table
    st.divider()
    st.subheader("📋 All Items by Location")

    if df.empty:
        st.info("No inventory items yet.")
        return

    loc_lookup = (
        {r["id"]: f"{r['icon']} {r['name']}" for r in locations_df.to_dict("records")}
        if not locations_df.empty
        else {}
    )

    summary = df[
        ["item_name", "quantity", "custom_unit", "location_id", "updated_at"]
    ].copy()
    summary["Location"] = summary["location_id"].map(loc_lookup).fillna("📦 Unassigned")
    summary = summary.drop(columns=["location_id"])
    summary = summary.rename(columns={
        "item_name":   "Item",
        "quantity":    "Quantity",
        "custom_unit": "Unit",
        "updated_at":  "Last Updated",
    })
    summary = summary.sort_values(["Location", "Item"]).reset_index(drop=True)

    st.dataframe(
        summary[["Location", "Item", "Quantity", "Unit", "Last Updated"]],
        use_container_width=True,
        hide_index=True,
        column_config={
            "Quantity":     st.column_config.NumberColumn(format="%.2f"),
            "Last Updated": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm"),
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# 13.  DASHBOARD TAB
# ─────────────────────────────────────────────────────────────────────────────
def render_dashboard(df: pd.DataFrame, prefs: dict, locations_df: pd.DataFrame) -> None:
    layout: dict = prefs.get("dashboard_layout", {})

    # ── KPI Metrics ───────────────────────────────────────────────────────
    st.subheader("📊 Key Metrics")

    total_items:    int   = len(df)
    total_quantity: float = float(df["quantity"].sum()) if not df.empty else 0.0
    low_stock:      int   = int((df["quantity"] < 5).sum()) if not df.empty else 0

    active: list[tuple] = []
    if layout.get("show_total_items", True):
        active.append(("Total Distinct Items", total_items, None))
    if layout.get("show_total_quantity", True):
        active.append(("Total Aggregate Quantity", f"{total_quantity:,.1f}", None))
    if layout.get("show_low_stock", True):
        active.append((
            "⚠️ Low Stock (qty < 5)", low_stock,
            "items need restocking" if low_stock else "All stocked",
        ))

    if active:
        metric_cols = st.columns(len(active))
        for col, (label, value, help_text) in zip(metric_cols, active):
            with col:
                st.metric(label=label, value=value, help=help_text)
    else:
        st.info("All metrics are hidden. Enable them in ⚙️ Settings.")

    st.divider()

    if df.empty:
        st.info("📭 Your inventory is empty — add items in the 📦 Inventory tab!")
        return

    # ── Expiry Radar ──────────────────────────────────────────────────────
    st.subheader("🚨 Expiry Radar — Next 30 Days")
    st.caption("Items from Consumables and Toiletries categories expiring soon.")

    today     = pd.Timestamp.now(tz="UTC").normalize()
    in_30     = today + pd.Timedelta(days=30)

    if "expiry_date" in df.columns:
        expiry_df = df[df["expiry_date"].notna()].copy()
        expiry_df["expiry_date"] = pd.to_datetime(expiry_df["expiry_date"], utc=True, errors="coerce")
        expiry_df = expiry_df[
            (expiry_df["expiry_date"] >= today) &
            (expiry_df["expiry_date"] <= in_30)
        ].sort_values("expiry_date")
    else:
        expiry_df = pd.DataFrame()

    if expiry_df.empty:
        st.success("✅ Nothing expiring in the next 30 days.")
    else:
        st.warning(f"⚠️ {len(expiry_df)} item(s) expiring within 30 days.")

        # Build location lookup
        loc_lookup = (
            {r["id"]: f"{r['icon']} {r['name']}" for r in locations_df.to_dict("records")}
            if not locations_df.empty else {}
        )

        radar_display = expiry_df[
            ["item_name", "category", "quantity", "custom_unit",
             "expiry_date", "location_id"]
        ].copy()
        radar_display["Location"]    = radar_display["location_id"].map(loc_lookup).fillna("Unassigned")
        radar_display["Days Left"]   = (
            radar_display["expiry_date"] - today
        ).dt.days
        radar_display = radar_display.rename(columns={
            "item_name":   "Item",
            "category":    "Category",
            "quantity":    "Qty",
            "custom_unit": "Unit",
            "expiry_date": "Expires On",
        })[["Item", "Category", "Location", "Qty", "Unit", "Expires On", "Days Left"]]

        st.dataframe(
            radar_display,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Expires On":  st.column_config.DatetimeColumn(format="DD/MM/YYYY"),
                "Days Left":   st.column_config.NumberColumn(format="%d days"),
                "Qty":         st.column_config.NumberColumn(format="%.0f"),
            },
        )

    st.divider()

    # ── Insurance Ledger ──────────────────────────────────────────────────
    st.subheader("🏦 Value by Location")
    st.caption("Sum of estimated values for Electronics, Appliances, and Valuables.")

    if "estimated_value" in df.columns:
        asset_df = df[df["estimated_value"].notna() & (df["estimated_value"] > 0)].copy()
    else:
        asset_df = pd.DataFrame()

    if asset_df.empty:
        st.info("No asset values recorded yet. Add estimated values when logging Electronics, Appliances, or Valuables.")
    else:
        loc_lookup = (
            {r["id"]: f"{r['icon']} {r['name']}" for r in locations_df.to_dict("records")}
            if not locations_df.empty else {}
        )
        asset_df["Location"] = asset_df["location_id"].map(loc_lookup).fillna("📦 Unassigned")

        ledger = (
            asset_df.groupby("Location")["estimated_value"]
            .sum()
            .reset_index()
            .rename(columns={"estimated_value": "Total Value (£)"})
            .sort_values("Total Value (£)", ascending=False)
        )

        total_value = ledger["Total Value (£)"].sum()

        # Top metric
        st.metric("💷 Total Household Asset Value", f"£{total_value:,.2f}")

        col_tbl, col_chart = st.columns([1, 1])
        with col_tbl:
            ledger_display = ledger.copy()
            ledger_display["Total Value (£)"] = ledger_display["Total Value (£)"].apply(
                lambda x: f"£{x:,.2f}"
            )
            st.dataframe(ledger_display, use_container_width=True, hide_index=True)

        with col_chart:
            fig = px.bar(
                ledger,
                x="Location",
                y="Total Value (£)",
                color="Location",
                color_discrete_sequence=px.colors.qualitative.Set2,
                text_auto=".2s",
            )
            fig.update_layout(
                showlegend=False,
                height=300,
                margin=dict(t=20, b=10, l=10, r=10),
                xaxis_title=None,
            )
            fig.update_traces(textposition="outside")
            st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ── Altair bar chart ──────────────────────────────────────────────────
    st.subheader("📊 Quantity by Item")

    chart_df          = df[["item_name", "quantity"]].copy()
    chart_df.columns  = ["Item", "Quantity"]
    selection         = alt.selection_point(fields=["Item"])

    bar = (
        alt.Chart(chart_df)
        .mark_bar(cornerRadiusTopLeft=5, cornerRadiusTopRight=5)
        .encode(
            x=alt.X("Item:N", sort="-y", axis=alt.Axis(labelAngle=-30, labelLimit=120)),
            y=alt.Y("Quantity:Q"),
            color=alt.condition(selection, alt.value("#4A90D9"), alt.value("#b8d4f0")),
            tooltip=[
                alt.Tooltip("Item:N",     title="Item"),
                alt.Tooltip("Quantity:Q", title="Qty", format=".2f"),
            ],
        )
        .add_params(selection)
        .properties(height=350)
    )

    chart_event = st.altair_chart(
        bar, theme="streamlit", use_container_width=True,
        on_select="rerun", key="altair_bar_chart",
    )
    if chart_event:
        st.session_state["chart_selection"] = getattr(chart_event, "selection", None)

# ─────────────────────────────────────────────────────────────────────────────
# 14.  INVENTORY TAB
# ─────────────────────────────────────────────────────────────────────────────
def render_inventory(df: pd.DataFrame) -> None:
    st.subheader("📦 Inventory Items")

    col_btn, col_filter = st.columns([1, 3])
    with col_btn:
        if st.button("➕ Add Item", type="primary", use_container_width=True):
            dialog_add_item()

    DISPLAY_COLS = ["item_name", "quantity", "custom_unit", "description", "updated_at"]
    with col_filter:
        visible_cols: list[str] = st.multiselect(
            "Visible columns",
            options=DISPLAY_COLS,
            default=DISPLAY_COLS,
            label_visibility="collapsed",
        )
    if not visible_cols:
        visible_cols = DISPLAY_COLS

    if df.empty:
        st.info("No items found. Click ➕ Add Item to get started.")
        return

    safe_visible = [c for c in visible_cols if c in df.columns]
    view_df      = df[["id"] + safe_visible].copy()

    grid_event = st.dataframe(
        view_df.drop(columns=["id"]),
        use_container_width=True,
        hide_index=True,
        selection_mode="multi-row",
        on_select="rerun",
        key="inventory_grid",
        column_config={
            "item_name":   st.column_config.TextColumn("Item Name",    width="medium"),
            "quantity":    st.column_config.NumberColumn("Qty",        format="%.2f"),
            "custom_unit": st.column_config.TextColumn("Unit",        width="small"),
            "description": st.column_config.TextColumn("Description", width="large"),
            "updated_at":  st.column_config.DatetimeColumn(
                "Last Updated", format="DD/MM/YYYY HH:mm"
            ),
        },
    )

    selected_rows: list[int] = []
    if grid_event and hasattr(grid_event, "selection") and grid_event.selection:
        selected_rows = grid_event.selection.get("rows", [])

    if not selected_rows:
        st.caption("Click row(s) in the table above to edit or delete them.")
        return

    selected_data  = view_df.iloc[selected_rows]
    selected_ids   = selected_data["id"].tolist()
    selected_names = (
        selected_data["item_name"].tolist()
        if "item_name" in selected_data.columns
        else selected_ids
    )

    st.markdown(f"**{len(selected_rows)} row(s) selected**")
    col_edit, col_delete, col_spacer = st.columns([1, 1, 5])

    with col_edit:
        edit_disabled = len(selected_rows) != 1
        if st.button(
            "✏️ Edit",
            disabled=edit_disabled,
            help="Select exactly 1 row to edit." if edit_disabled else None,
            use_container_width=True,
        ):
            full_row: dict = df[df["id"] == selected_ids[0]].iloc[0].to_dict()
            dialog_edit_item(full_row)

    with col_delete:
        if st.button("🗑️ Delete", type="primary", use_container_width=True):
            dialog_confirm_delete(selected_ids, selected_names)


# ─────────────────────────────────────────────────────────────────────────────
# 15.  SETTINGS TAB
# ─────────────────────────────────────────────────────────────────────────────
def render_settings(prefs: dict) -> None:
    col_settings, col_account = st.columns([3, 2])

    with col_settings:
        st.subheader("⚙️ Dashboard Layout")
        st.caption("Toggle which KPI metrics appear on your dashboard.")

        layout: dict = prefs.get("dashboard_layout", {})

        show_items = st.toggle("Show 'Total Distinct Items'",    value=layout.get("show_total_items", True))
        show_qty   = st.toggle("Show 'Total Aggregate Quantity'", value=layout.get("show_total_quantity", True))
        show_low   = st.toggle("Show 'Low Stock Alerts'",        value=layout.get("show_low_stock", True))

        st.divider()
        st.subheader("🎨 Appearance")
        theme_options = ["system", "light", "dark"]
        current_theme = prefs.get("theme", "system")
        theme_index   = theme_options.index(current_theme) if current_theme in theme_options else 0
        theme = st.selectbox(
            "Preferred theme", options=theme_options, index=theme_index,
            help="Streamlit Community Cloud honours the system setting.",
        )

        if st.button("💾 Save Preferences", type="primary"):
            new_prefs = {
                "theme": theme,
                "dashboard_layout": {
                    "show_total_items":    show_items,
                    "show_total_quantity": show_qty,
                    "show_low_stock":      show_low,
                },
            }
            if upsert_preferences(new_prefs):
                st.toast("✅ Preferences saved!", icon="💾")
                st.rerun()

    with col_account:
        st.subheader("👤 Account")
        st.markdown("**Email:**")
        st.code(st.session_state.get("user_email", "—"), language=None)
        st.markdown("**User ID (UUID):**")
        st.code(st.session_state.get("user_id", "—"), language=None)
        st.caption(
            "Your User ID is the primary key used to isolate your data "
            "via Row Level Security at the database level."
        )


# ─────────────────────────────────────────────────────────────────────────────
# 16.  MAIN APPLICATION SHELL
# ─────────────────────────────────────────────────────────────────────────────
def render_main_app() -> None:
    """
    3 Supabase round-trips per full rerun:
        1. fetch_inventory()
        2. fetch_preferences()
        3. fetch_locations()
    All results passed as arguments — no N+1 queries inside renderers.
    """
    with st.spinner("Loading your data…"):
        df:           pd.DataFrame = fetch_inventory()
        prefs:        dict         = fetch_preferences()
        locations_df: pd.DataFrame = fetch_locations()

    render_sidebar(prefs, df)   # ← was render_sidebar(prefs)

    tab_locations, tab_inventory, tab_dashboard = st.tabs(
        ["🏠 Locations", "📦 Inventory", "📊 Dashboard"]
    )

    with tab_locations:
        render_home_tab(df, locations_df)

    with tab_inventory:
        render_inventory(df)

    with tab_dashboard:
        render_dashboard(df, prefs, locations_df)

# ─────────────────────────────────────────────────────────────────────────────
# 17.  ENTRY POINT  —  Security Gate
# ─────────────────────────────────────────────────────────────────────────────
if verify_session():
    render_main_app()
else:
    render_auth_page()
