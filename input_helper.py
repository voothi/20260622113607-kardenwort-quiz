"""Console input helper for tsv_quiz.lua on Windows.

Modes:
  --key   Read a single key and print it (for press_any_key).
  --line  Read a full line with Esc (prints /d) and Ctrl+C (prints /q)
          interception; echoes typed characters directly to the console.
          Supports advanced line editing (Shift selection, Ctrl word jumping).
"""

import sys
import os
import re
import ctypes
from ctypes import wintypes
import threading
import queue
import json
import socket
import subprocess
import time

kernel32 = ctypes.windll.kernel32

class KEY_EVENT_RECORD(ctypes.Structure):
    _fields_ = [
        ("bKeyDown", wintypes.BOOL),
        ("wRepeatCount", wintypes.WORD),
        ("wVirtualKeyCode", wintypes.WORD),
        ("wVirtualScanCode", wintypes.WORD),
        ("UnicodeChar", wintypes.WCHAR),
        ("dwControlKeyState", wintypes.DWORD),
    ]

class INPUT_RECORD(ctypes.Structure):
    _fields_ = [
        ("EventType", wintypes.WORD),
        ("KeyEvent", KEY_EVENT_RECORD),
    ]

# Complete ctypes signatures to prevent 64-bit pointer truncation
if sys.platform == 'win32':
    kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel32.GetStdHandle.restype = wintypes.HANDLE

    kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel32.CreateFileW.restype = wintypes.HANDLE

    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    kernel32.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    kernel32.WriteFile.restype = wintypes.BOOL

    kernel32.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetConsoleMode.restype = wintypes.BOOL

    kernel32.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.SetConsoleMode.restype = wintypes.BOOL

    kernel32.ReadConsoleInputW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    kernel32.ReadConsoleInputW.restype = wintypes.BOOL

    kernel32.WriteConsoleInputW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    kernel32.WriteConsoleInputW.restype = wintypes.BOOL

    kernel32.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
    kernel32.WaitNamedPipeW.restype = wintypes.BOOL

    kernel32.PeekNamedPipe.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD)]
    kernel32.PeekNamedPipe.restype = wintypes.BOOL

    kernel32.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    kernel32.ReadFile.restype = wintypes.BOOL

INVALID_HANDLE = ctypes.c_void_p(-1).value  # 0xFFFFFFFF on 32-bit, 0xFFFFFFFFFFFFFFFF on 64-bit

def _is_invalid_handle(h):
    return h is None or h == 0 or h == INVALID_HANDLE or h == 0xFFFFFFFF or h == -1

STD_INPUT_HANDLE = -10
STD_OUTPUT_HANDLE = -11
hIn = kernel32.GetStdHandle(STD_INPUT_HANDLE)
hOut = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)

# Queue and Helper Functions for Bidirectional IPC Broker
sync_event_queue = queue.Queue()

def wake_up_main_thread():
    if sys.platform == 'win32':
        record = INPUT_RECORD()
        record.EventType = 0x0001  # KEY_EVENT
        record.KeyEvent.bKeyDown = True
        record.KeyEvent.wRepeatCount = 1
        record.KeyEvent.wVirtualKeyCode = 0xFF  # Special custom VK
        record.KeyEvent.wVirtualScanCode = 0
        record.KeyEvent.UnicodeChar = '\x00'
        record.KeyEvent.dwControlKeyState = 0
        
        written = wintypes.DWORD(0)
        kernel32.WriteConsoleInputW(hIn, ctypes.byref(record), 1, ctypes.byref(written))

def run_ipc_server_thread(address, family):
    from multiprocessing.connection import Listener
    try:
        if family == 'AF_UNIX' and os.path.exists(address):
            try:
                os.remove(address)
            except Exception:
                pass
        
        listener = Listener(address, family=family)
        while True:
            conn = listener.accept()
            try:
                msg = conn.recv()
                sync_event_queue.put(msg)
                wake_up_main_thread()
            except Exception:
                pass
            finally:
                conn.close()
    except Exception:
        pass

