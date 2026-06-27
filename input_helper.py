"""Console input helper for tsv_quiz.lua on Windows.

Modes:
  --key   Read a single key and print it (for press_any_key).
  --line  Read a full line with Esc (prints /d) and Ctrl+C (prints /q)
          interception; echoes typed characters directly to the console.
          Supports advanced line editing (Shift selection, Ctrl word jumping).
"""

import sys
import os
import shutil
import re
import ctypes
from ctypes import wintypes
import threading
import queue
import json
import socket
import subprocess
import time
import unicodedata
import string

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

    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD

    kernel32.PeekConsoleInputW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    kernel32.PeekConsoleInputW.restype = wintypes.BOOL

    kernel32.GetNumberOfConsoleInputEvents.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetNumberOfConsoleInputEvents.restype = wintypes.BOOL

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
            
        err = ctypes.GetLastError()
        # Retry on: 231 = ERROR_PIPE_BUSY, 5 = ERROR_ACCESS_DENIED
        remaining_ms = int(timeout_ms - (time.time() - start_time) * 1000)
        if (err != 231 and err != 5) or remaining_ms <= 0:
            raise Exception(f"Failed to open named pipe, error: {err}")
            
        # Wait for the pipe to become available, max 50ms per wait call to be responsive
        kernel32.WaitNamedPipeW(pipe_path, min(50, remaining_ms))
            
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

def send_ipc_payload(pipe_path, command_dict_or_list):
    if isinstance(command_dict_or_list, list):
        payload = b"".join((json.dumps(cmd) + "\n").encode('utf-8') for cmd in command_dict_or_list)
    else:
        payload = (json.dumps(command_dict_or_list) + "\n").encode('utf-8')
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
            # Retry on: 231 = ERROR_PIPE_BUSY, 5 = ERROR_ACCESS_DENIED
            remaining_ms = int((timeout - (time.time() - start_time)) * 1000)
            if (err != 231 and err != 5) or remaining_ms <= 0:
                return None
                
            # Wait for pipe to be available, max 50ms per wait call to be responsive
            kernel32.WaitNamedPipeW(pipe_path, min(50, remaining_ms))
            
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
        
    # Sort candidates alphabetically by full path to guarantee deterministic selection order
    candidates.sort(key=lambda x: x[0])
        
    if lang:
        for full_path, name_no_ext in candidates:
            cand_parts = name_no_ext.split('.')
            if len(cand_parts) >= 2:
                cand_lang = cand_parts[-1]
                if cand_lang.lower() == lang.lower():
                    return full_path
                
    return candidates[0][0]

def spawn_mpv(pipe_path, video_path, start_time, mpv_cmd="mpv"):
    cmd = [mpv_cmd, f"--input-ipc-server={pipe_path}"]
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

def sync_mpv(pipe_path, tsv_path, timestamp, play_on_sync=False, mpv_cmd="mpv"):
    media_file = find_media_file(tsv_path)
    if not media_file:
        print(f"Error: Could not find media file for {tsv_path}", file=sys.stderr)
        return False
        
    media_file_mpv = media_file.replace('\\', '/')
    
    current_info = send_receive_ipc(pipe_path, {"command": ["get_property", "path"]})
    if current_info is None:
        spawn_mpv(pipe_path, media_file_mpv, timestamp, mpv_cmd or "mpv")
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
        
    commands = []
    if is_same:
        commands.append({"command": ["seek", timestamp, "absolute"]})
    else:
        commands.append({"command": ["loadfile", media_file_mpv, "replace"]})
        commands.append({"command": ["seek", timestamp, "absolute"]})
        
    if play_on_sync:
        commands.append({"command": ["set_property", "pause", False]})
        
    try:
        send_ipc_payload(pipe_path, commands)
    except Exception:
        spawn_mpv(pipe_path, media_file_mpv, timestamp, mpv_cmd or "mpv")
        
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
        elif record.EventType == 0x0004:  # WINDOW_BUFFER_SIZE_EVENT
            mock_key = KEY_EVENT_RECORD()
            mock_key.bKeyDown = True
            mock_key.wVirtualKeyCode = 0xFE  # Special custom VK for resize
            mock_key.wVirtualScanCode = 0
            mock_key.UnicodeChar = '\x00'
            mock_key.dwControlKeyState = 0
            return mock_key

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
        elif e.wVirtualKeyCode == 0xFE:  # Special custom VK for resize
            print("/resize", end="")
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
            if e.wVirtualKeyCode == 0x1B:
                print("\x1b", end="")
            elif e.wVirtualKeyCode == 0x0D:
                print("\r", end="")
            elif e.wVirtualKeyCode == 0x08:
                print("\b", end="")
            return

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

