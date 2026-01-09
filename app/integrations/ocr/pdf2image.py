"""
PDF to Image Converter

Convert uploaded PDF files to JPG images.
Each page of the PDF will be converted to a separate JPG image and output a share url.
"""
import io
import tempfile
from pathlib import Path
from typing import List, Union, Tuple
from pdf2image import convert_from_bytes, convert_from_path
from PIL import Image


def pdf_to_images(
    file_data: Union[bytes, io.IOBase],
    dpi: int = 200,
    fmt: str = "JPEG",
    quality: int = 85,
    first_page: int = None,
    last_page: int = None
) -> List[Tuple[bytes, str]]:
    """
    Convert PDF file to JPG images (one image per page)
    
    :param file_data: PDF file binary data (bytes) or file stream (like UploadFile.file)
    :param dpi: Resolution for conversion (default: 200, higher = better quality but larger file)
    :param fmt: Output image format (default: "JPEG", can be "PNG", "TIFF", etc.)
    :param quality: JPEG quality (1-100, default: 85)
    :param first_page: First page to process (None = start from first page)
    :param last_page: Last page to process (None = process until last page)
    :return: List of tuples containing (image_bytes, suggested_filename)
    """
    
    try:
        # Convert file stream to bytes if necessary
        if not isinstance(file_data, bytes):
            file_data.seek(0)
            pdf_bytes = file_data.read()
        else:
            pdf_bytes = file_data
        
        # Convert PDF to PIL Image objects
        images = convert_from_bytes(
            pdf_bytes,
            dpi=dpi,
            first_page=first_page,
            last_page=last_page,
            fmt=fmt
        )
        
        # Convert PIL Images to bytes
        result = []
        for idx, image in enumerate(images, start=1):
            # Create BytesIO buffer to store image bytes
            img_buffer = io.BytesIO()
            
            # Save image to buffer
            if fmt.upper() == "JPEG" or fmt.upper() == "JPG":
                # Convert RGBA to RGB for JPEG (JPEG doesn't support transparency)
                if image.mode in ("RGBA", "LA", "P"):
                    rgb_image = Image.new("RGB", image.size, (255, 255, 255))
                    rgb_image.paste(image, mask=image.split()[-1] if image.mode == "RGBA" else None)
                    image = rgb_image
                
                image.save(img_buffer, format="JPEG", quality=quality, optimize=True)
                file_extension = "jpg"
            else:
                image.save(img_buffer, format=fmt, quality=quality, optimize=True)
                file_extension = fmt.lower()
            
            # Get bytes from buffer
            img_bytes = img_buffer.getvalue()
            img_buffer.close()
            
            # Generate suggested filename
            suggested_filename = f"page_{idx:03d}.{file_extension}"
            
            result.append((img_bytes, suggested_filename))
        
        return result
    
    except Exception as e:
        raise Exception(f"PDF conversion failed: {str(e)}")


def pdf_to_single_image(
    file_data: Union[bytes, io.IOBase],
    dpi: int = 200,
    quality: int = 85,
    page_number: int = 1
) -> Tuple[bytes, str]:
    """
    Convert a single page of PDF to JPG image
    
    :param file_data: PDF file binary data (bytes) or file stream
    :param dpi: Resolution for conversion (default: 200)
    :param quality: JPEG quality (1-100, default: 85)
    :param page_number: Page number to convert (1-indexed, default: 1)
    :return: Tuple containing (image_bytes, suggested_filename)
    """
    
    results = pdf_to_images(
        file_data=file_data,
        dpi=dpi,
        quality=quality,
        first_page=page_number,
        last_page=page_number
    )
    
    if not results:
        raise Exception(f"Failed to convert page {page_number}")
    
    return results[0]


def get_pdf_page_count(file_data: Union[bytes, io.IOBase]) -> int:
    """
    Get the number of pages in a PDF file
    
    :param file_data: PDF file binary data (bytes) or file stream
    :return: Number of pages
    """
    try:
        # Convert file stream to bytes if necessary
        if not isinstance(file_data, bytes):
            file_data.seek(0)
            pdf_bytes = file_data.read()
        else:
            pdf_bytes = file_data
        
        # Convert PDF to get page count
        images = convert_from_bytes(pdf_bytes, dpi=72)  # Low DPI just to count pages
        return len(images)
    
    except Exception as e:
        raise Exception(f"Failed to get PDF page count: {str(e)}")

