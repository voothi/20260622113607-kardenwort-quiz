"""Console input helper for tsv_quiz.lua on Windows.

Modes:
  --key   Read a single key and print it (for press_any_key).
  --line  Read a full line with Esc (prints /d) and Ctrl+C (prints /q)
          interception; echoes typed characters directly to the console.
"""

import sys


def read_key():
    """Read a single key, print it, exit."""
    if not sys.stdin.isatty():
        return
    import msvcrt

    ch = msvcrt.getwch()
    if ch in ("\x00", "\xe0"):
        msvcrt.getwch()  # consume extended key second byte
        return
    print(ch, end="")


def read_line(enable_arrows=False):
    """Read a full line, echoing to console. Esc -> /d, Ctrl+C -> /q."""
    if not sys.stdin.isatty():
        print("NOT_TTY", end="")
        return
    import msvcrt

    chars = []
    cursor_pos = 0
    con = open("CONOUT$", "w", encoding="utf-8")
    
    while True:
        try:
            c = msvcrt.getwch()
        except Exception:
            break
            
        if c == "\x1b":  # Esc
            print("/d", end="")
            break
        elif c in ("\r", "\n"):  # Enter
            print("".join(chars), end="")
            break
        elif c == "\x08":  # Backspace
            if cursor_pos > 0:
                chars.pop(cursor_pos - 1)
                cursor_pos -= 1
                con.write("\b")
                con.write("".join(chars[cursor_pos:]) + " ")
                con.write("\b" * (len(chars) - cursor_pos + 1))
                con.flush()
            continue
        elif c in ("\x00", "\xe0"):  # extended keys (arrows, F-keys)
            ext = msvcrt.getwch()
            if enable_arrows:
                hint_cmd = None
                if ext == "K":  # Left
                    hint_cmd = "/hint_left"
                elif ext == "M":  # Right
                    hint_cmd = "/hint_right"
                elif ext == "P":  # Down
                    hint_cmd = "/hint_down"
                elif ext == "H":  # Up
                    hint_cmd = "/hint_up"
                
                if hint_cmd:
                    if cursor_pos > 0:
                        con.write("\b" * cursor_pos)
                    con.write(" " * len(chars))
                    con.write("\b" * len(chars))
                    con.flush()
                    print(hint_cmd, end="")
                    break
            else:
                # Line navigation when arrow hints are disabled
                if ext == "K":  # Left
                    if cursor_pos > 0:
                        cursor_pos -= 1
                        con.write("\b")
                        con.flush()
                elif ext == "M":  # Right
                    if cursor_pos < len(chars):
                        con.write(chars[cursor_pos])
                        cursor_pos += 1
                        con.flush()
                elif ext == "S":  # Delete
                    if cursor_pos < len(chars):
                        chars.pop(cursor_pos)
                        con.write("".join(chars[cursor_pos:]) + " ")
                        con.write("\b" * (len(chars) - cursor_pos + 1))
                        con.flush()
                elif ext == "G":  # Home
                    if cursor_pos > 0:
                        con.write("\b" * cursor_pos)
                        cursor_pos = 0
                        con.flush()
                elif ext == "O":  # End
                    if cursor_pos < len(chars):
                        con.write("".join(chars[cursor_pos:]))
                        cursor_pos = len(chars)
                        con.flush()
            continue
        elif c == "\x03":  # Ctrl+C
            print("/q", end="")
            break
        else:
            try:
                chars.insert(cursor_pos, c)
                con.write("".join(chars[cursor_pos:]))
                cursor_pos += 1
                if cursor_pos < len(chars):
                    con.write("\b" * (len(chars) - cursor_pos))
                con.flush()
            except Exception:
                pass
    con.close()


if __name__ == "__main__":
    mode = "--key"
    enable_arrows = False
    if len(sys.argv) > 1:
        mode = sys.argv[1]
    if "--arrows" in sys.argv:
        enable_arrows = True

    if mode == "--line":
        read_line(enable_arrows)
    else:
        read_key()

