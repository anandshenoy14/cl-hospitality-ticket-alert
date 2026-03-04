// ============================================================
//  NUFC vs FC Barcelona — Ticket Price Monitor
//  Paste this into your browser DevTools Console on the ticket page
//  Works entirely in-browser, no installs needed.
// ============================================================

const CONFIG = {
  maxPrice: 300,           // Alert if cheapest ticket is below this (£)
  intervalMinutes: 30,     // How often to refresh and check
  notifyAlways: true,      // true = notify every check; false = only on price drop
};

// ── Helpers ─────────────────────────────────────────────────

function log(msg) {
  console.log(`%c[NUFC Monitor] ${new Date().toLocaleTimeString()} — ${msg}`,
    'color: #241F5E; font-weight: bold; font-size: 13px;');
}

function extractPrices() {
  const parseGBP = el => {
    if (!el) return null;
    const match = el.textContent.trim().match(/£([\d,]+(?:\.\d{1,2})?)/);
    return match ? parseFloat(match[1].replace(',', '')) : null;
  };

  const ranges = [];

  // Collect EVERY .price-range block on the page (one per zone/stand)
  // There can be many — one per seating section/stand
  document.querySelectorAll('.price-range').forEach(block => {
    const min = parseGBP(block.querySelector('.min-price'));
    const max = parseGBP(block.querySelector('.max-price'));
    if (min !== null || max !== null) ranges.push({ min, max });
  });

  // Also catch any orphaned .min-price elements outside a .price-range wrapper
  const coveredMins = new Set(document.querySelectorAll('.price-range .min-price'));
  document.querySelectorAll('.min-price').forEach(el => {
    if (!coveredMins.has(el)) {
      const val = parseGBP(el);
      if (val !== null) ranges.push({ min: val, max: null });
    }
  });

  log(`Found ${ranges.length} price block(s): ${ranges.map(r => `£${r.min ?? '?'}–£${r.max ?? '?'}`).join(' | ')}`);

  // Sort ascending by min price — cheapest zone always first
  return ranges.sort((a, b) => (a.min ?? Infinity) - (b.min ?? Infinity));
}

async function requestNotificationPermission() {
  if (!('Notification' in window)) {
    log('❌ This browser does not support notifications.');
    return false;
  }
  if (Notification.permission === 'granted') return true;
  if (Notification.permission === 'denied') {
    log('❌ Notifications blocked. Go to Site Settings and allow notifications for this page.');
    return false;
  }
  const result = await Notification.requestPermission();
  return result === 'granted';
}

function sendBrowserNotification(title, body, urgent = false) {
  if (Notification.permission !== 'granted') return;
  const n = new Notification(title, {
    body,
    icon: 'https://book.newcastleunited.com/favicon.ico',
    tag: 'nufc-ticket-monitor',   // replaces previous notification instead of stacking
    requireInteraction: urgent,   // stays on screen until dismissed if urgent
  });
  n.onclick = () => { window.focus(); n.close(); };
}

function checkPrices() {
  log('Reloading page to get fresh prices...');
  location.reload();
}

function runCheck() {
  log('Scanning for ticket prices...');

  const ranges = extractPrices();

  if (ranges.length === 0) {
    log('⚠️ No prices detected. The page may still be loading — will retry next cycle.');
    sendBrowserNotification(
      '⚠️ NUFC Monitor — Parse Warning',
      'Could not detect prices on the page. Check the console.',
      false
    );
    return;
  }

  // Cheapest is first after sort
  const cheapest = ranges[0];
  const minPrice = cheapest.min;
  const maxPrice = cheapest.max;
  const rangeStr = (minPrice !== null && maxPrice !== null)
    ? `£${minPrice} – £${maxPrice}`
    : `£${minPrice ?? maxPrice}`;

  // All zones summary for the console
  const allZones = ranges.map(r => `£${r.min ?? '?'}–£${r.max ?? '?'}`).join(', ');
  log(`Cheapest zone: ${rangeStr} | All zones: ${allZones}`);

  if (minPrice !== null && minPrice < CONFIG.maxPrice) {
    log(`🚨 Min price £${minPrice} is UNDER £${CONFIG.maxPrice} threshold!`);
    sendBrowserNotification(
      `🎟️ NUFC Alert! Tickets from £${minPrice}`,
      `Cheapest zone: ${rangeStr}\nAll zones: ${allZones}\nClick to buy now.`,
      true  // stays on screen until dismissed
    );
  } else {
    log(`Cheapest is £${minPrice} — still above £${CONFIG.maxPrice} threshold.`);
    if (CONFIG.notifyAlways) {
      sendBrowserNotification(
        `NUFC Monitor — Cheapest from £${minPrice}`,
        `Cheapest zone: ${rangeStr}\nNo tickets under £${CONFIG.maxPrice} yet.`,
        false
      );
    }
  }
}

function scheduleNextCheck() {
  const ms = CONFIG.intervalMinutes * 60 * 1000;
  log(`✅ Next check in ${CONFIG.intervalMinutes} minutes.`);
  setTimeout(checkPrices, ms);
}

async function init() {
  const permitted = await requestNotificationPermission();
  if (!permitted) {
    log('Cannot run without notification permission. Please allow notifications and re-paste the script.');
    return;
  }

  if (sessionStorage.getItem('__nufcMonitorActive') === 'true') {
    log('🔄 Page reloaded as part of monitor cycle. Waiting for content to render...');
    setTimeout(() => {
      runCheck();
      scheduleNextCheck();
    }, 4000);
  } else {
    sessionStorage.setItem('__nufcMonitorActive', 'true');
    log(`🟢 Monitor started! Checking every ${CONFIG.intervalMinutes} min for tickets under £${CONFIG.maxPrice}.`);
    setTimeout(() => {
      runCheck();
      scheduleNextCheck();
    }, 2000);
  }
}

init();
