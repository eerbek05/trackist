// ---- Chat init ----
const chat = document.querySelector('.chat-area');
chat.scrollTop = chat.scrollHeight;

document.getElementById('clearChatBtn').addEventListener('click', async function() {
  await fetch('/clear');
  chat.innerHTML = '';
});

// ---- Chat toggle ----
const chatToggleBtn = document.getElementById('chatToggleBtn');
let chatHidden = false;

chatToggleBtn.addEventListener('click', function() {
  chatHidden = !chatHidden;
  document.body.classList.toggle('chat-hidden', chatHidden);
  chatToggleBtn.textContent = 'Toggle Chat';
});

// ---- Countdown (synced to OpenSky 60s interval) ----
(function() {
  const el = document.getElementById('liveCountdown');
  if (!el) return;
  let secs = 60;
  setInterval(() => { secs = secs <= 1 ? 60 : secs - 1; el.textContent = secs; }, 1000);
})();

// ---- Toast ----
let toastTimeout = null;
function showMapToast(message) {
  const toast = document.getElementById('mapToast');
  toast.textContent = message;
  toast.classList.add('visible');
  clearTimeout(toastTimeout);
  toastTimeout = setTimeout(() => toast.classList.remove('visible'), 3000);
}

// ---- Flight focus ----
function extractFlightCode(text) {
  const match = text.match(/\b([A-Z]{2,3}\s?\d{1,4})\b/);
  return match ? match[1].replace(/\s+/g, '') : null;
}

async function focusOnFlight(flightId) {
  if (!flightId) return;
  await openMap();
  let marker = flightMarkers[flightId];

  if (!marker) {
    try {
      const res = await fetch(`/api/flights/${encodeURIComponent(flightId)}`);
      if (res.ok) {
        const f = await res.json();
        if (f && f.lat != null && f.lng != null) marker = addOrUpdateFlightMarker(f);
      }
    } catch (e) {
      console.error('Flight lookup failed', e);
    }
  }

  if (marker) {
    flightMap.flyTo(marker.getLatLng(), 7, { duration: 1.2 });
    openDashboard(marker._flightData, { pin: true });
    setTimeout(() => setActiveMarker(marker), 50);
  } else {
    showMapToast(`No position data available for ${flightId} right now.`);
  }
}

// ---- Image upload / preview ----
const imagePreviewWrap = document.getElementById('imagePreviewWrap');
const imagePreview     = document.getElementById('imagePreview');
const removeImageBtn   = document.getElementById('removeImage');
const soruInput        = document.getElementById('soruInput');

function showPreview(file) {
  const reader = new FileReader();
  reader.onload = function(e) {
    imagePreview.src = e.target.result;
    imagePreviewWrap.style.display = 'block';
  };
  reader.readAsDataURL(file);
}

function clearPreview() {
  imagePreviewWrap.style.display = 'none';
  imagePreview.src = '';
  window.pendingImage = null;
  document.getElementById('imageInput').value = '';
}

removeImageBtn.addEventListener('click', clearPreview);

soruInput.addEventListener('paste', function(e) {
  const items = e.clipboardData.items;
  for (let item of items) {
    if (item.type.startsWith('image/')) {
      e.preventDefault();
      const file = item.getAsFile();
      window.pendingImage = file;
      showPreview(file);
      break;
    }
  }
});

document.getElementById('imageInput').addEventListener('change', function() {
  const file = this.files[0];
  if (!file) return;
  window.pendingImage = file;
  showPreview(file);
});

// ---- Boarding pass analysis ----
async function sendImage(file) {
  const btn = document.querySelector('button[type="submit"]');
  btn.textContent = 'Analyzing...';
  btn.disabled = true;

  const userDiv = document.createElement('div');
  userDiv.className = 'msg user';
  const imgEl = document.createElement('img');
  imgEl.src = imagePreview.src;
  userDiv.appendChild(imgEl);
  chat.appendChild(userDiv);

  const thinkingDiv = document.createElement('div');
  thinkingDiv.className = 'msg assistant';
  thinkingDiv.id = 'thinking';
  thinkingDiv.textContent = 'Reading flight code...';
  chat.appendChild(thinkingDiv);
  chat.scrollTop = chat.scrollHeight;

  clearPreview();

  const formData = new FormData();
  formData.append('image', file);

  const response = await fetch('/analyze', { method: 'POST', body: formData });
  const data     = await response.json();

  document.getElementById('thinking').textContent = data.cevap;
  document.getElementById('thinking').removeAttribute('id');
  chat.scrollTop = chat.scrollHeight;

  btn.textContent = 'Send';
  btn.disabled = false;
  soruInput.focus();

  if (data.flight_code) focusOnFlight(data.flight_code);
}

// ---- Chat form submit ----
document.getElementById('chatForm').addEventListener('submit', async function(e) {
  e.preventDefault();
  const btn = document.querySelector('button[type="submit"]');

  if (window.pendingImage) {
    await sendImage(window.pendingImage);
    return;
  }

  const soru = soruInput.value.trim();
  if (!soru) return;

  soruInput.value = '';
  btn.disabled = true;

  const userDiv = document.createElement('div');
  userDiv.className = 'msg user';
  userDiv.textContent = soru;
  chat.appendChild(userDiv);

  const responseDiv = document.createElement('div');
  responseDiv.className = 'msg assistant streaming';
  responseDiv.textContent = '...';
  chat.appendChild(responseDiv);
  chat.scrollTop = chat.scrollHeight;

  const flightCode = extractFlightCode(soru.toUpperCase());
  if (flightCode) focusOnFlight(flightCode);

  let fullText = '';
  let hasText  = false;

  try {
    const res = await fetch('/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ soru })
    });

    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let   buffer  = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        let data;
        try { data = JSON.parse(line.slice(6)); } catch { continue; }

        if (data.type === 'token' && data.text) {
          if (!hasText) { responseDiv.textContent = ''; hasText = true; }
          fullText += data.text;
          responseDiv.textContent = fullText;
          chat.scrollTop = chat.scrollHeight;

        } else if (data.type === 'tool' && !hasText) {
          const label = data.name.replace(/^tool_/, '').replace(/_/g, ' ');
          responseDiv.textContent = `Looking up ${label}…`;

        } else if (data.type === 'done') {
          // Only auto-focus if the response is about a single flight (not a list)
          if (fullText.length < 400) {
            const answerCode = extractFlightCode(fullText);
            if (answerCode && answerCode !== flightCode) focusOnFlight(answerCode);
          }

        } else if (data.type === 'error') {
          responseDiv.textContent = data.text || 'An error occurred.';
        }
      }
    }
  } catch (err) {
    responseDiv.textContent = 'Connection error. Please try again.';
    console.error(err);
  } finally {
    responseDiv.classList.remove('streaming');
    btn.disabled = false;
    soruInput.focus();
  }
});
