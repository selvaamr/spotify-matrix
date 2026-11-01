/**
 * @file app.js
 * @brief Lógica de la interfaz web de la matriz LED.
 *
 * Descarga el estado de la API (/api/state), dibuja los controles a partir del
 * esquema de ajustes de cada escena y envía los cambios al servidor. Además
 * refresca la vista previa en vivo de la matriz.
 */
"use strict";

/** @brief Milisegundos entre refrescos de la vista previa. */
const PREVIEW_INTERVAL_MS = 250;

/** @brief Milisegundos entre consultas de estado en segundo plano (por si lo cambia otro dispositivo). */
const STATE_INTERVAL_MS = 5000;

/** @brief Milisegundos mínimos entre envíos mientras se arrastra un deslizador. */
const SEND_INTERVAL_MS = 150;

/** @brief Último estado recibido de la API, o null si aún no hay. */
let state = null;

/** @brief Última respuesta de estado en texto, para no redibujar si no ha cambiado nada. */
let lastStateJson = "";

/** @brief true mientras el usuario toca un control (evita redibujarlo bajo su dedo). */
let interacting = false;

/** @brief Atajo para document.getElementById. */
const $ = (id) => document.getElementById(id);

/**
 * @brief Crea un elemento del DOM.
 * @param {string} tag Nombre de la etiqueta.
 * @param {Object} [props] Propiedades a asignar (className, textContent, type...).
 * @param {Array<Node>} [children] Hijos a añadir.
 * @return {HTMLElement} Elemento creado.
 */
function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  Object.assign(node, props);
  children.forEach((child) => node.appendChild(child));
  return node;
}

/**
 * @brief Muestra un aviso breve en la parte inferior de la pantalla.
 * @param {string} message Texto del aviso.
 */
function toast(message) {
  const box = $("toast");
  box.textContent = message;
  box.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => box.classList.remove("show"), 3000);
}

/**
 * @brief Llama a la API y devuelve el JSON de la respuesta.
 * @param {string} path Ruta, p. ej. "/api/state".
 * @param {Object} [options] Opciones de fetch.
 * @return {Promise<Object>} Cuerpo de la respuesta.
 * @throws {Error} Si la respuesta no es correcta (el mensaje es el detalle del servidor).
 */
async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = (await response.json()).detail || detail;
    } catch (ignored) { /* la respuesta no era JSON */ }
    throw new Error(detail);
  }
  return response.json();
}

/**
 * @brief Envía una petición POST con cuerpo JSON.
 * @param {string} path Ruta de la API.
 * @param {Object} body Cuerpo a enviar.
 * @return {Promise<Object>} Cuerpo de la respuesta.
 */
function post(path, body) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/**
 * @brief Limita la frecuencia de una función, garantizando que la última llamada siempre se ejecuta.
 * @param {Function} fn Función a limitar.
 * @param {number} ms Intervalo mínimo entre ejecuciones, en milisegundos.
 * @return {Function} Versión limitada de fn.
 */
function throttle(fn, ms) {
  let last = 0;
  let timer = null;
  let pending = null;
  return (...args) => {
    pending = args;
    const wait = ms - (Date.now() - last);
    if (wait <= 0) {
      last = Date.now();
      pending = null;
      fn(...args);
    } else if (!timer) {
      timer = setTimeout(() => {
        timer = null;
        last = Date.now();
        const next = pending;
        pending = null;
        if (next) fn(...next);
      }, wait);
    }
  };
}

/**
 * @brief Construye un deslizador con su etiqueta y su valor actual.
 * @param {Object} options Opciones del deslizador.
 * @param {string} options.label Texto de la etiqueta.
 * @param {number} options.min Valor mínimo.
 * @param {number} options.max Valor máximo.
 * @param {number} options.step Paso.
 * @param {number} options.value Valor inicial.
 * @param {function(number): void} options.onChange Se llama (limitada en frecuencia) al mover el deslizador y una vez más al soltarlo.
 * @return {HTMLElement} Contenedor del control.
 */
function buildSlider({ label, min, max, step, value, onChange }) {
  const decimals = step < 1 ? 1 : 0;
  const output = el("span", { className: "control-value", textContent: Number(value).toFixed(decimals) });
  const input = el("input", { type: "range", min, max, step, value });
  const send = throttle(onChange, SEND_INTERVAL_MS);

  input.addEventListener("input", () => {
    output.textContent = Number(input.value).toFixed(decimals);
    send(Number(input.value));
  });
  input.addEventListener("change", () => onChange(Number(input.value)));

  return el("div", { className: "control" }, [
    el("div", { className: "control-head" }, [el("span", { textContent: label }), output]),
    input,
  ]);
}

