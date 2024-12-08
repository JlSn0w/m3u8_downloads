import sys
import os
import requests
import m3u8
import concurrent.futures
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                            QSpinBox, QProgressBar, QTableWidget, QTableWidgetItem,
                            QMessageBox, QTextEdit, QSplitter, QFileDialog, 
                            QCheckBox, QGroupBox)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
import subprocess
import urllib.parse
from datetime import datetime
import json
from PyQt6.QtGui import QIcon, QFont
from PyQt6.QtCore import QSize

class DownloadWorker(QThread):
    progress_updated = pyqtSignal(int)
    download_completed = pyqtSignal()
    error_occurred = pyqtSignal(str)
    log_message = pyqtSignal(str)

    def __init__(self, url, headers, output_dir, max_workers):
        super().__init__()
        self.url = url
        self.headers = headers
        self.output_dir = output_dir
        self.max_workers = max_workers
        self.is_paused = False
        self.downloaded_segments = set()

    def pause(self):
        self.is_paused = True
        self.log_message.emit("下载已暂停")
        
    def resume(self):
        self.is_paused = False
        self.log_message.emit("下载已恢复")
    
    def log(self, message):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_message.emit(f"[{timestamp}] {message}")

    def run(self):
        try:
            self.log(f"开始下载，URL: {self.url}")
            
            # 加载断点续传信息
            progress_file = os.path.join(self.output_dir, "download_progress.json")
            if os.path.exists(progress_file):
                with open(progress_file, 'r') as f:
                    self.downloaded_segments = set(json.load(f))
                self.log(f"找到断点续传信息，已下载 {len(self.downloaded_segments)} 个片段")

            # 验证URL是否是m3u8文件
            if not self.url.strip().lower().endswith('.m3u8'):
                self.error_occurred.emit("URL必须是m3u8文件")
                return

            # 先获取m3u8内容
            try:
                response = requests.get(self.url, headers=self.headers)
                response.raise_for_status()  # 检查响应状态

                # 尝试不同的编码方式
                content = None
                encodings = ['utf-8', 'iso-8859-1', 'cp1252', None]

                for encoding in encodings:
                    try:
                        if encoding:
                            content = response.content.decode(encoding)
                        else:
                            content = response.text
                        break
                    except Exception as e:
                        print(f"尝试使用 {encoding} 解码失败: {str(e)}")
                        continue

                if not content:
                    raise Exception("无法解码m3u8内容")

                # 解析m3u8内容
                playlist = m3u8.loads(content)

                # 如果m3u8 URL是相对路径，需要处理基础URL
                base_uri = self.url.rsplit('/', 1)[0] + '/'
                playlist.base_uri = base_uri

            except requests.exceptions.RequestException as e:
                self.error_occurred.emit(f"请求m3u8文件失败: {str(e)}")
                return
            except Exception as e:
                self.error_occurred.emit(f"处理m3u8文件失败: {str(e)}")
                return

            if not playlist.segments:
                self.error_occurred.emit("未找到可下载的视频片段")
                return

            total_segments = len(playlist.segments)
            print(f"找到 {total_segments} 个视频片段")
            print(f"第一个片段URL: {playlist.segments[0].uri}")  # 调试信息

            # 创建输出目录
            os.makedirs(self.output_dir, exist_ok=True)

            # 下载所有分片
            downloaded = len(self.downloaded_segments)
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = []
                for index, segment in enumerate(playlist.segments):
                    if str(index) in self.downloaded_segments:
                        continue
                        
                    while self.is_paused:
                        self.msleep(100)
                        
                    segment_url = segment.absolute_uri or urllib.parse.urljoin(base_uri, segment.uri)
                    future = executor.submit(
                        self.download_segment,
                        segment_url,
                        os.path.join(self.output_dir, f"segment_{index}.ts"),
                        index
                    )
                    futures.append(future)

                for future in concurrent.futures.as_completed(futures):
                    try:
                        index = future.result()
                        self.downloaded_segments.add(str(index))
                        downloaded += 1
                        progress = int((downloaded / total_segments) * 100)
                        self.progress_updated.emit(progress)
                        
                        # 保存进度
                        with open(progress_file, 'w') as f:
                            json.dump(list(self.downloaded_segments), f)
                            
                    except Exception as e:
                        self.error_occurred.emit(f"下载片段失败: {str(e)}")
                        return

            self.log("所有片段下载完成，开始合并...")
            self.merge_segments(total_segments)
            self.download_completed.emit()

        except Exception as e:
            self.error_occurred.emit(str(e))

    def download_segment(self, segment_url, output_path, index):
        try:
            if not os.path.exists(output_path):
                response = requests.get(segment_url, headers=self.headers)
                response.raise_for_status()
                with open(output_path, 'wb') as f:
                    f.write(response.content)
            return index
        except Exception as e:
            raise Exception(f"下载片段 {segment_url} 失败: {str(e)}")

    def merge_segments(self, total_segments):
        # 创建文件列表
        with open(os.path.join(self.output_dir, 'filelist.txt'), 'w') as f:
            for i in range(total_segments):
                f.write(f"file 'segment_{i}.ts'\n")

        # 使用ffmpeg合并
        subprocess.run([
            'ffmpeg', '-f', 'concat', '-safe', '0',
            '-i', os.path.join(self.output_dir, 'filelist.txt'),
            '-c', 'copy',
            os.path.join(self.output_dir, 'output.mp4')
        ])

