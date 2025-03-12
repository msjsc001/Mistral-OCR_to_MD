"""
Mistral AI PDF OCR 脚本 
制作时间：2025-03-12_02:22:30 

功能：
1. 使用 Mistral AI 的 OCR 服务将 PDF 文件转换为 Markdown 格式的文本。
2. 如果 PDF 文件超过 Mistral AI 的大小限制，会自动将其拆分成多个较小的 PDF 文件，然后分别进行 OCR 处理。
3. 提取 PDF 中的图片，并保存到单独的文件夹中。
4. 将 OCR 识别的文本和图片链接整合到一个 Markdown 文件中。
5. 自动获取Mistral AI API允许的最大文件大小, 并据此拆分PDF文件.

使用方法：
1. 安装必要的库：
   pip install mistralai PyPDF2
2. 将此脚本保存为 .py 文件 (例如 mistral_ocr.py)。
3. 在脚本尾部中设置以下变量：
   - API_KEY: 你的 Mistral AI API 密钥。
   - PDF_PATH: 要处理的 PDF 文件的路径。
4. 在命令行或VScode中运行脚本：
   python mistral_ocr.py

输出：
- 处理结果将保存在脚本所在目录下，以 PDF 文件名命名的文件夹中。
- 文件夹内包含一个 Markdown 文件（包含 OCR 识别的文本和图片链接）和一个 images 文件夹（包含提取的图片）。
- 如果 PDF 文件被拆分，拆分后的 PDF 文件将保存在一个单独的文件夹中（不会自动删除）。

注意事项：
- 确保你的 Mistral AI API 密钥有效且有足够的配额。
- PDF 文件路径可以是绝对路径或相对路径（相对于脚本文件）。
- 此脚本会自动处理文件大小限制和拆分，无需手动干预。
- 输出的 Markdown 文件名包含时间戳，以避免覆盖。
- 拆分后的临时PDF文件不会自动删除，这样二次生成时就不用再切.
- 如果PDF中有非字符号，识别可能出一些看不懂的乱码，这是 Mistral AI 的问题。
"""

from mistralai import Mistral
from pathlib import Path
import os
import base64
from mistralai import DocumentURLChunk
from mistralai.models import OCRResponse
from PyPDF2 import PdfReader, PdfWriter  # 导入 PyPDF2 库
import shutil
import datetime
import re  # 导入正则表达式模块

def save_ocr_results(ocr_response: OCRResponse, output_file: str, images_dir: str) -> None:
    """保存 OCR 结果，包括 Markdown 文本和图片。"""
    all_markdowns = []

    for page_num, page in enumerate(ocr_response.pages):
        # 保存图片
        page_images = {}
        for img in page.images:
            try:
                img_data = base64.b64decode(img.image_base64.split(',')[1])
            except Exception as e:
                print(f"解码图片失败: {e}")
                continue

            img_filename = f"page_{page_num + 1}_{img.id}.png"  # 图片文件名包含页码
            img_path = os.path.join(images_dir, img_filename)
            try:
                with open(img_path, 'wb') as f:
                    f.write(img_data)
                page_images[img.id] = f"images/{img_filename}"  # 相对路径
            except Exception as e:
                 print(f"保存图片失败: {e}")

        # 使用新的图片路径替换 Markdown 中的占位符（如果有图片）
        page_markdown = page.markdown
        for img_id, img_path in page_images.items():
            page_markdown = page_markdown.replace(f"![{img_id}]({img_id})", f"![{img_id}]({img_path})")


        all_markdowns.append(page_markdown)


    # 追加 Markdown 文本
    with open(output_file, 'a', encoding='utf-8') as f:
        f.write("\n\n".join(all_markdowns))
        f.write("\n\n")

