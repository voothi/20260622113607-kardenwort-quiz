# install.py
# ==============================================================================
# B2 Deutsch Quiz — Windows SendTo Shortcut Installer
# Creates a "B2 Deutsch Quiz" shortcut in the Windows "Send to" folder.
# Right-click a .tsv file → Send to → B2 Deutsch Quiz to start studying!
# ==============================================================================

import os
import subprocess
import sys
import shutil

SHORTCUT_DISPLAY_NAME = "B2 Deutsch Quiz"
SENDTO_DIRECTORY = r"%APPDATA%\Microsoft\Windows\SendTo"

def main():
    print(f"=== {SHORTCUT_DISPLAY_NAME} Shortcut Installer ===")

    # 1. Locate script paths
    current_dir = os.path.dirname(os.path.abspath(__file__))
    script_path = os.path.join(current_dir, "tsv_quiz.lua")

    if not os.path.exists(script_path):
        print(f"Error: Could not find {script_path}")
        sys.exit(1)

    # 2. Locate Lua executable
    lua_path = shutil.which("lua")
    if not lua_path:
        # Fallback to the user's specific path if not in system PATH
        fallback_path = r"C:\lua\lua-5.5.0_Win64_bin\lua.exe"
        if os.path.exists(fallback_path):
            lua_path = fallback_path
        else:
            print("Error: Could not find lua.exe in your PATH or fallback directory.")
            sys.exit(1)

    sendto_dir = os.path.expandvars(SENDTO_DIRECTORY)
    os.makedirs(sendto_dir, exist_ok=True)
    shortcut_path = os.path.join(sendto_dir, f"{SHORTCUT_DISPLAY_NAME}.lnk")

    print(f"Script Path:       {script_path}")
    print(f"Lua Path:          {lua_path}")
    print(f"SendTo Directory:  {sendto_dir}")
    print(f"Shortcut Path:     {shortcut_path}")

    # 3. Create shortcut using PowerShell WScript.Shell
    ps_script = (
        f"$WshShell = New-Object -ComObject WScript.Shell; "
        f"$Shortcut = $WshShell.CreateShortcut('{shortcut_path}'); "
        f"$Shortcut.TargetPath = '{lua_path}'; "
        f"$Shortcut.Arguments = '\"{script_path}\"'; "
        f"$Shortcut.Description = 'Runs B2 German Vocabulary Quiz on the selected TSV file'; "
        f"$Shortcut.WindowStyle = 1; "   # SW_SHOWNORMAL
        f"$Shortcut.Save()"
    )

    try:
        print(f"\nCreating shortcut in Windows 'Send to' menu...")
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            text=True,
            check=True,
        )
        print(f"\nSUCCESS: '{SHORTCUT_DISPLAY_NAME}' shortcut created!")
        print("\nHow to use:")
        print("  1. Locate your German vocabulary .tsv file in Windows Explorer.")
        print(f"  2. Right-click → Send to → '{SHORTCUT_DISPLAY_NAME}'.")
    except subprocess.CalledProcessError as exc:
        print(f"Error: Failed to create shortcut.\nPowerShell error:\n{exc.stderr}")
        sys.exit(1)

if __name__ == "__main__":
    main()
