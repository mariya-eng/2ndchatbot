"""
AI Agent - Phase 2
Flask backend: Firebase Auth verification, file upload + Pandas processing,
user-scoped Firestore storage, and Gemini-powered chat.

Flow:
  Browser -> Flask (verifies Firebase ID token) -> Pandas (parses file)
  -> Firestore (users/{uid}/documents/{doc_id}) -> Flask (builds context)
  -> Gemini API -> Flask -> Browser

The Gemini API never talks to Firestore directly. Flask is the only
component that reads/writes Firestore and it always scopes every query
to the authenticated user's uid pulled from the verified ID token -
never from a client-supplied field.
"""

import os
import json
import uuid
import datetime
import io

from flask import Flask, request, jsonify, g, send_from_directory
from functools import wraps

import pandas as pd

import firebase_admin
from firebase_admin import credentials, auth as fb_auth, firestore

import google.generativeai as genai

# --------------------------------------------------------------------------
# App / config
# --------------------------------------------------------------------------

app = Flask(__name__, static_folder="static", template_folder="templates")

MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "10"))
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

# Cap on how many rows of an uploaded file we embed directly into a
# Firestore document (Firestore has a 1MB per-document limit). Large
# files should additionally be pushed to Firebase Storage - see README.
MAX_ROWS_IN_FIRESTORE = int(os.environ.get("MAX_ROWS_IN_FIRESTORE", "500"))

# Rows actually sent to Gemini as context per question (keeps prompts small
# and avoids leaking the entire dataset into every single turn).
MAX_ROWS_IN_PROMPT = int(os.environ.get("MAX_ROWS_IN_PROMPT", "50"))

ALLOWED_EXTENSIONS = {"csv", "xls", "xlsx", "json"}


# --------------------------------------------------------------------------
# Firebase Admin init (Auth + Firestore)
# --------------------------------------------------------------------------
#
# Provide credentials via ONE of:
#   1. FIREBASE_SERVICE_ACCOUNT_JSON  - the full JSON key as a string (used on Render)
#   2. GOOGLE_APPLICATION_CREDENTIALS - path to a JSON key file (used locally)

def _init_firebase():
    if firebase_admin._apps:
        return
    sa_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
    if sa_json:
        cred = credentials.Certificate(json.loads(sa_json))
    else:
        cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "serviceAccountKey.json")
        cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred)


_init_firebase()
db = firestore.client()

# --------------------------------------------------------------------------
# Gemini init
# --------------------------------------------------------------------------

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY environment variable is not set")

genai.configure(api_key=GEMINI_API_KEY)
GEMINI_MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
gemini_model = genai.GenerativeModel(GEMINI_MODEL_NAME)


# --------------------------------------------------------------------------
# Auth decorator - every protected route uses this. It NEVER trusts a
# client-supplied user id; the uid always comes from the verified token.
# --------------------------------------------------------------------------

def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return jsonify({"error": "Missing or invalid Authorization header"}), 401
        id_token = header.split("Bearer ", 1)[1].strip()
        try:
            decoded = fb_auth.verify_id_token(id_token)
        except Exception as e:
            return jsonify({"error": f"Invalid or expired token: {e}"}), 401
        g.uid = decoded["uid"]
        g.user_email = decoded.get("email", "")
        return f(*args, **kwargs)
    return wrapper


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# --------------------------------------------------------------------------
# Pandas parsing helpers
# --------------------------------------------------------------------------

def parse_uploaded_file(file_storage, filename):
    ext = filename.rsplit(".", 1)[1].lower()
    raw = file_storage.read()

    if ext == "csv":
        df = pd.read_csv(io.BytesIO(raw))
    elif ext in ("xls", "xlsx"):
        df = pd.read_excel(io.BytesIO(raw))
    elif ext == "json":
        df = pd.read_json(io.BytesIO(raw))
    else:
        raise ValueError("Unsupported file type")

    # Basic cleaning/validation
    df = df.dropna(how="all")
    df.columns = [str(c).strip() for c in df.columns]

    return df


def df_to_firestore_payload(df, filename):
    total_rows = len(df)
    truncated = total_rows > MAX_ROWS_IN_FIRESTORE
    sample_df = df.head(MAX_ROWS_IN_FIRESTORE)

    # Firestore can't store NaN - convert to None, and make sure everything
    # is JSON-serializable (numpy types -> native python types).
    records = json.loads(sample_df.to_json(orient="records"))

    return {
        "filename": filename,
        "columns": list(df.columns),
        "row_count": total_rows,
        "truncated": truncated,
        "rows_stored": len(records),
        "data": records,
        "uploaded_at": firestore.SERVER_TIMESTAMP,
    }


# --------------------------------------------------------------------------
# Routes - static frontend
# --------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(app.template_folder, "index.html")


# --------------------------------------------------------------------------
# Routes - file upload
# --------------------------------------------------------------------------

