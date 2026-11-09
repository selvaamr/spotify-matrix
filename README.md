<div align="center">

# 💿 KATXI MATRIX

**Un tocadiscos de LEDs que pone a girar la portada de lo que suena en Spotify.**

Raspberry Pi · Matriz RGB 64×64 · Python · FastAPI

</div>

---

KATXI MATRIX es una pantalla decorativa hecha con una Raspberry Pi y una matriz LED de 64×64. Cuando suena algo en Spotify, la portada del disco aparece en la matriz girando como un vinilo en un plato. Cuando no hay música, la matriz sirve de reloj, calendario con notas, estación del tiempo o marco de pixel art. Todo se controla desde una web en el móvil, sin tocar la Raspberry.

El conjunto va dentro de un marco impreso en 3D con forma de tocadiscos estilo Technics.

## ✨ Qué hace

| Modo | Descripción |
|---|---|
| 🎵 **Spotify** | La portada de la canción actual gira como un disco. Diseños: *Vinilo clásico*, *Brillo*, *CD* y *Vinilo color*, con velocidad ajustable. Sin música (o tras 3 s en pausa) muestra **PLAY SPOTIFY**. |
| 🕐 **Reloj** | Varios estilos y dos tipografías pixel (Pixelya y Pixelfy). |
| 📅 **Calendario** | Muestra la fecha y las notas del día elegido, cada una en su color. |
| ⛅ **Tiempo** | Previsión descargada de [Open-Meteo](https://open-meteo.com/) en segundo plano. |
| 🖼️ **Pixel art** | Galería de imágenes 64×64 que se suben desde la web. |

Y además:

- **Cambio automático a Spotify**: al empezar a sonar música se pasa solo al modo Spotify, y al parar (6 s) vuelve al modo que había. Si cambias de modo a mano, se respeta.
- **Modo noche**: brillo mínimo y todo en rojo, con intensidad ajustable. Se activa solo de 22:00 a 08:00 (horario configurable) y pone el reloj en una versión mínima; al terminar vuelve al modo anterior.
- **Ajustes persistentes**: modo, brillo y ajustes de cada escena se guardan y se recuperan al reiniciar.
- **Apagado seguro**: el botón OFF de la web apaga la Raspberry Pi correctamente.

## 📱 Interfaz web

Al arrancar, la Raspberry Pi sirve una web de control en el puerto `8000`, accesible desde cualquier dispositivo de la misma red:

```
http://<nombre-de-la-pi>.local:8000
http://<ip-de-la-pi>:8000
```

Desde ahí se puede:

- Cambiar de modo y ver una **vista previa en vivo** de la matriz.
- Ajustar brillo, velocidad de giro, diseño del disco, estilo del reloj…
- Gestionar **notas** del calendario (`/notas`) con colores y leyenda.
- Subir y elegir imágenes de **pixel art** (`/imagenes`).
- Encender, apagar y programar el **modo noche**.
- Apagar la Raspberry Pi con el botón **OFF**.

## 🔧 Hardware

| Componente | Notas |
|---|---|
| Raspberry Pi 3 Model B (v2.1) | |
| Matriz LED RGB 64×64 (HUB75) | |
| [Adafruit RGB Matrix HAT + RTC](https://www.adafruit.com/product/2345) | Con el puente **GPIO4–GPIO18 soldado** (modo calidad, PWM por hardware) |
| Fuente de alimentación 5 V | Dimensionada para la matriz (los LEDs a pleno brillo consumen bastante) |
| Marco impreso en 3D | Forma de tocadiscos estilo Technics |

La configuración física de la matriz está fija en `core/display.py` (tamaño, mapeo de pines, `gpio_slowdown`, bits de PWM…). Si cambias de panel o de HAT, se ajusta ahí.

> **Sin el puente soldado** hay que cambiar `HARDWARE_MAPPING` a `"adafruit-hat"` y poner `DISABLE_HARDWARE_PULSING = True`.
>
> **Con el puente** hay que desactivar el audio de la placa (`dtparam=audio=off` en `/boot/firmware/config.txt`), porque comparte el PWM por hardware.

## 📂 Estructura

```
├── main.py                  # Punto de entrada: escenas, bucle principal y web
├── core/
│   ├── controller.py        # Operaciones de alto nivel (la web solo las expone)
│   ├── display.py           # Matriz real (rgbmatrix) y pantalla simulada (PNG)
│   ├── manager.py           # Gestor de escenas
│   ├── settings.py          # Ajustes persistentes (settings.json)
│   ├── autoswitch.py        # Cambio automático a Spotify y vuelta al modo anterior
│   ├── nightmode.py         # Modo noche (night.json)
│   ├── notes.py             # Notas del calendario (notes.json)
│   ├── pixelart.py          # Galería de pixel art
│   └── preview.py           # Último fotograma para la vista previa web
├── scenes/
│   ├── spotify_record.py    # Disco girando con la portada
│   ├── clock.py             # Reloj
│   ├── calendar_scene.py    # Calendario con notas
│   ├── weather.py           # Tiempo
│   ├── pixel_art.py         # Imágenes de pixel art
│   ├── pixeltext.py         # Texto en píxeles
│   └── textfonts.py         # Tipografías de texto (Pequeña, Fina, Alta)
├── services/
│   ├── spotify.py           # Cliente y sondeo de la API de Spotify
│   └── weather.py           # Descarga del tiempo (Open-Meteo)
└── web/
    ├── server.py            # API REST (FastAPI) y servidor uvicorn
    ├── notes_api.py         # API de notas
    ├── pixelart_api.py      # API de la galería
    ├── night_api.py         # API del modo noche
    ├── power_api.py         # Botón OFF
    └── static/              # HTML, CSS, JS e iconos
        └── fonts/           # ⚠️ No incluida: ver «Tipografías» en la instalación
```

## 🚀 Instalación

### 1. Librería de la matriz

Instala [hzeller/rpi-rgb-led-matrix](https://github.com/hzeller/rpi-rgb-led-matrix) con sus bindings de Python. La forma más sencilla con el HAT de Adafruit es su script de instalación:

```bash
curl https://raw.githubusercontent.com/adafruit/Raspberry-Pi-Installer-Scripts/main/rgb-matrix.sh > rgb-matrix.sh
sudo bash rgb-matrix.sh
```

Elige *Adafruit RGB Matrix HAT + RTC* y, si has soldado el puente, el modo **Quality**.

### 2. Proyecto y dependencias

```bash
git clone https://github.com/<tu-usuario>/katxi-matrix.git
cd katxi-matrix
python3 -m venv --system-site-packages .venv   # para ver los bindings de rgbmatrix
.venv/bin/pip install pillow fastapi uvicorn python-dotenv
```

### 3. Credenciales de Spotify

1. Crea una app en el [Spotify Developer Dashboard](https://developer.spotify.com/dashboard).
2. Añade como *Redirect URI*: `http://127.0.0.1:8888/callback`
3. Crea un archivo `.env` junto a `main.py`:

```env
SPOTIFY_CLIENT_ID=tu_client_id
SPOTIFY_CLIENT_SECRET=tu_client_secret
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback
```

4. Autoriza la cuenta una vez (guarda el token en `.cache/spotify_token.json`):

```bash
sudo -E .venv/bin/python main.py --auth-only --no-browser
```

Abre la URL que aparece, acepta, y pega la dirección a la que te redirige.

### 4. Tipografías (no incluidas)

La carpeta `web/static/fonts/` **no está en el repositorio**: las tipografías **Pixelya** y **Pixelfy** tienen licencia y no se pueden redistribuir. Tienes que conseguirlas tú y ponerlas a mano:

1. Descarga **Pixelya** y **Pixelfy** desde la página de sus autores, respetando su licencia.
2. Crea la carpeta:

   ```bash
   mkdir -p web/static/fonts
   ```

3. Copia los archivos `.ttf` con **estos nombres exactos** (se distinguen mayúsculas y minúsculas):

   ```
   web/static/fonts/
   ├── pixelya.ttf
   └── Pixelfy.ttf
   ```

La interfaz web las usa en el título, los encabezados y el selector de tipografía del reloj. Si faltan, la web funciona igual, pero esos textos salen con una fuente monoespaciada del sistema.

> ¿Prefieres otra tipografía? Pon cualquier `.ttf` con uno de esos dos nombres o cambia las rutas en los `@font-face` de `web/static/style.css`.

## ▶️ Uso

```bash
sudo -E .venv/bin/python main.py
```

Se necesita `sudo` para acceder a los GPIO. Todos los ajustes se cambian desde la web, así que no hacen falta más parámetros.

### Opciones

| Opción | Qué hace |
|---|---|
| `--no-spotify` | Arranca sin Spotify (solo reloj, calendario, tiempo y pixel art) |
| `--no-web` | No arranca la interfaz web |
| `--mock-output out/frame.png` | Sin hardware: guarda cada fotograma en un PNG |
| `--once` | Dibuja un solo fotograma y termina |
| `--preview-frames carpeta/` | Genera fotogramas de ejemplo de cada diseño del disco y termina |
| `--auth-only` | Solo autoriza Spotify y guarda el token |
| `--no-browser` | Muestra la URL de autorización sin abrir el navegador |
| `--fps 20` | Fotogramas por segundo (por defecto 20) |
| `--poll-seconds 2` | Cada cuánto se consulta Spotify (por defecto 2 s) |

### Probar sin la matriz

```bash
python3 main.py --no-spotify --mock-output out/frame.png --once
```

### Arranque automático (systemd)

Ejemplo de `/etc/systemd/system/katxi-matrix.service` (ajusta la ruta):

```ini
[Unit]
Description=KATXI MATRIX
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=/home/pi/Documents/spotify-matrix
ExecStart=/home/pi/Documents/spotify-matrix/.venv/bin/python main.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now katxi-matrix
```

## 🌐 API

La documentación interactiva completa está en `http://<pi>:8000/docs`. Las rutas principales:

| Método | Ruta | Qué hace |
|---|---|---|
| `GET` | `/api/state` | Modo activo, brillo y ajustes de todas las escenas |
| `POST` | `/api/scene` | Cambia de modo · `{"name": "clock"}` |
| `POST` | `/api/scenes/{name}/settings` | Cambia ajustes · `{"values": {...}}` |
| `POST` | `/api/brightness` | Cambia el brillo · `{"value": 0-100}` |
| `GET` | `/api/preview.png` | Último fotograma (PNG 64×64) |
| `GET/POST` | `/api/night` | Estado del modo noche / encender y apagar |
| `POST` | `/api/night/schedule` | Horario del modo noche |
| `POST` | `/api/night/level` | Intensidad del modo noche |
| `GET` | `/api/notes-legend` | Leyenda de colores de las notas |
| `GET` | `/api/notes-days` | Días con notas |
| `POST` | `/api/notes-view-day` | Día que muestra la matriz |
| `POST` | `/api/power/off` | Apaga la Raspberry Pi |

## 🗂️ Archivos generados

Se crean junto a `main.py` y **no deben subirse al repositorio**:

| Archivo | Contenido |
|---|---|
| `.env` | Credenciales de Spotify |
| `.cache/spotify_token.json` | Token de acceso a tu cuenta |
| `settings.json` | Modo, brillo y ajustes guardados |
| `night.json` | Horario e intensidad del modo noche |
| `notes.json` | Notas del calendario |
| `pixelart/` | Imágenes subidas desde la web |

## 🙏 Créditos

Este proyecto parte de [**spotify-matrix**](https://github.com/tnarla/spotify-matrix) de [**@tnarla**](https://github.com/tnarla), la idea y el código original de mostrar en una matriz LED lo que suena en Spotify. Muchas gracias por compartirlo. 💚

También usa:

- [hzeller/rpi-rgb-led-matrix](https://github.com/hzeller/rpi-rgb-led-matrix) — control de la matriz LED
- [Spotify Web API](https://developer.spotify.com/documentation/web-api)
- [Open-Meteo](https://open-meteo.com/) — datos del tiempo
- Tipografías pixel **Pixelya** y **Pixelfy**, de sus respectivos autores (no incluidas en el repositorio)

---

<div align="center">Hecho con 💿 y muchas horas de soldador.</div>
