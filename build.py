import sys
from cx_Freeze import setup, Executable

build_exe_options = {
    "packages": ["tkinter", "pygame", "PIL", "mutagen", "customtkinter", "requests", "yt_dlp", "plyer"],
    "include_files": ["assets/"],
    "excludes": ["old", "main"]
}

base = None
if sys.platform == "win32":
    base = "Win32GUI"

setup(
    name="Siffy dev_build",
    version="1.5",
    description="MP3 Player",
    options={"build_exe": build_exe_options},
    executables=[Executable("test.py", base=base, icon="assets/icon.ico")]
)