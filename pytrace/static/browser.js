

const STATE_DEAD = -1
const STATE_IDLE = 0
const STATE_RUNNING = 1
const STATE_WAIT = 2

const WS_CMD_STDIN = "WS_CMD_STDIN"
const WS_CMD_STDOUT = "WS_CMD_STDOUT"
const WS_CMD_START = "WS_CMD_START"
const WS_CMD_WAIT = "WS_CMD_WAIT"
const WS_CMD_STEP = "WS_CMD_STEP"
const WS_CMD_STOP = "WS_CMD_STOP"
const WS_CMD_STATE = "WS_CMD_STATE"
const WS_CMD_DATA = "WS_CMD_DATA"

const codeArea = document.getElementById("codeArea")
const terminalArea = document.getElementById("terminalArea");
const dataArea = document.getElementById("dataArea");
const startBtn = document.getElementById("startBtn");
const stepBtn = document.getElementById("stepBtn");
const stopBtn = document.getElementById("stopBtn");

let state = STATE_DEAD;
startBtn.disabled = false;
stepBtn.disabled = true;
stopBtn.disabled = true;
let variables = {};
let currLine = -1;
let visitedLines = new Set();
let ws = null;

const cm = CodeMirror.fromTextArea(codeArea, {
    mode: "python",
    lineNumbers: true,
    theme: "default",
    indentUnit: 4,
    tabSize: 4,
    indentWithTabs: false,
    lineWrapping: true,
    smartIndent: true,
    spellcheck: false,
    autocorrect: false,
    readOnly: false,
    extraKeys: {
        Tab: (cm) => cm.execCommand("indentMore"),
        "Shift-Tab": (cm) => cm.execCommand("indentLess"),
  },
});
cm.getWrapperElement().style.fontSize = "14px";
cm.setSize('100%', '100%');   // ensures .CodeMirror gets inline size

cm.refresh(); 

setupListeners();
connect();

function renderData(data) {
    const entries = Object.entries(data);

    entries.sort(([a], [b]) => a.localeCompare(b));

    const frag = document.createDocumentFragment();

    for (const [name, value] of entries) {
        let highlight = false;
        if (name in variables) {
            if (variables[name] !== value) {
                highlight = true;
            }
        } else {
            highlight = true;
        }

        const card = document.createElement("div");
        if (highlight) {
            card.className = "var-card var-changed"
        } else {
            card.className = "var-card"
        }
        card.setAttribute("role", "listitem");

        const key = document.createElement("div");
        key.className = "var-key";
        key.textContent = name;

        const val = document.createElement("div");
        val.className = "var-val";
        val.textContent = String(value);

        card.appendChild(key);
        card.appendChild(val);
        frag.appendChild(card);
        variables[name] = value;
    }
    dataArea.innerHTML = "";
    dataArea.appendChild(frag);

}

function renderCodeHighlights(line_number) {
    if (currLine != -1) {
        cm.removeLineClass(currLine, "background", "code-current")
        cm.addLineClass(currLine, "background", "code-visited")
    }
    currLine = line_number - 1;
    if (visitedLines.has(currLine)) {
        cm.removeLineClass(currLine, "background", "code-visited");
    }
    cm.addLineClass(currLine, "background", "code-current");
    visitedLines.add(currLine);
}

function clearCodeHighlights() {
    for (const value of visitedLines) {
        if (currLine == value) {
            cm.removeLineClass(value, "background", "code-current")
        } else {
            cm.removeLineClass(value, "background", "code-visited")
        }
    }
    currLine = -1;
    visitedLines = new Set();
}

function connect() {
    ws = new WebSocket(`ws://${location.host}/ws`);
    ws.onopen = () => {
        terminalArea.value += "\n--- CONNECTED TO SERVER ---\n";
        requestAnimationFrame(() => moveCaretToEnd(terminalArea));
        state = STATE_IDLE;
        startBtn.disabled = false;
        stepBtn.disabled = true;
        stopBtn.disabled = true;
    }
    ws.onclose = () => {
        if (state != STATE_DEAD) {
            terminalArea.value += "\n--- SERVER IS DOWN ---\n"
            requestAnimationFrame(() => moveCaretToEnd(terminalArea));
        }
        state = STATE_DEAD
        startBtn.disabled = true;
        stepBtn.disabled = true;
        stopBtn.disabled = true;
        setTimeout(connect, 3000);
    }
    ws.onerror = () => {
        ws.close();
    }
    ws.onmessage = (event) => {
        handle_ws(event);
    }
}