def strip_ansi(str_val):
    return re.sub(r'\x1b\[\d+;?\d*;?\d*m', '', str_val)

def tokenize_ansi_utf8(str_val):
    tokens = []
    i = 0
    length = len(str_val)
    ansi_pattern = re.compile(r'\x1b\[[\d;]*m')
    while i < length:
        m = ansi_pattern.match(str_val, i)
        if m:
            val = m.group(0)
            tokens.append({"type": "ansi", "val": val})
            i += len(val)
        else:
            tokens.append({"type": "char", "val": str_val[i]})
            i += 1
    return tokens

def split_word_by_width(word, max_width):
    tokens = tokenize_ansi_utf8(word)
    parts = []
    current_part = []
    current_visible_len = 0
    active_ansi = []
    
    for tok in tokens:
        if tok["type"] == "ansi":
            current_part.append(tok["val"])
            if tok["val"] == "\x1b[0m":
                active_ansi = []
            else:
                active_ansi.append(tok["val"])
        else:
            if current_visible_len >= max_width:
                if len(active_ansi) > 0:
                    current_part.append("\x1b[0m")
                parts.append("".join(current_part))
                current_part = []
                current_visible_len = 0
                for ansi_val in active_ansi:
                    current_part.append(ansi_val)
            current_part.append(tok["val"])
            current_visible_len += 1
            
    if len(current_part) > 0:
        parts.append("".join(current_part))
    return parts

def wrap_text(text, max_width):
    lines = []
    raw_lines = (text + "\n").split("\n")[:-1]
    
    for line in raw_lines:
        if line == "":
            lines.append("")
        else:
            current_line = ""
            current_len = 0
            for word, space in re.findall(r'(\S*)(\s*)', line):
                if word != "" or space != "":
                    word_len = len(strip_ansi(word))
                    space_len = len(strip_ansi(space))
                    
                    if word_len > max_width:
                        if current_len > 0:
                            lines.append(current_line.rstrip())
                            current_line = ""
                            current_len = 0
                        word_parts = split_word_by_width(word, max_width)
                        for idx in range(len(word_parts) - 1):
                            lines.append(word_parts[idx])
                        last_part = word_parts[-1]
                        current_line = last_part + space
                        current_len = len(strip_ansi(last_part)) + space_len
                    else:
                        if current_len > 0 and current_len + word_len > max_width:
                            lines.append(current_line.rstrip())
                            current_line = word + space
                            current_len = word_len + space_len
                        else:
                            current_line = current_line + word + space
                            current_len = current_len + word_len + space_len
            if current_line != "":
                lines.append(current_line.rstrip())
                
    if len(lines) > 0 and lines[-1] == "":
        lines.pop()
        
    return "\n".join(lines)

def get_wrap_width():
    columns = 0
    env_cols = os.environ.get("COLUMNS")
    if env_cols:
        try:
            columns = int(env_cols)
        except ValueError:
            pass
    if not columns:
        if sys.platform == 'win32':
            try:
                with open("CONOUT$", "w") as f:
                    columns = os.get_terminal_size(f.fileno()).columns
            except Exception:
                pass
    if not columns:
        try:
            columns = os.get_terminal_size(sys.__stdout__.fileno()).columns
        except Exception:
            try:
                columns, _ = shutil.get_terminal_size((120, 30))
            except Exception:
                columns = 120
    return columns - 1

def is_punctuation_or_space(c):
    if c.isspace():
        return True
    category = unicodedata.category(c)
    return category.startswith('P') or category.startswith('S')

