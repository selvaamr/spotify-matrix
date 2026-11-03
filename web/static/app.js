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

/**
 * @brief Icono de cada modo. Se busca la primera palabra que aparezca en el nombre o la etiqueta de la escena.
 */
const SCENE_ICONS = [
  { match: ["spotify", "disco", "vinilo"], icon: "spotify" },
  { match: ["reloj", "clock", "hora"], icon: "reloj" },
  { match: ["tiempo", "clima", "weather"], icon: "tiempo" },
  { match: ["calendario", "calendar"], icon: "calendario" },
  { match: ["pixel", "imagen", "image"], icon: "pixelart" },
];

/**
 * @brief Devuelve el icono de una escena.
 * @param {Object} scene Escena (name, label).
 * @return {string|null} Nombre del icono (sin extensión) o null si no tiene.
 */
function sceneIcon(scene) {
  const text = `${scene.name} ${scene.label}`.toLowerCase();
  const found = SCENE_ICONS.find((entry) => entry.match.some((word) => text.includes(word)));
  return found ? found.icon : null;
}

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
 * @param {string} [options.variant] Estilo especial de la barra ("speed" o "brightness").
 * @param {boolean} [options.showValue] Si es false no se muestra el número.
 * @return {HTMLElement} Contenedor del control.
 */
function buildSlider({ label, min, max, step, value, onChange, variant, showValue = true }) {
  const decimals = step < 1 ? 1 : 0;
  const output = el("span", { className: "control-value", textContent: Number(value).toFixed(decimals) });
  const input = el("input", { type: "range", min, max, step, value });
  if (variant) input.classList.add(`range-${variant}`);
  if (!label) input.setAttribute("aria-label", "Brillo");
  const send = throttle(onChange, SEND_INTERVAL_MS);

  /** Pasa al CSS la posición de la bolita (0 a 1) para rellenar la barra solo hasta ahí. */
  const updateFill = () => {
    const ratio = (Number(input.value) - min) / (max - min || 1);
    input.style.setProperty("--p", String(ratio));
  };
  updateFill();

  input.addEventListener("input", () => {
    output.textContent = Number(input.value).toFixed(decimals);
    updateFill();
    send(Number(input.value));
  });
  input.addEventListener("change", () => onChange(Number(input.value)));

  const head = [];
  if (label) head.push(el("span", { textContent: label }));
  if (showValue) head.push(output);
  const children = head.length ? [el("div", { className: "control-head" }, head), input] : [input];
  return el("div", { className: "control" }, children);
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
  const children = label ? [el("div", { className: "control-head" }, [el("span", { textContent: label })]), chips] : [chips];
  return el("div", { className: "control" }, children);
}

/** @brief Etiquetas de ajustes que no se muestran (solo se ven sus botones). */
const HIDDEN_LABELS = [/dise[ñn]o del disco/i];

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
 * @brief Construye el selector del reloj: tipografías en columna a la izquierda y, a la derecha,
 *        los dos estilos como círculos con una vista previa de cómo se verá la matriz.
 *
 * Las vistas previas son imágenes en blanco (static/icons/clock/<estilo>-<tipografía>.png) que se
 * usan como máscara y se pintan con el color elegido, así siempre coinciden con los ajustes.
 *
 * @param {Object} scene Escena del reloj.
 * @param {Object} styleSpec Ajuste "style" del esquema.
 * @param {Object} fontSpec Ajuste "font" del esquema.
 * @return {HTMLElement} Contenedor del control.
 */
function buildClockPicker(scene, styleSpec, fontSpec) {
  const settings = scene.settings;
  const colorSpec = scene.schema.find((spec) => spec.type === "color");
  const colorChoice = colorSpec && colorSpec.choices.find((choice) => choice.value === settings[colorSpec.key]);
  const ledColor = colorChoice ? colorChoice.color : "#1ed760";

  const fonts = el("div", { className: "clock-fonts" });
  fontSpec.choices.forEach((choice) => {
    const chip = el("button", { type: "button", className: "chip", textContent: choice.label });
    chip.dataset.font = choice.value;
    chip.setAttribute("aria-pressed", String(choice.value === settings[fontSpec.key]));
    chip.addEventListener("click", () => sendSetting(scene, fontSpec.key, choice.value, true));
    fonts.appendChild(chip);
  });

  const styles = el("div", { className: "clock-styles" });
  styleSpec.choices.forEach((choice) => {
    const face = el("span", { className: "clock-face" });
    face.style.setProperty("--led", ledColor);
    face.style.setProperty("--img", `url("/static/icons/clock/${choice.value}-${settings[fontSpec.key]}.png")`);
    const button = el("button", { type: "button", className: "clock-style", title: choice.label }, [face]);
    button.setAttribute("aria-label", choice.label);
    button.setAttribute("aria-pressed", String(choice.value === settings[styleSpec.key]));
    button.addEventListener("click", () => sendSetting(scene, styleSpec.key, choice.value, true));
    styles.appendChild(button);
  });

  return el("div", { className: "control clock-picker" }, [fonts, styles]);
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

/** @brief Dibuja los botones de selección de modo (con icono si lo tiene; si no, con texto). */
function renderScenes() {
  const container = $("scenes");
  container.replaceChildren();
  state.scenes.forEach((scene) => {
    const icon = sceneIcon(scene);
    const button = icon
      ? el("button", { type: "button", className: "mode", title: scene.label }, [
        el("img", { src: `/static/icons/${icon}.png`, alt: "" }),
      ])
      : el("button", { type: "button", className: "chip", textContent: scene.label });
    button.setAttribute("aria-label", scene.label);
    button.setAttribute("aria-pressed", String(scene.name === state.scene));
    button.addEventListener("click", () => selectScene(scene.name));
    container.appendChild(button);
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

  // El reloj tiene una disposición propia para el estilo y la tipografía.
  const styleSpec = scene.schema.find((spec) => spec.key === "style");
  const fontSpec = scene.schema.find((spec) => spec.key === "font");
  const clockPicker = sceneIcon(scene) === "reloj" && styleSpec && fontSpec;

  scene.schema.forEach((spec) => {
    if (!isVisible(spec, scene.settings)) return;
    if (clockPicker && spec === fontSpec) return;
    if (clockPicker && spec === styleSpec) {
      container.appendChild(buildClockPicker(scene, styleSpec, fontSpec));
      return;
    }
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
        label: HIDDEN_LABELS.some((pattern) => pattern.test(label)) ? "" : label,
        choices: spec.choices,
        value,
        onChange: (next) => sendSetting(scene, spec.key, next, true),
      }));
    } else if (spec.type === "float" || spec.type === "int") {
      const range = spec.max - spec.min;
      const isSpeed = /velocidad|speed|rpm/i.test(`${spec.key} ${label}`);
      const step = spec.type === "int" ? 1 : (range >= 20 ? 1 : 0.1);
      container.appendChild(buildSlider({
        label: label.replace(/\s*\(rpm\)/i, ""),
        variant: isSpeed ? "speed" : undefined,
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
    label: "",
    variant: "brightness",
    showValue: false,
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

/** @brief Muestra "Notas" solo en el modo calendario e "Imágenes" solo en el modo pixel art. */
function renderLinks() {
  const scene = activeScene();
  const icon = scene ? sceneIcon(scene) : null;
  const notes = $("notes-card");
  const images = $("images-card");
  if (notes) notes.hidden = icon !== "calendario";
  if (images) images.hidden = icon !== "pixelart";
}

/** @brief Dibuja toda la interfaz a partir del estado actual. */
function renderAll() {
  renderScenes();
  renderSettings();
  renderBrightness();
  renderLinks();
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

start()
