# Mistral-OCR_to_MD
使用Mistral-OCR把扫描版PDF书籍转换为Markdown格式（带图）

# Mistral AI PDF OCR 脚本 
制作时间：2025-03-12_02:22:30 

# 功能：
1. 使用 Mistral AI 的 OCR 服务将 PDF 文件转换为 Markdown 格式的文本。
2. 如果 PDF 文件超过 Mistral AI 的大小限制，会自动将其拆分成多个较小的 PDF 文件，然后分别进行 OCR 处理。
3. 提取 PDF 中的图片，并保存到单独的文件夹中。
4. 将 OCR 识别的文本和图片链接整合到一个 Markdown 文件中。
5. 自动获取Mistral AI API允许的最大文件大小, 并据此拆分PDF文件.

# 使用方法：
1. 安装必要的库：
   pip install mistralai PyPDF2
2. 将此脚本保存为 .py 文件 (例如 mistral_ocr.py)。
3. 在脚本尾部中设置以下变量：
   - API_KEY: 你的 Mistral AI API 密钥。
   - PDF_PATH: 要处理的 PDF 文件的路径。
4. 在命令行或VScode中运行脚本：
   python mistral_ocr.py

# 输出：
- 处理结果将保存在脚本所在目录下，以 PDF 文件名命名的文件夹中。
- 文件夹内包含一个 Markdown 文件（包含 OCR 识别的文本和图片链接）和一个 images 文件夹（包含提取的图片）。
- 如果 PDF 文件被拆分，拆分后的 PDF 文件将保存在一个单独的文件夹中（不会自动删除）。

# 注意事项：
- 确保你的 Mistral AI API 密钥有效且有足够的配额。
- PDF 文件路径可以是绝对路径或相对路径（相对于脚本文件）。
- 此脚本会自动处理文件大小限制和拆分，无需手动干预。
- 输出的 Markdown 文件名包含时间戳，以避免覆盖。
- 拆分后的临时PDF文件不会自动删除，这样二次生成时就不用再切.
- 如果PDF中有非字符号，识别可能出一些看不懂的乱码，这是 Mistral AI 的问题。
