# PyInstaller: สร้าง moddi.exe ไฟล์เดียว (GitHub Actions ใช้ไฟล์นี้)
from PyInstaller.utils.hooks import collect_all

datas = [("app/site", "site"), ("app/fonts", "fonts")]
binaries, hidden = [], ["tkinter", "tkinter.filedialog"]
for pkg in ("UnityPy", "TypeTreeGeneratorAPI", "texture2ddecoder", "etcpak", "astc_encoder", "fmod_toolkit", "archspec"):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hidden += h
    except Exception:
        pass

a = Analysis(["app/app.py"], pathex=["app"], binaries=binaries, datas=datas, hiddenimports=hidden,
             excludes=["matplotlib", "numpy.tests", "IPython", "pytest"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="moddi", icon="app/moddi.ico",
          console=True, upx=False, runtime_tmpdir=None)
