"""
@file pixelart.py
@brief Galería de imágenes de pixel art (PNG y GIF animados) para la escena "Pixel art".

Las imágenes se convierten al subirlas a 64x64 y se guardan ya listas en una carpeta (pixelart/),
así la Pi no tiene que procesarlas cada vez. Solo se carga en memoria la imagen que se está
mostrando, y hay un máximo de imágenes para no llenar la tarjeta SD.

@par Cómo se ajusta una imagen a la matriz
La matriz está detrás de una estructura circular, así que todo se ajusta al círculo (radio 30) y lo
que queda fuera se pone en negro, como en las portadas de Spotify:
- Se recorta el fondo sobrante si la imagen tiene un fondo liso (se detecta por los bordes).
- Si la imagen es (casi) cuadrada y llena todo el cuadro, se ajusta como una portada: llena el círculo.
- En cualquier otro caso se encoge lo justo para que se vea entera dentro del círculo, sobre el
  color del fondo.
- Si cabe, se amplía por un número entero de veces sin difuminar (píxeles nítidos); si es más grande,
  se reduce promediando (BOX), que conserva bien los detalles.
"""
from __future__ import annotations

import io
import os
import re
import threading
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageSequence

## Lado de la matriz, en píxeles.
MATRIX_SIZE = 64

## Radio (en píxeles) del círculo visible a través de la estructura.
CIRCLE_RADIUS = 30

## Máximo de imágenes guardadas a la vez.
MAX_IMAGES = 10

## Tamaño máximo del archivo subido, en bytes.
MAX_FILE_BYTES = 2 * 1024 * 1024

## Máximo de fotogramas de un GIF.
MAX_FRAMES = 100

## Máximo de píxeles de la imagen original (evita imágenes gigantes que agoten la memoria).
MAX_SOURCE_PIXELS = 4000 * 4000

## Duración mínima de un fotograma de GIF, en milisegundos (muchos GIF piden 0 ms).
MIN_FRAME_MS = 40

class PixelArtError(ValueError):
    """@brief Error al procesar o guardar una imagen (el mensaje está en español y se muestra tal cual)."""


@dataclass
class FitPlan:
    """
    @brief Cómo se transforma cada fotograma: recorte, escala y color de fondo (se calcula con el primero).
    """

    ## Recorte (izquierda, arriba, derecha, abajo) sobre la imagen original.
    crop: tuple[int, int, int, int]
    ## Tamaño final del contenido, en píxeles.
    size: tuple[int, int]
    ## True si se amplía por un número entero de veces (sin difuminar).
    integer_upscale: bool
    ## True si la imagen llena el círculo como una portada (en vez de encogerse para verse entera).
    cover: bool
    ## Color del lienzo.
    background: tuple[int, int, int]


def _flatten(image: Image.Image) -> Image.Image:
    """
    @brief Convierte a RGB poniendo lo transparente sobre negro.
    @param image Imagen de cualquier modo.
    @return Imagen RGB.
    """
    rgba = image.convert("RGBA")
    base = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
    return Image.alpha_composite(base, rgba).convert("RGB")


def detect_background(image: Image.Image) -> tuple[int, int, int] | None:
    """
    @brief Detecta un fondo liso mirando el borde de la imagen.
    @param image Imagen RGB.
    @return El color del fondo, o None si el borde no es (casi) de un único color.
    """
    width, height = image.size
    pixels = image.load()
    border = [pixels[x, 0] for x in range(width)] + [pixels[x, height - 1] for x in range(width)]
    border += [pixels[0, y] for y in range(1, height - 1)] + [pixels[width - 1, y] for y in range(1, height - 1)]
    colors: dict[tuple[int, int, int], int] = {}
    for color in border:
        colors[color] = colors.get(color, 0) + 1
    color, count = max(colors.items(), key=lambda item: item[1])
    return color if count >= 0.5 * len(border) else None


