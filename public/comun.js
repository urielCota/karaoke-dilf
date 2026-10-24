// Utilidades compartidas por las tres páginas.
const K = (() => {
  let desfase = 0; // diferencia entre el reloj del servidor y el de este dispositivo (ms)

  async function sincronizar() {
    const muestras = [];
    for (let i = 0; i < 6; i++) {
      const t0 = Date.now();
      try {
        const r = await fetch('/api/tiempo', { cache: 'no-store' });
        const { ahora } = await r.json();
        const t1 = Date.now();
        muestras.push({ rtt: t1 - t0, off: ahora - (t0 + t1) / 2 });
      } catch { /* sin red: se reintenta en la siguiente sincronización */ }
    }
    if (muestras.length) {
      muestras.sort((a, b) => a.rtt - b.rtt);
      desfase = muestras[0].off;
    }
  }

  const ahora = () => Date.now() + desfase;

  // EventSource se reconecta solo si se cae la red.
  function escuchar(cb) {
    const es = new EventSource('/api/eventos');
    es.onmessage = (e) => {
      try { cb(JSON.parse(e.data)); } catch (err) { console.error(err); }
    };
    return es;
  }

  async function api(ruta, datos, pin) {
    const headers = { 'Content-Type': 'application/json' };
    if (pin) headers['X-Pin'] = pin;
    const r = await fetch(ruta, { method: 'POST', headers, body: JSON.stringify(datos || {}) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) {
      const err = new Error(j.error || 'Error ' + r.status);
      err.status = r.status;
      throw err;
    }
    return j;
  }

  // Crea elementos sin usar innerHTML (los nombres de los invitados nunca se interpretan como HTML).
  function h(tag, attrs, ...hijos) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === 'class') el.className = v;
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else if (v !== false && v != null) el.setAttribute(k, v === true ? '' : v);
    }
    for (const c of hijos.flat()) {
      if (c == null || c === false) continue;
      el.append(c.nodeType ? c : document.createTextNode(String(c)));
    }
    return el;
  }

  const leer = (k, def) => { try { const v = localStorage.getItem(k); return v == null ? def : JSON.parse(v); } catch { return def; } };
  const escribir = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* modo privado */ } };

  function qr(contenedor, texto, tam) {
    contenedor.replaceChildren();
    if (window.QRCode) {
      new QRCode(contenedor, { text: texto, width: tam, height: tam, colorDark: '#000000', colorLight: '#ffffff', correctLevel: QRCode.CorrectLevel.M });
    } else {
      contenedor.append(h('p', { class: 'sinqr' }, 'Sin internet para dibujar el QR. Escribe la dirección en el navegador.'));
    }
  }

  const fmt = (s) => {
    s = Math.max(0, Math.floor(s));
    return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
  };

  sincronizar();
  setInterval(sincronizar, 60000);

  return { sincronizar, ahora, escuchar, api, h, leer, escribir, qr, fmt };
})();