def get_inline_colored_diff(user_str, original_target, case_sensitive, ignore_punctuation, diff_inverted_colors=False):
    GREEN_CODE = "32"
    RED_CODE = "31"
    
    def c(code, text):
        if diff_inverted_colors:
            return f"\033[7m\033[{code}m{text}\033[0m"
        else:
            return f"\033[{code}m\033[1m{text}\033[0m"
            
    if ignore_punctuation:
        user_clean = "".join(ch for ch in user_str if not is_punctuation_or_space(ch))
        target_clean = "".join(ch for ch in original_target if not is_punctuation_or_space(ch))
    else:
        user_clean = "".join(ch for ch in user_str if not ch.isspace())
        target_clean = "".join(ch for ch in original_target if not ch.isspace())
        
    if not target_clean:
        return original_target
        
    A = list(user_clean)
    B = list(target_clean)
    n = len(A)
    m = len(B)
    
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
        
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if case_sensitive:
                cost = 0 if A[i - 1] == B[j - 1] else 1
            else:
                cost = 0 if A[i - 1].lower() == B[j - 1].lower() else 1
            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost)
            
    i, j = n, m
    ops = []
    last_op = None
    
    while i > 0 or j > 0:
        match = False
        if i > 0 and j > 0:
            if case_sensitive:
                match = (A[i - 1] == B[j - 1])
            else:
                match = (A[i - 1].lower() == B[j - 1].lower())
        cost = 0 if match else 1
        
        can_match = i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + cost
        can_missing = j > 0 and dp[i][j] == dp[i][j - 1] + 1
        can_extra = i > 0 and dp[i][j] == dp[i - 1][j] + 1
        
        op_type = None
        if can_match and cost == 0:
            if last_op == "match" or (not can_missing and not can_extra):
                op_type = "match"
            elif last_op == "missing" and can_missing:
                op_type = "missing"
            elif last_op == "extra" and can_extra:
                op_type = "extra"
            elif can_missing:
                op_type = "missing"
            else:
                op_type = "extra"
        else:
            if can_missing and can_extra:
                if last_op == "missing":
                    op_type = "missing"
                elif last_op == "extra":
                    op_type = "extra"
                else:
                    op_type = "missing"
            elif can_missing:
                op_type = "missing"
            elif can_extra:
                op_type = "extra"
            else:
                op_type = "replace"
            
        ops.append({"type": op_type})
        last_op = op_type
        if op_type == "match" or op_type == "replace":
            i -= 1
            j -= 1
        elif op_type == "missing":
            j -= 1
        elif op_type == "extra":
            i -= 1
            
    tags = []
    for op in reversed(ops):
        if op["type"] != "extra":
            tags.append(op["type"])
            
    res = []
    tag_idx = 0
    for ch in list(original_target):
        if is_punctuation_or_space(ch):
            res.append(c(GREEN_CODE, ch))
        else:
            tag = tags[tag_idx] if tag_idx < len(tags) else "missing"
            tag_idx += 1
            if tag == "match":
                res.append(c(GREEN_CODE, ch))
            else:
                res.append(c(RED_CODE, ch))
    return "".join(res)

def format_wildcard(text, blank_inverted_colors, color_code=None, blank_color=None):
    if color_code == "33":
        if blank_color == "standard":
            color_code = None
        elif blank_color in ("gray", "grey"):
            color_code = "90"
    if color_code:
        if blank_inverted_colors:
            return f"\033[7m\033[{color_code}m{text}\033[0m"
        else:
            return f"\033[1m\033[{color_code}m{text}\033[0m"
    else:
        if blank_inverted_colors:
            return f"\033[7m{text}\033[0m"
        else:
            return f"\033[1m{text}\033[0m"