@app.route("/api/upload", methods=["POST"])
@require_auth
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "No file part in request"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": "Only CSV, XLS, XLSX and JSON files are supported"}), 400

    try:
        df = parse_uploaded_file(file, file.filename)
    except Exception as e:
        return jsonify({"error": f"Could not parse file: {e}"}), 400

    if df.empty:
        return jsonify({"error": "File contains no usable data"}), 400

    payload = df_to_firestore_payload(df, file.filename)

    doc_id = str(uuid.uuid4())
    doc_ref = db.collection("users").document(g.uid).collection("documents").document(doc_id)
    doc_ref.set(payload)

    return jsonify({
        "doc_id": doc_id,
        "filename": payload["filename"],
        "columns": payload["columns"],
        "row_count": payload["row_count"],
        "truncated": payload["truncated"],
    }), 201


@app.route("/api/files", methods=["GET"])
@require_auth
def list_files():
    docs = (
        db.collection("users").document(g.uid).collection("documents")
        .order_by("uploaded_at", direction=firestore.Query.DESCENDING)
        .stream()
    )
    result = []
    for d in docs:
        data = d.to_dict()
        result.append({
            "doc_id": d.id,
            "filename": data.get("filename"),
            "columns": data.get("columns"),
            "row_count": data.get("row_count"),
            "truncated": data.get("truncated"),
        })
    return jsonify({"files": result})


@app.route("/api/files/<doc_id>", methods=["DELETE"])
@require_auth
def delete_file(doc_id):
    # Scoped to g.uid - a user can only ever reach their own subcollection,
    # regardless of what doc_id they pass in.
    ref = db.collection("users").document(g.uid).collection("documents").document(doc_id)
    if not ref.get().exists:
        return jsonify({"error": "File not found"}), 404
    ref.delete()
    return jsonify({"status": "deleted"})


# --------------------------------------------------------------------------
# Routes - chat
# --------------------------------------------------------------------------

def build_context_for_user(uid, doc_id=None):
    """Pull the authenticated user's Firestore data and shape it into a
    compact text context for Gemini. Flask controls this - Gemini never
    queries Firestore itself."""
    col = db.collection("users").document(uid).collection("documents")
    docs = [col.document(doc_id).get()] if doc_id else list(col.stream())

    context_parts = []
    for d in docs:
        if not d.exists:
            continue
        data = d.to_dict()
        rows = data.get("data", [])[:MAX_ROWS_IN_PROMPT]
        context_parts.append(
            f"File: {data.get('filename')}\n"
            f"Columns: {', '.join(data.get('columns', []))}\n"
            f"Total rows in file: {data.get('row_count')}\n"
            f"Sample rows (JSON, up to {MAX_ROWS_IN_PROMPT}):\n{json.dumps(rows)}"
        )
    return "\n\n---\n\n".join(context_parts) if context_parts else "(no uploaded data yet)"


@app.route("/api/chat", methods=["POST"])
@require_auth
def chat():
    body = request.get_json(silent=True) or {}
    message = (body.get("message") or "").strip()
    session_id = body.get("session_id") or str(uuid.uuid4())
    doc_id = body.get("doc_id")  # optional: scope question to one uploaded file

    if not message:
        return jsonify({"error": "message is required"}), 400

    chat_col = (
        db.collection("users").document(g.uid)
        .collection("chats").document(session_id)
        .collection("messages")
    )

    # Store the user's message
    chat_col.add({
        "role": "user",
        "content": message,
        "timestamp": firestore.SERVER_TIMESTAMP,
    })

    context_text = build_context_for_user(g.uid, doc_id)

    prompt = (
        "You are a data assistant. Answer the user's question using ONLY the "
        "data context below when it's relevant. If the question is unrelated "
        "to the data, answer normally. Be concise.\n\n"
        f"DATA CONTEXT:\n{context_text}\n\n"
        f"USER QUESTION:\n{message}"
    )

    try:
        response = gemini_model.generate_content(prompt)
        answer = response.text
    except Exception as e:
        answer = f"Sorry, I couldn't reach the AI service right now ({e})."

    chat_col.add({
        "role": "assistant",
        "content": answer,
        "timestamp": firestore.SERVER_TIMESTAMP,
    })

    return jsonify({"session_id": session_id, "answer": answer})


@app.route("/api/history", methods=["GET"])
@require_auth
def history():
    session_id = request.args.get("session_id")
    if not session_id:
        return jsonify({"error": "session_id is required"}), 400

    msgs = (
        db.collection("users").document(g.uid)
        .collection("chats").document(session_id)
        .collection("messages")
        .order_by("timestamp")
        .stream()
    )
    result = [{"role": m.to_dict().get("role"), "content": m.to_dict().get("content")} for m in msgs]
    return jsonify({"session_id": session_id, "messages": result})


@app.route("/api/sessions", methods=["GET"])
@require_auth
def sessions():
    sess = db.collection("users").document(g.uid).collection("chats").stream()
    return jsonify({"sessions": [s.id for s in sess]})


# --------------------------------------------------------------------------
# Health check (useful for Render)
# --------------------------------------------------------------------------

@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok", "time": datetime.datetime.utcnow().isoformat()})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG", "0") == "1")