def send_win_pipe(pipe_path, data, timeout_ms=5000):
    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    OPEN_EXISTING = 3
    FILE_SHARE_READ = 1
    FILE_SHARE_WRITE = 2
    
    start_time = time.time()
    handle = None
    
    while True:
        handle = kernel32.CreateFileW(
            pipe_path,
            GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_EXISTING,
            0,
            None
        )
        if not _is_invalid_handle(handle):
            break
            
        handle = kernel32.CreateFileW(
            pipe_path,
            GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_EXISTING,
            0,
            None
        )
        if not _is_invalid_handle(handle):
            break
            
        err = ctypes.GetLastError()
        # 231 = ERROR_PIPE_BUSY
        if err != 231 or (time.time() - start_time) > timeout_ms / 1000.0:
            raise Exception(f"Failed to open named pipe, error: {err}")
            
        # Wait for the pipe to become available, max 500ms per wait call
        kernel32.WaitNamedPipeW(pipe_path, 500)
            
    written = wintypes.DWORD(0)
    res = kernel32.WriteFile(
        handle,
        data,
        len(data),
        ctypes.byref(written),
        None
    )
    kernel32.CloseHandle(handle)
    if not res:
        raise Exception("Failed to write to named pipe")

def send_unix_socket(socket_path, data):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(socket_path)
    s.sendall(data)
    s.close()

def send_ipc_payload(pipe_path, command_dict):
    payload = (json.dumps(command_dict) + "\n").encode('utf-8')
    if sys.platform == 'win32':
        send_win_pipe(pipe_path, payload)
    else:
        send_unix_socket(pipe_path, payload)

def send_receive_ipc(pipe_path, command_dict, timeout=1.0):
    payload = (json.dumps(command_dict) + "\n").encode('utf-8')
    if sys.platform == 'win32':
        GENERIC_READ = 0x80000000
        GENERIC_WRITE = 0x40000000
        OPEN_EXISTING = 3
        FILE_SHARE_READ = 1
        FILE_SHARE_WRITE = 2
        
        start_time = time.time()
        handle = None
        
        while True:
            handle = kernel32.CreateFileW(
                pipe_path,
                GENERIC_READ | GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                None,
                OPEN_EXISTING,
                0,
                None
            )
            if not _is_invalid_handle(handle):
                break
                
            err = ctypes.GetLastError()
            # 231 = ERROR_PIPE_BUSY
            if err != 231 or (time.time() - start_time) > timeout:
                return None
                
            # Wait for pipe to be available
            kernel32.WaitNamedPipeW(pipe_path, int(timeout * 1000))
            
        written = wintypes.DWORD(0)
        res = kernel32.WriteFile(
            handle,
            payload,
            len(payload),
            ctypes.byref(written),
            None
        )
        if not res:
            kernel32.CloseHandle(handle)
            return None
            
        start_time = time.time()
        response_bytes = b""
        while True:
            if time.time() - start_time > timeout:
                break
            avail = wintypes.DWORD(0)
            if not kernel32.PeekNamedPipe(handle, None, 0, None, ctypes.byref(avail), None):
                break
            if avail.value > 0:
                buf = ctypes.create_string_buffer(avail.value)
                read = wintypes.DWORD(0)
                if kernel32.ReadFile(handle, buf, avail.value, ctypes.byref(read), None):
                    response_bytes += buf.raw[:read.value]
                    if b"\n" in response_bytes:
                        break
            time.sleep(0.01)
            
        kernel32.CloseHandle(handle)
        if not response_bytes:
            return None
        for line in response_bytes.decode('utf-8', errors='ignore').split('\n'):
            line = line.strip()
            if line:
                try:
                    return json.loads(line)
                except Exception:
                    pass
        return None
    else:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            s.connect(pipe_path)
            s.sendall(payload)
            response = b""
            start_time = time.time()
            while True:
                if time.time() - start_time > timeout:
                    break
                chunk = s.recv(4096)
                if not chunk:
                    break
                response += chunk
                if b"\n" in response:
                    break
            s.close()
            for line in response.decode('utf-8', errors='ignore').split('\n'):
                line = line.strip()
                if line:
                    try:
                        return json.loads(line)
                    except Exception:
                        pass
            return None
        except Exception:
            return None