def get_preview_replacement(u_part, target, use_exact, battleship, case_sensitive, ignore_punctuation, blank_inverted_colors=None, diff_inverted_colors=None, blank_color=None, hint_mask=None):
    if blank_inverted_colors is None:
        blank_inverted_colors = diff_inverted_colors if diff_inverted_colors is not None else False
    target_len = len(target)
    p_len = len(u_part)
    
    if p_len == 0:
        if hint_mask:
            placeholder = hint_mask
        else:
            placeholder = "_" * target_len if use_exact else "___"
        return format_wildcard(placeholder, blank_inverted_colors, "33", blank_color)
        
    if use_exact:
        if p_len < target_len:
            remaining = hint_mask[p_len:] if hint_mask else "_" * (target_len - p_len)
            if battleship:
                target_prefix = target[:p_len]
                colored = get_inline_colored_diff(u_part, target_prefix, case_sensitive, ignore_punctuation, blank_inverted_colors)
                return colored + format_wildcard(remaining, blank_inverted_colors, "33", blank_color)
            else:
                typed_colored = format_wildcard(u_part, blank_inverted_colors, None, blank_color)
                return typed_colored + format_wildcard(remaining, blank_inverted_colors, "33", blank_color)
        elif p_len > target_len:
            fitted_plain = target
            if target_len <= 1:
                fitted_plain = "…"
            else:
                fitted_plain = target[:target_len - 1] + "…"
                
            if battleship:
                return get_inline_colored_diff(fitted_plain, target, case_sensitive, ignore_punctuation, blank_inverted_colors)
            else:
                return format_wildcard(fitted_plain, blank_inverted_colors, None, blank_color)
        else:
            if battleship:
                return get_inline_colored_diff(u_part, target, case_sensitive, ignore_punctuation, blank_inverted_colors)
            else:
                return format_wildcard(u_part, blank_inverted_colors, None, blank_color)
    else:
        if battleship:
            target_prefix = target[:p_len] if p_len < target_len else target
            return get_inline_colored_diff(u_part, target_prefix, case_sensitive, ignore_punctuation, blank_inverted_colors)
        else:
            return format_wildcard(u_part, blank_inverted_colors, None, blank_color)

def render_preview_template(template, typed_text, use_exact, battleship, case_sensitive, ignore_punctuation, blank_inverted_colors=None, diff_inverted_colors=None, blank_color=None, hint_masks=None):
    if blank_inverted_colors is None:
        blank_inverted_colors = diff_inverted_colors if diff_inverted_colors is not None else False
    placeholders = re.findall(r'\[\[TARGET:(.*?)\]\]', template)
    if not placeholders:
        return template
        
    u_parts = re.findall(r'[^\s]+', typed_text)
    
    rendered = template
    for idx, target in enumerate(placeholders):
        u_part = u_parts[idx] if idx < len(u_parts) else ""
        hint_mask = hint_masks[idx] if (hint_masks and idx < len(hint_masks)) else None
        replacement = get_preview_replacement(u_part, target, use_exact, battleship, case_sensitive, ignore_punctuation, blank_inverted_colors, None, blank_color, hint_mask)
        rendered = rendered.replace(f"[[TARGET:{target}]]", replacement, 1)
        
    return rendered

def clean_word(word, ignore_punctuation, case_sensitive):
    if ignore_punctuation:
        cleaned = "".join(ch for ch in word if not is_punctuation_or_space(ch))
    else:
        cleaned = "".join(ch for ch in word if not ch.isspace())
    if not case_sensitive:
        cleaned = cleaned.lower()
    return cleaned

def check_auto_submit(typed_text, placeholders, mode, case_sensitive, ignore_punctuation):
    if not placeholders:
        return False
    if typed_text.startswith("/"):
        return False
    u_parts = re.findall(r'[^\s]+', typed_text)
    if len(u_parts) < len(placeholders):
        return False
    for idx, target in enumerate(placeholders):
        u_part = u_parts[idx] if idx < len(u_parts) else ""
        clean_target = clean_word(target, ignore_punctuation, case_sensitive)
        clean_u_part = clean_word(u_part, ignore_punctuation, case_sensitive)
        if mode == "correct":
            if clean_u_part != clean_target:
                return False
        elif mode == "filled":
            if len(clean_u_part) < len(clean_target):
                return False
    return True

