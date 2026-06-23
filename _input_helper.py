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

def read_line():
    """Read a full line, echoing to console. Esc -> /d, Ctrl+C -> /q."""
    if not sys.stdin.isatty():
        return
    import msvcrt
    chars = []
    con = open("CONOUT$", "w", encoding="utf-8")
    while True:
        try:
            c = msvcrt.getch()
        except Exception:
            break
        if c == b"\x1b":          # Esc
            print("/d", end="")
            break
        if c in (b"\r", b"\n"):   # Enter
            print("".join(chars), end="")
            break
        if c == b"\x08":          # Backspace
            if chars:
                chars.pop()
                con.write("\b \b")
                con.flush()
            continue
        if c in (b"\x00", b"\xe0"):  # extended keys (arrows, F-keys)
            msvcrt.getch()
            continue
        if c == b"\x03":          # Ctrl+C
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
    mode = sys.argv[1] if len(sys.argv) > 1 else "--key"
    if mode == "--line":
        read_line()
    else:
        read_key()