def paths_are_equal(p1, p2):
    if not p1 or not p2:
        return False
    p1_norm = p1.replace('\\', '/').lower()
    p2_norm = p2.replace('\\', '/').lower()
    return p1_norm.strip('"\' ') == p2_norm.strip('"\' ')

def find_media_file(tsv_path):
    tsv_dir = os.path.dirname(tsv_path) or "."
    tsv_name = os.path.basename(tsv_path)
    
    m = re.match(r"^(\d{14})", tsv_name)
    if not m:
        return None
    zid = m.group(1)
    
    parts = tsv_name.rsplit('.', 2)
    lang = None
    if len(parts) >= 3:
        lang = parts[-2]
        
    video_exts = {'.mp4', '.mkv', '.avi', '.webm', '.flv', '.mov', '.wmv', '.mpg', '.mpeg'}
    candidates = []
    
    def scan_dir(d):
        try:
            for entry in os.listdir(d):
                full_path = os.path.join(d, entry)
                if os.path.isfile(full_path):
                    name_no_ext, ext = os.path.splitext(entry)
                    if ext.lower() in video_exts and zid in name_no_ext:
                        candidates.append((full_path, name_no_ext))
        except Exception:
            pass
            
    scan_dir(tsv_dir)

        
    if not candidates:
        return None
        
    if lang:
        for full_path, name_no_ext in candidates:
            if name_no_ext.endswith("." + lang) or name_no_ext.endswith("-" + lang) or name_no_ext.endswith("_" + lang):
                return full_path
                
    return candidates[0][0]

def spawn_mpv(pipe_path, video_path, start_time):
    cmd = ["mpv", f"--input-ipc-server={pipe_path}"]
    if video_path:
        cmd.append(video_path)
    if start_time is not None:
        cmd.append(f"--start={start_time}")
        
    kwargs = {}
    if sys.platform == 'win32':
        kwargs['creationflags'] = 0x00000008  # DETACHED_PROCESS
        
    subprocess.Popen(cmd, **kwargs)
    
    retries = 20
    delay = 0.05
    for i in range(retries):
        time.sleep(delay)
        try:
            if sys.platform == 'win32':
                h = kernel32.CreateFileW(
                    pipe_path, 0x40000000, 1|2, None, 3, 0, None
                )
                if not _is_invalid_handle(h):
                    kernel32.CloseHandle(h)
                    return True
            else:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.connect(pipe_path)
                s.close()
                return True
        except Exception:
            pass
        delay = min(delay * 1.5, 0.5)
    return False

def sync_mpv(pipe_path, tsv_path, timestamp, play_on_sync=False):
    media_file = find_media_file(tsv_path)
    if not media_file:
        print(f"Error: Could not find media file for {tsv_path}", file=sys.stderr)
        return False
        
    media_file_mpv = media_file.replace('\\', '/')
    
    current_info = send_receive_ipc(pipe_path, {"command": ["get_property", "path"]})
    if current_info is None:
        spawn_mpv(pipe_path, media_file_mpv, timestamp)
        if play_on_sync:
            try:
                send_ipc_payload(pipe_path, {"command": ["set_property", "pause", False]})
            except Exception:
                pass
        return True
        
    is_same = False
    if isinstance(current_info, dict) and current_info.get("error") == "success":
        current_path = current_info.get("data")
        is_same = paths_are_equal(current_path, media_file_mpv)
        
    try:
        if is_same:
            send_ipc_payload(pipe_path, {"command": ["seek", timestamp, "absolute"]})
        else:
            send_ipc_payload(pipe_path, {"command": ["loadfile", media_file_mpv, "replace"]})
            send_ipc_payload(pipe_path, {"command": ["seek", timestamp, "absolute"]})
    except Exception:
        spawn_mpv(pipe_path, media_file_mpv, timestamp)

    if play_on_sync:
        try:
            send_ipc_payload(pipe_path, {"command": ["set_property", "pause", False]})
        except Exception:
            pass
    return True

