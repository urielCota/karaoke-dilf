#!/usr/bin/env python3
"""Karaoke QR - servidor sin dependencias (solo Python 3.8+).

Páginas:
  /          -> los invitados eligen canción y escriben su nombre (abre con el QR)
  /cola      -> control de turnos (acciones protegidas con PIN)
  /pantalla  -> pantalla de karaoke a pantalla completa (se puede abrir en varias pantallas)
"""
import hmac
import json
import os
import re
import socket
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlparse

BASE = os.path.dirname(os.path.abspath(__file__))
CANCIONES = os.path.join(BASE, "canciones")
PUBLIC = os.path.join(BASE, "public")
ARCHIVO_DATOS = os.path.join(BASE, "datos", "cola.json")

# PORT lo asigna el hosting (Render, Koyeb...); en la red local se usa KARAOKE_PUERTO.
PUERTO = int(os.environ.get("PORT") or os.environ.get("KARAOKE_PUERTO", "8000"))
PIN = os.environ.get("KARAOKE_PIN", "1234")
CUENTA_REGRESIVA = 10  # segundos antes de comenzar la canción
MAX_COLA = 500

EXT_AUDIO = (".mp3", ".m4a", ".ogg", ".wav", ".webm", ".aac", ".mp4")
TIPOS = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8", ".json": "application/json",
    ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".ico": "image/x-icon",
    ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".mp4": "video/mp4", ".ogg": "audio/ogg",
    ".wav": "audio/wav", ".webm": "audio/webm", ".aac": "audio/aac",
}

lock = threading.Condition()
estado = {"cola": [], "actual": None, "auto": False, "version": 0}


def ahora_ms():
    return int(time.time() * 1000)


# ---------------------------------------------------------------- canciones

RE_TIEMPO = re.compile(r"\[(\d+):(\d+(?:[.:]\d+)?)\]")
RE_META = re.compile(r"^\[([a-zA-Z]+):(.*)\]$")


def leer_lrc(ruta):
    meta, lineas = {}, []
    with open(ruta, encoding="utf-8-sig", errors="replace") as f:
        for crudo in f:
            crudo = crudo.strip()
            m = RE_META.match(crudo)
            if m:
                meta[m.group(1).lower()] = m.group(2).strip()
                continue
            tiempos = RE_TIEMPO.findall(crudo)
            if not tiempos:
                continue
            texto = RE_TIEMPO.sub("", crudo).strip()
            # Quita marcas de palabra del formato LRC extendido: <00:12.34>
            texto = re.sub(r"<\d+:\d+(?:\.\d+)?>", "", texto).strip()
            for mm, ss in tiempos:
                lineas.append({"t": round(int(mm) * 60 + float(ss.replace(":", ".")), 3), "texto": texto})
    try:
        desfase = float(meta.get("offset", 0)) / 1000  # ms; positivo = la letra aparece antes
    except ValueError:
        desfase = 0
    for l in lineas:
        l["t"] = max(0, round(l["t"] - desfase, 3))
    lineas.sort(key=lambda l: l["t"])
    return meta, lineas


def a_segundos(texto):
    try:
        partes = [float(p) for p in texto.split(":")]
    except ValueError:
        return None
    s = 0
    for p in partes:
        s = s * 60 + p
    return s


def _cargar_catalogo():
    canciones = {}
    archivos = sorted(os.listdir(CANCIONES))
    for nombre in archivos:
        base, ext = os.path.splitext(nombre)
        if ext.lower() != ".lrc":
            continue
        try:
            meta, lineas = leer_lrc(os.path.join(CANCIONES, nombre))
        except OSError as e:
            print(f"  ! No se pudo leer {nombre}: {e}")
            continue
        audio = next((a for a in archivos
                      if os.path.splitext(a)[0] == base and os.path.splitext(a)[1].lower() in EXT_AUDIO), None)
        ultima = lineas[-1]["t"] if lineas else 0
        largo = a_segundos(meta["length"]) if meta.get("length") else None
        if largo:
            duracion = largo + 3
        elif audio:
            duracion = ultima + 120  # se ajusta cuando la pantalla con audio reporta la duración real
        else:
            duracion = ultima + 6
        canciones[base] = {
            "id": base,
            "titulo": meta.get("ti") or base,
            "artista": meta.get("ar", ""),
            "audio": audio,
            "duracion": duracion,
            "lineas": lineas,
        }
    return canciones


