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
Busy := false  ; true while a previous utterance is still being typed
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
    if (Recording or Busy)  ; auto-repeat, or still typing the last utterance
        return
    Recording := true
    try {
        Http("POST", "/start", 3000)
        WaveShow("rec")
    } catch as e {
        Recording := false
        Flash("WhisperPTT: backend not ready — " e.Message)
    }
}

StopDictation(*) {
    global Recording, Busy
    if !Recording
        return
    Recording := false
    Busy := true
    WaveShow("proc")
    try req := HttpReq("POST", "/stop", 120000)
    catch as e {
        Busy := false
        WaveHide()
        Flash("WhisperPTT: transcription failed — " e.Message)
        return
    }
    if (req.Status = 200) {
        ; Short/cleanup-less utterance: final text inline.
        WaveHide()
        ; Newlines would be typed as Enter keypresses (submits chat inputs) —
        ; the backend already collapses them, this is defense in depth.
        text := Trim(RegExReplace(req.ResponseText, "[`r`n]+", " "))
        if (text != "")
            SendText text
        else
            Flash("WhisperPTT: nothing heard (discarded as silence — see logs)")
    } else if (req.Status = 202) {
        StreamDeltas()  ; LLM is generating — type words as they arrive
    } else {
        WaveHide()
        Flash("WhisperPTT: error " req.Status " — " req.ResponseText)
    }
    Busy := false
}