# Enable VT processing for CONOUT$
mode = wintypes.DWORD()
kernel32.GetConsoleMode(hOut, ctypes.byref(mode))
kernel32.SetConsoleMode(hOut, mode.value | 0x0004)

def get_key_event():
    record = INPUT_RECORD()
    events_read = wintypes.DWORD(0)
    while True:
        kernel32.ReadConsoleInputW(hIn, ctypes.byref(record), 1, ctypes.byref(events_read))
        if record.EventType == 0x0001:  # KEY_EVENT
            if record.KeyEvent.bKeyDown:
                return record.KeyEvent

def read_key(enable_arrows=False, swap_arrows=False):
    """Read a single key, print it, exit."""
    if not sys.stdin.isatty():
        return
    while True:
        e = get_key_event()
        if e.wVirtualKeyCode == 0xFF:
            try:
                msg = sync_event_queue.get_nowait()
                if isinstance(msg, dict):
                    print(f"/sync {msg.get('zid', '')} {msg.get('time', '0')}", end="")
                else:
                    print(f"/{msg}", end="")
            except Exception:
                pass
            return
        # Return if it's a character or significant key
        if e.UnicodeChar != '\x00':
            print(e.UnicodeChar, end="")
            return
        elif enable_arrows and e.wVirtualKeyCode in (0x25, 0x27, 0x26, 0x28):
            hint_cmd = None
            if e.wVirtualKeyCode == 0x25: hint_cmd = "/hint_left" if swap_arrows else "/hint_right"
            elif e.wVirtualKeyCode == 0x27: hint_cmd = "/hint_right" if swap_arrows else "/hint_left"
            elif e.wVirtualKeyCode == 0x28: hint_cmd = "/hint_down" if swap_arrows else "/hint_up"
            elif e.wVirtualKeyCode == 0x26: hint_cmd = "/hint_up" if swap_arrows else "/hint_down"
            if hint_cmd:
                print(hint_cmd, end="")
                return
        elif e.wVirtualKeyCode in (0x1B, 0x0D, 0x08): # Esc, Enter, Backspace
            return # Actually just return nothing for these in press_any_key, or handle appropriately?
            # Wait, press_any_key uses read_key which originally returned single char.

def get_word_boundary(chars, pos, direction):
    p = pos
    if direction == -1:
        while p > 0 and chars[p - 1].isspace():
            p -= 1
        while p > 0 and not chars[p - 1].isspace():
            p -= 1
    else:
        while p < len(chars) and not chars[p].isspace():
            p += 1
        while p < len(chars) and chars[p].isspace():
            p += 1
    return p

