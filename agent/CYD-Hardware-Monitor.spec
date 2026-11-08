# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['agent.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('../imgs/icone-cyd-resource-monitor.ico', 'imgs'),
        ('../imgs/icone-cyd-resource-monitor.png', 'imgs'),
        ('../imgs/imgsCYD.ico', 'imgs'),
    ],
    hiddenimports=['serial', 'serial.tools.list_ports', 'psutil', 'wmi', 'win32com.client', 'PIL', 'pystray', 'pystray._win32', 'qrcode', 'mobile_web', 'winrt', 'winrt.windows.media.control', 'winrt.windows.storage.streams', 'winrt.windows.foundation', 'winrt.windows.foundation.collections', 'paramiko'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='CYD-Hardware-Monitor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['../imgs/icone-cyd-resource-monitor.ico'],
    version='file_version_info.txt',
)