; Poll /delta and type each increment. The cleaned text is generated
; left-to-right and never revised, so append-only typing is safe.
StreamDeltas() {
    typed := false
    deadline := A_TickCount + 90000
    while (A_TickCount < deadline) {
        try r := HttpReq("GET", "/delta", 5000)
        catch
            break
        if (r.Status != 200)
            break
        ; Strip CR/LF only — no Trim, interior chunk spacing matters.
        chunk := RegExReplace(r.ResponseText, "[`r`n]+", " ")
        if (chunk != "") {
            if !typed {
                WaveHide()  ; words are landing — get out of the way
                typed := true
            }
            SendText chunk
        }
        done := "0"
        try done := r.GetResponseHeader("X-Done")
        if (done = "1")
            break
        Sleep 80
    }
    WaveHide()
    if !typed
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
HttpReq(method, path, timeoutMs) {
    req := ComObject("WinHttp.WinHttpRequest.5.1")
    req.Open(method, BaseUrl path, false)
    req.SetTimeouts(2000, 2000, 2000, timeoutMs)
    req.Send()
    return req
}

Http(method, path, timeoutMs) {
    req := HttpReq(method, path, timeoutMs)
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

; ---------- status text indicator (backend startup messages only) ----------
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

; ---------- waveform overlay (recording / transcribing) ----------
; Wispr-Flow-inspired but quieter: a small translucent pill, bottom-center,
; with capsule bars that move with the actual mic level (GET /level) while
; recording, and settle into a gentle cool-toned idle wave while the LLM
; works. GDI+ layered window: per-pixel alpha, no chrome, never activates.
global Wave := {hwnd: 0, gui: 0, w: 84, h: 30, mode: "", level: 0.0, smooth: 0.0, t: 0.0,
    hdc: 0, hbm: 0, obm: 0, gfx: 0, token: 0}

WaveShow(mode) {
    global Wave
    if !Wave.hwnd
        WaveInit()
    Wave.mode := mode
    if (mode = "rec")
        Wave.smooth := 0.0
    x := (A_ScreenWidth - Wave.w) // 2
    y := A_ScreenHeight - Wave.h - 76
    ; HWND_TOPMOST, SWP_NOACTIVATE | SWP_SHOWWINDOW
    DllCall("SetWindowPos", "Ptr", Wave.hwnd, "Ptr", -1,
        "Int", x, "Int", y, "Int", Wave.w, "Int", Wave.h, "UInt", 0x50)
    SetTimer WaveFrame, 40
    WaveFrame()
}

WaveHide() {
    global Wave
    SetTimer WaveFrame, 0
    if Wave.hwnd
        DllCall("ShowWindow", "Ptr", Wave.hwnd, "Int", 0)  ; SW_HIDE
}

WaveInit() {
    global Wave
    g := Gui("+AlwaysOnTop -Caption +ToolWindow +E0x80000 +E0x08000000")  ; layered + noactivate
    g.Show("NA x0 y0 w" Wave.w " h" Wave.h)
    DllCall("ShowWindow", "Ptr", g.Hwnd, "Int", 0)
    Wave.gui := g
    Wave.hwnd := g.Hwnd
    si := Buffer(24, 0)
    NumPut("UInt", 1, si)
    token := 0
    DllCall("gdiplus\GdiplusStartup", "Ptr*", &token, "Ptr", si, "Ptr", 0)
    Wave.token := token
    bi := Buffer(40, 0)
    NumPut("UInt", 40, bi, 0)
    NumPut("Int", Wave.w, bi, 4)
    NumPut("Int", -Wave.h, bi, 8)   ; top-down DIB
    NumPut("UShort", 1, bi, 12)
    NumPut("UShort", 32, bi, 14)
    bits := 0
    Wave.hbm := DllCall("CreateDIBSection", "Ptr", 0, "Ptr", bi, "UInt", 0, "Ptr*", &bits, "Ptr", 0, "UInt", 0, "Ptr")
    Wave.hdc := DllCall("CreateCompatibleDC", "Ptr", 0, "Ptr")
    Wave.obm := DllCall("SelectObject", "Ptr", Wave.hdc, "Ptr", Wave.hbm, "Ptr")
    gfx := 0
    DllCall("gdiplus\GdipCreateFromHDC", "Ptr", Wave.hdc, "Ptr*", &gfx)
    Wave.gfx := gfx
    DllCall("gdiplus\GdipSetSmoothingMode", "Ptr", gfx, "Int", 4)  ; antialias
}

WaveFrame() {
    global Wave
    static n := 0
    Wave.t += 0.04
    n += 1
    if (Wave.mode = "rec" && Mod(n, 3) = 0) {  ; poll mic level ~every 120ms
        try Wave.level := Number(Http("GET", "/level", 1000))
        catch
            Wave.level := 0.0
    }
    ; Map mic RMS to 0..1 — divisor tuned so normal speech on this mic hits
    ; the upper range (measured speech rms ~0.008-0.014); idle wave otherwise.
    target := (Wave.mode = "rec") ? Min(1.0, Wave.level / 0.011) : 0.30
    Wave.smooth += (target - Wave.smooth) * 0.40
    WaveDraw()
}

WaveDraw() {
    global Wave
    gfx := Wave.gfx
    DllCall("gdiplus\GdipGraphicsClear", "Ptr", gfx, "UInt", 0x00000000)
    WaveRoundFill(gfx, 0, 0, Wave.w, Wave.h, Wave.h / 2, 0xB414141A)  ; translucent dark pill
    barCount := 5
    barW := 3.5
    gap := 6.0
    span := barCount * barW + (barCount - 1) * gap
    x0 := (Wave.w - span) / 2
    cy := Wave.h / 2
    maxH := Wave.h - 6
    color := (Wave.mode = "rec") ? 0xFFFF7A66 : 0xFF9AA8FF  ; warm coral / cool idle
    loop barCount {
        i := A_Index - 1
        ; two incommensurate sines per bar -> organic, non-repeating motion.
        ; pulse spans ~0.15-1.0 so bars travel most of the pill height.
        ph := Wave.t * 7.5 + i * 1.1
        pulse := 0.15 + 0.85 * ((Sin(ph) + Sin(ph * 0.57 + 1.9)) * 0.25 + 0.5)
        h := 3 + (maxH - 3) * pulse * Wave.smooth
        h := Min(maxH, Max(3, h))
        WaveRoundFill(gfx, x0 + i * (barW + gap), cy - h / 2, barW, h, barW / 2, color)
    }
    ; present via UpdateLayeredWindow (per-pixel alpha)
    size := Buffer(8, 0)
    NumPut("Int", Wave.w, size, 0)
    NumPut("Int", Wave.h, size, 4)
    srcPt := Buffer(8, 0)
    blend := Buffer(4, 0)
    NumPut("UChar", 0, blend, 0)    ; AC_SRC_OVER
    NumPut("UChar", 0, blend, 1)
    NumPut("UChar", 255, blend, 2)  ; constant alpha
    NumPut("UChar", 1, blend, 3)    ; AC_SRC_ALPHA
    DllCall("UpdateLayeredWindow", "Ptr", Wave.hwnd, "Ptr", 0, "Ptr", 0, "Ptr", size,
        "Ptr", Wave.hdc, "Ptr", srcPt, "UInt", 0, "Ptr", blend, "UInt", 2)  ; ULW_ALPHA
}

; Filled rounded rectangle (capsule when r = h/2 or w/2).
WaveRoundFill(gfx, x, y, w, h, r, argb) {
    path := 0
    DllCall("gdiplus\GdipCreatePath", "Int", 0, "Ptr*", &path)
    d := r * 2
    DllCall("gdiplus\GdipAddPathArc", "Ptr", path, "Float", x, "Float", y, "Float", d, "Float", d, "Float", 180, "Float", 90)
    DllCall("gdiplus\GdipAddPathArc", "Ptr", path, "Float", x + w - d, "Float", y, "Float", d, "Float", d, "Float", 270, "Float", 90)
    DllCall("gdiplus\GdipAddPathArc", "Ptr", path, "Float", x + w - d, "Float", y + h - d, "Float", d, "Float", d, "Float", 0, "Float", 90)
    DllCall("gdiplus\GdipAddPathArc", "Ptr", path, "Float", x, "Float", y + h - d, "Float", d, "Float", d, "Float", 90, "Float", 90)
    DllCall("gdiplus\GdipClosePathFigure", "Ptr", path)
    brush := 0
    DllCall("gdiplus\GdipCreateSolidFill", "UInt", argb, "Ptr*", &brush)
    DllCall("gdiplus\GdipFillPath", "Ptr", gfx, "Ptr", brush, "Ptr", path)
    DllCall("gdiplus\GdipDeleteBrush", "Ptr", brush)
    DllCall("gdiplus\GdipDeletePath", "Ptr", path)
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