def is_new_keypress_available():
    num_events = wintypes.DWORD(0)
    if not kernel32.GetNumberOfConsoleInputEvents(hIn, ctypes.byref(num_events)):
        return False
    if num_events.value == 0:
        return False
    records = (INPUT_RECORD * num_events.value)()
    events_peeked = wintypes.DWORD(0)
    if not kernel32.PeekConsoleInputW(hIn, ctypes.byref(records), num_events.value, ctypes.byref(events_peeked)):
        return False
    for i in range(events_peeked.value):
        rec = records[i]
        if rec.EventType == 0x0001:  # KEY_EVENT
            if rec.KeyEvent.bKeyDown:
                if rec.KeyEvent.wVirtualKeyCode != 0xFF:
                    return True
    return False

def read_line(enable_arrows=False, initial_text="", save_esc=False, swap_arrows=False, preview_data=None):
    if not sys.stdin.isatty():
        print("NOT_TTY", end="")
        return

    con = open("CONOUT$", "w", encoding="utf-8")
    chars = list(initial_text)
    cursor_pos = len(chars)
    anchor_pos = -1
    drawn_cursor_pos = 0
    drawn_len = 0

    header_text = None
    template = None
    hint_text = None
    prompt_text = None
    use_exact = False
    battleship = False
    case_sensitive = True
    ignore_punctuation = True
    diff_inverted_colors = False
    blank_inverted_colors = False
    blank_color = None
    hint_masks = None
    placeholders = []
    battleship_auto_submit_delay = 0.0
    context_left_list = None
    context_right_list = None
    context_lines = 0
    
    if preview_data:
        header_text = preview_data.get("header")
        template = preview_data.get("template")
        if template:
            placeholders = re.findall(r'\[\[TARGET:(.*?)\]\]', template)
        hint_text = preview_data.get("hint")
        prompt_text = preview_data.get("prompt")
        use_exact = bool(preview_data.get("exact_length_mask"))
        battleship = bool(preview_data.get("battleship_feedback"))
        case_sensitive = bool(preview_data.get("case_sensitive_diff"))
        ignore_punctuation = bool(preview_data.get("ignore_punctuation"))
        diff_inverted_colors = bool(preview_data.get("diff_inverted_colors"))
        blank_inverted_colors = bool(preview_data.get("blank_inverted_colors"))
        blank_color = preview_data.get("blank_color")
        hint_masks = preview_data.get("hint_masks")
        try:
            battleship_auto_submit_delay = float(preview_data.get("battleship_auto_submit_delay", 0.0))
        except (ValueError, TypeError):
            battleship_auto_submit_delay = 0.0
        context_left_list = preview_data.get("context_left_list")
        context_right_list = preview_data.get("context_right_list")
        try:
            context_lines = int(preview_data.get("context_lines", 0))
        except (ValueError, TypeError):
            context_lines = 0

    def draw():
        nonlocal drawn_cursor_pos, drawn_len
        
        typed = "".join(chars)
        preview_typed = "" if typed.startswith("/") else typed
        
        if preview_data and template:
            live_context = render_preview_template(
                template, preview_typed, use_exact, battleship,
                case_sensitive, ignore_punctuation, blank_inverted_colors,
                blank_color=blank_color, hint_masks=hint_masks
            )
            con.write("\033[2J\033[H")
            con.write(header_text)
            if context_lines > 0:
                if context_left_list:
                    for line in context_left_list:
                        con.write("\033[2m" + wrap_text(line, get_wrap_width()) + "\033[0m\n")
            con.write(wrap_text(live_context, get_wrap_width()) + "\n")
            if context_lines > 0:
                if context_right_list:
                    for line in context_right_list:
                        con.write("\033[2m" + wrap_text(line, get_wrap_width()) + "\033[0m\n")
            if hint_text:
                con.write(hint_text + "\n")
            con.write(prompt_text)
        else:
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
        
        clear_len = max(0, drawn_len - len(chars))
        if clear_len > 0:
            con.write(" " * clear_len)
            con.write("\b" * clear_len)
            
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
        
        if vk == 0xFE:  # Special custom VK for resize
            draw()
            continue

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
                print("\x1b/d", end="")
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
                    if preview_data and battleship and preview_data.get("battleship_auto_submit") in ("correct", "filled"):
                        typed = "".join(chars)
                        if check_auto_submit(typed, placeholders, preview_data.get("battleship_auto_submit"), case_sensitive, ignore_punctuation):
                            aborted = False
                            if battleship_auto_submit_delay > 0:
                                start_time = time.time()
                                while time.time() - start_time < battleship_auto_submit_delay:
                                    if sys.platform == 'win32':
                                        time.sleep(0.02)
                                        if is_new_keypress_available():
                                            aborted = True
                                            break
                                    else:
                                        time.sleep(0.05)
                            if not aborted:
                                print(typed, end="")
                                break

    con.close()

