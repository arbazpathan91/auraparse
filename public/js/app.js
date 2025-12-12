// ==========================================
// 1. Configuration & Init
// ==========================================

const firebaseConfig = {
  apiKey: "[REDACTED]",
  authDomain: "promptmail.firebaseapp.com",
  projectId: "promptmail",
  storageBucket: "promptmail.firebasestorage.app",
  messagingSenderId: "1063448783198",
  appId: "1:1063448783198:web:f658150f106b55ee0d87cf"
};

firebase.initializeApp(firebaseConfig);
const auth = firebase.auth();
// Use the main domain to leverage Firebase Rewrites (No CORS issues)
const API_URL = 'https://auraparse.web.app';

// ==========================================
// 2. Theme Logic (Dark Mode)
// ==========================================

const SUN_ICON = `<svg class="w-5 h-5 text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z"/></svg>`;
const MOON_ICON = `<svg class="w-5 h-5 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z"/></svg>`;

function initTheme() {
    if (localStorage.theme === 'dark' || (!('theme' in localStorage) && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
        document.documentElement.classList.add('dark');
        document.getElementById('themeIcon').innerHTML = SUN_ICON;
    } else {
        document.documentElement.classList.remove('dark');
        document.getElementById('themeIcon').innerHTML = MOON_ICON;
    }
}

function toggleTheme() {
    if (document.documentElement.classList.contains('dark')) {
        document.documentElement.classList.remove('dark');
        localStorage.theme = 'light';
        document.getElementById('themeIcon').innerHTML = MOON_ICON;
    } else {
        document.documentElement.classList.add('dark');
        localStorage.theme = 'dark';
        document.getElementById('themeIcon').innerHTML = SUN_ICON;
    }
}

// ==========================================
// 3. Auth Flow
// ==========================================

auth.onAuthStateChanged(async (user) => {
  if (user) {
    document.getElementById('userEmail').textContent = user.email;
    document.getElementById('signInSection').classList.add('hidden');
    document.getElementById('navLoggedOut').classList.add('hidden');
    document.getElementById('navLoggedIn').classList.remove('hidden');
    document.getElementById('authenticatedSection').classList.remove('hidden');
    await getOrCreateAPIKey(user);
  } else {
    document.getElementById('signInSection').classList.remove('hidden');
    document.getElementById('navLoggedOut').classList.remove('hidden');
    document.getElementById('navLoggedIn').classList.add('hidden');
    document.getElementById('authenticatedSection').classList.add('hidden');
  }
});

async function signInWithGoogle() { try { await auth.signInWithPopup(new firebase.auth.GoogleAuthProvider()); } catch(e){ showToast(e.message, "error"); } }

async function signInWithEmail() {
    const email = document.getElementById('emailInput').value;
    if(!email) return showToast("Please enter email", "error");
    try {
        await auth.sendSignInLinkToEmail(email, { url: window.location.href, handleCodeInApp: true });
        document.getElementById('emailSentMsg').classList.remove('hidden');
        showToast("Magic Link Sent!", "success");
    } catch(e) { showToast(e.message, "error"); }
}

function signOut() { auth.signOut(); localStorage.removeItem('receiptApiKey'); location.reload(); }

// Handle Magic Link Return
if (auth.isSignInWithEmailLink(window.location.href)) {
    let email = localStorage.getItem('emailForSignIn') || prompt('Please confirm your email for login:');
    auth.signInWithEmailLink(email, window.location.href).then(() => {
      localStorage.removeItem('emailForSignIn');
      window.history.replaceState({}, document.title, "/");
    }).catch(e => showToast(e.message, "error"));
}

// ==========================================
// 4. API Key & Dashboard Logic
// ==========================================

async function getOrCreateAPIKey(user) {
  try {
    const idToken = await user.getIdToken();
    const response = await fetch(`${API_URL}/api/v1/key`, { headers: { 'Authorization': `Bearer ${idToken}` } });
    const data = await response.json();
    
    if (response.ok && data.masked_key) {
        updateDashboardUI(data);
    } else if (response.status === 404) {
        await createNewKey(idToken, user.email);
    }
  } catch (e) { console.error(e); }
}

async function createNewKey(idToken, email) {
  const response = await fetch(`${API_URL}/api/v1/signup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${idToken}` },
    body: JSON.stringify({ email: email, plan: 'free' })
  });
  const data = await response.json();
  if (data.key) revealNewKey(data);
}

