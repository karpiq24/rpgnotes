// RPG Notes Recorder — records a session for the rpgnotes pipeline.
//
// Runs only in the active GM's browser. The GM starts and stops it (token
// controls toggle, /rpgnotes chat command or the module API); the module only
// suggests: starting when players connect, saving when the world is shut down
// or the GM logs out. The recording is saved as session<NN>.json, a browser
// download, so it lands in the Downloads folder rpgnotes reads. Everything is
// kept in IndexedDB while recording, so a reload or a crash loses nothing.
// Chat command: /rpgnotes [status|start|stop|key|discard|number N].

const MODULE_ID = "rpgnotes-recorder";
const FORMAT = "rpgnotes-foundry";
const FORMAT_VERSION = 1;

const STALE_SESSION_MS = 30 * 60 * 1000; // unfinished recording found on load
const START_PROMPT_COOLDOWN_MS = 15 * 60 * 1000; // after "Not now"
const DOWNLOAD_SETTLE_MS = 1500; // let the download start before leaving the page
const SCENE_SETTLE_MS = 3000; // let textures load before the scene snapshot
const SNAPSHOT_MAX_DIM = 1600;
const SNAPSHOT_QUALITY = 0.8;
const DEDUPE_THRESHOLD = 3; // mean abs grayscale diff (0-255) on a 32x32 thumbnail
const SIGNATURE_SIZE = 32;
const MAX_TEXT_CHARS = 500; // chat text; spell/feature cards are cut here
const MAX_JOURNAL_CHARS = 2000;
const NOISE_SPEAKERS = new Set(["Tidbits"]);
const NOISE_FLAGS = ["tidbits"];
const NOISE_TEXT = ["Welcome to Plutonium"];

const state = {
  db: null,
  session: null, // {number, startedAt, worldTimeStart}
  snapshotTimer: null,
  lastSignature: null,
  promptOpen: false,
  lastStartPrompt: 0,
};

// --------------------------------------------------------------------------
// Storage (IndexedDB, one database per world)
// --------------------------------------------------------------------------

function openDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(`${MODULE_ID}-${game.world.id}`, 1);
    request.onupgradeneeded = () => {
      const db = request.result;
      db.createObjectStore("meta");
      db.createObjectStore("events", { autoIncrement: true });
      db.createObjectStore("snapshots", { autoIncrement: true });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function withStore(name, mode, fn) {
  return new Promise((resolve, reject) => {
    const transaction = state.db.transaction(name, mode);
    const request = fn(transaction.objectStore(name));
    transaction.oncomplete = () => resolve(request?.result);
    transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () => reject(transaction.error);
  });
}

const dbGetAll = (name) => withStore(name, "readonly", (store) => store.getAll());
const dbCount = (name) => withStore(name, "readonly", (store) => store.count());
const dbAdd = (name, value) => withStore(name, "readwrite", (store) => store.add(value));
const dbPut = (name, value, key) => withStore(name, "readwrite", (store) => store.put(value, key));
const dbClear = (name) => withStore(name, "readwrite", (store) => store.clear());

function dbLastEvent() {
  return withStore("events", "readonly", (store) => store.openCursor(null, "prev")).then(
    (cursor) => cursor?.value ?? null
  );
}

// --------------------------------------------------------------------------
// Helpers
// --------------------------------------------------------------------------

const setting = (key) => game.settings.get(MODULE_ID, key);
const activePlayers = () => game.users.filter((user) => user.active && !user.isGM);
const isRecorder = () => game.user.isGM && (game.users.activeGM?.isSelf ?? true);
const iso = (ms) => new Date(ms).toISOString();

function notify(message, level = "info") {
  ui.notifications?.[level](`rpgnotes: ${message}`);
}

/** A dialog with `buttons` ([{action, label, icon}], the first is the default). Resolves to the action, or null. */
async function ask(content, buttons) {
  state.promptOpen = true;
  try {
    return await foundry.applications.api.DialogV2.wait({
      window: { title: "RPG Notes Recorder", icon: "fa-solid fa-circle-dot" },
      content: `<p>${content}</p>`,
      buttons: buttons.map((button, index) => ({ ...button, default: index === 0 })),
      position: { width: 440 },
    });
  } finally {
    state.promptOpen = false;
  }
}

function refreshControls() {
  ui.controls?.render({ reset: true });
}

function safe(fn) {
  try {
    return fn();
  } catch {
    return undefined;
  }
}

function plainText(html, limit = MAX_TEXT_CHARS) {
  if (!html) return "";
  // DOMParser does not load images or run scripts, unlike innerHTML on a live node.
  // The space before each tag keeps "Cure Wounds</h3><p>1st Level" from gluing together.
  const spaced = String(html).replace(/</g, " <");
  const text = new DOMParser().parseFromString(spaced, "text/html").body.textContent ?? "";
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > limit ? `${flat.slice(0, limit - 1)}…` : flat;
}

function compact(object) {
  return Object.fromEntries(
    Object.entries(object).filter(
      ([, value]) => value !== undefined && value !== null && value !== "" && !(Array.isArray(value) && !value.length)
    )
  );
}

function formatDuration(ms) {
  const minutes = Math.round(ms / 60000);
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

async function record(event) {
  if (!state.session) return;
  await dbAdd("events", { t: Date.now(), ...compact(event) });
}

// --------------------------------------------------------------------------
// Snapshots of the map canvas (no browser or Foundry UI on them)
// --------------------------------------------------------------------------

function renderCanvas() {
  const hideHidden = setting("hideHiddenTokens");
  const hidden = hideHidden ? canvas.tokens.placeables.filter((token) => token.document.hidden) : [];
  const restore = hidden.flatMap((token) => [token, token.mesh].filter(Boolean).map((obj) => [obj, obj.visible]));
  for (const [obj] of restore) obj.visible = false;
  try {
    canvas.app.renderer.render(canvas.stage);
    return canvas.app.renderer.extract.canvas();
  } finally {
    for (const [obj, visible] of restore) obj.visible = visible;
  }
}

function downscale(source, maxDim = SNAPSHOT_MAX_DIM) {
  const scale = Math.min(1, maxDim / Math.max(source.width, source.height));
  const target = document.createElement("canvas");
  target.width = Math.max(1, Math.round(source.width * scale));
  target.height = Math.max(1, Math.round(source.height * scale));
  target.getContext("2d").drawImage(source, 0, 0, target.width, target.height);
  return target;
}

function signature(source) {
  const thumb = document.createElement("canvas");
  thumb.width = thumb.height = SIGNATURE_SIZE;
  const context = thumb.getContext("2d", { willReadFrequently: true });
  context.drawImage(source, 0, 0, SIGNATURE_SIZE, SIGNATURE_SIZE);
  const pixels = context.getImageData(0, 0, SIGNATURE_SIZE, SIGNATURE_SIZE).data;
  const gray = new Uint8Array(SIGNATURE_SIZE * SIGNATURE_SIZE);
  for (let i = 0; i < gray.length; i++) {
    gray[i] = (pixels[i * 4] + pixels[i * 4 + 1] + pixels[i * 4 + 2]) / 3;
  }
  return gray;
}

function meanDiff(a, b) {
  let total = 0;
  for (let i = 0; i < a.length; i++) total += Math.abs(a[i] - b[i]);
  return total / a.length;
}

function toBlob(source) {
  return new Promise((resolve, reject) =>
    source.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error("image encoding failed"))),
      "image/webp",
      SNAPSHOT_QUALITY
    )
  );
}

async function storeSnapshot(source, fields) {
  const image = downscale(source);
  await dbAdd("snapshots", { t: Date.now(), ...compact(fields), blob: await toBlob(image) });
}

/** Snapshot of what the players see. Skipped while the GM looks at an inactive scene. */
async function snapshot(reason, { key = false } = {}) {
  if (!state.session || !canvas?.ready || !canvas.scene?.active) return false;
  try {
    const source = renderCanvas();
    const current = signature(source);
    if (reason === "interval" && state.lastSignature && meanDiff(current, state.lastSignature) < DEDUPE_THRESHOLD) {
      return false;
    }
    state.lastSignature = current;
    await storeSnapshot(source, { reason, key, scene: canvas.scene.name });
    return true;
  } catch (error) {
    console.warn(`${MODULE_ID} | snapshot failed`, error);
    return false;
  }
}

/** A handout image shown to the players, stored as a key frame. */
async function snapshotImage(src, title) {
  if (!state.session || !src) return;
  try {
    const image = new Image();
    image.crossOrigin = "anonymous";
    image.src = src;
    await image.decode();
    const source = document.createElement("canvas");
    source.width = image.naturalWidth;
    source.height = image.naturalHeight;
    source.getContext("2d").drawImage(image, 0, 0);
    await storeSnapshot(source, { reason: "handout", key: true, title });
  } catch (error) {
    console.warn(`${MODULE_ID} | could not store handout image ${src}`, error);
  }
}

