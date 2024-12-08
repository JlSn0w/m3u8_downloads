#!/bin/bash

# 设置Python环境变量
export PYTHONPATH=$(pwd)

# 创建必要的目录
mkdir -p icons

# 安装依赖
pip install -r requirements.txt
pip install pyinstaller  # 确保安装最新版本的pyinstaller

# 检查ffmpeg
if ! command -v ffmpeg &> /dev/null; then
    echo "Installing ffmpeg..."
    brew install ffmpeg
fi

# 清理之前的构建
rm -rf build dist

# 运行pyinstaller
pyinstaller --clean --noconfirm m3u8_downloader.spec

# 检查是否成功
if [ -d "dist/M3U8下载器.app" ]; then
    echo "打包成功！应用程序在 dist/M3U8下载器.app"
    
    # 修复权限
    chmod -R 755 "dist/M3U8下载器.app"
    
    # 签名应用（如果有开发者证书）
    # codesign --force --deep --sign - "dist/M3U8下载器.app"
    
    echo "你可以将应用拖到应用程序文件夹使用了"
else
    echo "打包失败！"
    exit 1
fi 