_cache = {"firma": None, "datos": {}}


def catalogo():
    """Lee la carpeta canciones/ y solo la vuelve a procesar si algo cambió."""
    try:
        firma = tuple(sorted((f, os.path.getmtime(os.path.join(CANCIONES, f))) for f in os.listdir(CANCIONES)))
    except FileNotFoundError:
        return {}
    if firma != _cache["firma"]:
        _cache["datos"] = _cargar_catalogo()
        _cache["firma"] = firma
    return _cache["datos"]


# ---------------------------------------------------------------- estado (llamar con lock tomado)

def guardar():
    os.makedirs(os.path.dirname(ARCHIVO_DATOS), exist_ok=True)
    tmp = ARCHIVO_DATOS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"cola": estado["cola"], "auto": estado["auto"]}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ARCHIVO_DATOS)


def cargar():
    try:
        with open(ARCHIVO_DATOS, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return
    estado["cola"] = d.get("cola", [])
    estado["auto"] = bool(d.get("auto", False))
    # Si el servidor se reinició a media canción, ese turno regresa a la cola.
    for e in estado["cola"]:
        if e.get("estado") == "cantando":
            e["estado"] = "pendiente"


def cambio():
    estado["version"] += 1
    guardar()
    lock.notify_all()


def foto():
    return {"cola": estado["cola"], "actual": estado["actual"], "auto": estado["auto"],
            "url": URL_PUBLICA, "version": estado["version"]}


def buscar(entrada_id):
    return next((e for e in estado["cola"] if e["id"] == entrada_id), None)


def terminar_actual():
    a = estado["actual"]
    if a:
        e = buscar(a["entrada_id"])
        if e:
            e["estado"] = "terminado"
        estado["actual"] = None


def reproducir(e):
    c = catalogo().get(e["cancion_id"])
    if not c:
        raise LookupError("Esa canción ya no está en la carpeta de canciones")
    terminar_actual()
    inicio = ahora_ms() + CUENTA_REGRESIVA * 1000
    e["estado"] = "cantando"
    estado["actual"] = {
        "entrada_id": e["id"], "cancion_id": c["id"], "nombre": e["nombre"],
        "titulo": c["titulo"], "artista": c["artista"], "audio": bool(c["audio"]),
        "inicio": inicio, "fin": inicio + int(c["duracion"] * 1000),
    }


def siguiente_pendiente():
    return next((e for e in estado["cola"] if e["estado"] == "pendiente"), None)


def finalizar():
    terminar_actual()
    if estado["auto"]:
        sig = siguiente_pendiente()
        if sig:
            try:
                reproducir(sig)
            except LookupError:
                sig["estado"] = "terminado"
    cambio()


def vigilante():
    """Da por terminada la canción cuando llega su hora de fin."""
    while True:
        time.sleep(0.5)
        with lock:
            a = estado["actual"]
            if a and ahora_ms() > a["fin"]:
                finalizar()


def accion_admin(accion, d):
    cola = estado["cola"]
    if accion == "verificar":
        return
    if accion == "auto":
        estado["auto"] = bool(d.get("valor"))
    elif accion == "siguiente":
        terminar_actual()
        sig = siguiente_pendiente()
        if sig:
            reproducir(sig)
    elif accion == "detener":
        terminar_actual()
    elif accion == "limpiar":
        estado["cola"] = [e for e in cola if e["estado"] != "terminado"]
    else:
        e = buscar(d.get("id"))
        if not e:
            raise LookupError("Turno no encontrado")
        if accion == "reproducir":
            reproducir(e)
        elif accion == "eliminar":
            if estado["actual"] and estado["actual"]["entrada_id"] == e["id"]:
                estado["actual"] = None
            cola.remove(e)
        elif accion == "reencolar":
            e["estado"] = "pendiente"
            cola.remove(e)
            cola.append(e)
        elif accion == "mover":
            if e["estado"] != "pendiente":
                raise ValueError("Solo se pueden mover turnos pendientes")
            idx = [i for i, x in enumerate(cola) if x["estado"] == "pendiente"]
            pos = idx.index(cola.index(e))
            j = pos + (1 if d.get("dir", 1) > 0 else -1)
            if 0 <= j < len(idx):
                a, b = idx[pos], idx[j]
                cola[a], cola[b] = cola[b], cola[a]
        else:
            raise KeyError(accion)
    cambio()


# ---------------------------------------------------------------- HTTP

def ruta_segura(base, relativa):
    base = os.path.realpath(base)
    completa = os.path.realpath(os.path.join(base, relativa))
    if completa.startswith(base + os.sep) and os.path.isfile(completa):
        return completa
    return None


class Manejador(BaseHTTPRequestHandler):
    server_version = "KaraokeQR/1.0"

    def log_message(self, *args):
        pass

    def _json(self, datos, status=200):
        cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _error(self, mensaje, status=400):
        self._json({"error": mensaje}, status)

    def _archivo(self, ruta):
        if not ruta:
            return self._error("No encontrado", 404)
        tamano = os.path.getsize(ruta)
        inicio, fin, status = 0, tamano - 1, 200
        rango = self.headers.get("Range")
        if rango:
            m = re.match(r"bytes=(\d*)-(\d*)", rango)
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    inicio = int(m.group(1))
                    fin = int(m.group(2)) if m.group(2) else tamano - 1
                else:
                    inicio = max(0, tamano - int(m.group(2)))
                fin = min(fin, tamano - 1)
                if inicio > fin:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{tamano}")
                    self.end_headers()
                    return
                status = 206
        self.send_response(status)
        self.send_header("Content-Type", TIPOS.get(os.path.splitext(ruta)[1].lower(), "application/octet-stream"))
        self.send_header("Content-Length", str(fin - inicio + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache")
        if status == 206:
            self.send_header("Content-Range", f"bytes {inicio}-{fin}/{tamano}")
        self.end_headers()
        try:
            with open(ruta, "rb") as f:
                f.seek(inicio)
                restante = fin - inicio + 1
                while restante > 0:
                    bloque = f.read(min(65536, restante))
                    if not bloque:
                        break
                    self.wfile.write(bloque)
                    restante -= len(bloque)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def _eventos(self):
        """Server-Sent Events: envía el estado cada vez que cambia."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        ultima = -1
        try:
            self.wfile.write(b"retry: 2000\n\n")
            while True:
                with lock:
                    if estado["version"] == ultima:
                        lock.wait(timeout=15)
                    datos = None
                    if estado["version"] != ultima:
                        ultima = estado["version"]
                        datos = json.dumps(foto(), ensure_ascii=False)
                if datos is not None:
                    self.wfile.write(f"data: {datos}\n\n".encode("utf-8"))
                else:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            return

    def do_GET(self):
        url = urlparse(self.path)
        p = url.path
        paginas = {"/": "index.html", "/cola": "cola.html", "/pantalla": "pantalla.html"}
        if p in paginas:
            return self._archivo(os.path.join(PUBLIC, paginas[p]))
        if p.startswith("/static/"):
            return self._archivo(ruta_segura(PUBLIC, unquote(p[len("/static/"):])))
        if p.startswith("/media/"):
            return self._archivo(ruta_segura(CANCIONES, unquote(p[len("/media/"):])))
        if p == "/api/tiempo":
            return self._json({"ahora": ahora_ms()})
        if p == "/api/estado":
            with lock:
                datos = foto()
            return self._json(datos)
        if p == "/api/eventos":
            return self._eventos()
        if p == "/api/canciones":
            lista = [{"id": c["id"], "titulo": c["titulo"], "artista": c["artista"], "audio": bool(c["audio"])}
                     for c in catalogo().values()]
            lista.sort(key=lambda c: (c["titulo"].lower(), c["artista"].lower()))
            return self._json(lista)
        if p == "/api/letra":
            cid = parse_qs(url.query).get("id", [""])[0]
            c = catalogo().get(cid)
            if not c:
                return self._error("Canción no encontrada", 404)
            return self._json({"id": c["id"], "titulo": c["titulo"], "artista": c["artista"],
                               "lineas": c["lineas"],
                               "audio": "/media/" + quote(c["audio"]) if c["audio"] else None})
        if p == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        self._error("No encontrado", 404)

    def do_POST(self):
        p = urlparse(self.path).path
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 20000:
                return self._error("Petición demasiado grande", 413)
            d = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(d, dict):
                raise ValueError
        except ValueError:
            return self._error("Datos inválidos")

        if p == "/api/cola":
            nombre = " ".join(str(d.get("nombre", "")).split())[:30]
            if not nombre:
                return self._error("Escribe tu nombre o nickname")
            c = catalogo().get(str(d.get("cancion_id", "")))
            if not c:
                return self._error("Canción no encontrada", 404)
            with lock:
                if len(estado["cola"]) >= MAX_COLA:
                    return self._error("La lista está llena, pide que limpien los turnos terminados", 409)
                e = {"id": uuid.uuid4().hex[:10], "nombre": nombre, "cancion_id": c["id"],
                     "titulo": c["titulo"], "artista": c["artista"], "estado": "pendiente",
                     "creado": ahora_ms()}
                estado["cola"].append(e)
                posicion = sum(1 for x in estado["cola"] if x["estado"] == "pendiente")
                cambio()
            return self._json({"entrada": e, "posicion": posicion})

        if p == "/api/duracion":
            # La pantalla con audio informa cuánto dura realmente la pista.
            try:
                dur = float(d.get("duracion"))
            except (TypeError, ValueError):
                return self._error("Duración inválida")
            with lock:
                a = estado["actual"]
                if a and a["entrada_id"] == d.get("entrada_id") and not a.get("dur_real") and 5 < dur < 3600:
                    a["fin"] = a["inicio"] + int((dur + 4) * 1000)
                    a["dur_real"] = True
                    cambio()
            return self._json({"ok": True})

        if p.startswith("/api/admin/"):
            if not hmac.compare_digest(self.headers.get("X-Pin", ""), PIN):
                return self._error("PIN incorrecto", 401)
            try:
                with lock:
                    accion_admin(p[len("/api/admin/"):], d)
            except KeyError:
                return self._error("Acción desconocida", 404)
            except (LookupError, ValueError) as e:
                return self._error(str(e))
            return self._json({"ok": True})

        self._error("No encontrado", 404)


def ip_local():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


# Render publica la dirección del sitio en RENDER_EXTERNAL_URL (sin la "/" final).
URL_PUBLICA = os.environ.get("KARAOKE_URL") or os.environ.get("RENDER_EXTERNAL_URL")
URL_PUBLICA = URL_PUBLICA.rstrip("/") + "/" if URL_PUBLICA else f"http://{ip_local()}:{PUERTO}/"

if __name__ == "__main__":
    os.makedirs(CANCIONES, exist_ok=True)
    cargar()
    threading.Thread(target=vigilante, daemon=True).start()
    servidor = ThreadingHTTPServer(("0.0.0.0", PUERTO), Manejador)
    servidor.daemon_threads = True
    base = URL_PUBLICA.rstrip("/")
    print("=" * 60)
    print("  KARAOKE QR funcionando")
    print("=" * 60)
    print(f"  Invitados (QR) : {base}/")
    print(f"  Control turnos : {base}/cola     (PIN: {PIN})")
    print(f"  Pantalla(s)    : {base}/pantalla")
    print(f"  Canciones      : {len(catalogo())} en {CANCIONES}")
    print("  Ctrl+C para detener")
    print("=" * 60)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido.")
