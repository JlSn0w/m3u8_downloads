# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

# 检查icons目录是否存在
import os
icon_path = 'icons'
if not os.path.exists(icon_path):
    os.makedirs(icon_path)

a = Analysis(
    ['m3u8_downloader.py'],
    pathex=[],
    binaries=[
        ('/opt/homebrew/bin/ffmpeg', './ffmpeg')  # 修改ffmpeg路径
    ],
    datas=[
        ('icons', 'icons')
    ],
    hiddenimports=[
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'requests',
        'm3u8'
    ],  # 添加隐式导入
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher
)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='M3U8下载器',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,
    target_arch='arm64',
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='M3U8下载器',
)

app = BUNDLE(
    coll,
    name='M3U8下载器.app',
    icon=None,  # 暂时移除图标
    bundle_identifier='com.yourcompany.m3u8downloader',
    info_plist={
        'NSHighResolutionCapable': 'True',
        'LSBackgroundOnly': 'False',
        'CFBundleShortVersionString': '1.0.0',
        'CFBundleVersion': '1.0.0',
        'NSRequiresAquaSystemAppearance': 'No',  # 支持暗黑模式
        'CFBundleDisplayName': 'M3U8下载器',
        'CFBundleName': 'M3U8下载器',
        'CFBundleExecutable': 'M3U8下载器',  # 确保与name匹配
        'LSMinimumSystemVersion': '10.13.0',
    },
) 