function updateDashboardUI(data) {
  const input = document.getElementById('apiKeyDisplay');
  input.value = data.masked_key;
  
  // Reset style to "masked" state
  input.classList.remove('text-green-600', 'font-bold');
  input.classList.add('text-slate-600', 'dark:text-slate-300');
  
  document.getElementById('copyApiKeyBtn').classList.add('hidden');
  document.getElementById('keyWarningMsg').classList.add('hidden');
  
  const plan = data.plan || 'free';
  const used = data.requests_this_month || 0;
  
  // Prioritize backend limit, fallback to defaults
  const limit = data.limit || { free: 50, pro: 5000, enterprise: 100000 }[plan] || 50;
  
  document.getElementById('requestCount').textContent = used.toLocaleString();
  document.getElementById('requestsLimit').textContent = limit.toLocaleString();
  
  const percentage = Math.min((used / limit) * 100, 100);
  const bar = document.getElementById('usageBar');
  bar.style.width = `${percentage}%`;
  
  if (percentage > 90) { bar.classList.remove('bg-indigo-600'); bar.classList.add('bg-red-500'); }
  else { bar.classList.add('bg-indigo-600'); bar.classList.remove('bg-red-500'); }

  updatePlanCards(plan);
}

function revealNewKey(data) {
    const input = document.getElementById('apiKeyDisplay');
    input.value = data.key;
    input.classList.remove('text-slate-600', 'dark:text-slate-300');
    input.classList.add('text-green-600', 'font-bold');
    document.getElementById('copyApiKeyBtn').classList.remove('hidden');
    document.getElementById('keyWarningMsg').classList.remove('hidden');
    
    // Reset Stats locally
    document.getElementById('requestCount').textContent = '0';
    document.getElementById('usageBar').style.width = '0%';
    
    localStorage.setItem('receiptApiKey', data.key);
}

// ==========================================
// 5. Plans & Billing UI
// ==========================================

const PLAN_LEVELS = { 'free': 0, 'pro': 1, 'enterprise': 2 };
const PLAN_DETAILS = {
    'free': { label: 'Free', price: '$0', limit: '50 reqs/mo' },
    'pro': { label: 'Pro', price: '$29', limit: '5,000 reqs/mo' },
    'enterprise': { label: 'Enterprise', price: '$299', limit: '100k reqs/mo' }
};

function updatePlanCards(currentPlan) {
  currentPlan = currentPlan || 'free';
  const currentLevel = PLAN_LEVELS[currentPlan];

  const manageBtn = document.getElementById('manageSubBtn');
  if (currentLevel > 0) manageBtn.classList.remove('hidden');
  else manageBtn.classList.add('hidden');

  ['free', 'pro', 'enterprise'].forEach(planName => {
    const card = document.getElementById(`planCard-${planName}`);
    if (!card) return;

    const details = PLAN_DETAILS[planName];
    const cardLevel = PLAN_LEVELS[planName];
    
    // Base Card Style
    card.className = `relative flex items-center justify-between p-5 rounded-2xl border transition-all duration-200 
        bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700 hover:border-indigo-300 dark:hover:border-indigo-700`;

    let actionHtml = '';
    
    if (planName === currentPlan) {
        // Active
        card.classList.remove('border-slate-200', 'dark:border-slate-700');
        card.classList.add('ring-2', 'ring-indigo-500', 'dark:ring-indigo-400', 'bg-indigo-50/50', 'dark:bg-indigo-900/20', 'border-transparent');
        actionHtml = `
            <div class="flex flex-col items-end">
                <span class="text-xl font-extrabold text-slate-900 dark:text-white">${details.price}</span>
                <span class="mt-1 inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400">Current</span>
            </div>`;
    } 
    else if (cardLevel < currentLevel) {
        // Downgrade
        actionHtml = `
            <div class="flex flex-col items-end gap-2">
                <span class="text-xl font-extrabold text-slate-900 dark:text-white">${details.price}</span>
                <button onclick="openPortal()" class="text-xs font-semibold py-1.5 px-3 rounded-lg border border-slate-300 dark:border-slate-600 text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors">Downgrade</button>
            </div>`;
    } 
    else {
        // Upgrade
        const btnClass = planName === 'enterprise' 
            ? 'bg-slate-900 hover:bg-black dark:bg-white dark:text-slate-900 dark:hover:bg-slate-200 text-white' 
            : 'bg-indigo-600 hover:bg-indigo-700 text-white';
        actionHtml = `
            <div class="flex flex-col items-end gap-2">
                <span class="text-xl font-extrabold text-slate-900 dark:text-white">${details.price}</span>
                <button onclick="upgradePlan('${planName}')" class="text-xs font-bold py-1.5 px-4 rounded-lg shadow-sm transition-transform active:scale-95 ${btnClass}">Upgrade</button>
            </div>`;
    }

    card.innerHTML = `
        <div class="flex flex-col justify-center">
            <h3 class="text-lg font-bold text-slate-900 dark:text-white">${details.label}</h3>
            <p class="text-xs font-medium text-slate-500 dark:text-slate-400 mt-0.5">${details.limit}</p>
        </div>
        ${actionHtml}
    `;
  });
}

