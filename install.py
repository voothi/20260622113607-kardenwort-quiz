# install.py
# ==============================================================================
# Kardenwort TSV Quiz — Windows SendTo Shortcut Installer
# Creates a "Kardenwort TSV Quiz" shortcut in the Windows "Send to" folder.
# Right-click a .tsv file → Send to → Kardenwort TSV Quiz to start studying!
# ==============================================================================

import os
import subprocess
import sys
import shutil
import base64

SHORTCUT_DISPLAY_NAME = "Kardenwort TSV Quiz"
LEGACY_SHORTCUT_NAMES = ("B2 Deutsch Quiz", "kardenwort tsv quiz")
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

    # 3. Clean up legacy shortcuts (if any)
    for legacy_name in LEGACY_SHORTCUT_NAMES:
        old_path = os.path.join(sendto_dir, f"{legacy_name}.lnk")
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
                print(f"Cleaned up legacy shortcut: {os.path.basename(old_path)}")
            except Exception as exc:
                print(f"Warning: Could not remove old shortcut: {exc}")

    print(f"Script Path:       {script_path}")
    print(f"Lua Path:          {lua_path}")
    print(f"SendTo Directory:  {sendto_dir}")
    print(f"Shortcut Path:     {shortcut_path}")

    # 3. Create shortcut using PowerShell WScript.Shell via EncodedCommand
    # We use cmd.exe as the target so it handles console settings (like chcp 65001 and word wrapping)
    # properly before launching lua.exe.
    ps_script = f'''
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut('{shortcut_path}')
$Shortcut.TargetPath = 'cmd.exe'
$Shortcut.Arguments = '/c chcp 65001>nul & "{lua_path}" "{script_path}"'
$Shortcut.Description = 'Runs vocabulary study quiz on the selected TSV file'
$Shortcut.WindowStyle = 1
$Shortcut.Save()
'''
    encoded_ps = base64.b64encode(ps_script.encode('utf-16le')).decode('utf-8')

    try:
        print(f"\nCreating shortcut in Windows 'Send to' menu...")
        subprocess.run(
            ["powershell", "-NoProfile", "-EncodedCommand", encoded_ps],
            capture_output=True,
            text=True,
            check=True,
        )
        print(f"\nSUCCESS: '{SHORTCUT_DISPLAY_NAME}' shortcut created!")
        print("\nHow to use:")
        print("  1. Locate your vocabulary .tsv file in Windows Explorer.")
        print(f"  2. Right-click → Send to → '{SHORTCUT_DISPLAY_NAME}'.")
    except subprocess.CalledProcessError as exc:
        print(f"Error: Failed to create shortcut.\nPowerShell error:\n{exc.stderr}")
        sys.exit(1)


if __name__ == "__main__":
    main()
