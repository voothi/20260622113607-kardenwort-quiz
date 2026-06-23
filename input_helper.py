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

    ch = msvcrt.getch()
    if ch in (b"\x00", b"\xe0"):
        msvcrt.getch()  # consume extended key second byte
        return
    print(ch.decode("utf-8", "ignore"), end="")


def read_line(enable_arrows=False):
    """Read a full line, echoing to console. Esc -> /d, Ctrl+C -> /q."""
    if not sys.stdin.isatty():
        print("NOT_TTY", end="")
        return
    import msvcrt

    chars = []
    con = open("CONOUT$", "w", encoding="utf-8")
    while True:
        try:
            c = msvcrt.getch()
        except Exception:
            break
        if c == b"\x1b":  # Esc
            print("/d", end="")
            break
        if c in (b"\r", b"\n"):  # Enter
            print("".join(chars), end="")
            break
        if c == b"\x08":  # Backspace
            if chars:
                chars.pop()
                con.write("\b \b")
                con.flush()
            continue
        if c in (b"\x00", b"\xe0"):  # extended keys (arrows, F-keys)
            ext = msvcrt.getch()
            if enable_arrows:
                hint_cmd = None
                if ext == b"K":  # Left
                    hint_cmd = "/hint_left"
                elif ext == b"M":  # Right
                    hint_cmd = "/hint_right"
                elif ext == b"P":  # Down
                    hint_cmd = "/hint_down"
                elif ext == b"H":  # Up
                    hint_cmd = "/hint_up"
                
                if hint_cmd:
                    for _ in chars:
                        con.write("\b \b")
                    con.flush()
                    print(hint_cmd, end="")
                    break
            continue
        if c == b"\x03":  # Ctrl+C
            print("/q", end="")
            break
        try:
            char = c.decode("utf-8")
            con.write(char)
            con.flush()
            chars.append(char)
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