async function upgradePlan(plan) {
    const user = firebase.auth().currentUser;
    if (!user) return showToast("Please sign in first", "error");
    
    try {
        const idToken = await user.getIdToken();
        const res = await fetch(`${API_URL}/api/v1/create-checkout?plan=${plan}`, {
            method: 'POST', headers: { 'Authorization': `Bearer ${idToken}` }
        });
        const data = await res.json();
        if(res.ok && data.checkout_url) window.location.href = data.checkout_url;
        else showToast(data.detail || "Checkout failed", "error");
    } catch(e) { showToast(e.message, "error"); }
}

async function openPortal() {
    const user = firebase.auth().currentUser;
    try {
        const idToken = await user.getIdToken();
        const res = await fetch(`${API_URL}/api/v1/create-portal`, {
            method: 'POST', headers: { 'Authorization': `Bearer ${idToken}` }
        });
        const data = await res.json();
        if(data.url) window.location.href = data.url;
        else showToast(data.detail || "Error opening portal", "error");
    } catch (e) { showToast(e.message, "error"); }
}

// ==========================================
// 6. Sandbox Workflow (Select -> Extract)
// ==========================================

let currentSelectedFile = null;

function handleFileSelection(e) {
  const file = e.target.files[0];
  if (!file) return;
  if (file.size > 10 * 1024 * 1024) { showToast("File too large. Max 10MB.", "error"); return; }
  currentSelectedFile = file;
  
  const btn = document.getElementById('extractBtn');
  btn.disabled = false;
  btn.innerHTML = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg> Extract Data`;
  btn.classList.remove('opacity-50', 'cursor-not-allowed');

  const reader = new FileReader();
  reader.onload = (e) => {
    document.getElementById('dropContent').classList.add('hidden');
    const preview = document.getElementById('previewImage');
    preview.className = "absolute inset-0 w-full h-full object-contain p-4 z-10";
    
    if (file.type === 'application/pdf') {
      preview.src = "https://cdn-icons-png.flaticon.com/512/4726/4726010.png";
      preview.style.padding = "40px";
    } else {
      preview.src = e.target.result;
      preview.style.padding = "10px";
    }
    preview.classList.remove('hidden');
  };
  reader.readAsDataURL(file);
}

async function triggerExtraction() {
  if (!currentSelectedFile) { showToast("Select a file first.", "error"); return; }
  
  const key = document.getElementById('testApiKeyInput').value.trim();
  const docType = document.getElementById('docTypeInput').value;
  
  if (!key || key.includes('••••')) { 
    showToast("Please paste your REAL API Key.", "error"); 
    document.getElementById('testApiKeyInput').focus(); 
    return; 
  }

  // Convert file to Base64
  const reader = new FileReader();
  reader.onload = (e) => {
     performApiCall(e.target.result.split(',')[1], currentSelectedFile.type, docType, key);
  };
  reader.readAsDataURL(currentSelectedFile);
}

async function performApiCall(base64, mime, docType, key) {
  const loadingDiv = document.getElementById('processingIndicator');
  const resultsArea = document.getElementById('resultsArea');
  const btn = document.getElementById('extractBtn');
  
  loadingDiv.classList.remove('hidden');
  resultsArea.classList.add('opacity-30');
  btn.disabled = true;
  btn.innerHTML = "Processing...";

  try {
    const res = await fetch(`${API_URL}/api/v1/extract`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-API-Key': key },
      body: JSON.stringify({ file_data: base64, mime_type: mime, doc_type: docType })
    });
    
    const data = await res.json();
    
    if(res.ok) {
       showToast("Extraction Successful!", "success");
       // Optimistic counter update
       const countEl = document.getElementById('requestCount');
       if(countEl) {
           const curr = parseInt(countEl.textContent.replace(/,/g,'')) || 0;
           countEl.textContent = (curr+1).toLocaleString();
       }
    } else {
       showToast(data.detail || "Extraction Failed", "error");
    }
    resultsArea.textContent = JSON.stringify(data, null, 2);

  } catch (e) {
    showToast("Network Error", "error");
    resultsArea.textContent = "Error: " + e.message;
  } finally {
    loadingDiv.classList.add('hidden');
    resultsArea.classList.remove('opacity-30');
    btn.disabled = false;
    btn.innerHTML = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg> Extract Data`;
  }
}