/**
 * @brief Construye un selector de opciones (botones) para un ajuste de tipo "choice".
 * @param {Object} options Opciones del selector.
 * @param {string} options.label Texto de la etiqueta.
 * @param {Array<{value: string, label: string}>} options.choices Opciones disponibles.
 * @param {string} options.value Valor seleccionado.
 * @param {function(string): void} options.onChange Se llama al elegir una opción.
 * @return {HTMLElement} Contenedor del control.
 */
function buildChoice({ label, choices, value, onChange }) {
  const chips = el("div", { className: "chips" });
  choices.forEach((choice) => {
    const chip = el("button", { type: "button", className: "chip", textContent: choice.label });
    chip.setAttribute("aria-pressed", String(choice.value === value));
    chip.addEventListener("click", () => onChange(choice.value));
    chips.appendChild(chip);
  });
  return el("div", { className: "control" }, [
    el("div", { className: "control-head" }, [el("span", { textContent: label })]),
    chips,
  ]);
}

/**
 * @brief Construye un selector de color: una fila de círculos, cada uno con su color (sin texto).
 * @param {Object} options Opciones del selector.
 * @param {string} options.label Texto de la etiqueta del control.
 * @param {Array<{value: string, label: string, color: string}>} options.choices Colores disponibles ("color" en formato #rrggbb;
 *        "label" se usa solo como texto accesible).
 * @param {string} options.value Valor seleccionado.
 * @param {function(string): void} options.onChange Se llama al elegir un color.
 * @return {HTMLElement} Contenedor del control.
 */
function buildColor({ label, choices, value, onChange }) {
  const swatches = el("div", { className: "swatches" });
  choices.forEach((choice) => {
    const swatch = el("button", { type: "button", className: "swatch", title: choice.label });
    swatch.style.backgroundColor = choice.color;
    swatch.setAttribute("aria-label", choice.label);
    swatch.setAttribute("aria-pressed", String(choice.value === value));
    swatch.addEventListener("click", () => onChange(choice.value));
    swatches.appendChild(swatch);
  });
  return el("div", { className: "control" }, [
    el("div", { className: "control-head" }, [el("span", { textContent: label })]),
    swatches,
  ]);
}

/**
 * @brief Indica si un ajuste debe mostrarse con los valores actuales.
 *
 * Un ajuste puede declarar "show_if" en su esquema, por ejemplo {"style": ["analog"]}, y entonces solo
 * se muestra cuando el ajuste "style" tiene uno de esos valores.
 *
 * @param {Object} spec Descripción del ajuste (una entrada del esquema).
 * @param {Object} settings Valores actuales de los ajustes de la escena.
 * @return {boolean} true si el ajuste debe mostrarse.
 */
function isVisible(spec, settings) {
  if (!spec.show_if) return true;
  return Object.entries(spec.show_if).every(([key, allowed]) => allowed.includes(settings[key]));
}

/**
 * @brief Devuelve la escena activa del estado actual.
 * @return {Object|undefined} Escena (name, label, settings, schema) o undefined.
 */
function activeScene() {
  return state && state.scenes.find((scene) => scene.name === state.scene);
}

/** @brief Dibuja los botones de selección de modo. */
function renderScenes() {
  const container = $("scenes");
  container.replaceChildren();
  state.scenes.forEach((scene) => {
    const chip = el("button", { type: "button", className: "chip", textContent: scene.label });
    chip.setAttribute("aria-pressed", String(scene.name === state.scene));
    chip.addEventListener("click", () => selectScene(scene.name));
    container.appendChild(chip);
  });
}

/**
 * @brief Envía un cambio de ajuste de una escena y actualiza el estado local con lo que el servidor aplicó.
 * @param {Object} scene Escena a la que pertenece el ajuste.
 * @param {string} key Clave del ajuste.
 * @param {*} value Nuevo valor.
 * @param {boolean} rerender Si es true, vuelve a dibujar los ajustes (necesario en los selectores).
 * @return {Promise<void>}
 */
async function sendSetting(scene, key, value, rerender) {
  try {
    const result = await post(`/api/scenes/${encodeURIComponent(scene.name)}/settings`, { values: { [key]: value } });
    scene.settings = result.settings;
    lastStateJson = JSON.stringify(state);
    if (rerender) renderSettings();
  } catch (error) {
    toast(`No se pudo guardar el ajuste: ${error.message}`);
  }
}

