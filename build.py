import sys
from cx_Freeze import setup, Executable

build_exe_options = {
    "packages": ["tkinter", "pygame", "PIL", "mutagen"],
    "include_files": ["downloads/", "assets/"],
    "excludes": ["test"]
}

base = None
if sys.platform == "win32":
    base = "Win32GUI"

setup(
    name="Siffy",
    version="1.0",
    description="MP3 Player",
    options={"build_exe": build_exe_options},
    executables=[Executable("main.py", base=base, icon="assets/icon.ico")]
)