function startSnapshotTimer() {
  clearInterval(state.snapshotTimer);
  const minutes = Number(setting("snapshotMinutes"));
  if (minutes > 0) state.snapshotTimer = setInterval(() => snapshot("interval"), minutes * 60000);
}

// --------------------------------------------------------------------------
// Session lifecycle
// --------------------------------------------------------------------------

async function start({ manual = false } = {}) {
  if (state.session) return;
  state.session = {
    number: Number(setting("sessionNumber")),
    startedAt: Date.now(),
    worldTimeStart: game.time.worldTime,
  };
  state.lastSignature = null;
  await dbPut("meta", state.session, "session");
  await record({ kind: "session_start", manual: manual || undefined });
  for (const user of activePlayers()) await record(playerEvent(user, true));
  if (game.scenes.active) await record({ kind: "scene", scene: game.scenes.active.name });
  startSnapshotTimer();
  setTimeout(() => snapshot("start"), 1000);
  refreshControls();
  notify(`recording session ${state.session.number}. "/rpgnotes" in chat shows the status.`);
}

function stopTimers() {
  clearInterval(state.snapshotTimer);
  state.snapshotTimer = null;
}

async function resetStorage() {
  await Promise.all([dbClear("events"), dbClear("snapshots"), dbClear("meta")]);
  state.session = null;
  state.lastSignature = null;
}

async function discard() {
  if (!state.session) return;
  const { number } = state.session;
  stopTimers();
  await resetStorage();
  refreshControls();
  notify(`recording of session ${number} discarded.`);
}

async function finish() {
  if (!state.session) return;
  stopTimers();
  const { number, startedAt } = state.session;
  const duration = Date.now() - startedAt;
  await record({ kind: "session_end" });
  const data = await buildExport();
  const filename = `session${number}.json`;
  foundry.utils.saveDataToFile(JSON.stringify(data), "application/json", filename);
  await game.settings.set(MODULE_ID, "sessionNumber", number + 1);
  await resetStorage();
  refreshControls();
  notify(
    `session ${number} saved as ${filename} (${formatDuration(duration)}, ${data.events.length} events, ` +
      `${data.snapshots.length} snapshots). Next session: ${number + 1}.`
  );
  if (setting("offerClearChat")) await offerClearChat();
}

/** Suggest starting when enough players are connected; "Not now" mutes it for a while. */
async function suggestStart() {
  if (state.session || state.promptOpen || !setting("suggestStart")) return;
  const players = activePlayers();
  if (players.length < Number(setting("minPlayers"))) return;
  if (Date.now() - state.lastStartPrompt < START_PROMPT_COOLDOWN_MS) return;
  state.lastStartPrompt = Date.now();
  const names = players.map((user) => user.character?.name ?? user.name).join(", ");
  const choice = await ask(`${players.length} players are connected (${names}). Start recording session ${setting("sessionNumber")}?`, [
    { action: "start", label: "Start recording", icon: "fa-solid fa-circle-dot" },
    { action: "later", label: "Not now", icon: "fa-solid fa-clock" },
  ]);
  if (choice === "start") await start();
}

/** Before the GM leaves the world: save, leave the recording for later, or stay. Resolves to false to stay. */
async function offerSaveBeforeLeaving(leaving) {
  if (!isRecorder() || !state.session) return true;
  const { number, startedAt } = state.session;
  const choice = await ask(
    `Session ${number} has been recorded for ${formatDuration(Date.now() - startedAt)}. Save it before you ${leaving}?`,
    [
      { action: "save", label: `Save and ${leaving}`, icon: "fa-solid fa-floppy-disk" },
      { action: "keep", label: "Keep recording for later", icon: "fa-solid fa-pause" },
      { action: "stay", label: "Cancel", icon: "fa-solid fa-xmark" },
    ]
  );
  if (choice === "save") {
    await finish();
    await new Promise((resolve) => setTimeout(resolve, DOWNLOAD_SETTLE_MS));
  }
  return choice === "save" || choice === "keep";
}