if __name__ == "__main__":
    args = sys.argv[1:]
    
    if "--help" in args or "-h" in args:
        print("Console input helper for tsv_quiz.lua on Windows.")
        print()
        print("Usage:")
        print("  python input_helper.py [options]")
        print()
        print("Modes:")
        print("  --key                    Read a single key and print it (default).")
        print("  --line                   Read a full line with Esc/Ctrl+C/arrow key interception.")
        print("  --width                  Print the current terminal width in columns and exit.")
        print("  --sync-mpv <pipe> <tsv> <time>  Sync media playback to MPV at timestamp.")
        print()
        print("Options:")
        print("  --play                   When used with --sync-mpv, automatically plays/unpauses the video.")
        print("                           Note: In direct CLI usage, this flag is required to auto-play.")
        print("                           (The Lua launcher configures this via the mpv_play_on_sync setting).")
        print("  --mpv-cmd <cmd>          Executable command or full path for the MPV binary (default: mpv).")
        print("  --arrows                 Enable dynamic visual arrow key hints.")
        print("  --swap-arrows            Enable and swap dynamic visual arrow key hints.")
        print("  --save-esc               Save the input buffer on Esc key press instead of clearing.")
        print("  --initial <text>         Pre-populate the line editor with initial text.")
        print("  --mpv-integration        Start the reverse IPC server thread to listen for MPV events.")
        print("  --quiz-pipe-path <path>  Override the named pipe or socket path for reverse IPC.")
        sys.exit(0)

    mode = "--key"
    enable_arrows = False
    swap_arrows = False
    save_esc = False
    initial_text = ""
    mpv_integration = False
    quiz_pipe_path = None
    preview_data = None
    
    play_on_sync = "--play" in args
    mpv_cmd_path = "mpv"
    
    # First find --mpv-cmd to ensure it's loaded before we potentially execute --sync-mpv
    for idx in range(len(args)):
        if args[idx] == "--mpv-cmd" and idx + 1 < len(args):
            mpv_cmd_path = args[idx + 1]
            
    # Main argument parsing loop
    sync_args = None
    i = 0
    while i < len(args):
        if args[i] == "--sync-mpv" and i + 3 < len(args):
            sync_args = (args[i + 1], args[i + 2], args[i + 3])
            i += 4
            continue
        elif args[i] == "--width":
            print(get_wrap_width() + 1)
            sys.exit(0)
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
        elif args[i] == "--preview-data" and i + 1 < len(args):
            hex_data = args[i + 1]
            try:
                preview_data_str = bytes.fromhex(hex_data).decode('utf-8')
                preview_data = json.loads(preview_data_str)
            except Exception:
                pass
            i += 1
        elif args[i] == "--mpv-cmd" and i + 1 < len(args):
            # Already handled in pre-scan, just skip
            i += 1
        elif args[i] == "--play":
            # Already handled via play_on_sync, just skip
            pass
        i += 1

    if sync_args:
        pipe_path, tsv_path, timestamp_str = sync_args
        try:
            timestamp = float(timestamp_str)
        except ValueError:
            timestamp = 0.0
        
        success = sync_mpv(pipe_path, tsv_path, timestamp, play_on_sync, mpv_cmd_path)
        sys.exit(0 if success else 1)

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
        read_line(enable_arrows, initial_text, save_esc, swap_arrows, preview_data)
    else:
        read_key(enable_arrows, swap_arrows)
