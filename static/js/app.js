// Upload + chat logic. Every request attaches a fresh Firebase ID token;
// the server derives the user id from that token, so there is no client
// state here that could leak one user's data into another user's view.

const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("file-input");
const uploadStatus = document.getElementById("upload-status");
const fileListEl = document.getElementById("file-list");
const fileEmptyEl = document.getElementById("file-empty");
const schemaChips = document.getElementById("schema-chips");

const chatLog = document.getElementById("chat-log");
const chatEmpty = document.getElementById("chat-empty");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const chatSend = document.getElementById("chat-send");

let sessionId = null;       // reset per signed-in user, see resetAppState()
let selectedDocId = null;   // null = ask across all of the user's files

function resetAppState() {
  sessionId = null;
  selectedDocId = null;
  fileListEl.innerHTML = "";
  chatLog.innerHTML = "";
  chatLog.appendChild(chatEmpty);
  chatEmpty.classList.remove("hidden");
  schemaChips.textContent = "All uploaded files";
}

window.onUserSignedOut = resetAppState;
window.onUserReady = async () => {
  resetAppState();
  await loadFiles();
};

// ---------------- upload ----------------

dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.style.borderColor = "var(--accent)"; });
dropzone.addEventListener("dragleave", () => { dropzone.style.borderColor = ""; });
dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.style.borderColor = "";
  if (e.dataTransfer.files.length) {
    fileInput.files = e.dataTransfer.files;
    handleUpload();
  }
});
fileInput.addEventListener("change", handleUpload);

async function handleUpload() {
  const file = fileInput.files[0];
  if (!file) return;

  uploadStatus.textContent = `Uploading ${file.name}…`;
  uploadStatus.className = "upload-status";

  try {
    const token = await getIdToken();
    const formData = new FormData();
    formData.append("file", file);

    const res = await fetch("/api/upload", {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: formData,
    });
    const data = await res.json();

    if (!res.ok) throw new Error(data.error || "Upload failed");

    uploadStatus.textContent = `Loaded ${data.filename} (${data.row_count} rows)${data.truncated ? " — showing first " + data.row_count + " rows to the agent" : ""}`;
    uploadStatus.classList.add("ok");
    await loadFiles();
  } catch (err) {
    uploadStatus.textContent = err.message;
    uploadStatus.classList.add("err");
  } finally {
    fileInput.value = "";
  }
}

// ---------------- file list ----------------

async function loadFiles() {
  const token = await getIdToken();
  const res = await fetch("/api/files", { headers: { Authorization: `Bearer ${token}` } });
  const data = await res.json();
  renderFiles(data.files || []);
}

function renderFiles(files) {
  fileListEl.innerHTML = "";
  fileEmptyEl.classList.toggle("hidden", files.length > 0);

  const allItem = document.createElement("li");
  allItem.className = "file-item" + (selectedDocId === null ? " active" : "");
  allItem.innerHTML = `<span class="file-name">All files</span><span class="file-meta">Ask across everything you've uploaded</span>`;
  allItem.addEventListener("click", () => selectFile(null, files));
  fileListEl.appendChild(allItem);

  files.forEach((f) => {
    const li = document.createElement("li");
    li.className = "file-item" + (selectedDocId === f.doc_id ? " active" : "");
    li.innerHTML = `<span class="file-name">${escapeHtml(f.filename)}</span><span class="file-meta">${f.row_count} rows · ${f.columns.length} columns</span>`;
    li.addEventListener("click", () => selectFile(f.doc_id, files));
    fileListEl.appendChild(li);
  });
}

function selectFile(docId, files) {
  selectedDocId = docId;
  renderFiles(files);
  if (docId === null) {
    schemaChips.textContent = "All uploaded files";
  } else {
    const f = files.find((x) => x.doc_id === docId);
    schemaChips.innerHTML = f.columns.map((c) => `<span class="chip">${escapeHtml(c)}</span>`).join("");
  }
}

// ---------------- chat ----------------

chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const message = chatInput.value.trim();
  if (!message) return;

  chatEmpty.classList.add("hidden");
  appendMessage("user", message);
  chatInput.value = "";
  chatSend.disabled = true;

  const thinkingEl = appendMessage("assistant", "Thinking…", true);

  try {
    const token = await getIdToken();
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ message, session_id: sessionId, doc_id: selectedDocId }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Something went wrong");

    sessionId = data.session_id;
    thinkingEl.textContent = data.answer;
    thinkingEl.classList.remove("thinking");
  } catch (err) {
    thinkingEl.textContent = err.message;
    thinkingEl.classList.remove("thinking");
  } finally {
    chatSend.disabled = false;
    chatInput.focus();
  }
});

function appendMessage(role, text, thinking = false) {
  const el = document.createElement("div");
  el.className = `msg msg-${role}` + (thinking ? " thinking" : "");
  el.textContent = text;
  chatLog.appendChild(el);
  chatLog.scrollTop = chatLog.scrollHeight;
  return el;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}