async function offerClearChat() {
  const confirmed = await foundry.applications.api.DialogV2.confirm({
    window: { title: "RPG Notes Recorder" },
    content: "<p>The session is saved. Clear the chat log now?</p>",
  });
  if (confirmed) await ChatMessage.implementation.deleteDocuments([], { deleteAll: true });
}

function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

async function buildExport() {
  const [events, snapshots] = await Promise.all([dbGetAll("events"), dbGetAll("snapshots")]);
  const { number, startedAt, worldTimeStart } = state.session;
  const players = {};
  for (const event of events) {
    if (event.kind === "player_join") players[event.user] = event.character ?? null;
  }
  return {
    format: FORMAT,
    version: FORMAT_VERSION,
    title: `session${number}`,
    archiveDate: new Date(startedAt).toLocaleDateString("sv-SE"), // YYYY-MM-DD, local
    session: number,
    world: game.world.title,
    foundry: game.version,
    system: `${game.system.id} ${game.system.version}`,
    startedAt: iso(startedAt),
    endedAt: iso(Date.now()),
    gameTime: { start: worldTimeStart, end: game.time.worldTime },
    players: Object.entries(players).map(([user, character]) => compact({ user, character })),
    events: events.map((event) => ({ ...event, t: iso(event.t) })),
    snapshots: await Promise.all(
      snapshots.map(async ({ t, blob, ...rest }) => ({ t: iso(t), ...rest, data: await blobToDataUrl(blob) }))
    ),
  };
}

async function status() {
  if (!state.session) {
    notify(`not recording. Next session: ${setting("sessionNumber")}. "/rpgnotes start" starts now.`);
    return;
  }
  const [events, snapshots] = await Promise.all([dbCount("events"), dbCount("snapshots")]);
  notify(
    `recording session ${state.session.number} for ${formatDuration(Date.now() - state.session.startedAt)}: ` +
      `${events} events, ${snapshots} snapshots. "/rpgnotes stop" saves it now.`
  );
}

// --------------------------------------------------------------------------
// Events
// --------------------------------------------------------------------------

function playerEvent(user, joined) {
  return { kind: joined ? "player_join" : "player_leave", user: user.name, character: user.character?.name };
}

function messageEvent(message) {
  if (NOISE_SPEAKERS.has(message.alias) || NOISE_FLAGS.some((flag) => message.flags?.[flag])) return null;
  if (NOISE_TEXT.some((marker) => String(message.content ?? "").includes(marker))) return null;
  const rolls = message.rolls.map((roll) =>
    compact({
      formula: roll.formula,
      total: roll.total,
      critical: roll.isCritical || undefined,
      fumble: roll.isFumble || undefined,
      target: roll.options?.target,
      damageType: roll.options?.type,
    })
  );
  const type = message.type === "base" ? (rolls.length ? "roll" : "chat") : message.type;
  // Roll and usage cards repeat the dice markup or the whole item description;
  // the structured fields carry what matters.
  const text = rolls.length || type === "usage" ? "" : plainText(message.content);
  const style = Object.entries(CONST.CHAT_MESSAGE_STYLES ?? {}).find(([, value]) => value === message.style)?.[0];
  const event = compact({
    kind: "chat",
    type,
    style: style?.toLowerCase(),
    speaker: message.alias,
    actor: safe(() => message.getAssociatedActor?.()?.name),
    user: (message.author ?? message.user)?.name,
    whisperTo: message.whisper.map((id) => game.users.get(id)?.name).filter(Boolean),
    blind: message.blind || undefined,
    flavor: plainText(message.flavor, 300),
    text,
    item: safe(() => message.getAssociatedItem?.()?.name),
    activity: safe(() => message.getAssociatedActivity?.()?.name),
    rolls,
  });
  return event.text || event.rolls || event.item || event.flavor ? event : null;
}