def read_line(enable_arrows=False, initial_text="", save_esc=False, swap_arrows=False):
    if not sys.stdin.isatty():
        print("NOT_TTY", end="")
        return

    con = open("CONOUT$", "w", encoding="utf-8")
    chars = list(initial_text)
    cursor_pos = len(chars)
    anchor_pos = -1
    drawn_cursor_pos = 0
    drawn_len = 0

    def draw():
        nonlocal drawn_cursor_pos, drawn_len
        
        # move back to start of what we drew
        if drawn_cursor_pos > 0:
            con.write("\b" * drawn_cursor_pos)
            
        text = ""
        s_start = min(anchor_pos, cursor_pos) if anchor_pos != -1 else -1
        s_end = max(anchor_pos, cursor_pos) if anchor_pos != -1 else -1
        
        for i, c in enumerate(chars):
            if s_start != -1 and s_start <= i < s_end:
                text += "\033[7m" + c + "\033[0m"
            else:
                text += c
                
        con.write(text)
        
        # clear leftover characters
        clear_len = max(0, drawn_len - len(chars))
        if clear_len > 0:
            con.write(" " * clear_len)
            con.write("\b" * clear_len)
            
        # move to actual cursor pos
        if len(chars) > cursor_pos:
            con.write("\b" * (len(chars) - cursor_pos))
            
        con.flush()
        drawn_cursor_pos = cursor_pos
        drawn_len = len(chars)

    def delete_selection():
        nonlocal chars, cursor_pos, anchor_pos
        if anchor_pos != -1 and anchor_pos != cursor_pos:
            s = min(anchor_pos, cursor_pos)
            e = max(anchor_pos, cursor_pos)
            chars = chars[:s] + chars[e:]
            cursor_pos = s
            anchor_pos = -1
            return True
        anchor_pos = -1
        return False

    # Control flags
    SHIFT_PRESSED = 0x0010
    LEFT_CTRL_PRESSED = 0x0008
    RIGHT_CTRL_PRESSED = 0x0004

    draw()

    while True:
        e = get_key_event()
        vk = e.wVirtualKeyCode
        char = e.UnicodeChar
        ctrl = e.dwControlKeyState
        
        is_shift = bool(ctrl & SHIFT_PRESSED)
        is_ctrl = bool(ctrl & (LEFT_CTRL_PRESSED | RIGHT_CTRL_PRESSED))
        
        if vk == 0xFF:
            try:
                msg = sync_event_queue.get_nowait()
                if isinstance(msg, dict):
                    print(f"/sync {msg.get('zid', '')} {msg.get('time', '0')}", end="")
                else:
                    print(f"/{msg}", end="")
            except Exception:
                pass
            break
        
        if vk == 0x1B:  # Esc
            if save_esc:
                print("\x1b" + "".join(chars), end="")
            else:
                print("/d", end="")
            break
        elif vk == 0x0D:  # Enter
            print("".join(chars), end="")
            break
        elif vk == 0x43 and is_ctrl:  # Ctrl+C
            print("/q", end="")
            break
        elif vk == 0x08:  # Backspace
            if not delete_selection():
                if cursor_pos > 0:
                    chars.pop(cursor_pos - 1)
                    cursor_pos -= 1
            draw()
        elif vk == 0x2E:  # Delete
            if not delete_selection():
                if cursor_pos < len(chars):
                    chars.pop(cursor_pos)
            draw()
        elif vk == 0x57 and is_ctrl:  # Ctrl+W
            if not delete_selection():
                if cursor_pos > 0:
                    bound = get_word_boundary(chars, cursor_pos, -1)
                    chars = chars[:bound] + chars[cursor_pos:]
                    cursor_pos = bound
            draw()
        elif vk in (0x25, 0x27, 0x26, 0x28):  # Arrows
            if enable_arrows and not is_shift and not is_ctrl:
                # Use as hints
                hint_cmd = None
                if vk == 0x25: hint_cmd = "/hint_left" if swap_arrows else "/hint_right"
                elif vk == 0x27: hint_cmd = "/hint_right" if swap_arrows else "/hint_left"
                elif vk == 0x28: hint_cmd = "/hint_down" if swap_arrows else "/hint_up"
                elif vk == 0x26: hint_cmd = "/hint_up" if swap_arrows else "/hint_down"
                
                if hint_cmd:
                    # Clear line visually
                    if drawn_cursor_pos > 0:
                        con.write("\b" * drawn_cursor_pos)
                    con.write(" " * drawn_len)
                    con.write("\b" * drawn_len)
                    con.flush()
                    print(hint_cmd, end="")
                    break
            else:
                # Line navigation
                if is_shift:
                    if anchor_pos == -1:
                        anchor_pos = cursor_pos
                else:
                    if anchor_pos != -1:
                        # If we have a selection and press Left/Right without Shift, 
                        # jump to the edge of the selection.
                        if vk == 0x25: cursor_pos = min(cursor_pos, anchor_pos)
                        elif vk == 0x27: cursor_pos = max(cursor_pos, anchor_pos)
                        anchor_pos = -1
                        draw()
                        continue
                        
                if vk == 0x25:  # Left
                    if is_ctrl: cursor_pos = get_word_boundary(chars, cursor_pos, -1)
                    else: cursor_pos = max(0, cursor_pos - 1)
                elif vk == 0x27:  # Right
                    if is_ctrl: cursor_pos = get_word_boundary(chars, cursor_pos, 1)
                    else: cursor_pos = min(len(chars), cursor_pos + 1)
                elif vk == 0x24:  # Home (Not an arrow, but handled separately below? wait)
                    pass # We handle Home below
                
                if is_shift and anchor_pos == cursor_pos:
                    anchor_pos = -1
                draw()
        elif vk == 0x24:  # Home
            if is_shift:
                if anchor_pos == -1: anchor_pos = cursor_pos
            else:
                if anchor_pos != -1: anchor_pos = -1
            cursor_pos = 0
            draw()
        elif vk == 0x23:  # End
            if is_shift:
                if anchor_pos == -1: anchor_pos = cursor_pos
            else:
                if anchor_pos != -1: anchor_pos = -1
            cursor_pos = len(chars)
            draw()
        else:
            # Printable char?
            if char != '\x00':
                # Ignore control characters (except maybe tabs if we want, but usually no)
                if ord(char) >= 32:
                    delete_selection()
                    chars.insert(cursor_pos, char)
                    cursor_pos += 1
                    draw()

    con.close()