def process_single_pdf(pdf_path: str, api_key: str, output_file: str, client: Mistral, images_dir: str):
    """处理单个 PDF 文件（可能是拆分后的文件）。"""
    pdf_file = Path(pdf_path)
    if not pdf_file.is_file():
        raise FileNotFoundError(f"PDF 文件不存在: {pdf_path}")

    # 上传并处理 PDF
    uploaded_file = client.files.upload(
        file={
            "file_name": pdf_file.name,  # 使用包含 _part_ 的文件名
            "content": pdf_file.read_bytes(),
        },
        purpose="ocr",
    )

    signed_url = client.files.get_signed_url(file_id=uploaded_file.id, expiry=1)
    pdf_response = client.ocr.process(
        document=DocumentURLChunk(document_url=signed_url.url),
        model="mistral-ocr-latest",
        include_image_base64=True  # 获取base64图片
    )

    # 保存结果到指定的 Markdown 文件和图片文件夹
    save_ocr_results(pdf_response, output_file, images_dir)
    print(f"OCR 处理完成: {pdf_path}")


def get_max_file_size(client: Mistral) -> int:
    """
    获取Mistral AI允许上传的PDF最大文件大小.

    参数:
        client: Mistral AI客户端

    返回:
        int: 允许最大文件大小
    """
    try:
        limits = client.usage.get_limits()
        max_size_mb = limits.ocr_max_file_size_mb
        # 将MB转换为字节，并减去1MB作为安全边际
        max_size_bytes = (max_size_mb - 1) * 1024 * 1024
        return int(max_size_bytes)  # 转为int类型
    except Exception as e:
        print(f"获取最大文件大小失败, 使用默认50MB: {e}")
        return 50 * 1024 * 1024  # 默认50MB

def process_pdf(pdf_path: str, api_key: str) -> None:  # 移除output_file参数
   # 初始化客户端
    client = Mistral(api_key=api_key)

    # 确认PDF文件存在
    pdf_file = Path(pdf_path)
    if not pdf_file.is_file():
        raise FileNotFoundError(f"PDF文件不存在: {pdf_path}")

    # 获取最大文件大小限制
    max_file_size = get_max_file_size(client)

    # 创建输出目录和图片目录
    script_dir = Path(__file__).resolve().parent
    output_dir = script_dir / f"{pdf_file.stem}_ocr_results"  # 修改输出目录名
    images_dir = output_dir / "images"
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(images_dir, exist_ok=True)

    # 生成输出 Markdown 文件名
    now = datetime.datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"{pdf_file.stem}_{timestamp}.md"

    # 清空或创建输出文件
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("")

    # 拆分 PDF (如果文件太大且尚未拆分)
    split_dir = script_dir / f"{pdf_file.stem}_split"  # 拆分文件目录
    if pdf_file.stat().st_size > max_file_size and not list(split_dir.glob(f"{pdf_file.stem}_part_*.pdf")):  # 检查是否需要拆分
        print("PDF 文件太大，正在拆分...")
        reader = PdfReader(pdf_file)
        num_pages = len(reader.pages)

        # 计算拆分策略
        estimated_page_size = pdf_file.stat().st_size / num_pages
        split_size = max(1, int(max_file_size // estimated_page_size))

        os.makedirs(split_dir, exist_ok=True)  # 创建拆分目录

        for i in range(0, num_pages, split_size):
            writer = PdfWriter()
            for j in range(i, min(i + split_size, num_pages)):
                writer.add_page(reader.pages[j])

            part_num = i // split_size + 1
            split_file_path = split_dir / f"{pdf_file.stem}_part_{part_num}.pdf"

            with open(split_file_path, "wb") as output_pdf:
                writer.write(output_pdf)

            print(f"拆分文件已保存: {split_file_path}")

    # 处理 PDF 文件（如果已拆分，则处理拆分后的文件）
    if list(split_dir.glob(f"{pdf_file.stem}_part_*.pdf")):  # 检查是否有拆分文件
        print("检测到已拆分的文件，正在处理...")
        for split_file in sorted(split_dir.glob(f"{pdf_file.stem}_part_*.pdf")):
            process_single_pdf(str(split_file), api_key, str(output_file), client, str(images_dir))
    else:
        # 文件大小在限制范围内，直接处理
        process_single_pdf(str(pdf_file), api_key, str(output_file), client, str(images_dir))

    print(f"OCR处理完成, 结果保存在: {output_file}")

if __name__ == "__main__":
    # 使用示例
    API_KEY = "你的kye"  # 输入你的API KEY
    PDF_PATH = r"X:\你的路径\pdf名.pdf"  # 输入你的PDF目录

    process_pdf(PDF_PATH, API_KEY)
