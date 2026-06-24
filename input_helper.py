"""Console input helper for tsv_quiz.lua on Windows.

Modes:
  --key   Read a single key and print it (for press_any_key).
  --line  Read a full line with Esc (prints /d) and Ctrl+C (prints /q)
          interception; echoes typed characters directly to the console.
          Supports advanced line editing (Shift selection, Ctrl word jumping).
"""

import sys
import ctypes
from ctypes import wintypes

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

STD_INPUT_HANDLE = -10
STD_OUTPUT_HANDLE = -11
hIn = kernel32.GetStdHandle(STD_INPUT_HANDLE)
hOut = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)

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
    
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] in ("--key", "--line"):
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
        i += 1

    if mode == "--line":
        read_line(enable_arrows, initial_text, save_esc, swap_arrows)
    else:
        read_key(enable_arrows, swap_arrows)
