// GameBridge Ethiopia - Mobile App & PWA Scripts

let toastTimeoutId;

const navMenu = document.querySelector('.nav-menu');
if (navMenu) {
  const mobileNav = window.matchMedia('(max-width: 760px)');
  const syncNavMenu = () => {
    navMenu.open = !mobileNav.matches;
  };
  syncNavMenu();
  mobileNav.addEventListener('change', syncNavMenu);
}

function showToast(message, tone = 'success') {
  const toast = document.getElementById('gb-toast');
  if (!toast) return;
  window.clearTimeout(toastTimeoutId);
  toast.textContent = message;
  toast.dataset.tone = tone;
  toast.hidden = false;
  toastTimeoutId = window.setTimeout(() => { toast.hidden = true; }, 4200);
}

// 1. Service Worker Registration
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').then(
      (reg) => console.log('PWA ServiceWorker registered with scope:', reg.scope),
      (err) => console.warn('PWA ServiceWorker registration failed:', err)
    );
  });
}

// 2. Telegram Mini App Auto-Authentication
document.addEventListener('DOMContentLoaded', () => {
  if (window.Telegram && window.Telegram.WebApp) {
    const tg = window.Telegram.WebApp;
    tg.ready();
    tg.expand();
    const initData = tg.initData;
    if (initData && !document.cookie.includes('gb_session=')) {
      fetch('/api/auth/telegram-webapp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ init_data: initData })
      })
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          window.location.reload();
        }
      })
      .catch(err => console.error('Telegram auto-login failed:', err));
    }
  }
});

// 3. Client-Side Image Compression for Evidence Upload (Section 13)
async function compressImageBeforeUpload(file, maxDimension = 1280, quality = 0.85) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.readAsDataURL(file);
    reader.onload = (event) => {
      const img = new Image();
      img.src = event.target.result;
      img.onload = () => {
        let width = img.width;
        let height = img.height;

        if (width > maxDimension || height > maxDimension) {
          if (width > height) {
            height = Math.round((height * maxDimension) / width);
            width = maxDimension;
          } else {
            width = Math.round((width * maxDimension) / height);
            height = maxDimension;
          }
        }

        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(img, 0, 0, width, height);

        canvas.toBlob((blob) => {
          resolve(new File([blob], file.name.replace(/\.[^/.]+$/, ".jpg"), { type: 'image/jpeg' }));
        }, 'image/jpeg', quality);
      };
      img.onerror = reject;
    };
    reader.onerror = reject;
  });
}

// 4. Language Switcher helper
function setLanguage(lang) {
  fetch('/api/auth/set-language', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ language: lang })
  })
  .then((response) => {
    if (!response.ok) throw new Error('Could not change language.');
    window.location.reload();
  })
  .catch(() => showToast('Could not change language. Please try again.', 'error'));
}