function handle_ws(event) {
    let data;

    try {
        data = JSON.parse(event.data);
    } catch (_) {
        console.log("ERROR: Expected JSON => ", event.data);
        return;
    }

    if (!("CMD" in data)) {
        console.log("ERROR: Missing CMD parameter => ", data);
        return;
    }

    if (!("CONTENT" in data)) {
        console.log("ERROR: Missing CONTENT parameter => ", data);
        return;
    }

    console.log(">CMD: ",data.CMD," CONTENT: ",data.CONTENT);
    switch (data.CMD) {
        case WS_CMD_STDOUT:
            terminalArea.value += data.CONTENT.TEXT;
            requestAnimationFrame(() => moveCaretToEnd(terminalArea));
            break;

        case WS_CMD_STATE:
            if (data.CONTENT.STATE === STATE_IDLE) {
                startBtn.disabled = false;
                stepBtn.disabled = true;
                stopBtn.disabled = true;
                clearCodeHighlights()
                cm.setOption("readOnly", false);
            } else if (data.CONTENT.STATE === STATE_RUNNING) {
                startBtn.disabled = true;
                stepBtn.disabled = true;
                stopBtn.disabled = false;
                cm.setOption("readOnly", "nocursor");
            } else if (data.CONTENT.STATE === STATE_WAIT) {
                startBtn.disabled = true;
                stepBtn.disabled = false;
                stopBtn.disabled = false;
                cm.setOption("readOnly", "nocursor");
            } else {
                console.log("ERROR: Invalid state => ", data.CONTENT.STATE);
                return;
            }
            state = data.CONTENT.STATE;
            break;

        case WS_CMD_DATA:
            renderData(data.CONTENT.variables);
            renderCodeHighlights(data.CONTENT.line);
            break;

        default:
            console.log("ERROR: Invalid Command => ", data.CMD);
    }
}

function moveCaretToEnd(el) {
    el.focus();
    const len = el.value.length;
    el.setSelectionRange(len, len);
    el.scrollTop = el.scrollHeight;
}

function setupListeners() {
    // terminalArea.addEventListener("focus", () => moveCaretToEnd(terminalArea));
    // terminalArea.addEventListener("mouseup", () => requestAnimationFrame(() => moveCaretToEnd(terminalArea)));
    // terminalArea.addEventListener("keydown", () => requestAnimationFrame(() => moveCaretToEnd(terminalArea)));

    terminalArea.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
            event.preventDefault();
            ws_send(WS_CMD_STDIN, {"TEXT" : "\n"});
        }
    });

    terminalArea.addEventListener("beforeinput", (event) => {
        event.preventDefault();
        if (event.inputType === "insertText" || event.inputType === "insertFromPaste") {
            if (event.data != null) {
                ws_send(WS_CMD_STDIN, {"TEXT" : event.data});
            }
        } else if (event.inputType === "insertLineBreak") {
            ws_send(WS_CMD_STDIN, {"TEXT" : "\n"});
        }
    });

    stopBtn.addEventListener("click", () => ws_send(WS_CMD_STOP, {}));
    startBtn.addEventListener("click", () => ws_send(WS_CMD_START, {"CODE" : cm.getValue()}));
    stepBtn.addEventListener("click", () => ws_send(WS_CMD_STEP, {}));
}

function ws_send(command, content) {
    if (ws != null) {
        ws.send(JSON.stringify({ "CMD": command, "CONTENT" : content }));
        console.log("<CMD: ",command," CONTENT: ",content);
    } else {
        console.log("ERROR: Tried to call ws.send while ws in null.");
    }
}

