# 🎤 Karaoke QR

Sitio de karaoke para fiestas/eventos. Funciona en la red local (Wi‑Fi) y **no necesita instalar nada más que Python 3**.

| Página | Para quién | Qué hace |
|---|---|---|
| `/` | Invitados (abren con el QR) | Ven el listado de canciones, eligen una, escriben su nombre o nickname y quedan al final de la lista. Ven su lugar en la fila en vivo. |
| `/cola` | Quien controla el evento | Lista de turnos (nombre + canción), botón ▶ para reproducir, subir/bajar, quitar, siguiente, auto‑siguiente. Las acciones piden PIN. |
| `/pantalla` | TVs / proyectores | Muestra el QR y los próximos turnos; al dar ▶ hace cuenta regresiva de **10 s** y luego la letra a pantalla completa estilo karaoke. Se puede abrir en **varias pantallas** a la vez y todas van sincronizadas. |

## Cómo arrancar

1. Doble clic en `iniciar.bat` (o `python server.py`).
2. La consola muestra las direcciones, por ejemplo `http://192.168.1.50:8000/`.
3. En la computadora del evento abre `http://…:8000/cola` e ingresa el PIN (por defecto **1234**; cámbialo en `iniciar.bat`).
4. En cada TV/proyector abre `http://…:8000/pantalla`:
   - **Con audio** → solo en la pantalla conectada a las bocinas.
   - **Solo letra** → en las demás.
   - Doble clic o tecla **F** para pantalla completa.
5. Los invitados escanean el QR que aparece en la pantalla (o en `/cola`).

> Todos los dispositivos deben estar en la misma red Wi‑Fi. La primera vez, Windows puede preguntar si permites a Python en el Firewall: acepta para **redes privadas**.
> El código QR se dibuja con una librería de internet (cdnjs). Si no hay internet, se muestra la dirección en texto.

## Agregar canciones

Pon en la carpeta `canciones/` dos archivos con **el mismo nombre**:

```
canciones/
  Mi Canción.lrc   ← letra con tiempos (obligatorio)
  Mi Canción.mp3   ← pista/instrumental (opcional: .mp3 .m4a .ogg .wav)
```

No hace falta reiniciar el servidor; la lista se actualiza sola.

El archivo `.lrc` es texto con el tiempo de cada línea:

```
[ti:Título de la canción]
[ar:Artista]
[00:12.50]Primera línea de la letra
[00:16.00]Segunda línea
[00:20.00]
[00:25.30]Una línea vacía marca una pausa musical
```

- `[offset:500]` adelanta la letra 0.5 s si va atrasada respecto al audio (negativo para atrasarla).
- `[length:3:45]` (opcional) indica la duración total si no hay audio.
- Puedes conseguir archivos `.lrc` sincronizados en sitios como lrclib.net o crearlos con un editor de LRC.
- Si no hay audio, la letra avanza sola con el reloj (útil si la música suena desde otro lado).

## Notas

- La lista se guarda en `datos/cola.json`, así que sobrevive si se reinicia el servidor.
- Si una canción termina, la pantalla muestra "¡Aplausos!" y vuelve a la espera; con **auto‑siguiente** activado arranca la cuenta regresiva del siguiente turno.
- Variables opcionales: `KARAOKE_PIN`, `KARAOKE_PUERTO` (8000), `KARAOKE_URL` (para forzar la dirección del QR).

## Publicar en internet (Render, gratis)

1. Sube esta carpeta a un repositorio de GitHub (sin la carpeta `datos/`).
2. En render.com: **New → Blueprint**, elige el repositorio; usa `render.yaml`.
3. Cuando lo pida, escribe un **PIN** nuevo (no uses 1234 en internet).
4. El QR usa solo la dirección `https://….onrender.com/`.

> En el plan gratuito el sitio se duerme tras ~15 min sin visitas (tarda ~1 min en despertar) y la lista de turnos se borra cuando se reinicia.