// ==========================================
// 7. UI Utils (Toast, Modal, Tabs)
// ==========================================

// Toasts
function showToast(message, type = 'success') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    let border = type === 'success' ? 'border-green-500' : 'border-red-500';
    let text = type === 'success' ? 'text-green-800' : 'text-red-800';
    
    toast.className = `toast-item flex items-center gap-3 px-4 py-3 rounded-lg min-w-[300px] ${border} bg-white dark:bg-slate-800 dark:text-white ${text}`;
    toast.innerHTML = `<span class="font-medium text-sm">${message}</span>`;
    container.appendChild(toast);
    
    setTimeout(() => { toast.style.opacity = '0'; toast.style.transform = 'translateX(100%)'; setTimeout(() => toast.remove(), 300); }, 3500);
}

// Modals
function rotateKey() { document.getElementById('rotateModal').classList.remove('hidden'); }
function closeRotateModal() { document.getElementById('rotateModal').classList.add('hidden'); }

async function confirmRotate() {
    closeRotateModal();
    const user = firebase.auth().currentUser;
    try {
        const res = await fetch(`${API_URL}/api/v1/regenerate-key`, {
          method: 'POST', headers: { 'Authorization': `Bearer ${await user.getIdToken()}` }
        });
        const data = await res.json();
        if (data.key) {
            revealNewKey(data);
            showToast("Key Rotated Successfully", "success");
        }
    } catch(e) { showToast(e.message, "error"); }
}

// Key Visibility
function toggleTestKeyVisibility() { const el = document.getElementById('testApiKeyInput'); el.type = el.type === 'password' ? 'text' : 'password'; }
function copyAPIKey() {
    const input = document.getElementById('apiKeyDisplay');
    input.select(); document.execCommand('copy');
    showToast("API Key Copied", "success");
}

// Code Tabs
function switchCodeTab(lang) {
    ['curl', 'python', 'node', 'mcp'].forEach(l => document.getElementById(`code-${l}`).classList.add('hidden'));
    document.getElementById(`code-${lang}`).classList.remove('hidden');
    
    ['curl', 'python', 'node', 'mcp'].forEach(l => {
        const btn = document.getElementById(`tab-${l}`);
        if(l === lang) {
             if (l === 'mcp') btn.className = "text-xs font-bold px-3 py-1 rounded-md bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300 flex items-center gap-1";
             else btn.className = "text-xs font-medium px-3 py-1 rounded-md bg-indigo-100 text-indigo-700 dark:bg-indigo-900 dark:text-indigo-300";
        } else {
             if (l === 'mcp') btn.className = "text-xs font-medium px-3 py-1 rounded-md text-purple-600 hover:bg-purple-50 dark:text-purple-400 dark:hover:bg-purple-900/30 flex items-center gap-1 transition-colors";
             else btn.className = "text-xs font-medium px-3 py-1 rounded-md text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white";
        }
    });
}

function copyCode() {
    const active = ['curl', 'python', 'node', 'mcp'].find(l => !document.getElementById(`code-${l}`).classList.contains('hidden'));
    const text = document.getElementById(`code-${active}`).innerText;
    navigator.clipboard.writeText(text);
    showToast("Snippet Copied", "success");
}

// Initialize
initTheme();