function registerHooks() {
  Hooks.on("userConnected", async (user, connected) => {
    if (!isRecorder() || user.isGM) return;
    if (!state.session) {
      if (connected) suggestStart();
      return;
    }
    record(playerEvent(user, connected));
    // Players often keep the tab open after the game, so this is rare; the
    // usual end is the save prompt when the world is shut down.
    if (connected || activePlayers().length || state.promptOpen) return;
    const choice = await ask(`All players left. Save session ${state.session.number} now?`, [
      { action: "save", label: "Save session", icon: "fa-solid fa-floppy-disk" },
      { action: "keep", label: "Keep recording", icon: "fa-solid fa-circle-dot" },
    ]);
    if (choice === "save") await finish();
  });

  Hooks.on("getSceneControlButtons", (controls) => {
    const tokens = controls.tokens;
    if (!game.user.isGM || !tokens?.tools) return;
    tokens.tools.rpgnotes = {
      name: "rpgnotes",
      order: 100,
      title: state.session ? `Recording session ${state.session.number}: click to save` : "Start recording the session (rpgnotes)",
      icon: "fa-solid fa-circle-dot",
      toggle: true,
      active: Boolean(state.session),
      onChange: () => (state.session ? command("stop") : command("start")),
    };
  });

  Hooks.on("createChatMessage", (message) => {
    if (!isRecorder() || !state.session) return;
    const event = messageEvent(message);
    if (event) record(event);
  });

  Hooks.on("updateScene", (scene, changes) => {
    if (!isRecorder() || !state.session || changes.active !== true) return;
    record({ kind: "scene", scene: scene.name });
  });

  Hooks.on("canvasReady", () => {
    if (!isRecorder() || !state.session) return;
    state.lastSignature = null;
    setTimeout(() => snapshot("scene"), SCENE_SETTLE_MS);
  });

  const visibleCombatants = (combat) =>
    combat.combatants.filter((combatant) => !combatant.hidden).map((combatant) => combatant.name);

  Hooks.on("combatStart", (combat) => {
    if (!isRecorder() || !state.session) return;
    record({ kind: "combat_start", combatants: visibleCombatants(combat) });
    snapshot("combat", { key: true });
  });

  Hooks.on("combatRound", (combat, updateData) => {
    if (!isRecorder() || !state.session) return;
    record({ kind: "combat_round", round: updateData.round });
  });

  Hooks.on("combatTurn", (combat, updateData) => {
    if (!isRecorder() || !state.session) return;
    const combatant = combat.turns[updateData.turn];
    if (combatant && !combatant.hidden) record({ kind: "combat_turn", round: updateData.round, combatant: combatant.name });
  });

  Hooks.on("deleteCombat", (combat) => {
    if (!isRecorder() || !state.session || !combat.started) return;
    record({ kind: "combat_end", rounds: combat.round });
  });

  // Linked actors report HP on the actor, unlinked tokens (most monsters) on
  // the token's delta; both may fire for one hit, so repeats are ignored.
  const recentlyDown = new Map();
  const recordDown = (name, type, hidden) => {
    if (!isRecorder() || !state.session || hidden) return;
    const now = Date.now();
    if (now - (recentlyDown.get(name) ?? 0) < 5000) return;
    recentlyDown.set(name, now);
    record({ kind: "down", actor: name, type });
  };
  Hooks.on("updateActor", (actor, changes) => {
    if (foundry.utils.getProperty(changes, "system.attributes.hp.value") !== 0) return;
    recordDown(actor.token?.name ?? actor.name, actor.type, actor.token?.hidden);
  });
  Hooks.on("updateToken", (token, changes) => {
    if (foundry.utils.getProperty(changes, "delta.system.attributes.hp.value") !== 0) return;
    recordDown(token.name, token.actor?.type, token.hidden);
  });

  Hooks.on("updatePlaylistSound", (sound, changes) => {
    if (!isRecorder() || !state.session || changes.playing !== true) return;
    record({ kind: "music", track: sound.name, playlist: sound.parent?.name });
  });

  Hooks.on("chatMessage", (_chatLog, message) => {
    const match = message.trim().match(/^\/rpgnotes\b\s*(\S*)\s*(.*)$/i);
    if (!match) return;
    if (game.user.isGM) command(match[1].toLowerCase(), match[2].trim());
    return false; // never post the command itself
  });
}

function wrapHandouts() {
  const ImagePopout = foundry.applications.apps.ImagePopout;
  const shareImage = ImagePopout.prototype.shareImage;
  ImagePopout.prototype.shareImage = function (...args) {
    if (isRecorder() && state.session) {
      const title = this.options?.caption || this.title;
      record({ kind: "handout", title, src: this.options?.src });
      snapshotImage(this.options?.src, title);
    }
    return shareImage.apply(this, args);
  };

  const Journal = foundry.documents.collections.Journal;
  const show = Journal.show;
  Journal.show = function (entry, options) {
    if (isRecorder() && state.session && entry) {
      const page = entry.documentName === "JournalEntryPage" ? entry : null;
      record({
        kind: "journal",
        title: page ? `${page.parent?.name}: ${page.name}` : entry.name,
        text: page?.type === "text" ? plainText(page.text?.content, MAX_JOURNAL_CHARS) : undefined,
      });
      if (page?.type === "image") snapshotImage(page.src, page.name);
    }
    return show.call(this, entry, options);
  };
}

