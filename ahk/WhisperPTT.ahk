; WhisperPTT — hold-to-talk dictation front-end.
; Owns the global hotkey, the on-screen recording indicator, typing the result
; into the focused window, and starting/stopping the Python backend.
;
; Protocol: localhost HTTP with plain-text bodies (see src/whisper_ptt/server.py).
;   POST /start -> begin recording        POST /stop -> transcribed text
;   GET  /ping  -> active device when ready (503 while the model loads)

#Requires AutoHotkey v2.0
#SingleInstance Force
Persistent

; ---------- locate root & config ----------
; Dev layout: this script lives in ahk\, config.ini in the parent.
; Installed layout: script/exe and config.ini side by side.
Root := FileExist(A_ScriptDir "\config.ini") ? A_ScriptDir
    : NormalizePath(A_ScriptDir "\..")
Ini := Root "\config.ini"
if !FileExist(Ini) {
    MsgBox "config.ini not found next to " A_ScriptDir, "WhisperPTT", "Iconx"
    ExitApp
}

HotkeyName := IniRead(Ini, "hotkey", "key", "RCtrl")
BaseUrl := "http://" IniRead(Ini, "server", "host", "127.0.0.1") ":" IniRead(Ini, "server", "port", "8765")
BackendCmd := IniRead(Ini, "backend", "command", "auto")
LogDir := Root "\" IniRead(Ini, "logging", "dir", "logs")

Recording := false
BackendPid := 0
IndGui := ""

; ---------- tray ----------
A_IconTip := "WhisperPTT — hold " HotkeyName " to dictate"
A_TrayMenu.Delete()
A_TrayMenu.Add("Backend status", ShowStatus)
A_TrayMenu.Add("Restart backend", RestartBackend)
A_TrayMenu.Add("Open log", (*) => Run('notepad.exe "' LogDir '\backend.log"'))
A_TrayMenu.Add("Edit config", (*) => Run('notepad.exe "' Ini '"'))
A_TrayMenu.Add()
A_TrayMenu.Add("Exit", (*) => ExitApp())

; ---------- startup ----------
OnExit(Cleanup)
EnsureBackend()
Hotkey "*" HotkeyName, StartDictation
Hotkey "*" HotkeyName " up", StopDictation
TrayTip "Hold " HotkeyName " to dictate", "WhisperPTT", "Mute"

; ---------- hotkey handlers ----------
StartDictation(*) {
    global Recording
    if Recording  ; ignore keyboard auto-repeat while held
        return
    Recording := true
    try {
        Http("POST", "/start", 3000)
        ShowIndicator("● REC")
    } catch as e {
        Recording := false
        Flash("WhisperPTT: backend not ready — " e.Message)
    }
}

StopDictation(*) {
    global Recording
    if !Recording
        return
    Recording := false
    ShowIndicator("… transcribing")
    text := ""
    try {
        text := Http("POST", "/stop", 120000)
    } catch as e {
        HideIndicator()
        Flash("WhisperPTT: transcription failed — " e.Message)
        return
    }
    HideIndicator()
    ; Newlines would be typed as Enter keypresses (submits chat inputs) —
    ; the backend already collapses them, this is defense in depth.
    text := Trim(RegExReplace(text, "[`r`n]+", " "))
    if (text != "")
        SendText text
    else
        Flash("WhisperPTT: nothing heard (discarded as silence — see logs)")
}

; ---------- backend lifecycle ----------
EnsureBackend() {
    global BackendPid
    if (PingStatus() = 200)
        return
    cmd := ResolveBackendCmd()
    Run cmd, Root, "Hide", &BackendPid
    ; First run can download the model and compile for NPU — allow minutes,
    ; but bail out early if the process dies (check logs\backend.log then).
    ShowIndicator("starting backend…")
    deadline := A_TickCount + 10 * 60000
    while (A_TickCount < deadline) {
        Sleep 500
        status := PingStatus()
        if (status = 200) {
            HideIndicator()
            return
        }
        if (status = 500 or (BackendPid and !ProcessExist(BackendPid)))
            break
        if (status = 503)
            ShowIndicator("loading model…")
    }
    HideIndicator()
    MsgBox "Backend failed to start. See " LogDir "\backend.log", "WhisperPTT", "Iconx"
}

ResolveBackendCmd() {
    if (BackendCmd != "auto")
        return BackendCmd
    exe := Root "\backend\whisper-ptt-backend.exe"
    if FileExist(exe)
        return '"' exe '"'
    pyw := Root "\.venv\Scripts\pythonw.exe"
    if FileExist(pyw)
        return '"' pyw '" -m whisper_ptt'
    MsgBox "No backend found.`nExpected " exe "`nor " pyw " (create the venv first).", "WhisperPTT", "Iconx"
    ExitApp
}

RestartBackend(*) {
    try Http("POST", "/shutdown", 3000)
    Sleep 1000
    EnsureBackend()
    ShowStatus()
}

ShowStatus(*) {
    status := PingStatus(&body)
    msg := (status = 200) ? "Ready — active device: " body
        : (status = 503) ? "Backend is still loading the model."
        : (status = -1) ? "Backend is not running."
        : "Backend error (" status "): " body
    TrayTip msg, "WhisperPTT", "Mute"
}

Cleanup(reason, code) {
    ; We own the backend: shut it down gracefully (no process killing).
    try Http("POST", "/shutdown", 2000)
}

; ---------- HTTP ----------
Http(method, path, timeoutMs) {
    req := ComObject("WinHttp.WinHttpRequest.5.1")
    req.Open(method, BaseUrl path, false)
    req.SetTimeouts(2000, 2000, 2000, timeoutMs)
    req.Send()
    if (req.Status != 200)
        throw Error("HTTP " req.Status " " req.ResponseText)
    return req.ResponseText
}

; Returns HTTP status of GET /ping, or -1 if the backend is unreachable.
PingStatus(&body := "") {
    try {
        req := ComObject("WinHttp.WinHttpRequest.5.1")
        req.Open("GET", BaseUrl "/ping", false)
        req.SetTimeouts(500, 500, 500, 1500)
        req.Send()
        body := req.ResponseText
        return req.Status
    } catch {
        body := ""
        return -1
    }
}

; ---------- indicator ----------
; Small always-on-top pill, bottom-center. WS_EX_NOACTIVATE so it never steals
; focus from the window receiving the dictated text.
ShowIndicator(text) {
    global IndGui
    if !IsObject(IndGui) {
        IndGui := Gui("+AlwaysOnTop -Caption +ToolWindow +E0x08000000")
        IndGui.BackColor := "1E1E1E"
        IndGui.SetFont("s11 Bold cFF4444", "Segoe UI")
        IndGui.MarginX := 14, IndGui.MarginY := 7
        IndGui.AddText("vTxt w180 Center", text)
    }
    IndGui["Txt"].Text := text
    IndGui.Show("NoActivate AutoSize Hide")
    IndGui.GetPos(,, &w, &h)
    IndGui.Show("NoActivate x" ((A_ScreenWidth - w) // 2) " y" (A_ScreenHeight - h - 90))
}

HideIndicator() {
    global IndGui
    if IsObject(IndGui)
        IndGui.Hide()
}

Flash(msg) {
    TrayTip msg, "WhisperPTT", "Mute"
}

NormalizePath(path) {
    len := DllCall("GetFullPathNameW", "Str", path, "UInt", 0, "Ptr", 0, "Ptr", 0, "UInt")
    buf := Buffer(len * 2)
    DllCall("GetFullPathNameW", "Str", path, "UInt", len, "Ptr", buf, "Ptr", 0, "UInt")
    return StrGet(buf)
}
