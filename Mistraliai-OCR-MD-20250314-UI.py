import customtkinter as ctk
from mistralai import Mistral
from pathlib import Path
import os
import base64
from mistralai import DocumentURLChunk
from mistralai.models import OCRResponse, SDKError
from PyPDF2 import PdfReader, PdfWriter
import shutil
import datetime
import re
import time
from threading import Thread
import configparser

# --- 版本号 ---
VERSION = "1.3.9"  # 版本号更新 - 移除 API 连接测试
CONFIG_FILE = "config.ini"

# --- 原有函数 (save_ocr_results, process_single_pdf, get_max_file_size) ---
# (这些函数保持不变，直接复制之前的版本)
def save_ocr_results(ocr_response: OCRResponse, output_file: str, images_dir: str) -> None:
    """保存 OCR 结果，包括 Markdown 文本和图片。"""
    all_markdowns = []

    for page_num, page in enumerate(ocr_response.pages):
        page_images = {}
        for img in page.images:
            try:
                img_data = base64.b64decode(img.image_base64.split(',')[1])
            except Exception as e:
                print(f"解码图片失败: {e}")
                continue

            img_filename = f"page_{page_num + 1}_{img.id}.png"
            img_path = os.path.join(images_dir, img_filename)
            try:
                with open(img_path, 'wb') as f:
                    f.write(img_data)
                page_images[img.id] = f"images/{img_filename}"
            except Exception as e:
                 print(f"保存图片失败: {e}")

        page_markdown = page.markdown
        for img_id, img_path in page_images.items():
            page_markdown = page_markdown.replace(f"![{img_id}]({img_id})", f"![{img_id}]({img_path})")

        all_markdowns.append(page_markdown)

    with open(output_file, 'a', encoding='utf-8') as f:
        f.write("\n\n".join(all_markdowns))
        f.write("\n\n")

def process_single_pdf(pdf_path: str, api_key: str, output_file: str, client: Mistral, images_dir: str):
    """处理单个 PDF 文件（可能是拆分后的文件）。"""
    pdf_file = Path(pdf_path)
    if not pdf_file.is_file():
        raise FileNotFoundError(f"PDF 文件不存在: {pdf_path}")

    retries = 3
    for attempt in range(retries):
        try:
            uploaded_file = client.files.upload(
                file={"file_name": pdf_file.name, "content": pdf_file.read_bytes()},
                purpose="ocr",
            )
            signed_url = client.files.get_signed_url(file_id=uploaded_file.id, expiry=1)
            pdf_response = client.ocr.process(
                document=DocumentURLChunk(document_url=signed_url.url),
                model="mistral-ocr-latest",
                include_image_base64=True
            )
            save_ocr_results(pdf_response, output_file, images_dir)
            print(f"OCR 处理完成: {pdf_path}")
            break

        except SDKError as e:
            if attempt == retries - 1:
                raise
            print(f"处理 {pdf_path} 时发生错误: {e}, 正在重试 ({attempt + 1}/{retries})")
            time.sleep(5)

def get_max_file_size(client: Mistral, default_max_size_mb: int) -> int:
    """获取Mistral AI允许上传的PDF最大文件大小, 如果获取失败则使用用户提供的默认值."""
    try:
        limits = client.usage.get_limits()
        max_size_mb = limits.ocr_max_file_size_mb
        max_size_bytes = (max_size_mb - 1) * 1024 * 1024
        return int(max_size_bytes)
    except Exception as e:
        print(f"获取最大文件大小失败, 使用用户设置的 {default_max_size_mb}MB: {e}")
        return default_max_size_mb * 1024 * 1024


def process_pdf_thread(pdf_path: str, api_key: str, max_file_size_mb: int, app):
    """PDF 处理函数 (在线程中运行)"""
    try:
        process_pdf(pdf_path, api_key, max_file_size_mb, app)
        app.after(0, lambda: app.on_thread_done('OCR 处理完成!'))
    except Exception as e:
        app.after(0, lambda: app.on_thread_error(str(e)))