if __name__ == "__main__":
    mode = "--key"
    enable_arrows = False
    swap_arrows = False
    save_esc = False
    initial_text = ""
    mpv_integration = False
    quiz_pipe_path = None
    
    args = sys.argv[1:]
    play_on_sync = "--play" in args
    i = 0
    while i < len(args):
        if args[i] == "--sync-mpv" and i + 3 < len(args):
            pipe_path = args[i + 1]
            tsv_path = args[i + 2]
            try:
                timestamp = float(args[i + 3])
            except ValueError:
                timestamp = 0.0
            
            success = sync_mpv(pipe_path, tsv_path, timestamp, play_on_sync)
            sys.exit(0 if success else 1)
        elif args[i] in ("--key", "--line"):
            mode = args[i]
        elif args[i] == "--arrows":
            enable_arrows = True
        elif args[i] == "--swap-arrows":
            enable_arrows = True
            swap_arrows = True
        elif args[i] == "--save-esc":
            save_esc = True
        elif args[i] == "--initial" and i + 1 < len(args):
            initial_text = args[i + 1]
            i += 1
        elif args[i] == "--mpv-integration":
            mpv_integration = True
        elif args[i] == "--quiz-pipe-path" and i + 1 < len(args):
            quiz_pipe_path = args[i + 1]
            i += 1
        i += 1

    if mpv_integration:
        # Start reverse IPC listener thread (Windows Named Pipe or Unix Socket)
        if not quiz_pipe_path:
            if sys.platform == 'win32':
                quiz_pipe_path = r'\\.\pipe\kardenwort-quiz'
            else:
                quiz_pipe_path = '/tmp/kardenwort-quiz'
                
        family = 'AF_PIPE' if sys.platform == 'win32' and quiz_pipe_path.startswith('\\\\.\\pipe\\') else 'AF_UNIX'
        
        t = threading.Thread(target=run_ipc_server_thread, args=(quiz_pipe_path, family))
        t.daemon = True
        t.start()

    if mode == "--line":
        read_line(enable_arrows, initial_text, save_esc, swap_arrows)
    else:
        read_key(enable_arrows, swap_arrows)
