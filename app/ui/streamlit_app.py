"""
app/ui/streamlit_app.py
Main Streamlit application entry point.
Run with: streamlit run app/ui/streamlit_app.py
"""
from __future__ import annotations

import streamlit as st

# Must be first Streamlit call
st.set_page_config(
    page_title="AUTOSAR HLD Assistant",
    page_icon="🏗️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

    /* Global font */
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    /* Dark theme overrides */
    .stApp {
        background: linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 50%, #16213e 100%);
    }

    /* Sidebar styling */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1a1a2e 0%, #0f0f1a 100%);
        border-right: 1px solid rgba(99, 102, 241, 0.2);
    }

    [data-testid="stSidebar"] .stMarkdown h1 {
        background: linear-gradient(135deg, #818cf8, #6366f1, #a78bfa);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 800;
        font-size: 1.4rem;
    }

    /* Card styling */
    .metric-card {
        background: linear-gradient(135deg, rgba(99, 102, 241, 0.1), rgba(139, 92, 246, 0.05));
        border: 1px solid rgba(99, 102, 241, 0.2);
        border-radius: 16px;
        padding: 1.2rem;
        backdrop-filter: blur(10px);
        transition: all 0.3s ease;
    }

    .metric-card:hover {
        border-color: rgba(99, 102, 241, 0.5);
        transform: translateY(-2px);
        box-shadow: 0 8px 32px rgba(99, 102, 241, 0.15);
    }

    .metric-value {
        font-size: 2.2rem;
        font-weight: 800;
        background: linear-gradient(135deg, #818cf8, #a78bfa);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }

    .metric-label {
        font-size: 0.85rem;
        color: #94a3b8;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }

    /* Button styling */
    .stButton > button {
        background: linear-gradient(135deg, #6366f1, #8b5cf6);
        color: white;
        border: none;
        border-radius: 10px;
        padding: 0.5rem 1.5rem;
        font-weight: 600;
        font-family: 'Inter', sans-serif;
        transition: all 0.3s ease;
    }

    .stButton > button:hover {
        background: linear-gradient(135deg, #818cf8, #a78bfa);
        box-shadow: 0 4px 24px rgba(99, 102, 241, 0.4);
        transform: translateY(-1px);
    }

    /* Status badges */
    .badge-approved { color: #34d399; font-weight: 600; }
    .badge-pending { color: #fbbf24; font-weight: 600; }
    .badge-rejected { color: #f87171; font-weight: 600; }

    /* Section headers */
    .section-header {
        font-size: 1.3rem;
        font-weight: 700;
        color: #e2e8f0;
        margin-bottom: 1rem;
        padding-bottom: 0.5rem;
        border-bottom: 2px solid rgba(99, 102, 241, 0.3);
    }

    /* Chat-style Q&A */
    .question-bubble {
        background: linear-gradient(135deg, rgba(99, 102, 241, 0.2), rgba(139, 92, 246, 0.1));
        border: 1px solid rgba(99, 102, 241, 0.3);
        border-radius: 12px 12px 12px 4px;
        padding: 1rem 1.2rem;
        margin-bottom: 0.5rem;
    }

    .answer-bubble {
        background: rgba(30, 41, 59, 0.5);
        border: 1px solid rgba(148, 163, 184, 0.15);
        border-radius: 12px 12px 4px 12px;
        padding: 1rem 1.2rem;
        margin-bottom: 1rem;
    }

    /* Table styling */
    .stDataFrame {
        border-radius: 12px;
        overflow: hidden;
    }

    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 0.5rem;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px 8px 0 0;
        font-weight: 600;
    }

    /* Expander */
    .streamlit-expanderHeader {
        font-weight: 600;
        color: #c7d2fe;
    }

    /* Hide default footer */
    footer { visibility: hidden; }
    .stDeployButton { display: none; }

    /* Scrollbar */
    ::-webkit-scrollbar { width: 6px; }
    ::-webkit-scrollbar-track { background: #1a1a2e; }
    ::-webkit-scrollbar-thumb { background: #6366f1; border-radius: 3px; }
</style>
""", unsafe_allow_html=True)


# ── Session state defaults ────────────────────────────────────────────────────

if "token" not in st.session_state:
    st.session_state.token = None
if "username" not in st.session_state:
    st.session_state.username = None
if "role" not in st.session_state:
    st.session_state.role = None
if "current_project" not in st.session_state:
    st.session_state.current_project = None


# ── API helper ────────────────────────────────────────────────────────────────

import requests
from app.core.config import get_settings


def api_url(path: str) -> str:
    settings = get_settings()
    return f"{settings.api_base_url}{path}"


def auth_headers() -> dict:
    return {"Authorization": f"Bearer {st.session_state.token}"}


def api_get(path: str, params: dict | None = None):
    try:
        resp = requests.get(api_url(path), headers=auth_headers(), params=params, timeout=30)
        return resp
    except requests.ConnectionError:
        st.error("⚠️ Cannot reach the API server. Is it running?")
        return None


def api_post(path: str, json_data: dict | None = None, data: dict | None = None, files: dict | None = None):
    try:
        resp = requests.post(api_url(path), headers=auth_headers(), json=json_data, data=data, files=files, timeout=60)
        return resp
    except requests.ConnectionError:
        st.error("⚠️ Cannot reach the API server. Is it running?")
        return None


def api_put(path: str, json_data: dict | None = None):
    try:
        resp = requests.put(api_url(path), headers=auth_headers(), json=json_data, timeout=30)
        return resp
    except requests.ConnectionError:
        st.error("⚠️ Cannot reach the API server. Is it running?")
        return None


# ── Login page ────────────────────────────────────────────────────────────────

def login_page():
    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        st.markdown("")
        st.markdown("")
        st.markdown("""
        <div style="text-align: center; margin-bottom: 2rem;">
            <div style="font-size: 3rem; margin-bottom: 0.5rem;">🏗️</div>
            <h1 style="background: linear-gradient(135deg, #818cf8, #6366f1, #a78bfa);
                        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
                        font-size: 2rem; font-weight: 800; margin-bottom: 0.3rem;">
                AUTOSAR HLD Assistant
            </h1>
            <p style="color: #94a3b8; font-size: 0.95rem;">
                Secure AI-powered document analysis
            </p>
        </div>
        """, unsafe_allow_html=True)

        with st.form("login_form"):
            username = st.text_input("Username", placeholder="Enter username")
            password = st.text_input("Password", type="password", placeholder="Enter password")
            submitted = st.form_submit_button("Sign In", use_container_width=True)

            if submitted:
                if not username or not password:
                    st.error("Please enter both username and password")
                    return
                try:
                    resp = requests.post(
                        api_url("/api/auth/token"),
                        data={"username": username, "password": password},
                        timeout=10,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        st.session_state.token = data["access_token"]
                        st.session_state.username = data["username"]
                        st.session_state.role = data["role"]
                        st.rerun()
                    else:
                        st.error("❌ Invalid credentials")
                except requests.ConnectionError:
                    st.error("⚠️ Cannot connect to API server. Run: `uvicorn app.api.main:app`")

        st.markdown("""
        <div style="text-align: center; margin-top: 1rem; color: #64748b; font-size: 0.8rem;">
            Default: admin / admin123
        </div>
        """, unsafe_allow_html=True)


# ── Dashboard page ────────────────────────────────────────────────────────────

def dashboard_page():
    st.markdown('<div class="section-header">📊 Dashboard</div>', unsafe_allow_html=True)

    # Fetch project list
    resp = api_get("/api/projects/")
    if not resp or resp.status_code != 200:
        st.info("No projects yet. Create one from the sidebar!")
        return

    projects = resp.json()

    # Metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value">{len(projects)}</div>
            <div class="metric-label">Projects</div>
        </div>
        """, unsafe_allow_html=True)

    total_docs = 0
    total_entities = 0
    for p in projects:
        doc_resp = api_get(f"/api/documents/{p['id']}")
        if doc_resp and doc_resp.status_code == 200:
            docs = doc_resp.json()
            total_docs += len(docs)

    with col2:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value">{total_docs}</div>
            <div class="metric-label">Documents</div>
        </div>
        """, unsafe_allow_html=True)

    with col3:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value">{st.session_state.role}</div>
            <div class="metric-label">Your Role</div>
        </div>
        """, unsafe_allow_html=True)

    with col4:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value">✓</div>
            <div class="metric-label">API Status</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("")

    # Project list
    st.markdown('<div class="section-header">🗂️ Your Projects</div>', unsafe_allow_html=True)
    for p in projects:
        with st.expander(f"📁 {p['name']}", expanded=False):
            st.write(p.get("description", ""))
            col1, col2, col3 = st.columns(3)
            with col1:
                if st.button(f"Select Project", key=f"select_{p['id']}"):
                    st.session_state.current_project = p
                    st.rerun()
            with col2:
                st.caption(f"ID: {p['id']}")
            with col3:
                st.caption(f"Created by: User #{p['created_by']}")


# ── Documents page ───────────────────────────────────────────────────────────

def documents_page():
    st.markdown('<div class="section-header">📄 Documents</div>', unsafe_allow_html=True)

    project = st.session_state.current_project
    if not project:
        st.warning("Please select a project from the Dashboard first.")
        return

    st.caption(f"Project: **{project['name']}** (ID: {project['id']})")

    # Upload form
    with st.expander("📤 Upload New Document", expanded=False):
        uploaded_file = st.file_uploader("Choose a PDF file", type=["pdf"])
        version_label = st.text_input("Version Label", placeholder="e.g. v1.0, draft-2")
        if st.button("Upload", disabled=not uploaded_file or not version_label):
            if uploaded_file and version_label:
                files = {"file": (uploaded_file.name, uploaded_file.getvalue(), "application/pdf")}
                data = {"project_id": str(project["id"]), "version_label": version_label}
                resp = requests.post(
                    api_url("/api/documents/upload"),
                    headers=auth_headers(),
                    data=data,
                    files=files,
                    timeout=120,
                )
                if resp and resp.status_code == 201:
                    st.success(f"✅ Document uploaded! ID: {resp.json()['id']}")
                    st.rerun()
                else:
                    st.error(f"❌ Upload failed: {resp.text if resp else 'Connection error'}")

    # Document list
    resp = api_get(f"/api/documents/{project['id']}")
    if not resp or resp.status_code != 200:
        st.info("No documents uploaded yet.")
        return

    docs = resp.json()
    if not docs:
        st.info("No documents in this project.")
        return

    for doc in docs:
        status_class = {
            "pending": "badge-pending",
            "approved": "badge-approved",
            "rejected": "badge-rejected",
        }.get(doc["status"], "badge-pending")

        with st.expander(f"📄 {doc['filename']} — v{doc['version_label']}", expanded=False):
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.markdown(f"**Status:** <span class='{status_class}'>{doc['status']}</span>", unsafe_allow_html=True)
            with col2:
                st.caption(f"Pages: {doc.get('page_count', '-')}")
            with col3:
                st.caption(f"OCR: {'Yes' if doc.get('ocr_used') else 'No'}")
            with col4:
                st.caption(f"ID: {doc['id']}")

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                if doc["status"] == "pending":
                    if st.button("✅ Approve", key=f"approve_{doc['id']}"):
                        resp = api_post(f"/api/documents/{doc['id']}/approve")
                        if resp and resp.status_code == 200:
                            st.success("Document approved!")
                            st.rerun()
                        else:
                            st.error(f"Failed: {resp.text if resp else 'Error'}")

            with col2:
                if st.button("🔍 Extract Entities", key=f"extract_{doc['id']}"):
                    with st.spinner("Extracting entities..."):
                        resp = api_post("/api/extraction/run", json_data={
                            "document_id": doc["id"], "use_llm": False
                        })
                        if resp and resp.status_code == 201:
                            st.success(f"Extracted {resp.json()['entities_extracted']} entities!")
                        else:
                            st.error(f"Failed: {resp.text if resp else 'Error'}")

            with col3:
                if st.button("🔎 Check Consistency", key=f"check_{doc['id']}"):
                    with st.spinner("Running checks..."):
                        resp = api_post(f"/api/consistency/run/{doc['id']}")
                        if resp and resp.status_code == 200:
                            st.success(f"Found {resp.json()['issues_found']} issues.")
                        else:
                            st.error(f"Failed: {resp.text if resp else 'Error'}")

            with col4:
                if st.button("📥 Export Report", key=f"export_{doc['id']}"):
                    resp = api_get(f"/api/export/entities/{doc['id']}/markdown")
                    if resp and resp.status_code == 200:
                        st.download_button(
                            "Download Markdown Report",
                            data=resp.content,
                            file_name=f"report_doc{doc['id']}.md",
                            mime="text/markdown",
                            key=f"dl_{doc['id']}",
                        )


# ── Query page ────────────────────────────────────────────────────────────────

def query_page():
    st.markdown('<div class="section-header">💬 Ask the Assistant</div>', unsafe_allow_html=True)

    project = st.session_state.current_project
    if not project:
        st.warning("Please select a project from the Dashboard first.")
        return

    st.caption(f"Querying project: **{project['name']}**")

    # Query history
    if "query_history" not in st.session_state:
        st.session_state.query_history = []

    # Display history
    for item in st.session_state.query_history:
        st.markdown(f"""
        <div class="question-bubble">
            <strong>🙋 You:</strong> {item['question']}
        </div>
        """, unsafe_allow_html=True)

        st.markdown(f"""
        <div class="answer-bubble">
            <strong>🤖 Assistant:</strong><br>{item['answer']}
        </div>
        """, unsafe_allow_html=True)

        if item.get("citations"):
            with st.expander(f"📖 Citations ({len(item['citations'])})"):
                for c in item["citations"]:
                    st.caption(
                        f"Doc {c['document_id']} (v{c['version_label']}) — "
                        f"Pages {c['page_start']}–{c['page_end']} | {c['section_path']}"
                    )

    # Query input
    with st.form("query_form", clear_on_submit=True):
        question = st.text_area(
            "Your question",
            placeholder="e.g. What SWCs are defined in the engine control module?",
            height=100,
        )
        col1, col2 = st.columns([3, 1])
        with col1:
            top_k = st.slider("Chunks to retrieve", 1, 20, 5)
        with col2:
            temp = st.slider("Temperature", 0.0, 1.0, 0.1, step=0.05)

        submitted = st.form_submit_button("🔎 Ask", use_container_width=True)

        if submitted and question:
            with st.spinner("Searching documents and generating answer..."):
                resp = api_post("/api/query/ask", json_data={
                    "question": question,
                    "project_id": project["id"],
                    "top_k": top_k,
                    "temperature": temp,
                })
                if resp and resp.status_code == 200:
                    data = resp.json()
                    st.session_state.query_history.append({
                        "question": question,
                        "answer": data["answer"],
                        "citations": data.get("citations", []),
                    })
                    st.rerun()
                else:
                    st.error(f"Query failed: {resp.text if resp else 'Connection error'}")


# ── Entities page ─────────────────────────────────────────────────────────────

def entities_page():
    st.markdown('<div class="section-header">🧩 Extracted Entities</div>', unsafe_allow_html=True)

    project = st.session_state.current_project
    if not project:
        st.warning("Please select a project from the Dashboard first.")
        return

    # Get documents for this project
    resp = api_get(f"/api/documents/{project['id']}")
    if not resp or resp.status_code != 200:
        st.info("No documents in this project.")
        return

    docs = resp.json()
    if not docs:
        st.info("No documents.")
        return

    doc_names = {d["id"]: f"{d['filename']} (v{d['version_label']})" for d in docs}
    selected_doc_id = st.selectbox(
        "Select document",
        options=list(doc_names.keys()),
        format_func=lambda x: doc_names[x],
    )

    if selected_doc_id:
        entity_type_filter = st.selectbox(
            "Filter by type",
            options=["All", "SWComponent", "Interface", "Signal", "Dependency", "DataFlow"],
        )

        params = {}
        if entity_type_filter != "All":
            params["entity_type"] = entity_type_filter

        resp = api_get(f"/api/extraction/{selected_doc_id}", params=params)
        if not resp or resp.status_code != 200:
            st.info("No entities extracted yet.")
            return

        entities = resp.json()
        if not entities:
            st.info("No entities found. Try running extraction first.")
            return

        st.caption(f"Found **{len(entities)}** entities")

        # Summary metrics
        import json as _json
        type_counts: dict[str, int] = {}
        for e in entities:
            type_counts[e["entity_type"]] = type_counts.get(e["entity_type"], 0) + 1

        cols = st.columns(min(len(type_counts), 5))
        for i, (etype, count) in enumerate(sorted(type_counts.items())):
            with cols[i % len(cols)]:
                st.metric(etype, count)

        # Entity table
        import pandas as pd
        df = pd.DataFrame([{
            "Name": e["name"],
            "Type": e["entity_type"],
            "Confidence": f"{e['confidence']:.0%}",
            "Page": e.get("page", "-"),
            "Section": e.get("section", "-"),
            "Status": e.get("review_status", "pending"),
            "Needs Review": "⚠️" if e.get("requires_human_review") else "✓",
        } for e in entities])

        st.dataframe(df, use_container_width=True, hide_index=True)

        # Entity details
        for e in entities:
            with st.expander(f"🔹 {e['entity_type']}: {e['name']} ({e['confidence']:.0%})"):
                try:
                    data = _json.loads(e["data_json"])
                    st.json(data)
                except Exception:
                    st.code(e["data_json"])

                col1, col2, col3 = st.columns(3)
                with col1:
                    if st.button("✅ Accept", key=f"accept_{e['id']}"):
                        resp = api_put(f"/api/extraction/entity/{e['id']}/review", json_data={
                            "status": "accepted"
                        })
                        if resp and resp.status_code == 200:
                            st.success("Accepted!")
                            st.rerun()
                with col2:
                    if st.button("✏️ Edit", key=f"edit_{e['id']}"):
                        st.session_state[f"editing_{e['id']}"] = True
                with col3:
                    if st.button("❌ Reject", key=f"reject_{e['id']}"):
                        resp = api_put(f"/api/extraction/entity/{e['id']}/review", json_data={
                            "status": "rejected", "comment": "Rejected by reviewer"
                        })
                        if resp and resp.status_code == 200:
                            st.warning("Rejected.")
                            st.rerun()


# ── Consistency page ──────────────────────────────────────────────────────────

def consistency_page():
    st.markdown('<div class="section-header">🔍 Consistency Issues</div>', unsafe_allow_html=True)

    project = st.session_state.current_project
    if not project:
        st.warning("Please select a project from the Dashboard first.")
        return

    resp = api_get(f"/api/documents/{project['id']}")
    if not resp or resp.status_code != 200:
        st.info("No documents.")
        return

    docs = resp.json()
    doc_names = {d["id"]: f"{d['filename']} (v{d['version_label']})" for d in docs}
    selected_doc_id = st.selectbox(
        "Select document",
        options=list(doc_names.keys()),
        format_func=lambda x: doc_names[x],
        key="consistency_doc_select",
    )

    if selected_doc_id:
        resp = api_get(f"/api/consistency/{selected_doc_id}")
        if not resp or resp.status_code != 200:
            st.info("No issues found or checks not run yet.")
            return

        issues = resp.json()
        if not issues:
            st.success("✅ No consistency issues found!")
            return

        # Severity breakdown
        import json as _json
        severity_counts = {}
        for issue in issues:
            sev = issue["severity"]
            severity_counts[sev] = severity_counts.get(sev, 0) + 1

        cols = st.columns(4)
        severity_colors = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}
        for i, (sev, count) in enumerate(sorted(severity_counts.items())):
            with cols[i % 4]:
                st.metric(f"{severity_colors.get(sev, '⚪')} {sev.upper()}", count)

        for issue in issues:
            sev_icon = severity_colors.get(issue["severity"], "⚪")
            with st.expander(f"{sev_icon} [{issue['rule_id']}] {issue['description'][:80]}..."):
                st.markdown(f"**Severity:** {issue['severity']}")
                st.markdown(f"**Status:** {issue['status']}")
                st.markdown(f"**Rule:** `{issue['rule_id']}`")
                st.markdown(f"**Details:** {issue['description']}")
                try:
                    evidence = _json.loads(issue["evidence_json"])
                    st.json(evidence)
                except Exception:
                    st.code(issue["evidence_json"])


# ── Admin page ────────────────────────────────────────────────────────────────

def admin_page():
    st.markdown('<div class="section-header">⚙️ Administration</div>', unsafe_allow_html=True)

    if st.session_state.role != "admin":
        st.error("🚫 Admin access required.")
        return

    tab1, tab2, tab3 = st.tabs(["👥 Users", "📝 Audit Log", "➕ Create Project"])

    with tab1:
        resp = api_get("/api/auth/users")
        if resp and resp.status_code == 200:
            users = resp.json()
            import pandas as pd
            df = pd.DataFrame(users)
            st.dataframe(df, use_container_width=True, hide_index=True)

            with st.expander("Register New User"):
                with st.form("register_form"):
                    new_username = st.text_input("Username")
                    new_email = st.text_input("Email")
                    new_password = st.text_input("Password", type="password")
                    new_role = st.selectbox("Role", [
                        "viewer", "tester", "developer", "architect", "manager", "admin"
                    ])
                    if st.form_submit_button("Create User"):
                        resp = api_post("/api/auth/register", json_data={
                            "username": new_username,
                            "email": new_email,
                            "password": new_password,
                            "role": new_role,
                        })
                        if resp and resp.status_code == 201:
                            st.success(f"User '{new_username}' created!")
                            st.rerun()
                        else:
                            st.error(f"Failed: {resp.text if resp else 'Error'}")

    with tab2:
        resp = api_get("/api/admin/audit-log", params={"limit": 50})
        if resp and resp.status_code == 200:
            entries = resp.json()
            if entries:
                import pandas as pd
                df = pd.DataFrame(entries)
                st.dataframe(df, use_container_width=True, hide_index=True)
            else:
                st.info("No audit log entries yet.")

    with tab3:
        with st.form("create_project_form"):
            project_name = st.text_input("Project Name")
            project_desc = st.text_area("Description")
            if st.form_submit_button("Create Project"):
                resp = api_post("/api/projects/", json_data={
                    "name": project_name,
                    "description": project_desc,
                })
                if resp and resp.status_code == 201:
                    st.success(f"Project '{project_name}' created!")
                    st.rerun()
                else:
                    st.error(f"Failed: {resp.text if resp else 'Error'}")


# ── Comparison page ───────────────────────────────────────────────────────────

def comparison_page():
    st.markdown('<div class="section-header">🔄 Revision Comparison</div>', unsafe_allow_html=True)

    project = st.session_state.current_project
    if not project:
        st.warning("Please select a project from the Dashboard first.")
        return

    resp = api_get(f"/api/documents/{project['id']}")
    if not resp or resp.status_code != 200:
        st.info("No documents in this project.")
        return

    docs = resp.json()
    if len(docs) < 2:
        st.info("Need at least 2 documents for comparison.")
        return

    doc_names = {d["id"]: f"{d['filename']} (v{d['version_label']})" for d in docs}

    col1, col2 = st.columns(2)
    with col1:
        doc_a = st.selectbox("Document A (older)", list(doc_names.keys()),
                             format_func=lambda x: doc_names[x], key="comp_a")
    with col2:
        doc_b = st.selectbox("Document B (newer)", list(doc_names.keys()),
                             format_func=lambda x: doc_names[x], key="comp_b")

    if st.button("Compare", disabled=doc_a == doc_b):
        with st.spinner("Comparing..."):
            resp = api_post("/api/comparison/compare", json_data={
                "doc_id_a": doc_a,
                "doc_id_b": doc_b,
            })
            if resp and resp.status_code == 201:
                result = resp.json()
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Added Chunks", result["added"])
                with col2:
                    st.metric("Removed Chunks", result["removed"])
                with col3:
                    st.metric("Modified Chunks", result["modified"])

                for diff in result.get("diffs", []):
                    icon = {"added": "🟢", "removed": "🔴", "modified": "🟡"}.get(diff["type"], "⚪")
                    with st.expander(f"{icon} Chunk {diff['chunk_index']} — {diff['type']}"):
                        if diff["text_a"]:
                            st.markdown("**Document A:**")
                            st.text(diff["text_a"][:500])
                        if diff["text_b"]:
                            st.markdown("**Document B:**")
                            st.text(diff["text_b"][:500])
            else:
                st.error(f"Failed: {resp.text if resp else 'Error'}")


# ── Navigation ────────────────────────────────────────────────────────────────

def main():
    if not st.session_state.token:
        login_page()
        return

    # Sidebar
    with st.sidebar:
        st.markdown("# 🏗️ AUTOSAR HLD")
        st.markdown(f"**{st.session_state.username}** ({st.session_state.role})")

        if st.session_state.current_project:
            st.caption(f"📁 {st.session_state.current_project['name']}")

        st.markdown("---")

        page = st.radio(
            "Navigation",
            ["📊 Dashboard", "📄 Documents", "💬 Query", "🧩 Entities",
             "🔍 Consistency", "🔄 Compare", "⚙️ Admin"],
            label_visibility="collapsed",
        )

        st.markdown("---")

        if st.button("🚪 Sign Out", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

    # Router
    pages = {
        "📊 Dashboard": dashboard_page,
        "📄 Documents": documents_page,
        "💬 Query": query_page,
        "🧩 Entities": entities_page,
        "🔍 Consistency": consistency_page,
        "🔄 Compare": comparison_page,
        "⚙️ Admin": admin_page,
    }
    pages[page]()


if __name__ == "__main__":
    main()
else:
    main()