def process_pdf(pdf_path: str, api_key: str, max_file_size_mb: int, app=None) -> None:
    """为了解耦, 此函数不直接操作UI, 通过app对象与UI通信."""
    client = Mistral(api_key=api_key)  # 不需要 test_api_connection，直接创建 client
    pdf_file = Path(pdf_path)
    if not pdf_file.is_file():
        raise FileNotFoundError(f"PDF文件不存在: {pdf_path}")

    max_file_size = get_max_file_size(client, max_file_size_mb)
    script_dir = Path(__file__).resolve().parent
    output_base_dir = Path(app.output_dir_var.get()) if app and app.output_dir_var.get() else script_dir
    output_dir = output_base_dir / f"{pdf_file.stem}_ocr_results"

    images_dir = output_dir / "images"
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(images_dir, exist_ok=True)

    now = datetime.datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"{pdf_file.stem}_{timestamp}.md"

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("")

    split_dir = script_dir / f"{pdf_file.stem}_split"
    os.makedirs(split_dir, exist_ok=True)

    if pdf_file.stat().st_size > max_file_size and not list(split_dir.glob(f"{pdf_file.stem}_part_*.pdf")):
        print("PDF 文件太大，正在拆分...")
        if app:
            app.log_message("PDF 文件太大，正在拆分...")

        reader = PdfReader(pdf_file)
        num_pages = len(reader.pages)
        estimated_page_size = pdf_file.stat().st_size / num_pages
        split_size = max(1, int(max_file_size // estimated_page_size))

        for i in range(0, num_pages, split_size):
            writer = PdfWriter()
            for j in range(i, min(i + split_size, num_pages)):
                writer.add_page(reader.pages[j])
            part_num = i // split_size + 1
            split_file_path = split_dir / f"{pdf_file.stem}_part_{part_num}.pdf"
            with open(split_file_path, "wb") as output_pdf:
                writer.write(output_pdf)
            print(f"拆分文件已保存: {split_file_path}, 大小: {split_file_path.stat().st_size / (1024 * 1024):.2f} MB")
            if app:
                app.log_message(f"拆分文件已保存: {split_file_path}, 大小: {split_file_path.stat().st_size / (1024 * 1024):.2f} MB")

    if list(split_dir.glob(f"{pdf_file.stem}_part_*.pdf")):
        print("检测到已拆分的文件，正在处理...")
        if app:
            app.log_message("检测到已拆分的文件，正在处理...")
        for split_file in sorted(split_dir.glob(f"{pdf_file.stem}_part_*.pdf")):
            process_single_pdf(str(split_file), api_key, str(output_file), client, str(images_dir))
            if app:
                app.log_message(f"处理完成: {split_file}")
    else:
        process_single_pdf(str(pdf_file), api_key, str(output_file), client, str(images_dir))

    print(f"OCR处理完成, 结果保存在: {output_file}")
    if app:
        app.log_message(f"OCR处理完成, 结果保存在: {output_file}")

# 不需要 test_api_connection 函数了

class OCRApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title(f"Mistral AI PDF OCR 工具 - v{VERSION}")
        self.geometry("800x650")
        ctk.set_default_color_theme("blue")

        self.appearance_mode = "light"
        self.api_key = ""
        self.output_dir = ""
        self.help_icon = None

        self.create_widgets()

        self.config = configparser.ConfigParser()
        self.load_config()

        self.set_appearance_mode(self.appearance_mode)

        if self.api_key:
            self.api_key_entry.insert(0, self.api_key)
        if self.output_dir:
            self.output_dir_var.set(self.output_dir)

    def create_widgets(self):
        # --- 标题栏 ---
        title_frame = ctk.CTkFrame(self, fg_color="transparent")
        title_frame.grid(row=0, column=0, columnspan=3, sticky="ew")

        ctk.CTkLabel(title_frame, text=f"Mistral AI PDF OCR 工具 - v{VERSION}", font=("Arial", 18, "bold")).pack(side=ctk.LEFT, padx=20, pady=10)

        help_button = ctk.CTkButton(title_frame, text="帮助", command=self.show_help, width=80, corner_radius=10, compound="left")
        help_button.pack(side=ctk.RIGHT, padx=10, pady=10)

        self.mode_switch = ctk.CTkButton(title_frame, text="",  width=40, command=self.toggle_mode)
        self.mode_switch.pack(side=ctk.RIGHT, padx=20, pady=10)
        self.update_mode_button()

        # --- 主要内容 ---
        ctk.CTkLabel(self, text="Mistral AI API 密钥:", anchor="w").grid(row=1, column=0, padx=20, pady=(10, 5), sticky="w")
        self.api_key_entry = ctk.CTkEntry(self, width=450, show="*", corner_radius=8)  # 增加了 width
        self.api_key_entry.grid(row=1, column=1, padx=(0, 20), pady=(10, 5), sticky="ew", columnspan=2)  # columnspan=2, 调整 padx
        # 移除了 "测试连接" 按钮

        ctk.CTkLabel(self, text="选择 PDF 文件:", anchor="w").grid(row=2, column=0, padx=20, pady=5, sticky="w")
        self.pdf_path_var = ctk.StringVar()
        self.pdf_path_entry = ctk.CTkEntry(self, width=400, textvariable=self.pdf_path_var, state="readonly", corner_radius=8)
        self.pdf_path_entry.grid(row=2, column=1, padx=(0, 5), pady=5, sticky="ew")
        ctk.CTkButton(self, text="浏览", command=self.browse_pdf, width=100, corner_radius=8).grid(row=2, column=2, padx=(5, 20), pady=5)

        ctk.CTkLabel(self, text="最大文件大小 (MB):", anchor="w").grid(row=3, column=0, padx=20, pady=5, sticky="w")
        self.max_size_entry = ctk.CTkEntry(self, width=50, corner_radius=8)
        self.max_size_entry.insert(0, "45")
        self.max_size_entry.grid(row=3, column=1, padx=(0, 5), pady=5, sticky="w")

        ctk.CTkLabel(self, text="输出目录:", anchor="w").grid(row=4, column=0, padx=20, pady=5, sticky="w")
        self.output_dir_var = ctk.StringVar()
        self.output_dir_entry = ctk.CTkEntry(self, width=400, textvariable=self.output_dir_var, state="readonly", corner_radius=8)
        self.output_dir_entry.grid(row=4, column=1, padx=(0, 5), pady=5, sticky="ew")
        ctk.CTkButton(self, text="浏览", command=self.browse_output_dir, width=100, corner_radius=8).grid(row=4, column=2, padx=(5, 20), pady=5)

        self.status_label = ctk.CTkLabel(self, text="就绪", anchor="w")
        self.status_label.grid(row=5, column=0, columnspan=3, padx=20, pady=5, sticky="ew")

        button_frame = ctk.CTkFrame(self, fg_color="transparent")
        button_frame.grid(row=6, column=0, columnspan=3, pady=10)
        self.start_button = ctk.CTkButton(button_frame, text="开始 OCR", command=self.start_ocr, width=200, height=40, corner_radius=10)
        self.start_button.pack(side=ctk.LEFT, padx=10)

        self.progress_bar = ctk.CTkProgressBar(self, width=400, height=20, corner_radius=8)
        self.progress_bar.grid(row=7, column=0, columnspan=3, padx=20, pady=10, sticky="ew")
        self.progress_bar.set(0)
        self.progress_bar.grid_remove()

        ctk.CTkLabel(self, text="日志:", anchor="w").grid(row=8, column=0, padx=20, pady=(10, 0), sticky="w")
        self.log_text = ctk.CTkTextbox(self, width=700, height=250, wrap=ctk.WORD, state="disabled", corner_radius=8)
        self.log_text.grid(row=9, column=0, columnspan=3, padx=20, pady=(0, 20), sticky="nsew")

        self.columnconfigure(1, weight=1)
        self.rowconfigure(9, weight=1)

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                self.config.read(CONFIG_FILE)
                self.api_key = self.config.get("Settings", "api_key", fallback="")
                self.appearance_mode = self.config.get("Settings", "appearance_mode", fallback="light")
                self.output_dir = self.config.get("Paths", "output_dir", fallback="")
            except configparser.Error:
                print("读取配置文件失败, 将使用默认值")
                self.api_key = ""
                self.appearance_mode = "light"
                self.output_dir = ""
        else:
            self.api_key = ""
            self.appearance_mode = "light"
            self.output_dir = ""

    def save_config(self):
        try:
            self.config["Settings"] = {
                "api_key": self.api_key_entry.get(),
                "appearance_mode": self.appearance_mode
            }
            self.config["Paths"] = {
                "output_dir": self.output_dir_entry.get(),
            }
            with open(CONFIG_FILE, "w") as configfile:
                self.config.write(configfile)
        except configparser.Error as e:
            print(f"保存配置文件失败: {e}")

    def set_appearance_mode(self, mode):
        self.appearance_mode = mode.lower()
        ctk.set_appearance_mode(self.appearance_mode)
        self.update_mode_button()

    def update_mode_button(self):
        if self.appearance_mode == "dark":
            self.mode_switch.configure(text="深")
        else:
            self.mode_switch.configure(text="浅")

    def toggle_mode(self):
        if self.appearance_mode == "dark":
            self.set_appearance_mode("light")
        else:
            self.set_appearance_mode("dark")
        self.save_config()

    def browse_pdf(self):
        filepath = ctk.filedialog.askopenfilename(filetypes=[("PDF Files", "*.pdf")])
        if filepath:
            self.pdf_path_var.set(filepath)

    def browse_output_dir(self):
        filepath = ctk.filedialog.askdirectory()
        if filepath:
            self.output_dir_var.set(filepath)

    # 移除了 test_api 方法

    def start_ocr(self):
        api_key = self.api_key_entry.get()
        pdf_path = self.pdf_path_var.get()
        try:
            max_size_mb = int(self.max_size_entry.get())
        except ValueError:
            self.log_message("请输入有效的最大文件大小 (整数)!", text_color='red')
            return

        if not api_key or not pdf_path:
            self.log_message("请填写 API 密钥并选择 PDF 文件!", text_color='red')
            return

        self.start_button.configure(state="disabled")
        self.progress_bar.grid()
        self.progress_bar.start()
        self.status_label.configure(text="正在处理中...")

        # 直接在 start_ocr 中创建 Mistral 客户端
        thread = Thread(target=process_pdf_thread, args=(pdf_path, api_key, max_size_mb, self))
        thread.start()

    def on_thread_done(self, message):
        self.start_button.configure(state="normal")
        self.progress_bar.stop()
        self.progress_bar.grid_remove()
        self.status_label.configure(text=message, text_color='green')

    def on_thread_error(self, error_message):
         self.start_button.configure(state="normal")
         self.progress_bar.stop()
         self.progress_bar.grid_remove()
         self.status_label.configure(text=f"发生错误: {error_message}", text_color='red')

    def log_message(self, message, text_color='grey'):
        self.log_text.configure(state="normal")
        self.log_text.insert(ctk.END, message + "\n", text_color)
        self.log_text.configure(state="disabled")
        self.log_text.see(ctk.END)

    def show_help(self):
        help_window = ctk.CTkToplevel(self)
        help_window.title("帮助")
        help_window.geometry("600x450")
        help_window.resizable(False, False)

    def show_help(self):
            help_window = ctk.CTkToplevel(self)
            help_window.title("帮助")
            help_window.geometry("600x450")
            help_window.resizable(False, False)
            help_window.columnconfigure(0, weight=1) # 让第 0 列可以扩展
            help_window.rowconfigure(0, weight=1)    # 让第 0 行可以扩展

            help_text = f"""
            Mistral AI PDF OCR 工具 (版本: {VERSION})

            功能：
            本工具使用 Mistral AI 的 OCR 服务将 PDF 文件转换为 Markdown 格式的文本，并提取 PDF 中的图片。

            使用步骤：
            1. 填写 API 密钥：
            - 在本工具的“Mistral AI API 密钥”输入框中粘贴您的 API 密钥。
            - （不再需要测试连接）
            2. 选择 PDF 文件：
            - 点击“浏览”按钮，选择您要进行 OCR 处理的 PDF 文件。
            3. 设置最大文件大小 (可选)：
            - 如果您的 PDF 文件较大，可以调整“最大文件大小 (MB)”设置。
                通常情况下，程序会自动处理文件大小限制，无需手动设置。
            4. 选择 输出目录 (可选):
            - 点击 "输出目录" 旁边的 "浏览" 按钮，选择您希望保存 OCR 结果的文件夹。
            - 如果不选择，结果将默认保存在程序脚本所在的目录。
            5. 开始 OCR：
            - 点击“开始 OCR”按钮。
            6. 查看结果：
            - OCR 处理完成后，结果将保存在您指定的输出目录中 (或默认目录)。
            - 文件夹内包含一个 Markdown 文件（包含 OCR 识别的文本和图片链接）和一个 images 文件夹（包含提取的图片）。
            - 如果 PDF 文件被拆分，拆分后的 PDF 文件将保存在一个单独的文件夹中。

            注意事项：
            - 确保您的 Mistral AI API 密钥有效且有足够的配额。
            - PDF 文件路径可以是绝对路径或相对路径。
            - 此程序会自动处理文件大小限制和拆分。
            - 输出的 Markdown 文件名包含时间戳，以避免覆盖。
            - 拆分后的临时 PDF 文件不会自动删除。
            """
            help_label = ctk.CTkTextbox(help_window,  wrap=ctk.WORD,  font=("Arial", 12)) # 移除 width=580
            help_label.insert("0.0", help_text)
            help_label.configure(state="disabled")
            help_label.grid(row=0, column=0, padx=20, pady=20, sticky="nsew") # 使用 grid 布局，并设置 sticky

if __name__ == "__main__":
    app = OCRApp()
    app.mainloop()