async function command(name, argument) {
  switch (name) {
    case "":
    case "status":
      return status();
    case "start":
      return state.session ? status() : start({ manual: true });
    case "stop":
    case "save": {
      if (!state.session) return status();
      const choice = await ask(`Save session ${state.session.number} and stop recording?`, [
        { action: "save", label: "Save session", icon: "fa-solid fa-floppy-disk" },
        { action: "keep", label: "Keep recording", icon: "fa-solid fa-circle-dot" },
      ]);
      if (choice === "save") return finish();
      return refreshControls(); // undo the toggle's visual state
    }
    case "key":
      if (await snapshot("manual", { key: true })) notify("key moment saved.");
      else notify("no recording, or this scene is not the active one.", "warn");
      return;
    case "discard":
      return discard();
    case "number": {
      const number = Number.parseInt(argument, 10);
      if (!Number.isFinite(number) || number < 1) return notify("usage: /rpgnotes number 85", "warn");
      await game.settings.set(MODULE_ID, "sessionNumber", number);
      if (state.session) {
        state.session.number = number;
        await dbPut("meta", state.session, "session");
      }
      return notify(`session number set to ${number}.`);
    }
    default:
      return notify("commands: status, start, stop, key, discard, number N.", "warn");
  }
}

// --------------------------------------------------------------------------
// Boot
// --------------------------------------------------------------------------

function registerSettings() {
  const world = (key, name, hint, type, defaultValue) =>
    game.settings.register(MODULE_ID, key, { name, hint, scope: "world", config: true, type, default: defaultValue });
  world("sessionNumber", "Next session number", "Used for the file name (session85.json). Goes up by one after each save.", Number, 1);
  world("suggestStart", "Suggest starting", "Ask whether to start recording when enough players are connected.", Boolean, true);
  world("minPlayers", "Players for the suggestion", "Connected players (not counting the GM) before it asks.", Number, 4);
  world("snapshotMinutes", "Map snapshot every (minutes)", "Plus one on every scene change and combat start. 0 = only those.", Number, 10);
  world("hideHiddenTokens", "Hide GM-only tokens in snapshots", "Snapshots then show the map as the players see it.", Boolean, true);
  world("offerClearChat", "Offer to clear the chat after saving", "A long chat log slows Foundry down.", Boolean, true);
}

async function resume() {
  state.session = await withStore("meta", "readonly", (store) => store.get("session"));
  if (!state.session) return;
  const last = await dbLastEvent();
  const lastAt = last?.t ?? state.session.startedAt;
  if (Date.now() - lastAt > STALE_SESSION_MS) {
    const { number, startedAt } = state.session;
    const when = new Date(startedAt).toLocaleString();
    const choice = await ask(
      `An unsaved recording of session ${number} was found (started ${when}, ${formatDuration(lastAt - startedAt)}).`,
      [
        { action: "save", label: "Save it now", icon: "fa-solid fa-floppy-disk" },
        { action: "continue", label: "Continue recording", icon: "fa-solid fa-circle-dot" },
        { action: "discard", label: "Discard", icon: "fa-solid fa-trash" },
      ]
    );
    if (choice === "save") return finish();
    if (choice === "discard") return discard();
  }
  startSnapshotTimer();
  refreshControls();
  notify(`recording session ${state.session.number} (resumed).`);
}

function wrapLeaving() {
  const shutDown = game.shutDown.bind(game);
  game.shutDown = async (...args) => ((await offerSaveBeforeLeaving("shut down")) ? shutDown(...args) : undefined);
  const logOut = game.logOut.bind(game);
  game.logOut = async (...args) => ((await offerSaveBeforeLeaving("log out")) ? logOut(...args) : undefined);
}

Hooks.once("init", () => {
  registerSettings();
  registerHooks();
  wrapHandouts();
});

Hooks.once("ready", async () => {
  if (!isRecorder()) return;
  state.db = await openDb();
  wrapLeaving();
  game.modules.get(MODULE_ID).api = { start, stop: finish, discard, status, snapshot, buildExport };
  await resume();
  await suggestStart();
});