def plan_fit(images: "Image.Image | list[Image.Image]") -> FitPlan:
    """
    @brief Calcula el recorte y el tamaño final de una imagen o de todos los fotogramas de un GIF.

    El fondo se detecta con el primer fotograma, y el recorte abarca el contenido de todos, para que
    el GIF no se corte cuando algo se mueve.

    @param images Imagen RGB, o lista de fotogramas RGB del mismo tamaño.
    @return Plan que luego se aplica a cada fotograma con apply_plan().
    """
    frames = images if isinstance(images, list) else [images]
    image = frames[0]
    background = detect_background(image)
    crop = (0, 0, image.width, image.height)
    if background is not None:
        # Recorta al contenido: todo lo que no es del color del fondo, en cualquiera de los fotogramas.
        boxes = [ImageChops.difference(frame, Image.new("RGB", frame.size, background)).getbbox() for frame in frames]
        boxes = [box for box in boxes if box is not None]
        if boxes:
            crop = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
    width, height = crop[2] - crop[0], crop[3] - crop[1]
    fill = background or (0, 0, 0)

    diameter = 2 * CIRCLE_RADIUS
    squareish = min(width, height) >= 0.9 * max(width, height)
    full_frame = width >= 0.9 * image.width and height >= 0.9 * image.height
    if squareish and full_frame:
        # Como una portada de Spotify: el lado más largo ocupa el diámetro del círculo y se recorta lo que sobre.
        side = min(width, height)
        factor = diameter // side if side < diameter else 0
        if factor >= 1 and factor * side >= 0.8 * diameter:
            return FitPlan(crop, (width * factor, height * factor), True, True, fill)
        scale = diameter / side
        return FitPlan(crop, (max(1, round(width * scale)), max(1, round(height * scale))), False, True, fill)

    limit = min(MATRIX_SIZE / max(width, height), diameter / (width ** 2 + height ** 2) ** 0.5)
    if limit >= 1:
        factor = int(limit)
        return FitPlan(crop, (width * factor, height * factor), True, False, fill)
    return FitPlan(crop, (max(1, round(width * limit)), max(1, round(height * limit))), False, False, fill)


def circle_mask() -> Image.Image:
    """
    @brief Máscara del círculo visible: blanco dentro (radio CIRCLE_RADIUS) y negro fuera.
    @return Imagen "L" de 64x64.
    """
    mask = Image.new("L", (MATRIX_SIZE, MATRIX_SIZE), 0)
    pixels = mask.load()
    for y in range(MATRIX_SIZE):
        for x in range(MATRIX_SIZE):
            if (x + 0.5 - MATRIX_SIZE / 2) ** 2 + (y + 0.5 - MATRIX_SIZE / 2) ** 2 <= CIRCLE_RADIUS ** 2:
                pixels[x, y] = 255
    return mask


## Máscara del círculo (se calcula una vez).
_MASK = circle_mask()


