// Handles sign up / log in / sign out and toggling between the auth screen
// and the app screen. The rest of the app (app.js) reacts to auth state via
// window.onUserReady / window.onUserSignedOut.

const authScreen = document.getElementById("auth-screen");
const appScreen = document.getElementById("app-screen");
const authForm = document.getElementById("auth-form");
const authError = document.getElementById("auth-error");
const authSubmit = document.getElementById("auth-submit");
const tabs = document.querySelectorAll(".auth-tab");
const userEmailEl = document.getElementById("user-email");

let mode = "login"; // or "signup"

tabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    tabs.forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    mode = tab.dataset.mode;
    authSubmit.textContent = mode === "login" ? "Log in" : "Create account";
    authError.textContent = "";
  });
});

authForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  authError.textContent = "";
  const email = document.getElementById("auth-email").value.trim();
  const password = document.getElementById("auth-password").value;

  try {
    if (mode === "login") {
      await firebase.auth().signInWithEmailAndPassword(email, password);
    } else {
      await firebase.auth().createUserWithEmailAndPassword(email, password);
    }
  } catch (err) {
    authError.textContent = err.message;
  }
});

document.getElementById("google-signin").addEventListener("click", async () => {
  authError.textContent = "";
  const provider = new firebase.auth.GoogleAuthProvider();
  try {
    await firebase.auth().signInWithPopup(provider);
  } catch (err) {
    authError.textContent = err.message;
  }
});

document.getElementById("signout-btn").addEventListener("click", () => {
  firebase.auth().signOut();
});

// Central auth-state listener drives which screen is visible.
firebase.auth().onAuthStateChanged((user) => {
  if (user) {
    authScreen.classList.add("hidden");
    appScreen.classList.remove("hidden");
    userEmailEl.textContent = user.email || "signed in";
    if (window.onUserReady) window.onUserReady(user);
  } else {
    appScreen.classList.add("hidden");
    authScreen.classList.remove("hidden");
    if (window.onUserSignedOut) window.onUserSignedOut();
  }
});

// Helper used by app.js: always fetches a FRESH ID token, and always for
// the currently signed-in user - never cached across accounts.
async function getIdToken() {
  const user = firebase.auth().currentUser;
  if (!user) throw new Error("Not signed in");
  return user.getIdToken();
}
