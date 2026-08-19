// Firebase Web SDK config for THIS project.
// These values identify your Firebase project and are safe to ship to the
// browser (this is normal for Firebase) - they are NOT secret credentials.
// Get them from: Firebase Console -> Project settings -> General -> Your apps -> Web app
//
// The actual secrets (Gemini API key, service account key) live only on the
// Flask server as environment variables - never here.

const firebaseConfig = {
  apiKey: "AIzaSyDFA8P8gv2TISJMc04b-XU-19HoqZLKNvs",
  authDomain: "ndchatbot-e93f4.firebaseapp.com",
  projectId: "ndchatbot-e93f4",
  storageBucket: "ndchatbot-e93f4.firebasestorage.app",
  messagingSenderId: "424383673834",
  appId: "1:424383673834:web:90d6ed6ac949d6d694ee93",
  measurementId: "G-MTVMBKNPK0"
};
firebase.initializeApp(firebaseConfig);
