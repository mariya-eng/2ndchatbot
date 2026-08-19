# Datum — AI Data Agent (Phase 2)

An AI chatbot that lets each authenticated user upload their own CSV / XLSX / JSON
files, stores the parsed data in per-user Firestore paths, and answers questions
about it using the Gemini API — with the Flask backend as the only thing that ever
talks to Firestore.

```
Browser (HTML/JS + Firebase Auth)
        │  Authorization: Bearer <Firebase ID token>
        ▼
Flask backend (Render)
        │  verifies token → uid
        ▼
Pandas  →  Cloud Firestore  (users/{uid}/documents/{doc_id})
        │
        ▼
Flask builds a context string scoped to that uid
        ▼
Gemini API  →  answer  →  Flask  →  Browser
```

Gemini never touches Firestore directly — Flask fetches the user's data,
builds the prompt, calls Gemini, and returns the answer.

---

## 1. Project layout

```
ai-agent-phase2/
├── app.py                     Flask backend (auth, upload, chat, isolation)
├── requirements.txt
├── Procfile                   Render start command
├── render.yaml                Render service definition (optional, "infra as code")
├── .env.example                Documents required environment variables
├── templates/index.html
└── static/
    ├── css/style.css
    └── js/
        ├── firebase-config.js  Public Firebase web config (fill in)
        ├── auth.js              Sign up / log in / sign out
        └── app.js                Upload, file list, chat
```

---

## 2. Firebase setup

1. Create a project at https://console.firebase.google.com
2. **Authentication** → Sign-in method → enable **Email/Password** (and **Google**
   if you want the "Continue with Google" button to work).
3. **Firestore Database** → Create database (production mode).
4. **Project settings → General → Your apps → Web app** → copy the config
   object into `static/js/firebase-config.js`. These values are *public* by
   design (they only identify the project), so it's fine that they ship to
   the browser.
5. **Project settings → Service accounts** → Generate new private key. This
   JSON file is a *secret* — it is what lets the Flask backend verify ID
   tokens and read/write Firestore as an admin. Do **not** commit it or put
   it in any frontend file.

### Firestore structure

```
users/{uid}/documents/{doc_id}   -> one uploaded file's parsed data + metadata
users/{uid}/chats/{session_id}/messages/{message_id} -> chat turns
```

### Firestore security rules (defense in depth)

The Flask backend already enforces isolation using the Admin SDK (which
bypasses rules), but if you also want the Firebase JS SDK to be safe to use
directly in the future, lock the database down with:

```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /users/{userId}/{document=**} {
      allow read, write: if request.auth != null && request.auth.uid == userId;
    }
  }
}
```

---

## 3. Gemini API key

Get a key at https://aistudio.google.com/apikey. This is used **only** on
the server (`GEMINI_API_KEY` env var) — never exposed to the browser.

---

## 4. Local development

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# edit .env: paste GEMINI_API_KEY, and either
#   - paste your service account JSON into FIREBASE_SERVICE_ACCOUNT_JSON, or
#   - save the key file as serviceAccountKey.json and leave
#     GOOGLE_APPLICATION_CREDENTIALS pointing at it

export $(cat .env | xargs)        # or use python-dotenv / your shell's method
python app.py
```

Visit http://localhost:5000, fill in `static/js/firebase-config.js` first.

---

## 5. Deploy to Render

1. Push this project to a **GitHub** repo.
2. In Render: **New → Web Service** → connect the repo.
3. Render will detect `Procfile` / `render.yaml` automatically. If not, set:
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn app:app --bind 0.0.0.0:$PORT`
4. Under **Environment**, add secrets (never in code):
   - `GEMINI_API_KEY`
   - `FIREBASE_SERVICE_ACCOUNT_JSON` (paste the entire service-account JSON as one value)
   - `GEMINI_MODEL` (optional, defaults to `gemini-2.5-flash`)
5. Deploy. You'll get a shared HTTPS URL (e.g. `https://ai-agent-phase2.onrender.com`)
   that any number of users can open from any device/browser at the same time.

---

## 6. How the requirements are met

| Requirement | Where |
|---|---|
| Upload CSV/XLS/XLSX/JSON | `static/js/app.js` (dropzone) → `POST /api/upload` |
| Flask + Pandas processing | `parse_uploaded_file()` in `app.py` |
| Store structured data in Firestore | `df_to_firestore_payload()` + `users/{uid}/documents/{doc_id}` |
| Agent answers from Firestore data, not directly from Gemini→Firestore | `build_context_for_user()` builds context in Flask; only Flask calls both Firestore and Gemini |
| Gemini key kept out of HTML/CSS/JS | Only read from `os.environ` inside `app.py`; frontend has no key |
| Multi-user cloud deployment | GitHub + Render + Firestore + Gemini, single HTTPS URL |
| Auth + per-user isolation | `require_auth` decorator derives `g.uid` **only** from the verified Firebase ID token; every Firestore query is scoped under `users/{g.uid}/...` — a client can never pass in someone else's id |
| Chat history isolated | `users/{uid}/chats/{session_id}/messages` |
| File list isolated | `GET /api/files` only ever reads `users/{g.uid}/documents` |

---

## 7. Demonstrating isolation (for submission)

1. Open the deployed URL in two different browsers (or one normal + one
   incognito window).
2. Sign up as **User A** in window 1, upload `students_A.xlsx`, ask a
   question about it.
3. Sign up as **User B** in window 2, upload `students_B.xlsx`, ask a
   question about it.
4. Show that:
   - User A's file list never shows `students_B.xlsx`, and vice versa.
   - Asking User A's agent about User B's data returns nothing (the context
     Flask builds only ever comes from `users/{A_uid}/...`).
   - Each user's chat log (visible in the chat panel, and readable via
     `GET /api/history?session_id=...`) only contains their own turns.
5. Optionally screenshot the Firestore console showing two separate
   `users/{uidA}` and `users/{uidB}` documents with their own subcollections.

---

## 8. Notes / limits

- Firestore documents cap at ~1MB, so very large files are truncated to
  `MAX_ROWS_IN_FIRESTORE` rows (default 500) before storage — the file's
  real row count is still recorded. For full-size originals, wire up
  Firebase Storage (`firebase_admin.storage`) in `upload_file()`; the
  requirements list this as optional.
- Gemini only ever sees `MAX_ROWS_IN_PROMPT` rows per turn to keep prompts
  small; increase if you need broader analysis on bigger files.
- `verify_id_token` calls Google's servers, so this deployment needs normal
  outbound internet access from Render (default).
