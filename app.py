
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

import html as html
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
/* KPI metric cards */
.kpi-card {
    border-radius: 12px;
    padding: 20px 22px;
    border: 1px solid rgba(255,255,255,0.06);
    box-shadow: 0 4px 20px rgba(0,0,0,0.25);
    margin-bottom: 8px;
}
/* Location card unit progress bar */
.unit-bar-track {
    background: #e2e8f0;
    border-radius: 4px;
    height: 5px;
    margin: 4px 0 10px 0;
}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def _esc(value: str) -> str:
    """HTML-escape any user-supplied string before injecting into markup."""
    return html.escape(str(value or ""), quote=True)

# ─────────────────────────────────────────────────────────────────────────────
# 3.  SUPABASE CLIENT
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def _init_supabase_client() -> Client:
    url: str = st.secrets["SUPABASE_URL"]
    key: str = st.secrets["SUPABASE_ANON_KEY"]
    return create_client(url, key)


supabase: Client = _init_supabase_client()

CARDS_PER_ROW: int = 3   # ← ADD THIS LINE HERE

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
        # Token expired — attempt silent refresh
        session = supabase.auth.get_session()
        if session and session.access_token:
            st.session_state["auth_token"] = session.access_token
            st.session_state["user_id"]    = session.user.id
            st.session_state["user_email"] = session.user.email
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
                            # Seed default locations on first ever login
                            try:
                                supabase.postgrest.auth(resp.session.access_token)
                                existing = supabase.table("locations").select("id").limit(1).execute()
                                if not existing.data:
                                    _seed_default_locations(resp.user.id, resp.session.access_token)
                            except Exception:
                                pass
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
                "expiry_date, estimated_value, warranty_until, unit_cost, "
                "min_threshold, location_id, unit_id, created_at, updated_at"
            )
            .order("created_at", desc=True)
            .range(0, 9999)
            .execute()
        )
        if resp.data:
            df = pd.DataFrame(resp.data)
            for col in ["quantity", "estimated_value", "unit_cost"]:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
            df["min_threshold"] = pd.to_numeric(df["min_threshold"], errors="coerce")
            # Leave min_threshold as NaN when unset — procurement filters on .notna()
            df["expiry_date"]    = pd.to_datetime(df["expiry_date"],   errors="coerce")
            df["warranty_until"] = pd.to_datetime(df["warranty_until"], errors="coerce")
            return df
        return pd.DataFrame(columns=[
            "id", "item_name", "category", "quantity", "custom_unit", "description",
            "expiry_date", "estimated_value", "warranty_until", "unit_cost",
            "min_threshold", "location_id", "unit_id", "created_at", "updated_at",
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
            .order("created_at", desc=True)
            .range(0, 9999)
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

def fetch_units() -> pd.DataFrame:
    try:
        _set_postgrest_auth()
        resp = (
            supabase.table("units")
            .select("id, location_id, name, icon, description, created_at")
            .order("created_at", desc=False)
            .range(0, 9999)
            .execute()
        )
        if resp.data:
            return pd.DataFrame(resp.data)
        return pd.DataFrame(columns=["id", "location_id", "name", "icon", "description", "created_at"])
    except Exception as exc:
        st.error(f"Failed to load units: {exc}")
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

def fetch_shopping_history() -> pd.DataFrame:
    try:
        _set_postgrest_auth()
        resp = (
            supabase.table("shopping_history")
            .select("id, item_name, category, quantity_bought, total_price_paid, purchase_date, created_at")
            .order("purchase_date", desc=True)
            .range(0, 9999)
            .execute()
        )
        if resp.data:
            df = pd.DataFrame(resp.data)
            df["quantity_bought"]  = pd.to_numeric(df["quantity_bought"],  errors="coerce").fillna(0)
            df["total_price_paid"] = pd.to_numeric(df["total_price_paid"], errors="coerce").fillna(0)
            df["purchase_date"]    = pd.to_datetime(df["purchase_date"],   errors="coerce")
            return df
        return pd.DataFrame(columns=[
            "id", "item_name", "category", "quantity_bought",
            "total_price_paid", "purchase_date", "created_at",
        ])
    except Exception as exc:
        st.error(f"Failed to load shopping history: {exc}")
        return pd.DataFrame()


def fetch_maintenance_tasks() -> pd.DataFrame:
    try:
        _set_postgrest_auth()
        resp = (
            supabase.table("maintenance_tasks")
            .select("id, inventory_id, task_name, frequency_days, last_completed, next_due, created_at")
            .order("next_due", desc=False)
            .range(0, 9999)
            .execute()
        )
        if resp.data:
            df = pd.DataFrame(resp.data)
            df["frequency_days"] = pd.to_numeric(df["frequency_days"], errors="coerce").fillna(30).astype(int)
            df["last_completed"] = pd.to_datetime(df["last_completed"], errors="coerce")
            df["next_due"]       = pd.to_datetime(df["next_due"],       errors="coerce")
            return df
        return pd.DataFrame(columns=[
            "id", "inventory_id", "task_name", "frequency_days",
            "last_completed", "next_due", "created_at",
        ])
    except Exception as exc:
        st.error(f"Failed to load maintenance tasks: {exc}")
        return pd.DataFrame()


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
    "Other / Custom",
]
_EXPIRY_CATS   = {"Consumables", "Toiletries"}
_WARRANTY_CATS = {"Electronics", "Appliances", "Valuables"}
_DURABLE_CATS  = {"Electronics", "Appliances", "Valuables", "Furniture"}


# ── Default locations seeded for every new user ───────────────────────────────
_DEFAULT_LOCATIONS = [
    {"name": "Kitchen",        "icon": "🍳", "color": "#fef9c3"},
    {"name": "Living Room",    "icon": "🛋️", "color": "#dbeafe"},
    {"name": "Master Bedroom", "icon": "🛏️", "color": "#ede9fe"},
    {"name": "Guest Bathroom", "icon": "🚿", "color": "#ccfbf1"},
    {"name": "Garage",         "icon": "🚗", "color": "#f1f5f9"},
    {"name": "Attic",          "icon": "📦", "color": "#ffedd5"},
]

def _seed_default_locations(user_id: str, access_token: str) -> None:
    try:
        supabase.postgrest.auth(access_token)
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
    except Exception as exc:
        st.toast(f"Could not create default locations: {exc}", icon="⚠️")



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
            <span style="font-size:1.5rem">{_esc(icon or '📦')}</span>
            <span style="font-weight:700;font-size:1.1rem;margin-left:10px;">
                {_esc(name or 'Location Name')}
            </span>
            <p style="color:#64748b;font-size:0.85rem;margin:4px 0 0 0;">
                {_esc(description or 'No description')}
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

@st.dialog("➕ Add Storage Unit", width="large")
def dialog_add_unit(location_id: str, location_name: str) -> None:
    st.caption(f"Adding a storage unit inside **{location_name}**")
    col_a, col_b = st.columns(2)
    with col_a:
        name = st.text_input("Unit Name *", placeholder="e.g. Top Shelf, Wardrobe, Drawer 1")
    with col_b:
        icon = st.text_input("Icon (emoji)", value="📦", max_chars=4)
    description = st.text_area("Description (optional)", height=80)

    st.divider()
    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button("💾 Save Unit", type="primary", use_container_width=True):
            if not name.strip():
                st.error("Unit Name is required.")
                return
            try:
                _set_postgrest_auth()
                supabase.table("units").insert({
                    "user_id":     st.session_state["user_id"],
                    "location_id": location_id,
                    "name":        name.strip(),
                    "icon":        icon.strip() or "📦",
                    "description": description.strip() or None,
                }).execute()
                st.toast(f"✅ Unit '{name.strip()}' added!", icon="📦")
                st.rerun()
            except Exception as exc:
                st.error(f"Failed to add unit: {exc}")
    with col_cancel:
        if st.button("Cancel", use_container_width=True):
            st.rerun()


@st.dialog("✏️ Edit Storage Unit", width="large")
def dialog_edit_unit(unit: dict) -> None:
    col_a, col_b = st.columns(2)
    with col_a:
        name = st.text_input("Unit Name *", value=unit.get("name", ""))
    with col_b:
        icon = st.text_input("Icon (emoji)", value=unit.get("icon", "📦"), max_chars=4)
    description = st.text_area("Description", value=unit.get("description") or "", height=80)

    st.divider()
    col_update, col_cancel = st.columns(2)
    with col_update:
        if st.button("💾 Update Unit", type="primary", use_container_width=True):
            if not name.strip():
                st.error("Unit Name is required.")
                return
            try:
                _set_postgrest_auth()
                supabase.table("units").update({
                    "name":        name.strip(),
                    "icon":        icon.strip() or "📦",
                    "description": description.strip() or None,
                }).eq("id", unit["id"]).execute()
                st.toast("✅ Unit updated!", icon="✏️")
                st.rerun()
            except Exception as exc:
                st.error(f"Update failed: {exc}")
    with col_cancel:
        if st.button("Cancel", use_container_width=True):
            st.rerun()


@st.dialog("🗑️ Delete Storage Unit")
def dialog_delete_unit(unit_id: str, unit_name: str) -> None:
    st.warning(
        f"Delete **{unit_name}**? Items inside it will become unassigned to any unit "
        f"(they stay in the room). This cannot be undone."
    )
    col_del, col_cancel = st.columns(2)
    with col_del:
        if st.button("Yes, Delete", type="primary", use_container_width=True):
            try:
                _set_postgrest_auth()
                supabase.table("units").delete().eq("id", unit_id).execute()
                st.toast(f"🗑️ '{unit_name}' removed.", icon="✅")
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
        category_raw = st.selectbox("Category *", options=_CATEGORIES)

    # Custom category input
    if category_raw == "Other / Custom":
        custom_cat = st.text_input("Custom Category Name *", placeholder="e.g. Pet Supplies")
        category   = custom_cat.strip() if custom_cat.strip() else "Other"
    else:
        category = category_raw

    col_c, col_d = st.columns(2)
    with col_c:
        quantity = st.number_input("Quantity *", min_value=0.0, step=1.0, value=1.0)
    with col_d:
        custom_unit = st.text_input("Unit", placeholder="e.g. pcs, kg")

    col_e, col_f = st.columns(2)
    with col_e:
        loc_label   = st.selectbox("Location", options=list(loc_options.keys()), key="add_loc")
        location_id = loc_options[loc_label]
    with col_f:
        min_threshold = st.number_input(
            "Min. Threshold", min_value=0.0, step=1.0, value=0.0,
            help="Alert in Procurement tab when quantity falls at or below this."
        )

    # Unit picker — filtered live by chosen location
    units_df = fetch_units()
    unit_options = {"— In Room (no unit) —": None}
    if not units_df.empty and location_id:
        for _, ur in units_df[units_df["location_id"] == location_id].iterrows():
            unit_options[f"{ur['icon']} {ur['name']}"] = ur["id"]
    unit_label = st.selectbox(
        "Storage Unit (optional)",
        options=list(unit_options.keys()),
        help="Select a shelf, drawer, wardrobe, etc. Leave blank if the item sits freely in the room.",
    )
    unit_id = unit_options[unit_label]

    col_g, col_h = st.columns(2)
    with col_g:
        unit_cost = st.number_input(
            "Unit Cost (£)", min_value=0.0, step=0.01, value=0.0,
            help="Cost per unit — used for budget estimates and sunk cost calculations."
        )
        if unit_cost == 0.0:
            unit_cost = None
    with col_h:
        st.empty()

    # ── Conditional fields ────────────────────────────────────────────────
    expiry_date     = None
    estimated_value = None
    warranty_until  = None

    if category in _EXPIRY_CATS:
        st.divider()
        st.caption("🗓️ Perishable fields")
        expiry_date = st.date_input(
            "Expiry Date", value=None,
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
                help="Used for insurance ledger."
            )
            if estimated_value == 0.0:
                estimated_value = None
        with col_w:
            warranty_until = st.date_input(
                "Warranty Until", value=None,
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
            if category_raw == "Other / Custom" and not category.strip():
                st.error("Please enter a custom category name.")
                return
            try:
                _set_postgrest_auth()
                supabase.table("inventory").insert({
                    "user_id":         st.session_state["user_id"],
                    "item_name":       item_name.strip(),
                    "category":        category,
                    "quantity":        float(quantity),
                    "custom_unit":     custom_unit.strip() or None,
                    "description":     description.strip() or None,
                    "location_id":     location_id,
                    "unit_id":         unit_id,
                    "unit_cost":       unit_cost,
                    "min_threshold":   float(min_threshold),
                    "expiry_date":     expiry_date.isoformat() if expiry_date else None,
                    "estimated_value": estimated_value,
                    "warranty_until":  warranty_until.isoformat() if warranty_until else None,
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

    # Handle custom category (not in preset list)
    current_cat = row.get("category") or _CATEGORIES[0]
    if current_cat in _CATEGORIES:
        cat_index      = _CATEGORIES.index(current_cat)
        initial_custom = ""
    else:
        cat_index      = _CATEGORIES.index("Other / Custom")
        initial_custom = current_cat

    col_a, col_b = st.columns(2)
    with col_a:
        item_name = st.text_input("Item Name *", value=row.get("item_name", ""))
    with col_b:
        category_raw = st.selectbox("Category *", options=_CATEGORIES, index=cat_index)

    if category_raw == "Other / Custom":
        custom_cat = st.text_input("Custom Category Name *", value=initial_custom)
        category   = custom_cat.strip() if custom_cat.strip() else "Other"
    else:
        category = category_raw

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
        min_threshold = st.number_input(
            "Min. Threshold", min_value=0.0, step=1.0,
            value=float(row.get("min_threshold") or 0.0),
        )
    
    # ADD after location_id is resolved, before min_threshold input:
    units_df    = fetch_units()
    unit_options = {"— In Room (no unit) —": None}
    if not units_df.empty and location_id:
        for _, ur in units_df[units_df["location_id"] == location_id].iterrows():
            unit_options[f"{ur['icon']} {ur['name']}"] = ur["id"]

    current_unit_id    = row.get("unit_id")
    unit_id_to_label   = {v: k for k, v in unit_options.items()}
    current_unit_label = unit_id_to_label.get(current_unit_id, "— In Room (no unit) —")
    unit_keys          = list(unit_options.keys())
    unit_index         = unit_keys.index(current_unit_label) if current_unit_label in unit_keys else 0

    unit_label = st.selectbox(
        "Storage Unit (optional)",
        options=unit_keys,
        index=unit_index,
        help="Select a shelf, drawer, wardrobe, etc.",
    )
    unit_id = unit_options[unit_label]

    col_g, col_h = st.columns(2)
    with col_g:
        unit_cost = st.number_input(
            "Unit Cost (£)", min_value=0.0, step=0.01,
            value=float(row.get("unit_cost") or 0.0),
        )
        if unit_cost == 0.0:
            unit_cost = None
    with col_h:
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
            try:    existing_expiry = datetime.fromisoformat(existing_expiry).date()
            except (ValueError, TypeError, AttributeError):
                existing_expiry = None
        elif hasattr(existing_expiry, "date"):
            existing_expiry = existing_expiry.date()
        expiry_date = st.date_input("Expiry Date", value=existing_expiry)

    if category in _WARRANTY_CATS:
        st.divider()
        st.caption("💰 Asset fields")
        existing_warranty = row.get("warranty_until")
        if isinstance(existing_warranty, str):
            try:    existing_warranty = datetime.fromisoformat(existing_warranty).date()
            except (ValueError, TypeError, AttributeError):
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
                    "item_name":       item_name.strip(),
                    "category":        category,
                    "quantity":        float(quantity),
                    "custom_unit":     custom_unit.strip() or None,
                    "description":     description.strip() or None,
                    "location_id":     location_id,
                    "unit_id":         unit_id,
                    "unit_cost":       unit_cost,
                    "min_threshold":   float(min_threshold),
                    "expiry_date":     expiry_date.isoformat() if expiry_date else None,
                    "estimated_value": estimated_value,
                    "warranty_until":  warranty_until.isoformat() if warranty_until else None,
                    "updated_at":      datetime.now(timezone.utc).isoformat(),
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
def render_sidebar(prefs: dict, df: pd.DataFrame, locations_df: pd.DataFrame, units_df: pd.DataFrame) -> None:
    with st.sidebar:
        st.divider()

        # ── Global Search ──────────────────────────────────────────────────
        st.markdown("Global Search")
        search_query = st.text_input(
            "🔍 Search inventory",
            placeholder="e.g. rice, lamp…",
            label_visibility="collapsed",
        )
        if search_query.strip():
            q    = search_query.strip().lower()
            hits = (
                df[df["item_name"].str.lower().str.contains(q, na=False)].copy()
                if not df.empty else pd.DataFrame()
            )
            if hits.empty:
                st.caption("No items match your search.")
            else:
                loc_lookup = (
                    {r["id"]: f"{r['icon']} {r['name']}" for r in locations_df.to_dict("records")}
                    if not locations_df.empty else {}
                )
                for _, hit in hits.iterrows():
                    loc_label = loc_lookup.get(hit.get("location_id"), "📦 Unassigned")
                    unit_id   = hit.get("unit_id")
                    unit_name = ""
                    if not units_df.empty and unit_id:
                        u_row = units_df[units_df["id"] == unit_id]
                        if not u_row.empty:
                            unit_name = f" › {u_row.iloc[0]['icon']} {u_row.iloc[0]['name']}"
                    path_label = f"{loc_label}{unit_name}"
                    qty  = hit["quantity"]
                    unit = hit.get("custom_unit") or ""
                    st.markdown(
                        f"""
                        <div style="background:#1e293b;border-left:3px solid #14b8a6;
                                    border-radius:6px;padding:8px 12px;margin:4px 0;">
                          <span style="color:#f1f5f9;font-weight:600;">{_esc(hit['item_name'])}</span><br>
                          <span style="color:#94a3b8;font-size:0.8rem;">
                            {qty:.0f} {_esc(unit)} · {_esc(path_label)}
                          </span>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

        st.divider()

        # ── Account & Settings popover ─────────────────────────────────────
        with st.popover("⚙️ Account & Settings", use_container_width=True):
            email = str(st.session_state.get("user_email", ""))
            uid   = str(st.session_state.get("user_id", ""))

            # Dashboard layout
            st.markdown("**Dashboard Layout**")
            layout     = dict(prefs.get("dashboard_layout", {}))
            show_items = st.toggle("Total Distinct Items",     value=layout.get("show_total_items", True),    key="pop_show_items")
            show_qty   = st.toggle("Total Aggregate Quantity", value=layout.get("show_total_quantity", True), key="pop_show_qty")
            show_low   = st.toggle("Low Stock Alerts",         value=layout.get("show_low_stock", True),      key="pop_show_low")

            st.markdown("**Appearance**")
            theme_options = ["system", "light", "dark"]
            current_theme = prefs.get("theme", "system")
            theme_index   = theme_options.index(current_theme) if current_theme in theme_options else 0
            theme         = st.selectbox("Theme", options=theme_options, index=theme_index, key="pop_theme")

            if st.button("💾 Save Settings", type="primary", use_container_width=True, key="pop_save_settings"):
                new_prefs = {
                    "theme": theme,
                    "dashboard_layout": {
                        "show_total_items":    show_items,
                        "show_total_quantity": show_qty,
                        "show_low_stock":      show_low,
                    },
                }
                if upsert_preferences(new_prefs):
                    st.toast("✅ Settings saved!", icon="✅")
                    st.rerun()

            st.divider()

            # Account info
            st.markdown("**Account**")
            st.markdown("Email")
            st.code(email, language=None)
            st.markdown("User ID")
            st.code(uid, language=None)
            st.caption("Your UUID is the RLS isolation key at the database level.")
            st.divider()

            # CSV export
            if not df.empty:
                export_df = df.drop(columns=["id", "location_id"], errors="ignore").copy()
                for col in ["expiry_date", "warranty_until", "created_at", "updated_at"]:
                    if col in export_df.columns:
                        export_df[col] = pd.to_datetime(export_df[col], errors="coerce").dt.strftime("%d/%m/%Y")
                csv_bytes = export_df.to_csv(index=False).encode("utf-8")
                st.download_button(
                    label="📥 Export Inventory as CSV",
                    data=csv_bytes,
                    file_name=f"inventory_export_{datetime.now().strftime('%Y%m%d%H%M')}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
            else:
                st.caption("No data to export yet.")

            st.divider()

            if st.button("🗑️ Delete My Account", use_container_width=True, type="primary",
                         help="Permanently deletes your account and all data.", key="pop_del_account"):
                dialog_delete_account()

            if st.button("🚪 Sign Out", use_container_width=True, key="pop_sign_out"):
                try:
                    supabase.auth.sign_out()
                except Exception:
                    pass
                _clear_session()
                st.rerun()

        st.caption("Built with Streamlit · Supabase")


# ─────────────────────────────────────────────────────────────────────────────
# 12.  HOME TAB  —  Location Card Grid
# ─────────────────────────────────────────────────────────────────────────────
@st.dialog("🏠 Room Details", width="large")
def dialog_view_room(loc: dict, loc_items: pd.DataFrame, loc_units: pd.DataFrame) -> None:
    bg   = loc.get("color", "#e0f2fe")
    icon = loc.get("icon", "📦")
    name = loc.get("name", "Location")
    loc_id = loc.get("id")

    st.markdown(
        f"""<div style="background:{_esc(bg)};border-radius:12px;padding:14px 20px;margin-bottom:14px">
          <span style="font-size:2rem">{_esc(icon)}</span>
          <span style="font-weight:800;font-size:1.35rem;margin-left:10px;color:#0f172a">{_esc(name)}</span>
        </div>""",
        unsafe_allow_html=True,
    )

    today = pd.Timestamp.now(tz="UTC").normalize()
    in_30 = today + pd.Timedelta(days=30)

    # ── Category mini donut + stats ───────────────────────────────────────
    if not loc_items.empty:
        cat_counts = (
            loc_items.groupby("category")["quantity"].sum().reset_index()
            .rename(columns={"category": "Category", "quantity": "Total Qty"})
        )
        fig_mini = px.pie(
            cat_counts, names="Category", values="Total Qty",
            hole=0.55, color_discrete_sequence=px.colors.qualitative.Pastel,
        )
        fig_mini.update_traces(textposition="outside", textinfo="label+percent")
        fig_mini.update_layout(
            height=230, margin=dict(t=10, b=10, l=10, r=10), showlegend=False,
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        )
        col_d, col_s = st.columns([2, 3])
        with col_d:
            st.plotly_chart(fig_mini, use_container_width=True)
        with col_s:
            expiring = 0
            if "expiry_date" in loc_items.columns:
                exp_ts   = pd.to_datetime(loc_items["expiry_date"], utc=True, errors="coerce")
                expiring = int(((exp_ts >= today) & (exp_ts <= in_30)).sum())
            total_val = float(
                pd.to_numeric(loc_items.get("estimated_value", pd.Series(dtype=float)), errors="coerce")
                .fillna(0).sum()
            )
            st.metric("Items",          len(loc_items))
            st.metric("Est. Value",     f"£{total_val:,.2f}")
            st.metric("Expiring (30d)", expiring)
        st.divider()

    # ── Storage units ─────────────────────────────────────────────────────
    if not loc_units.empty:
        for _, unit in loc_units.iterrows():
            uid        = unit["id"]
            unit_items = (
                loc_items[loc_items["unit_id"] == uid].copy()
                if not loc_items.empty and "unit_id" in loc_items.columns else pd.DataFrame()
            )
            ucount = len(unit_items)
            with st.expander(
                f"{unit.get('icon','📦')} **{unit.get('name','Unit')}** — {ucount} item{'s' if ucount != 1 else ''}",
                expanded=ucount > 0,
            ):
                if unit_items.empty:
                    st.caption("No items in this unit.")
                else:
                    for _, item in unit_items.iterrows():
                        u_str   = item.get("custom_unit") or ""
                        qty_fmt = f"{item['quantity']:.0f}" if item["quantity"] == int(item["quantity"]) else f"{item['quantity']:.2f}"
                        st.markdown(f"- **{item['item_name']}** — {qty_fmt} {u_str}".strip())

    # ── Directly in room ──────────────────────────────────────────────────
    direct = (
        loc_items[loc_items["unit_id"].isna()].copy()
        if not loc_items.empty and "unit_id" in loc_items.columns else loc_items.copy()
    )
    if not direct.empty:
        with st.expander(f"🏠 Directly in room ({len(direct)})", expanded=True):
            for _, item in direct.iterrows():
                u_str   = item.get("custom_unit") or ""
                qty_fmt = f"{item['quantity']:.0f}" if item["quantity"] == int(item["quantity"]) else f"{item['quantity']:.2f}"
                st.markdown(f"- **{item['item_name']}** — {qty_fmt} {u_str}".strip())



def _location_card(col, loc: dict, loc_items: pd.DataFrame, loc_units: pd.DataFrame) -> None:
    with col:
        bg       = loc.get("color", "#e0f2fe")
        icon     = loc.get("icon", "📦")
        name     = loc.get("name", "Location")
        loc_id   = loc.get("id")
        count    = len(loc_items) if not loc_items.empty else 0
        u_count  = len(loc_units) if not loc_units.empty else 0

        today    = pd.Timestamp.now(tz="UTC").normalize()
        in_30    = today + pd.Timedelta(days=30)
        expiring = 0
        if not loc_items.empty and "expiry_date" in loc_items.columns:
            exp_ts   = pd.to_datetime(loc_items["expiry_date"], utc=True, errors="coerce")
            expiring = int(((exp_ts >= today) & (exp_ts <= in_30)).sum())

        total_val = 0.0
        if not loc_items.empty and "estimated_value" in loc_items.columns:
            total_val = float(
                pd.to_numeric(loc_items["estimated_value"], errors="coerce").fillna(0).sum()
            )

        # ── Coloured header ────────────────────────────────────────────
        st.markdown(
            f"""<div style="background:{_esc(bg)};border-radius:16px 16px 0 0;
                        padding:20px 22px 14px 22px;
                        border:1px solid rgba(0,0,0,0.08);border-bottom:none;">
              <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                <div>
                  <p style="font-weight:800;font-size:1.35rem;margin:0 0 6px 0;
                             color:#0f172a;line-height:1.2">{_esc(name)}</p>
                  <span style="font-size:0.72rem;color:#475569;background:rgba(0,0,0,0.07);
                                border-radius:20px;padding:2px 9px">
                    {u_count} unit{'s' if u_count != 1 else ''}
                  </span>
                </div>
                <span style="font-size:2.8rem;line-height:1;opacity:0.9">{_esc(icon)}</span>
              </div>
            </div>""",
            unsafe_allow_html=True,
        )

        # ── Fixed-height stats body ────────────────────────────────────
        with st.container(border=True):
            m1, m2, m3 = st.columns(3)
            with m1:
                st.markdown(
                    f"""<div style="text-align:center;padding:10px 0">
                      <p style="font-size:1.7rem;font-weight:800;margin:0;color:#0f172a">{count}</p>
                      <p style="font-size:0.68rem;color:#64748b;margin:2px 0 0 0;text-transform:uppercase;letter-spacing:.05em">Items</p>
                    </div>""",
                    unsafe_allow_html=True,
                )
            with m2:
                val_str = f"£{total_val:,.0f}" if total_val > 0 else "—"
                st.markdown(
                    f"""<div style="text-align:center;padding:10px 0">
                      <p style="font-size:1.7rem;font-weight:800;margin:0;color:#0f172a">{_esc(val_str)}</p>
                      <p style="font-size:0.68rem;color:#64748b;margin:2px 0 0 0;text-transform:uppercase;letter-spacing:.05em">Value</p>
                    </div>""",
                    unsafe_allow_html=True,
                )
            with m3:
                exp_color = "#ef4444" if expiring > 0 else "#22c55e"
                st.markdown(
                    f"""<div style="text-align:center;padding:10px 0">
                      <p style="font-size:1.7rem;font-weight:800;margin:0;color:{exp_color}">{expiring}</p>
                      <p style="font-size:0.68rem;color:#64748b;margin:2px 0 0 0;text-transform:uppercase;letter-spacing:.05em">Expiring</p>
                    </div>""",
                    unsafe_allow_html=True,
                )
            st.divider()
            if st.button(
                "🔍 View Room",
                key=f"view_room_{loc_id}",
                use_container_width=True,
                type="primary",
            ):
                dialog_view_room(loc, loc_items, loc_units)

            st.divider()
            b1, b2, b3 = st.columns(3)
            with b1:
                if st.button("➕ Unit", key=f"add_unit_{loc_id}", use_container_width=True):
                    dialog_add_unit(loc_id, name)
            with b2:
                if st.button("✏️ Edit", key=f"edit_loc_{loc_id}", use_container_width=True):
                    dialog_edit_location(loc)
            with b3:
                if st.button("🗑️", key=f"del_loc_{loc_id}", use_container_width=True):
                    dialog_delete_location(loc_id, name)



def render_home_tab(df: pd.DataFrame, locations_df: pd.DataFrame, units_df: pd.DataFrame) -> None:

    # ── Triage Inbox (unassigned items) — TOP RIGHT ───────────────────────
    unassigned = pd.DataFrame()
    if not df.empty and "location_id" in df.columns:
        unassigned = df[df["location_id"].isna()].copy()

    if not unassigned.empty:
        st.markdown(
            """<div style="background:linear-gradient(135deg,#fef3c7,#fde68a);
                           border-left:4px solid #f59e0b;border-radius:10px;
                           padding:12px 18px;margin-bottom:16px;">
              <p style="font-weight:700;color:#78350f;margin:0 0 2px 0">
                📥 Triage Inbox — {n} Unassigned Item{s}
              </p>
              <p style="color:#92400e;font-size:0.82rem;margin:0">
                Quick-assign each item to a room below.
              </p>
            </div>""".replace("{n}", str(len(unassigned))).replace("{s}", "s" if len(unassigned) != 1 else ""),
            unsafe_allow_html=True,
        )
        loc_options = (
            {r["name"]: r["id"] for r in locations_df.to_dict("records")}
            if not locations_df.empty else {}
        )
        for _, item in unassigned.iterrows():
            item_id   = str(item["id"])
            unit_str  = item.get("custom_unit") or ""
            qty_fmt   = (
                f"{item['quantity']:.0f}"
                if item["quantity"] == int(item["quantity"])
                else f"{item['quantity']:.2f}"
            )
            col_name, col_sel, col_btn = st.columns([3, 3, 1])
            with col_name:
                st.markdown(
                    f"""<div style="padding:8px 0;">
                      <span style="font-weight:600">{_esc(item['item_name'])}</span>
                      <span style="color:#64748b;font-size:0.85rem"> — {_esc(qty_fmt)} {_esc(unit_str)}</span>
                    </div>""",
                    unsafe_allow_html=True,
                )
            with col_sel:
                chosen_room = st.selectbox(
                    "Assign to",
                    options=["— select room —"] + list(loc_options.keys()),
                    key=f"triage_room_{item_id}",
                    label_visibility="collapsed",
                )
            with col_btn:
                if st.button("✅", key=f"triage_btn_{item_id}", help="Assign to room"):
                    if chosen_room == "— select room —":
                        st.warning("Please select a room first.")
                    else:
                        try:
                            _set_postgrest_auth()
                            supabase.table("inventory").update({
                                "location_id": loc_options[chosen_room],
                                "updated_at":  datetime.now(timezone.utc).isoformat(),
                            }).eq("id", item_id).execute()
                            st.toast(f"✅ {item['item_name']} → {chosen_room}", icon="✅")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Failed to assign: {exc}")
        st.divider()

    # ── Page header ───────────────────────────────────────────────────────
    col_hdr, col_add = st.columns([5, 1])
    with col_hdr:
        st.markdown(
            "<h1 style='font-size:2.4rem;font-weight:800;margin:0 0 4px 0'>Locations</h1>",
            unsafe_allow_html=True,
        )
    with col_add:
        if st.button("➕ Add Location", type="primary", use_container_width=True):
            dialog_add_location()

    if locations_df.empty:
        render_empty_state(
            "No locations yet. Create a room or storage area to get started.",
            "➕ Add First Location",
            dialog_add_location,
        )
        return

    locs = locations_df.to_dict("records")

    # ── Lean card grid (3 per row, uniform height) ────────────────────────
    for row_start in range(0, len(locs), CARDS_PER_ROW):
        row_locs = locs[row_start: row_start + CARDS_PER_ROW]
        cols     = st.columns(CARDS_PER_ROW)
        for col, loc in zip(cols, row_locs):
            loc_id    = loc.get("id")
            loc_items = (
                df[df["location_id"] == loc_id].copy()
                if not df.empty and "location_id" in df.columns else pd.DataFrame()
            )
            loc_units = (
                units_df[units_df["location_id"] == loc_id].copy()
                if not units_df.empty else pd.DataFrame()
            )
            _location_card(col, loc, loc_items, loc_units)
        st.write("")

    # ── Spatial Overview — Digital Twin ──────────────────────────────────
    if not df.empty:
        st.divider()

        hdr_col, toggle_col = st.columns([3, 2])
        with hdr_col:
            st.markdown("**🗺️ Spatial Overview — Digital Twin**")
            st.caption("Inner ring = rooms · Outer ring = storage units · Sized by selected metric.")
        with toggle_col:
            view_metric = st.radio(
                "Size by", ["Item Count", "Est. Value (£)"],
                horizontal=True, key="spatial_metric",
            )

        loc_lookup  = (
            {r["id"]: r["name"] for r in locations_df.to_dict("records")}
            if not locations_df.empty else {}
        )
        loc_icon    = (
            {r["id"]: r.get("icon","📦") for r in locations_df.to_dict("records")}
            if not locations_df.empty else {}
        )
        loc_color_hex = (
            {r["id"]: r.get("color","#e0f2fe") for r in locations_df.to_dict("records")}
            if not locations_df.empty else {}
        )
        unit_lookup = (
            {r["id"]: r["name"] for r in units_df.to_dict("records")}
            if not units_df.empty else {}
        )

        tree_df = df[["item_name", "quantity", "estimated_value",
                       "location_id", "unit_id", "category"]].copy()
        tree_df["quantity"]        = pd.to_numeric(tree_df["quantity"], errors="coerce").fillna(0)
        tree_df["estimated_value"] = pd.to_numeric(tree_df["estimated_value"], errors="coerce").fillna(0)
        tree_df["Room"]      = tree_df["location_id"].map(loc_lookup).fillna("Unassigned")
        tree_df["RoomIcon"]  = tree_df["location_id"].map(loc_icon).fillna("📦")
        tree_df["Unit"]      = tree_df["unit_id"].map(unit_lookup).fillna("In Room")
        tree_df["RoomLabel"] = tree_df["RoomIcon"] + " " + tree_df["Room"]
        tree_df["UnitLabel"] = tree_df["Unit"]
        tree_df              = tree_df[tree_df["quantity"] > 0]

        value_col = "quantity" if view_metric == "Item Count" else "estimated_value"
        tree_df   = tree_df[tree_df[value_col] > 0]

        if tree_df.empty:
            st.info("Add items with quantity > 0 to see the spatial overview.")
        else:
            col_sun, col_bar = st.columns([3, 2])

            # ── Left: Sunburst ────────────────────────────────────────────
            with col_sun:
                import plotly.graph_objects as go

                # Build hierarchy: root → Room → Unit → item
                labels, parents, values, custom_text, marker_colors = [], [], [], [], []

                ROOM_PALETTE = [
                    "#14b8a6","#3b82f6","#a855f7","#f59e0b",
                    "#ec4899","#22c55e","#f97316","#06b6d4",
                ]
                room_names  = tree_df["RoomLabel"].unique().tolist()
                room_colour = {r: ROOM_PALETTE[i % len(ROOM_PALETTE)]
                               for i, r in enumerate(room_names)}

                # Root
                labels.append("🏠 Home")
                parents.append("")
                values.append(0)
                custom_text.append("")
                marker_colors.append("#1e293b")

                # Rooms
                for room in room_names:
                    room_df  = tree_df[tree_df["RoomLabel"] == room]
                    room_val = float(room_df[value_col].sum())
                    labels.append(room)
                    parents.append("🏠 Home")
                    values.append(room_val)
                    custom_text.append(f"{room_val:.0f}")
                    marker_colors.append(room_colour[room])

                    # Units within room
                    for unit in room_df["UnitLabel"].unique():
                        unit_label = f"{room} › {unit}"
                        unit_df    = room_df[room_df["UnitLabel"] == unit]
                        unit_val   = float(unit_df[value_col].sum())
                        labels.append(unit_label)
                        parents.append(room)
                        values.append(unit_val)
                        custom_text.append(f"{unit_val:.0f}")
                        # Slightly lighter shade of room colour
                        marker_colors.append(room_colour[room] + "bb")

                        # Items within unit
                        for _, row in unit_df.iterrows():
                            item_label = f"{row['item_name']} ({room}|{unit})"
                            labels.append(item_label)
                            parents.append(unit_label)
                            values.append(float(row[value_col]))
                            custom_text.append(row["item_name"])
                            marker_colors.append(room_colour[room] + "66")

                fig_sun = go.Figure(go.Sunburst(
                    labels=labels,
                    parents=parents,
                    values=values,
                    customdata=custom_text,
                    hovertemplate="<b>%{customdata}</b><br>%s: %%{value:.0f}<extra></extra>"
                                  % ("Qty" if view_metric == "Item Count" else "£"),
                    texttemplate="<b>%{customdata}</b>",
                    marker=dict(colors=marker_colors, line=dict(width=2, color="#0f172a")),
                    branchvalues="total",
                    maxdepth=3,
                    insidetextorientation="radial",
                    leaf=dict(opacity=0.85),
                ))
                fig_sun.update_layout(
                    height=460,
                    margin=dict(t=10, b=10, l=10, r=10),
                    paper_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#f1f5f9", size=12),
                )
                st.plotly_chart(fig_sun, use_container_width=True)

            # ── Right: Category stack per room ────────────────────────────
            with col_bar:
                st.markdown("**Category mix per room**")

                cat_room = (
                    tree_df.groupby(["Room", "category"])[value_col]
                    .sum()
                    .reset_index()
                    .rename(columns={
                        "Room":     "Room",
                        "category": "Category",
                        value_col:  "Value",
                    })
                )

                fig_stack = px.bar(
                    cat_room,
                    x="Value",
                    y="Room",
                    color="Category",
                    orientation="h",
                    color_discrete_sequence=px.colors.qualitative.Set2,
                    labels={"Value": "Qty" if view_metric == "Item Count" else "£"},
                    barmode="stack",
                )
                fig_stack.update_layout(
                    height=460,
                    margin=dict(t=10, b=10, l=10, r=10),
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    yaxis=dict(
                        autorange="reversed",
                        tickfont=dict(size=11, color="#cbd5e1"),
                        gridcolor="rgba(255,255,255,0.05)",
                    ),
                    xaxis=dict(
                        gridcolor="rgba(255,255,255,0.05)",
                        tickfont=dict(color="#94a3b8"),
                    ),
                    legend=dict(
                        orientation="h", yanchor="bottom", y=-0.38,
                        font=dict(size=10, color="#cbd5e1"),
                    ),
                    font=dict(color="#f1f5f9"),
                    showlegend=True,
                )
                fig_stack.update_traces(
                    marker_line_width=0,
                    hovertemplate="<b>%{y}</b><br>%{fullData.name}: %{x:.0f}<extra></extra>",
                )
                st.plotly_chart(fig_stack, use_container_width=True)



@st.dialog("➕ Add Maintenance Task", width="large")
def dialog_add_maintenance_task(inventory_df: pd.DataFrame) -> None:
    st.caption("Track recurring tasks like filter changes, appliance servicing, etc.")

    task_name = st.text_input("Task Name *", placeholder="e.g. Replace HVAC filter")

    item_options = {"— Not linked to an item —": None}
    if not inventory_df.empty:
        for _, r in inventory_df.iterrows():
            item_options[r["item_name"]] = r["id"]
    linked_item  = st.selectbox("Linked Inventory Item (optional)", options=list(item_options.keys()))
    inventory_id = item_options[linked_item]

    col_a, col_b = st.columns(2)
    with col_a:
        frequency_days = st.number_input("Repeat Every (days) *", min_value=1, step=1, value=30)
    with col_b:
        last_completed = st.date_input("Last Completed (optional)", value=None)

    next_due_calc = None
    if last_completed:
        from datetime import timedelta
        next_due_calc = last_completed + timedelta(days=int(frequency_days))
        st.caption(f"📅 Next due: **{next_due_calc.strftime('%d/%m/%Y')}**")

    st.divider()
    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button("💾 Save Task", type="primary", use_container_width=True):
            if not task_name.strip():
                st.error("Task Name is required.")
                return
            try:
                _set_postgrest_auth()
                supabase.table("maintenance_tasks").insert({
                    "user_id":        st.session_state["user_id"],
                    "task_name":      task_name.strip(),
                    "inventory_id":   inventory_id,
                    "frequency_days": int(frequency_days),
                    "last_completed": last_completed.isoformat() if last_completed else None,
                    "next_due":       next_due_calc.isoformat() if next_due_calc else None,
                }).execute()
                st.toast("✅ Task added!", icon="🔧")
                st.rerun()
            except Exception as exc:
                st.error(f"Failed to add task: {exc}")
    with col_cancel:
        if st.button("Cancel", use_container_width=True):
            st.rerun()

@st.dialog("🛒 Log a Purchase", width="large")
def dialog_log_purchase(df: pd.DataFrame, locations_df: pd.DataFrame) -> None:
    mode = st.radio(
        "What are you logging?",
        ["Log Existing Item", "Add & Log New Item"],
        horizontal=True,
        key="dlp_mode",
    )
    st.divider()

    if mode == "Log Existing Item":
        if df.empty:
            st.info("Add items to your inventory first.")
            return
        with st.form("log_existing_form"):
            item_names    = sorted(df["item_name"].unique().tolist())
            selected_item = st.selectbox("Item *", options=item_names)
            ca, cb, cc    = st.columns(3)
            with ca:
                qty_bought    = st.number_input("Qty Bought *", min_value=0.01, step=1.0, value=1.0)
            with cb:
                total_paid    = st.number_input("Total Paid (£)", min_value=0.0, step=0.01, value=0.0)
            with cc:
                purchase_date = st.date_input("Date", value=datetime.now(timezone.utc).date())
            submitted = st.form_submit_button("💾 Log Receipt", type="primary", use_container_width=True)

        if submitted:
            if qty_bought <= 0:
                st.error("Quantity must be greater than 0.")
                return
            try:
                _set_postgrest_auth()
                item_row      = df[df["item_name"] == selected_item].iloc[0]
                new_unit_cost = round(total_paid / qty_bought, 4) if total_paid > 0 else None
                supabase.rpc("increment_inventory_quantity", {
                    "p_inventory_id":   str(item_row["id"]),
                    "p_quantity_delta": float(qty_bought),
                    "p_new_unit_cost":  new_unit_cost,
                }).execute()
                supabase.table("shopping_history").insert({
                    "user_id":          st.session_state["user_id"],
                    "item_name":        selected_item,
                    "category":         item_row.get("category") or "Other",
                    "quantity_bought":  float(qty_bought),
                    "total_price_paid": float(total_paid),
                    "purchase_date":    purchase_date.isoformat(),
                    "inventory_id":     str(item_row["id"]),
                }).execute()
                st.toast(f"✅ Logged {selected_item}!", icon="🛒")
                st.rerun()
            except Exception as exc:
                st.error(f"Failed to log receipt: {exc}")

    else:  # ── Add & Log New Item ───────────────────────────────────────
        with st.form("log_new_item_form"):
            cn, cc2 = st.columns(2)
            with cn:
                new_item_name = st.text_input("New Item Name *", placeholder="e.g. Almond Milk")
            with cc2:
                new_category  = st.selectbox("Category *", options=CATEGORIES[:-1])
            ca2, cb2, cc3 = st.columns(3)
            with ca2:
                qty_bought    = st.number_input("Qty Bought *", min_value=0.01, step=1.0, value=1.0)
            with cb2:
                total_paid    = st.number_input("Total Paid (£)", min_value=0.0, step=0.01, value=0.0)
            with cc3:
                purchase_date = st.date_input("Date", value=datetime.now(timezone.utc).date())
            st.caption("The item will be created in your inventory with the purchased quantity.")
            submitted = st.form_submit_button("➕ Add Item & Log", type="primary", use_container_width=True)

        if submitted:
            if not new_item_name.strip():
                st.error("Item Name is required.")
                return
            if qty_bought <= 0:
                st.error("Quantity must be greater than 0.")
                return
            try:
                _set_postgrest_auth()
                new_unit_cost = round(total_paid / qty_bought, 4) if total_paid > 0 else None
                # Step 1 — INSERT new item, retrieve generated UUID
                inv_resp = supabase.table("inventory").insert({
                    "user_id":   st.session_state["user_id"],
                    "item_name": new_item_name.strip(),
                    "category":  new_category,
                    "quantity":  float(qty_bought),
                    "unit_cost": new_unit_cost,
                }).execute()
                new_inventory_id = inv_resp.data[0]["id"]
                # Step 2 — INSERT shopping_history log
                supabase.table("shopping_history").insert({
                    "user_id":          st.session_state["user_id"],
                    "item_name":        new_item_name.strip(),
                    "category":         new_category,
                    "quantity_bought":  float(qty_bought),
                    "total_price_paid": float(total_paid),
                    "purchase_date":    purchase_date.isoformat(),
                    "inventory_id":     str(new_inventory_id),
                }).execute()
                st.toast(f"✅ Added & logged {new_item_name.strip()}!", icon="✅")
                st.rerun()
            except Exception as exc:
                st.error(f"Failed to add & log item: {exc}")


def render_procurement(df: pd.DataFrame, shopping_df: pd.DataFrame, locations_df: pd.DataFrame) -> None:
    from datetime import timedelta
    loc_lookup = (
        {r["id"]: f"{r['icon']} {r['name']}" for r in locations_df.to_dict("records")}
        if not locations_df.empty else {}
    )

    col_hdr, col_btn = st.columns([4, 1])
    with col_hdr:
        st.subheader("🛒 Procurement")
    with col_btn:
        if st.button("➕ Log Purchase", type="primary", use_container_width=True):
            dialog_log_purchase(df, locations_df)
    st.divider()

    # ── Section A: Low Stock ──────────────────────────────────────────────
    st.markdown("**Low Stock Items**")
    st.caption("Items where current quantity ≤ min_threshold.")
    if not df.empty and "min_threshold" in df.columns:
        low = df[df["min_threshold"].notna() & (df["quantity"] <= df["min_threshold"])].copy()
    else:
        low = pd.DataFrame()

    if low.empty:
        st.success("All items are above their minimum threshold.")
    else:
        low["Location"]    = low["location_id"].map(loc_lookup).fillna("📦 Unassigned")
        low["Deficit"]     = (low["min_threshold"] - low["quantity"]).clip(lower=0)
        low["Est. Budget"] = (low["Deficit"] * low["unit_cost"].fillna(0)).round(2)
        display_low = (
            low[["item_name", "category", "Location", "quantity", "min_threshold", "Deficit", "Est. Budget"]]
            .rename(columns={
                "item_name":     "Item",
                "category":      "Category",
                "quantity":      "Current Qty",
                "min_threshold": "Min. Threshold",
            })
        )
        st.dataframe(display_low, use_container_width=True, hide_index=True, column_config={
            "Est. Budget": st.column_config.NumberColumn(format="£%.2f"),
        })
        total_budget = low["Est. Budget"].sum()
        st.metric("Estimated Restock Budget", f"£{total_budget:,.2f}")

        # ── Shopping List CSV Export ──────────────────────────────────────
        csv_bytes = display_low.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Download Shopping List (CSV)",
            data=csv_bytes,
            file_name="shopping_list.csv",
            mime="text/csv",
            use_container_width=True,
        )
    st.divider()

    # ── Section B: Spending Analytics ────────────────────────────────────
    st.markdown("**Spending Analytics**")
    if shopping_df.empty:
        st.info("No purchase history yet. Log a receipt above to see charts here.")
        return

    today_ts   = pd.Timestamp.now(tz="UTC").normalize()
    thirty_ago = today_ts - pd.Timedelta(days=30)
    recent     = shopping_df[
        pd.to_datetime(shopping_df["purchase_date"], utc=True, errors="coerce") >= thirty_ago
    ].copy()

    # ── High-level spend KPI ──────────────────────────────────────────────
    total_spent_30d = float(recent["total_price_paid"].sum()) if not recent.empty else 0.0
    st.metric("💳 Total Spent (Last 30 Days)", f"£{total_spent_30d:,.2f}")
    st.divider()

    col_pie, col_line = st.columns(2)

    with col_pie:
        st.markdown("**By Category — Last 30 Days**")
        if recent.empty:
            st.caption("No purchases in the last 30 days.")
        else:
            cat_spend = (
                recent.groupby("category")["total_price_paid"]
                .sum().reset_index()
                .rename(columns={"category": "Category", "total_price_paid": "Spent"})
            )
            fig_pie = px.pie(
                cat_spend, names="Category", values="Spent",
                hole=0.35,
                color_discrete_sequence=px.colors.qualitative.Set2,
            )
            fig_pie.update_traces(textposition="inside", textinfo="percent+label")
            fig_pie.update_layout(
                height=320, margin=dict(t=20, b=10, l=10, r=10), showlegend=False,
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_pie, use_container_width=True)

    with col_line:
        st.markdown("**Unit Cost Over Time**")
        item_list = sorted(shopping_df["item_name"].unique().tolist())
        if item_list:
            selected_line = st.selectbox(
                "Item", options=item_list, key="line_item_select", label_visibility="collapsed"
            )
            item_hist = shopping_df[shopping_df["item_name"] == selected_line].copy()
            item_hist = item_hist[item_hist["quantity_bought"] > 0].copy()
            item_hist["unit_cost_calc"] = item_hist["total_price_paid"] / item_hist["quantity_bought"]
            item_hist = item_hist.sort_values("purchase_date")
            if len(item_hist) < 2:
                st.caption("Need at least 2 purchases to show a trend.")
            else:
                fig_line = px.line(
                    item_hist, x="purchase_date", y="unit_cost_calc", markers=True,
                    labels={"purchase_date": "Date", "unit_cost_calc": "Unit Cost (£)"},
                    color_discrete_sequence=["#4A90D9"],
                )
                fig_line.update_layout(
                    height=320, margin=dict(t=20, b=10, l=10, r=10),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                )
                st.plotly_chart(fig_line, use_container_width=True)
    st.divider()

    # ── Section C: Full Purchase History ─────────────────────────────────
    st.markdown("**Full Purchase History**")
    history_display = (
        shopping_df[["item_name", "category", "quantity_bought", "total_price_paid", "purchase_date"]]
        .rename(columns={
            "item_name":        "Item",
            "category":         "Category",
            "quantity_bought":  "Qty Bought",
            "total_price_paid": "Total Paid",
            "purchase_date":    "Date",
        })
    )
    st.dataframe(history_display, use_container_width=True, hide_index=True, column_config={
        "Total Paid": st.column_config.NumberColumn(format="£%.2f"),
        "Date":       st.column_config.DatetimeColumn(format="DD/MM/YYYY"),
    })


def render_maintenance(maintenance_df: pd.DataFrame, df: pd.DataFrame) -> None:
    from datetime import timedelta, date as date_type

    col_hdr, col_add = st.columns([5, 1])
    with col_hdr:
        st.subheader("🔧 Maintenance Tasks")
    with col_add:
        if st.button("➕ Add Task", type="primary", use_container_width=True):
            dialog_add_maintenance_task(df)

    if maintenance_df.empty:
        render_empty_state(
            "No maintenance tasks yet. Track recurring jobs like filter changes or appliance servicing.",
            "➕ Add First Task",
            lambda: dialog_add_maintenance_task(df),
        )
        return

    today = pd.Timestamp.now(tz="UTC").normalize()

    # Build display table
    item_lookup = (
        {r["id"]: r["item_name"] for r in df.to_dict("records")}
        if not df.empty else {}
    )

    display = maintenance_df.copy()
    display["Linked Item"]  = display["inventory_id"].map(item_lookup).fillna("—")
    display["next_due_ts"]  = pd.to_datetime(display["next_due"], utc=True, errors="coerce")
    display["Status"]       = display["next_due_ts"].apply(
        lambda d: "🔴 Overdue" if pd.notna(d) and d < today
        else ("🟡 Due Soon" if pd.notna(d) and d <= today + pd.Timedelta(days=7)
              else "🟢 OK")
    )
    display["Days Until Due"] = (display["next_due_ts"] - today).dt.days

    show_cols = display[["task_name", "Linked Item", "frequency_days",
                          "last_completed", "next_due", "Days Until Due", "Status"]].rename(columns={
        "task_name":       "Task",
        "frequency_days":  "Every (days)",
        "last_completed":  "Last Done",
        "next_due":        "Next Due",
    })

    # Sort overdue first
    show_cols = show_cols.sort_values("Days Until Due", na_position="last")

    st.dataframe(
        show_cols,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Last Done":     st.column_config.DatetimeColumn(format="DD/MM/YYYY"),
            "Next Due":      st.column_config.DatetimeColumn(format="DD/MM/YYYY"),
            "Days Until Due": st.column_config.NumberColumn(format="%d days"),
        },
    )

    st.divider()

    # ── Mark Complete ─────────────────────────────────────────────────────
    st.markdown("#### ✅ Mark Task as Complete")
    task_options = {r["task_name"]: r["id"] for r in maintenance_df.to_dict("records")}

    col_sel, col_btn = st.columns([3, 1])
    with col_sel:
        chosen_task  = st.selectbox("Select task", options=list(task_options.keys()),
                                    label_visibility="collapsed")
    with col_btn:
        if st.button("✅ Mark Done", type="primary", use_container_width=True):
            task_id       = task_options[chosen_task]
            task_row      = maintenance_df[maintenance_df["id"] == task_id].iloc[0]
            freq          = int(task_row["frequency_days"])
            completed_today = datetime.now(timezone.utc).date()
            new_next_due    = completed_today + timedelta(days=freq)
            try:
                _set_postgrest_auth()
                supabase.table("maintenance_tasks").update({
                    "last_completed": completed_today.isoformat(),
                    "next_due":       new_next_due.isoformat(),
                }).eq("id", task_id).execute()
                st.toast(f"✅ '{chosen_task}' marked complete. Next due: {new_next_due.strftime('%d/%m/%Y')}", icon="🔧")
                st.rerun()
            except Exception as exc:
                st.error(f"Update failed: {exc}")

    st.divider()

    # ── Delete Task ───────────────────────────────────────────────────────
    with st.expander("🗑️ Delete a Task", expanded=False):
        del_task = st.selectbox("Task to delete", options=list(task_options.keys()), key="del_task_sel")
        if st.button("🗑️ Delete", type="primary"):
            try:
                _set_postgrest_auth()
                supabase.table("maintenance_tasks").delete().eq("id", task_options[del_task]).execute()
                st.toast(f"🗑️ '{del_task}' deleted.", icon="✅")
                st.rerun()
            except Exception as exc:
                st.error(f"Deletion failed: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# 13.  DASHBOARD TAB
# ─────────────────────────────────────────────────────────────────────────────
def _kpi_card(col, label: str, value: str, icon: str, accent: str, bg: str) -> None:
    with col:
        st.markdown(
            f"""
            <div class="kpi-card" style="background:{bg};border-left:4px solid {accent};">
              <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                <div>
                  <p style="color:#94a3b8;font-size:0.75rem;font-weight:700;
                             text-transform:uppercase;letter-spacing:0.1em;margin:0 0 10px 0">
                    {_esc(label)}
                  </p>
                  <p style="color:#f1f5f9;font-size:2.4rem;font-weight:800;margin:0;line-height:1.1">
                    {_esc(value)}
                  </p>
                </div>
                <span style="font-size:2.2rem;opacity:0.75;padding-top:4px">{icon}</span>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

def render_dashboard(df: pd.DataFrame, prefs: dict, locations_df: pd.DataFrame, maintenance_df: pd.DataFrame) -> None:
    layout     = dict(prefs.get("dashboard_layout", {}))
    loc_lookup = (
        {r["id"]: f"{r['icon']} {r['name']}" for r in locations_df.to_dict("records")}
        if not locations_df.empty else {}
    )

    if df.empty:
        render_empty_state(
            "Your inventory is empty — add items in the Inventory tab!",
            "➕ Add First Item",
            dialog_add_item,
        )
        return

    # ── KPIs ──────────────────────────────────────────────────────────────
    total_items    = len(df)
    total_quantity = float(df["quantity"].sum())
    low_stock      = int((df["quantity"] < 5).sum())
    total_value    = float(
        pd.to_numeric(df.get("estimated_value", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()
    )

    c1, c2, c3, c4 = st.columns(4)
    _kpi_card(c1, "Total Items",    str(total_items),         "🏠", "#14b8a6", "#0a2826")
    _kpi_card(c2, "Total Quantity", f"{total_quantity:,.0f}", "📦", "#3b82f6", "#0d1f3c")
    _kpi_card(c3, "Low Stock",      str(low_stock),           "⚠️", "#ef4444", "#3c0d0d")
    _kpi_card(c4, "Total Value",    f"£{total_value:,.0f}",   "💷", "#22c55e", "#0d2e1a")
    st.divider()

    # ── Charts row ────────────────────────────────────────────────────────
    col_bar, col_donut = st.columns([3, 2])

    with col_bar:
        st.markdown("**Quantity by Item**")
        chart_df = (
            df[["item_name", "quantity"]]
            .groupby("item_name")["quantity"]
            .sum()
            .reset_index()
            .sort_values("quantity", ascending=False)
            .head(10)
        )
        chart_df.columns = ["Item", "Quantity"]
        selection = alt.selection_point(fields=["Item"])
        bar = (
            alt.Chart(chart_df)
            .mark_bar(cornerRadiusTopRight=5, cornerRadiusBottomRight=5)
            .encode(
                y=alt.Y("Item:N", sort="-x", axis=alt.Axis(labelLimit=150)),
                x=alt.X("Quantity:Q", title="Quantity"),
                color=alt.condition(
                    selection,
                    alt.value("#14b8a6"),
                    alt.value("#1e4a44"),
                ),
                tooltip=[
                    alt.Tooltip("Item:N", title="Item"),
                    alt.Tooltip("Quantity:Q", title="Qty", format=".0f"),
                ],
            )
            .add_params(selection)
            .properties(height=340)
        )
        chart_event = st.altair_chart(bar, theme="streamlit", use_container_width=True, on_select="rerun", key="dash_bar_chart")
        if chart_event:
            st.session_state["chart_selection"] = getattr(chart_event, "selection", None)

    with col_donut:
        st.markdown("**Spending by Category**")
        if "estimated_value" in df.columns:
            spend = (
                df[df["estimated_value"] > 0]
                .groupby("category")["estimated_value"]
                .sum()
                .reset_index()
                .rename(columns={"category": "Category", "estimated_value": "Value"})
            )
        else:
            spend = pd.DataFrame()

        if not spend.empty:
            fig_donut = px.pie(
                spend, names="Category", values="Value",
                hole=0.52,
                color_discrete_sequence=px.colors.qualitative.Set2,
            )
            fig_donut.update_traces(textposition="outside", textinfo="label+percent")
            fig_donut.update_layout(
                height=340,
                margin=dict(t=20, b=40, l=10, r=10),
                showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=-0.35, font_size=11),
                annotations=[dict(
                    text=f"£{spend['Value'].sum():,.0f}",
                    x=0.5, y=0.5, font_size=17, showarrow=False,
                    font_color="#f1f5f9",
                )],
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_donut, use_container_width=True)
        else:
            st.caption("No asset values recorded yet.")

    st.divider()

    # ── All Items by Location ─────────────────────────────────────────────
    st.markdown("**All Items by Location**")
    max_qty  = max(float(df["quantity"].max()), 1.0)
    summary  = df[["item_name", "quantity", "custom_unit", "location_id", "updated_at"]].copy()
    summary["Location"] = summary["location_id"].map(loc_lookup).fillna("📦 Unassigned")
    summary = (
        summary.drop(columns=["location_id"])
        .rename(columns={
            "item_name":   "Item",
            "quantity":    "Quantity",
            "custom_unit": "Unit",
            "updated_at":  "Last Updated",
        })
        .sort_values(["Location", "Item"])
        .reset_index(drop=True)
    )
    st.dataframe(
        summary[["Location", "Item", "Quantity", "Unit", "Last Updated"]],
        use_container_width=True,
        hide_index=True,
        column_config={
            "Quantity": st.column_config.ProgressColumn(
                "Quantity", min_value=0, max_value=max_qty, format="%.0f"
            ),
            "Last Updated": st.column_config.DatetimeColumn(
                "Last Updated", format="DD/MM/YYYY HH:mm"
            ),
        },
    )
    st.divider()

    # ── Low Stock ─────────────────────────────────────────────────────────
    st.markdown("**Low Stock Items**")
    st.caption("Items where current quantity ≤ min_threshold.")
    if "min_threshold" in df.columns:
        low = df[df["min_threshold"].notna() & (df["quantity"] <= df["min_threshold"])].copy()
    else:
        low = pd.DataFrame()

    if low.empty:
        st.success("All items are above their minimum threshold.")
    else:
        low["Location"] = low["location_id"].map(loc_lookup).fillna("📦 Unassigned")
        low["Deficit"]      = (low["min_threshold"] - low["quantity"]).clip(lower=0)
        low["Est. Budget"]  = (low["Deficit"] * low["unit_cost"].fillna(0)).round(2)
        display_low = (
            low[["item_name", "category", "Location", "quantity", "min_threshold", "Deficit", "Est. Budget"]]
            .rename(columns={
                "item_name":     "Item",
                "category":      "Category",
                "quantity":      "Current Qty",
                "min_threshold": "Min. Threshold",
            })
        )
        st.dataframe(display_low, use_container_width=True, hide_index=True, column_config={
            "Est. Budget": st.column_config.NumberColumn(format="£%.2f"),
        })
        st.metric("Estimated Restock Budget", f"£{low['Est. Budget'].sum():,.2f}")
    st.divider()

    # ── Alerts row ────────────────────────────────────────────────────────
    col_expiry, col_maint = st.columns(2)
    today = pd.Timestamp.now(tz="UTC").normalize()
    in_30 = today + pd.Timedelta(days=30)

    with col_expiry:
        st.markdown("⏰ **Expiry Radar — 30 Days**")
        if "expiry_date" in df.columns:
            exp = df[df["expiry_date"].notna()].copy()
            exp["expiry_date"] = pd.to_datetime(exp["expiry_date"], utc=True, errors="coerce")
            exp = exp[(exp["expiry_date"] >= today) & (exp["expiry_date"] <= in_30)].sort_values("expiry_date")
        else:
            exp = pd.DataFrame()
        if exp.empty:
            st.success("Nothing expiring in 30 days.")
        else:
            st.warning(f"{len(exp)} items expiring soon.")
            r = exp[["item_name", "expiry_date", "quantity"]].copy()
            r["Days Left"] = (r["expiry_date"] - today).dt.days
            r = r.rename(columns={"item_name": "Item", "expiry_date": "Expires", "quantity": "Qty"})
            st.dataframe(r, use_container_width=True, hide_index=True, column_config={
                "Expires":   st.column_config.DatetimeColumn(format="DD/MM/YYYY"),
                "Days Left": st.column_config.NumberColumn(format="%d d"),
            })

    with col_maint:
        st.markdown("🔧 **Maintenance Alerts**")
        if maintenance_df.empty:
            st.info("No maintenance tasks set up yet.")
        else:
            m_ts      = pd.to_datetime(maintenance_df["next_due"], utc=True, errors="coerce")
            overdue   = maintenance_df[m_ts < today]
            due_soon  = maintenance_df[(m_ts >= today) & (m_ts <= today + pd.Timedelta(days=7))]
            if overdue.empty and due_soon.empty:
                st.success("No overdue or upcoming maintenance.")
            else:
                if not overdue.empty:
                    st.error(f"{len(overdue)} overdue task(s)")
                    for _, t in overdue.iterrows():
                        st.markdown(f"- {t['task_name']} — due {t['next_due']}")
                if not due_soon.empty:
                    st.warning(f"{len(due_soon)} due within 7 days")
                    for _, t in due_soon.iterrows():
                        st.markdown(f"- {t['task_name']} — due {t['next_due']}")
    st.divider()

    # ── Financial Overview ────────────────────────────────────────────────
    st.markdown("**Financial Overview**")
    sunk_cost = asset_value = 0.0
    if not df.empty:
        cons = df[df["category"].isin(_EXPIRY_CATS)].copy()
        cons["unit_cost"] = pd.to_numeric(cons.get("unit_cost", pd.Series(dtype=float)), errors="coerce").fillna(0)
        sunk_cost   = float((cons["quantity"] * cons["unit_cost"]).sum())
        durable     = df[df["category"].isin(_DURABLE_CATS)].copy()
        asset_value = float(pd.to_numeric(durable.get("estimated_value", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())

    cf1, cf2 = st.columns(2)
    with cf1:
        st.metric("Sunk Cost (Consumables/Toiletries)", f"£{sunk_cost:,.2f}",
                  help="Sum of quantity × unit_cost for perishable categories.")
    with cf2:
        st.metric("Asset Value (Durables)", f"£{asset_value:,.2f}",
                  help="Sum of estimated_value for Electronics, Appliances, Valuables, Furniture.")

    if "estimated_value" in df.columns:
        asset_df = df[df["estimated_value"].notna() & (df["estimated_value"] > 0)].copy()
        if not asset_df.empty:
            asset_df["Location"] = asset_df["location_id"].map(loc_lookup).fillna("📦 Unassigned")
            ledger = (
                asset_df.groupby("Location")["estimated_value"]
                .sum().reset_index()
                .rename(columns={"estimated_value": "Total Value"})
                .sort_values("Total Value", ascending=False)
            )
            fig_bar = px.bar(
                ledger, x="Location", y="Total Value",
                color="Location",
                color_discrete_sequence=px.colors.qualitative.Set2,
                text_auto=".2s",
            )
            fig_bar.update_layout(
                showlegend=False, height=260,
                margin=dict(t=10, b=10, l=10, r=10), xaxis_title=None,
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            )
            fig_bar.update_traces(textposition="outside")
            st.plotly_chart(fig_bar, use_container_width=True)


# ─────────────────────────────────────────────────────────────────────────────
# 14.  INVENTORY TAB
# ─────────────────────────────────────────────────────────────────────────────
def render_empty_state(message: str, button_text: str, action) -> None:
    """Centred empty-state card with a primary CTA button."""
    _, col, _ = st.columns([1, 2, 1])
    with col:
        with st.container(border=True):
            st.markdown(
                f"""
                <div style="text-align:center;padding:1.5rem 1rem 0.5rem 1rem;">
                    <p style="font-size:2.5rem;margin:0 0 0.5rem 0">📭</p>
                    <p style="color:#64748b;font-size:0.95rem;margin:0 0 1rem 0">
                        {_esc(message)}
                    </p>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button(button_text, type="primary", use_container_width=True):
                action()

def render_inventory(df: pd.DataFrame) -> None:
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
        render_empty_state(
            "No items yet. Add your first item to get started.",
            "➕ Add First Item",
            dialog_add_item,
        )
        return

    safe_visible = [c for c in visible_cols if c in df.columns]
    # view_df keeps "id" for DB lookups; it is NOT passed to the editor
    view_df = df[["id"] + safe_visible].copy()

    # ── Process pending inline quantity edits (from previous interaction) ─
    editor_state = st.session_state.get("inventory_editor") or {}
    edited_rows  = editor_state.get("edited_rows", {})
    if edited_rows:
        saved = False
        for idx_str, changes in edited_rows.items():
            if "quantity" in changes:
                idx = int(idx_str)
                if idx < len(view_df):
                    item_id = view_df.iloc[idx]["id"]
                    new_qty = float(changes["quantity"])
                    try:
                        _set_postgrest_auth()
                        supabase.table("inventory").update({
                            "quantity":   new_qty,
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        }).eq("id", item_id).execute()
                        saved = True
                    except Exception as exc:
                        st.error(f"Failed to save quantity for row {idx}: {exc}")
        if saved:
            st.session_state.pop("inventory_editor", None)
            st.toast("✅ Quantity saved!", icon="✅")
            st.rerun()

    # ── Inline-editable table (only Qty column is editable) ──────────────
    st.caption("✏️ Click any **Qty** cell to edit inline. Use the selector below to edit all fields or delete.")
    st.data_editor(
        view_df.drop(columns=["id"]),   # hide id from the user
        key="inventory_editor",
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        column_config={
            "item_name":   st.column_config.TextColumn("Item Name",   width="medium", disabled=True),
            "quantity":    st.column_config.NumberColumn("Qty",       format="%.2f",  disabled=False, min_value=0.0),
            "custom_unit": st.column_config.TextColumn("Unit",        width="small",  disabled=True),
            "description": st.column_config.TextColumn("Description", width="large",  disabled=True),
            "updated_at":  st.column_config.DatetimeColumn("Last Updated", format="DD/MM/YYYY HH:mm", disabled=True),
        },
    )

    # ── Row selector for full Edit / Delete ───────────────────────────────
    st.divider()
    selected_ids: list[str] = st.multiselect(
        "Select items to edit or delete",
        options=view_df["id"].tolist(),
        format_func=lambda iid: (
            view_df.loc[view_df["id"] == iid, "item_name"].iloc[0]
            if not view_df.loc[view_df["id"] == iid].empty else iid
        ),
        label_visibility="collapsed",
        placeholder="Select items to edit or delete…",
        key="inv_selection",
    )

    if selected_ids:
        st.markdown(f"**{len(selected_ids)} row(s) selected**")
        col_edit, col_delete, col_spacer = st.columns([1, 1, 5])
        with col_edit:
            edit_disabled = len(selected_ids) != 1
            if st.button(
                "✏️ Edit",
                disabled=edit_disabled,
                help="Select exactly 1 row to edit." if edit_disabled else None,
                use_container_width=True,
            ):
                full_row = dict(df[df["id"] == selected_ids[0]].iloc[0].to_dict())
                dialog_edit_item(full_row)
        with col_delete:
            if st.button("🗑️ Delete", type="primary", use_container_width=True):
                selected_names = view_df.loc[
                    view_df["id"].isin(selected_ids), "item_name"
                ].tolist()
                dialog_confirm_delete(selected_ids, selected_names)
    else:
        st.caption("Select items above to edit or delete them.")

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
    # ── Fetch all data (one set of round-trips per rerun) ─────────────────
    with st.spinner("Loading your data…"):
        df:             pd.DataFrame = fetch_inventory()
        prefs:          dict         = fetch_preferences()
        locations_df:   pd.DataFrame = fetch_locations()
        units_df:       pd.DataFrame = fetch_units()
        shopping_df:    pd.DataFrame = fetch_shopping_history()
        maintenance_df: pd.DataFrame = fetch_maintenance_tasks()

    # ── Page closures capture the fetched data ────────────────────────────
    def _page_home():
        render_home_tab(df, locations_df, units_df)

    def _page_inventory():
        render_inventory(df)

    def _page_dashboard():
        render_dashboard(df, prefs, locations_df, maintenance_df)

    def _page_procurement():
        render_procurement(df, shopping_df, locations_df)

    def _page_maintenance():
        render_maintenance(maintenance_df, df)

    # ── Register st.navigation pages ──────────────────────────────────────
    pg = st.navigation(
        [
            st.Page(_page_home,        title="Home",        icon="🏠", default=True),
            st.Page(_page_inventory,   title="Inventory",   icon="📦"),
            st.Page(_page_dashboard,   title="Dashboard",   icon="📊"),
            st.Page(_page_procurement, title="Procurement", icon="🛒"),
            st.Page(_page_maintenance, title="Maintenance", icon="🔧"),
        ],
        position="sidebar",
    )

    # ── Custom sidebar content renders below the nav links ────────────────
    render_sidebar(prefs, df, locations_df, units_df)

    # ── Run the active page in the main area ──────────────────────────────
    pg.run()

# ─────────────────────────────────────────────────────────────────────────────
# 17.  ENTRY POINT  —  Security Gate
# ─────────────────────────────────────────────────────────────────────────────
if verify_session():
    render_main_app()
else:
    render_auth_page()