/** @brief Dibuja los ajustes de la escena activa a partir de su esquema. */
function renderSettings() {
  const scene = activeScene();
  const card = $("settings-card");
  const container = $("settings");
  container.replaceChildren();

  if (!scene || scene.schema.length === 0) {
    card.hidden = true;
    return;
  }
  card.hidden = false;
  $("settings-title").textContent = `Ajustes · ${scene.label}`;

  scene.schema.forEach((spec) => {
    if (!isVisible(spec, scene.settings)) return;
    const value = scene.settings[spec.key];
    const label = spec.label || spec.key;
    if (spec.type === "color") {
      container.appendChild(buildColor({
        label,
        choices: spec.choices,
        value,
        onChange: (next) => sendSetting(scene, spec.key, next, true),
      }));
    } else if (spec.type === "choice") {
      container.appendChild(buildChoice({
        label,
        choices: spec.choices,
        value,
        onChange: (next) => sendSetting(scene, spec.key, next, true),
      }));
    } else if (spec.type === "float" || spec.type === "int") {
      const range = spec.max - spec.min;
      const step = spec.type === "int" ? 1 : (range >= 20 ? 1 : 0.1);
      container.appendChild(buildSlider({
        label,
        min: spec.min,
        max: spec.max,
        step,
        value,
        onChange: (next) => sendSetting(scene, spec.key, next, false),
      }));
    }
  });
}

/** @brief Dibuja el deslizador de brillo. */
function renderBrightness() {
  $("brightness").replaceChildren(buildSlider({
    label: "Brillo de la matriz",
    min: 0,
    max: 100,
    step: 1,
    value: state.brightness,
    onChange: async (value) => {
      try {
        state.brightness = (await post("/api/brightness", { value })).brightness;
        lastStateJson = JSON.stringify(state);
      } catch (error) {
        toast(`No se pudo cambiar el brillo: ${error.message}`);
      }
    },
  }));
}

/** @brief Dibuja toda la interfaz a partir del estado actual. */
function renderAll() {
  renderScenes();
  renderSettings();
  renderBrightness();
}

/**
 * @brief Cambia el modo de la matriz.
 * @param {string} name Identificador de la escena.
 * @return {Promise<void>}
 */
async function selectScene(name) {
  try {
    state = await post("/api/scene", { name });
    lastStateJson = JSON.stringify(state);
    renderAll();
  } catch (error) {
    toast(`No se pudo cambiar de modo: ${error.message}`);
  }
}

/**
 * @brief Descarga el estado de la API y redibuja la interfaz si ha cambiado.
 * @param {boolean} background Si es true es una consulta periódica: no avisa de errores ni
 *        redibuja mientras el usuario está tocando un control.
 * @return {Promise<void>}
 */
async function loadState(background) {
  try {
    const fresh = await api("/api/state");
    const json = JSON.stringify(fresh);
    if (background && (interacting || json === lastStateJson)) return;
    state = fresh;
    lastStateJson = json;
    renderAll();
  } catch (error) {
    if (!background) toast(`No se pudo conectar con la matriz: ${error.message}`);
  }
}

/** @brief true mientras hay una petición de vista previa en curso (evita acumularlas). */
let previewBusy = false;

/**
 * @brief Pide el último fotograma de la matriz y lo muestra.
 * @return {Promise<void>}
 */
async function refreshPreview() {
  if (previewBusy || document.hidden) return;
  previewBusy = true;
  try {
    const response = await fetch("/api/preview.png", { cache: "no-store" });
    if (response.ok) {
      const url = URL.createObjectURL(await response.blob());
      const image = $("preview");
      const previous = image.src;
      image.src = url;
      if (previous.startsWith("blob:")) URL.revokeObjectURL(previous);
    }
  } catch (ignored) { /* sin conexión: se reintenta en el siguiente ciclo */ } finally {
    previewBusy = false;
  }
}

/** @brief Arranca la interfaz: carga el estado y programa los refrescos periódicos. */
function start() {
  ["settings", "brightness"].forEach((id) => {
    $(id).addEventListener("pointerdown", () => { interacting = true; });
  });
  ["pointerup", "pointercancel"].forEach((name) => {
    document.addEventListener(name, () => { interacting = false; });
  });

  loadState(false);
  refreshPreview();
  setInterval(refreshPreview, PREVIEW_INTERVAL_MS);
  setInterval(() => loadState(true), STATE_INTERVAL_MS);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) loadState(true);
  });
}

start();