class HeadersDialog(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("请求头管理")
        self.setMinimumWidth(600)
        layout = QVBoxLayout(self)

        # 请求头表格
        self.headers_table = QTableWidget()
        self.headers_table.setColumnCount(2)
        self.headers_table.setHorizontalHeaderLabels(["Header", "Value"])
        self.headers_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.headers_table)

        # 添加常用请求头按钮
        add_common_btn = QPushButton("添加常用请求头")
        add_common_btn.clicked.connect(self.add_common_headers)
        layout.addWidget(add_common_btn)

        # 添加和删除按钮布局
        btn_layout = QHBoxLayout()
        add_btn = QPushButton("添加")
        delete_btn = QPushButton("删除")
        add_btn.clicked.connect(self.add_header)
        delete_btn.clicked.connect(self.delete_header)
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(delete_btn)
        layout.addLayout(btn_layout)

    def add_common_headers(self):
        common_headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Referer": "https://javday.tv/"
        }
        for key, value in common_headers.items():
            self.add_header_row(key, value)

    def add_header(self):
        self.add_header_row("", "")

    def add_header_row(self, key, value):
        row = self.headers_table.rowCount()
        self.headers_table.insertRow(row)
        self.headers_table.setItem(row, 0, QTableWidgetItem(key))
        self.headers_table.setItem(row, 1, QTableWidgetItem(value))

    def delete_header(self):
        current_row = self.headers_table.currentRow()
        if current_row >= 0:
            self.headers_table.removeRow(current_row)

    def get_headers(self):
        headers = {}
        for row in range(self.headers_table.rowCount()):
            key = self.headers_table.item(row, 0)
            value = self.headers_table.item(row, 1)
            if key and value and key.text().strip() and value.text().strip():
                headers[key.text().strip()] = value.text().strip()
        return headers

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("M3U8视频下载器")
        self.setMinimumWidth(900)
        self.setMinimumHeight(700)
        
        # 设置应用程序样式
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f5f5;
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #cccccc;
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 10px;
                color: #333333;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: #1976D2;
            }
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                padding: 5px 15px;
                border-radius: 4px;
                min-width: 80px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
            QPushButton:disabled {
                background-color: #BDBDBD;
            }
            QLineEdit {
                padding: 5px;
                border: 1px solid #cccccc;
                border-radius: 4px;
                background-color: white;
                color: #333333;
            }
            QLineEdit:focus {
                border: 1px solid #2196F3;
            }
            QProgressBar {
                border: 1px solid #cccccc;
                border-radius: 4px;
                text-align: center;
                background-color: white;
                color: #333333;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #2196F3;
            }
            QLabel {
                color: #333333;
            }
            QSpinBox {
                padding: 5px;
                border: 1px solid #cccccc;
                border-radius: 4px;
                background-color: white;
                color: #333333;
            }
            QCheckBox {
                color: #333333;
            }
            QTextEdit {
                background-color: white;
                color: #333333;
                border: 1px solid #cccccc;
                border-radius: 4px;
                padding: 5px;
            }
            QHeaderView::section {
                background-color: #f0f0f0;
                color: #333333;
                padding: 5px;
                border: none;
                border-right: 1px solid #cccccc;
                border-bottom: 1px solid #cccccc;
            }
            QTableWidget {
                background-color: white;
                color: #333333;
                gridline-color: #cccccc;
            }
        """)

        # 主布局
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)

        # 创建分割器
        splitter = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(splitter)

        # 上半部分控件
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setSpacing(10)

        # 设置组
        settings_group = QGroupBox("下载设置")
        settings_layout = QVBoxLayout(settings_group)
        settings_layout.setSpacing(10)

        # URL输入
        url_layout = QHBoxLayout()
        url_label = QLabel("M3U8 URL:")
        url_label.setMinimumWidth(80)
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("请输入M3U8文件的URL地址")
        url_layout.addWidget(url_label)
        url_layout.addWidget(self.url_input)
        settings_layout.addLayout(url_layout)

        # 输出目录选择
        output_layout = QHBoxLayout()
        output_label = QLabel("下载目录:")
        output_label.setMinimumWidth(80)
        self.output_path = QLineEdit()
        self.output_path.setPlaceholderText("选择视频片段保存位置")
        browse_btn = QPushButton("浏览")
        browse_btn.setMaximumWidth(100)
        output_layout.addWidget(output_label)
        output_layout.addWidget(self.output_path)
        output_layout.addWidget(browse_btn)
        settings_layout.addLayout(output_layout)

        # MP4输出设置
        mp4_layout = QHBoxLayout()
        mp4_label = QLabel("MP4输出:")
        mp4_label.setMinimumWidth(80)
        self.mp4_path = QLineEdit()
        self.mp4_path.setPlaceholderText("选择合成后的MP4保存位置")
        mp4_browse_btn = QPushButton("浏览")
        mp4_browse_btn.setMaximumWidth(100)
        mp4_layout.addWidget(mp4_label)
        mp4_layout.addWidget(self.mp4_path)
        mp4_layout.addWidget(mp4_browse_btn)
        settings_layout.addLayout(mp4_layout)

        # 高级设置
        advanced_layout = QHBoxLayout()
        # 线程设置
        thread_label = QLabel("下载线程:")
        thread_label.setMinimumWidth(80)
        self.thread_spinner = QSpinBox()
        self.thread_spinner.setRange(1, 32)
        self.thread_spinner.setValue(8)
        self.thread_spinner.setMaximumWidth(100)
        
        # 自动合成选项
        self.auto_merge = QCheckBox("下载完成后自动合成MP4")
        self.auto_merge.setChecked(True)
        
        advanced_layout.addWidget(thread_label)
        advanced_layout.addWidget(self.thread_spinner)
        advanced_layout.addStretch()
        advanced_layout.addWidget(self.auto_merge)
        settings_layout.addLayout(advanced_layout)

        top_layout.addWidget(settings_group)

        # 控制组
        control_group = QGroupBox("下载控制")
        control_layout = QHBoxLayout(control_group)
        control_layout.setSpacing(10)

        # 请求头管理按钮
        self.headers_dialog = HeadersDialog()
        headers_btn = QPushButton("请求头管理")
        headers_btn.clicked.connect(self.show_headers_dialog)

        self.download_button = QPushButton("开始下载")
        self.pause_button = QPushButton("暂停")
        self.merge_button = QPushButton("合成MP4")
        
        # 添加按钮的信号连接
        self.download_button.clicked.connect(self.start_download)
        self.pause_button.clicked.connect(self.toggle_pause)
        self.merge_button.clicked.connect(self.merge_to_mp4)
        
        control_layout.addWidget(headers_btn)
        control_layout.addStretch()
        control_layout.addWidget(self.download_button)
        control_layout.addWidget(self.pause_button)
        control_layout.addWidget(self.merge_button)
        
        top_layout.addWidget(control_group)

        # 进度组
        progress_group = QGroupBox("下载进度")
        progress_layout = QVBoxLayout(progress_group)
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimumHeight(25)
        progress_layout.addWidget(self.progress_bar)
        
        top_layout.addWidget(progress_group)
        splitter.addWidget(top_widget)

        # 日志区域
        log_group = QGroupBox("下载日志")
        log_layout = QVBoxLayout(log_group)
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        log_layout.addWidget(self.log_output)
        splitter.addWidget(log_group)

        # 设置分割器比例
        splitter.setSizes([400, 300])

        # 连接信号
        browse_btn.clicked.connect(lambda: self.browse_path(self.output_path, "选择下载目录"))
        mp4_browse_btn.clicked.connect(lambda: self.browse_path(self.mp4_path, "选择MP4保存位置"))

        # 设置日志输出字体
        # 使用系统默认等宽字体
        if sys.platform == 'darwin':  # macOS
            log_font = QFont("Menlo", 10)
        elif sys.platform == 'win32':  # Windows
            log_font = QFont("Consolas", 10)
        else:  # Linux 和其他系统
            log_font = QFont("Monospace", 10)
        self.log_output.setFont(log_font)
        
        # 自定义进度条文本
        self.progress_bar.setFormat("下载进度: %p%")
        
        # 设置按钮图标（如果有的话）
        try:
            if os.path.exists("icons/download.png"):
                self.download_button.setIcon(QIcon("icons/download.png"))
            if os.path.exists("icons/pause.png"):
                self.pause_button.setIcon(QIcon("icons/pause.png"))
            if os.path.exists("icons/merge.png"):
                self.merge_button.setIcon(QIcon("icons/merge.png"))
        except Exception as e:
            print(f"加载图标出错: {str(e)}")
        
        # 添加工具提示
        self.url_input.setToolTip("输入m3u8文件的URL地址")
        self.output_path.setToolTip("选择下载的视频片段保存位置")
        self.mp4_path.setToolTip("选择合成后的MP4文件保存位置")
        self.thread_spinner.setToolTip("设置同时下载的线程数，建议值：4-16")
        self.auto_merge.setToolTip("下载完成后自动将视频片段合成为MP4文件")

        # 在设置完输出路径的连接后添加
        self.output_path.textChanged.connect(self.check_enable_merge_button)

    def log(self, message):
        """添加日志到日志输出区域"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_output.append(f"[{timestamp}] {message}")
        # 滚动到底部
        self.log_output.verticalScrollBar().setValue(
            self.log_output.verticalScrollBar().maximum()
        )

    def check_enable_merge_button(self):
        """检查是否存在ts文件并启用合成按钮"""
        try:
            input_dir = self.output_path.text()
            output_dir = self.mp4_path.text()
            
            if os.path.exists(input_dir):
                ts_files = [f for f in os.listdir(input_dir) if f.endswith('.ts')]
                if ts_files and output_dir:  # 确保同时有ts文件和输出路径
                    self.merge_button.setEnabled(True)
                    self.log("找到现有ts文件，可以进行合成")
                    return
            self.merge_button.setEnabled(False)
        except Exception as e:
            self.log(f"检查合成按钮状态时出错: {str(e)}")
            self.merge_button.setEnabled(False)

    def browse_path(self, line_edit, title):
        dir_path = QFileDialog.getExistingDirectory(self, title)
        if dir_path:
            line_edit.setText(dir_path)
            # 如果是选择下载目录，自动设置MP4输出路径（如果还没设置的话）
            if line_edit == self.output_path and not self.mp4_path.text():
                self.mp4_path.setText(dir_path)
            self.check_enable_merge_button()

    def merge_to_mp4(self):
        try:
            input_dir = self.output_path.text()
            output_dir = self.mp4_path.text()
            
            if not output_dir:
                raise Exception("请先选择MP4输出目录")
            
            if not os.path.exists(input_dir):
                raise Exception("下载目录不存在")
                
            if not os.path.exists(output_dir):
                os.makedirs(output_dir)  # 如果输出目录不��在，创建它
            
            # 获取URL中的文件名或使用自定义文件名
            url = self.url_input.text()
            if url:
                filename = url.split('/')[-1].split('.')[0]
            else:
                # 如果没有URL，使用时间戳作为文件名
                filename = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            output_file = os.path.join(output_dir, f"{filename}.mp4")
            
            # 检查输入目录是否存在ts文件
            ts_files = sorted([f for f in os.listdir(input_dir) if f.endswith('.ts')])
            if not ts_files:
                raise Exception("未找到可合成的视频片段")

            self.log("开始合成MP4...")
            self.progress_bar.setFormat("正在合成MP4...")
            self.merge_button.setEnabled(False)  # 合成时禁用按钮
            
            # 创建文件列表
            filelist_path = os.path.join(input_dir, 'filelist.txt')
            with open(filelist_path, 'w', encoding='utf-8') as f:
                for ts_file in ts_files:
                    f.write(f"file '{os.path.join(input_dir, ts_file)}'\n")

            # 使用ffmpeg合并
            result = subprocess.run([
                'ffmpeg', '-f', 'concat', '-safe', '0',
                '-i', filelist_path,
                '-c', 'copy',
                '-y',  # 覆盖已存在的文件
                output_file
            ], capture_output=True, text=True)

            if result.returncode == 0:
                self.log(f"MP4合成完成！保存至: {output_file}")
                QMessageBox.information(self, "成功", f"MP4合成完成！\n\n文件保存至:\n{output_file}")
                # 清理临时文件
                os.remove(filelist_path)
            else:
                raise Exception(f"FFmpeg错误: {result.stderr}")

        except Exception as e:
            error_msg = f"MP4合成失败: {str(e)}"
            self.log(error_msg)
            QMessageBox.critical(self, "错误", error_msg)
        finally:
            self.progress_bar.setFormat("下载进度: %p%")
            self.check_enable_merge_button()  # 重新检查是否可以合成

    def start_download(self):
        # 验证输入
        url = self.url_input.text().strip()
        output_dir = self.output_path.text().strip()
        mp4_dir = self.mp4_path.text().strip()

        if not url:
            QMessageBox.warning(self, "错误", "请输入M3U8 URL")
            return
        if not output_dir:
            QMessageBox.warning(self, "错误", "请选择下载目录")
            return
        if not mp4_dir and self.auto_merge.isChecked():
            QMessageBox.warning(self, "错误", "请选择MP4保存位置")
            return

        # 其他下载代码保持不变...
        try:
            self.download_worker = DownloadWorker(
                url,
                self.headers_dialog.get_headers(),
                output_dir,
                self.thread_spinner.value()
            )
            self.download_worker.progress_updated.connect(self.update_progress)
            self.download_worker.download_completed.connect(self.download_finished)
            self.download_worker.error_occurred.connect(self.handle_error)
            self.download_worker.log_message.connect(self.log)
            
            self.download_button.setEnabled(False)
            self.pause_button.setEnabled(True)
            self.merge_button.setEnabled(False)
            self.progress_bar.setValue(0)
            self.download_worker.start()
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"启动下载失败: {str(e)}")
            self.download_button.setEnabled(True)
            self.pause_button.setEnabled(False)

    def download_finished(self):
        self.download_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.progress_bar.setValue(100)
        self.check_enable_merge_button()  # 下载完成后检查是否可以合成
        
        if self.auto_merge.isChecked():
            self.merge_to_mp4()
        else:
            QMessageBox.information(self, "完成", "下载完成！")
        self.log("下载完成")

    def toggle_pause(self):
        if hasattr(self, 'download_worker'):
            if self.download_worker.is_paused:
                self.download_worker.resume()
                self.pause_button.setText("暂停")
            else:
                self.download_worker.pause()
                self.pause_button.setText("继续")

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def handle_error(self, error_message):
        self.download_button.setEnabled(True)
        QMessageBox.critical(self, "错误", error_message)
        print(f"发生错误: {error_message}")

    def show_headers_dialog(self):
        self.headers_dialog.show()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec()) 