def apply_plan(image: Image.Image, plan: FitPlan) -> Image.Image:
    """
    @brief Aplica el plan a un fotograma, lo centra en 64x64 y deja en negro lo que cae fuera del círculo.
    @param image Fotograma RGB (del mismo tamaño que el usado para el plan).
    @param plan  Plan calculado con plan_fit().
    @return Imagen RGB de 64x64.
    """
    part = image.crop(plan.crop)
    resample = Image.Resampling.NEAREST if plan.integer_upscale or plan.cover and part.width < plan.size[0] else Image.Resampling.BOX
    part = part.resize(plan.size, resample)
    canvas = Image.new("RGB", (MATRIX_SIZE, MATRIX_SIZE), plan.background)
    canvas.paste(part, ((MATRIX_SIZE - part.width) // 2, (MATRIX_SIZE - part.height) // 2))
    return Image.composite(canvas, Image.new("RGB", canvas.size, (0, 0, 0)), _MASK)


def convert(data: bytes) -> tuple[list[Image.Image], list[int]]:
    """
    @brief Convierte los bytes de un archivo de imagen en fotogramas de 64x64.
    @param data Contenido del archivo (PNG, GIF, JPEG o WebP).
    @return (fotogramas, duraciones en ms). Una imagen fija devuelve un solo fotograma.
    @throws PixelArtError si el archivo es demasiado grande, no es una imagen o tiene demasiados fotogramas.
    """
    if len(data) > MAX_FILE_BYTES:
        raise PixelArtError(f"El archivo pesa demasiado (máximo {MAX_FILE_BYTES // (1024 * 1024)} MB).")
    try:
        source = Image.open(io.BytesIO(data))
        if source.width * source.height > MAX_SOURCE_PIXELS:
            raise PixelArtError("La imagen es demasiado grande (máximo 4000x4000 píxeles).")
        count = getattr(source, "n_frames", 1)
        if count > MAX_FRAMES:
            raise PixelArtError(f"El GIF tiene demasiados fotogramas ({count}; máximo {MAX_FRAMES}).")
        flats: list[Image.Image] = []
        durations: list[int] = []
        for frame in ImageSequence.Iterator(source):
            flats.append(_flatten(frame))
            durations.append(max(MIN_FRAME_MS, int(frame.info.get("duration", 100) or 100)))
        plan = plan_fit(flats)
        frames = [apply_plan(flat, plan) for flat in flats]
    except PixelArtError:
        raise
    except Exception as exc:  # noqa: BLE001 - PIL lanza muchos tipos de error distintos con archivos dañados
        raise PixelArtError("No se pudo leer la imagen (¿es un PNG, GIF o JPG válido?).") from exc
    if not frames:
        raise PixelArtError("La imagen no tiene fotogramas.")
    return frames, durations


def make_id(name: str) -> str:
    """
    @brief Convierte un nombre en un identificador seguro para usar como nombre de archivo.
    @param name Nombre escrito por el usuario.
    @return Texto en minúsculas con letras, números y guiones (máximo 24 caracteres).
    @throws PixelArtError si no queda ningún carácter válido.
    """
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", plain).strip("-")[:24].strip("-")
    if not slug:
        raise PixelArtError("Pon un nombre con letras o números.")
    return slug


def label_of(image_id: str) -> str:
    """
    @brief Nombre bonito de una imagen para la interfaz.
    @param image_id Identificador.
    @return Texto con espacios y la primera letra en mayúscula.
    """
    return image_id.replace("-", " ").capitalize()


class PixelArtStore:
    """
    @brief Carpeta de imágenes ya convertidas (PNG las fijas, GIF las animadas).

    Es seguro usarlo desde varios hilos (servidor web y bucle principal).
    """

    def __init__(self, directory: Path = Path("pixelart")) -> None:
        """
        @brief Prepara el almacén (no crea la carpeta hasta que haga falta).
        @param directory Carpeta donde se guardan las imágenes.
        """
        ## Carpeta de imágenes.
        self.directory = directory
        ## Cerrojo que protege la carpeta.
        self._lock = threading.RLock()
        ## Contador que sube con cada cambio; la escena lo usa para saber cuándo refrescar la lista.
        self.version = 0

    def install_defaults(self, defaults: Path) -> int:
        """
        @brief Copia las imágenes por defecto la primera vez (cuando todavía no existe la carpeta pixelart/).

        Después de esa primera vez no vuelve a copiarlas, así que si el usuario las borra no reaparecen.

        @param defaults Carpeta con las imágenes por defecto (PNG o GIF ya convertidos).
        @return Número de imágenes copiadas.
        """
        with self._lock:
            if self.directory.exists() or not defaults.is_dir():
                return 0
            self.directory.mkdir(parents=True, exist_ok=True)
            copied = 0
            for source in sorted(defaults.iterdir()):
                if source.suffix.lower() in (".png", ".gif") and copied < MAX_IMAGES:
                    self._write_bytes(self.directory / source.name.lower(), source.read_bytes())
                    copied += 1
            self.version += 1
            return copied

    def ids(self) -> list[str]:
        """
        @brief Identificadores de todas las imágenes, ordenados.
        @return Lista de identificadores.
        """
        with self._lock:
            if not self.directory.is_dir():
                return []
            return sorted(path.stem for path in self.directory.iterdir() if path.suffix in (".png", ".gif"))

    def describe(self) -> list[dict[str, object]]:
        """
        @brief Lista para la interfaz: identificador, nombre y si es animada.
        @return Lista de diccionarios.
        """
        with self._lock:
            return [{"id": i, "label": label_of(i), "animated": self._path(i).suffix == ".gif"} for i in self.ids()]

    def path_of(self, image_id: str) -> Path:
        """
        @brief Ruta del archivo de una imagen.
        @param image_id Identificador.
        @return Ruta del PNG o GIF.
        @throws KeyError si no existe.
        """
        with self._lock:
            path = self._path(image_id)
            if not path.exists():
                raise KeyError(image_id)
            return path

    def load(self, image_id: str) -> tuple[list[Image.Image], list[int]]:
        """
        @brief Carga una imagen en memoria.
        @param image_id Identificador.
        @return (fotogramas RGB de 64x64, duraciones en ms).
        @throws KeyError si no existe o no se puede leer.
        """
        path = self.path_of(image_id)
        try:
            with Image.open(path) as source:
                frames, durations = [], []
                for frame in ImageSequence.Iterator(source):
                    frames.append(_flatten(frame))
                    durations.append(max(MIN_FRAME_MS, int(frame.info.get("duration", 100) or 100)))
        except Exception as exc:  # noqa: BLE001
            raise KeyError(image_id) from exc
        return frames, durations

    def add(self, name: str, data: bytes) -> str:
        """
        @brief Convierte y guarda una imagen nueva.
        @param name Nombre elegido por el usuario.
        @param data Contenido del archivo subido.
        @return Identificador de la imagen guardada.
        @throws PixelArtError si ya hay el máximo de imágenes, el nombre no vale o la imagen no se puede procesar.
        """
        base = make_id(name)
        with self._lock:
            if len(self.ids()) >= MAX_IMAGES:
                raise PixelArtError(f"Ya hay {MAX_IMAGES} imágenes, que es el máximo. Borra alguna para añadir otra.")
            frames, durations = convert(data)
            existing = set(self.ids())
            image_id, number = base, 2
            while image_id in existing:
                image_id = f"{base[:21]}-{number}"
                number += 1
            self.directory.mkdir(parents=True, exist_ok=True)
            buffer = io.BytesIO()
            if len(frames) == 1:
                frames[0].save(buffer, "PNG", optimize=True)
                suffix = ".png"
            else:
                frames[0].save(buffer, "GIF", save_all=True, append_images=frames[1:], duration=durations, loop=0, disposal=1)
                suffix = ".gif"
            self._write_bytes(self.directory / f"{image_id}{suffix}", buffer.getvalue())
            self.version += 1
            return image_id

    def delete(self, image_id: str) -> None:
        """
        @brief Borra una imagen.
        @param image_id Identificador.
        @throws KeyError si no existe.
        """
        with self._lock:
            path = self.path_of(image_id)
            path.unlink()
            self.version += 1

    def _path(self, image_id: str) -> Path:
        """
        @brief Ruta (PNG o GIF) de un identificador, sin comprobar que exista.
        @param image_id Identificador (solo letras minúsculas, números y guiones).
        @return Ruta probable del archivo.
        """
        if not re.fullmatch(r"[a-z0-9-]{1,24}", image_id or ""):
            return self.directory / "__invalido__.png"
        gif = self.directory / f"{image_id}.gif"
        return gif if gif.exists() else self.directory / f"{image_id}.png"

    def _write_bytes(self, target: Path, data: bytes) -> None:
        """
        @brief Escribe un archivo de forma atómica (temporal + reemplazo), con el dueño de la carpeta si somos root.
        @param target Archivo final.
        @param data   Contenido.
        """
        tmp = target.with_name(target.name + ".tmp")
        with tmp.open("wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            try:
                stat = target.parent.stat()
                os.chown(tmp, stat.st_uid, stat.st_gid)
            except OSError:
                pass
        os.replace(tmp, target)
