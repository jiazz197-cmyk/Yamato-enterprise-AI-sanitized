import requests
import json
from typing import Dict, Any, Optional, List
import re
import time 


def extract_layout_info(image_url: str, api_url: str = "http://localhost:80/ocr/dotsocr/v1/chat/completions") -> List[Dict[str, Any]]:
    """
    Extract layout information from PDF image using DOTS OCR API.
    
    Args:
        image_url: URL of the image to be processed
        api_url: API endpoint URL (default: localhost)
        
    Returns:
        List of layout elements, each containing bbox, category, and optional text
        
    Raises:
        requests.exceptions.RequestException: If the API request fails
        json.JSONDecodeError: If the response content cannot be parsed
        KeyError: If the response structure is unexpected
    """
    headers = {
        "Content-Type": "application/json"
    }
    
    prompt_text = (
        "Please output the layout information from the PDF image, including each layout element's bbox, "
        "its category, and the corresponding text content within the bbox.\n\n"
        "1. Bbox format: [x1, y1, x2, y2]\n\n"
        "2. Layout Categories: The possible categories are ['Caption', 'Footnote', 'Formula', 'List-item', "
        "'Page-footer', 'Page-header', 'Picture', 'Section-header', 'Table', 'Text', 'Title'].\n\n"
        "3. Text Extraction & Formatting Rules:\n"
        "    - Picture: For the 'Picture' category, the text field should be omitted.\n"
        "    - Formula: Format its text as LaTeX.\n"
        "    - Table: Format its text as HTML.\n"
        "    - All Others (Text, Title, etc.): Format their text as Markdown.\n\n"
        "4. Constraints:\n"
        "    - The output text must be the original text from the image, with no translation.\n"
        "    - All layout elements must be sorted according to human reading order.\n\n"
        "5. Final Output: The entire output must be a single JSON object.\n"
    )
    
    payload = {
        "model": "rednote-hilab/dots.ocr",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt_text
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_url
                        }
                    }
                ]
            }
        ]
    }
    
    response = requests.post(api_url, headers=headers, json=payload)
    response.raise_for_status()
    
    # Extract content from response
    result = response.json()
    content_str = result["choices"][0]["message"]["content"]
    
    # Parse content string to Python object
    content = json.loads(content_str)
    
    return content

def extract_info(content: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Extract structured information from OCR content.
    
    Args:
        content: List of layout elements from OCR
        
    Returns:
        Structured dictionary with meta, documents, spec, and other info
    """
    from bs4 import BeautifulSoup
    
    # Find the table element
    table_element = None
    for element in content:
        if element.get("category") == "Table" and "text" in element:
            table_element = element
            break
    
    if not table_element:
        raise ValueError("No table found in content")
    
    # Parse HTML table
    soup = BeautifulSoup(table_element["text"], "html.parser")
    rows = soup.find_all("tr")
    
    # Initialize result structure
    result = {
        "meta": {},
        "documents": {},
        "spec": {},
        "regulation": "",
        "name_plate": {},
        "optional_spare_parts": "",
        "display_language": {},
        "remarks": "",
        "additional_info": []
    }
    
    # Track state for parsing
    in_spec_section = False
    display_lang_count = 0
    
    # Extract data from table rows
    for i, row in enumerate(rows):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        
        cell_texts = [cell.get_text(strip=True) for cell in cells]
        
        # Meta information (first row)
        if i == 0 and "Date" in cell_texts:
            result["meta"]["date"] = cell_texts[1] if len(cell_texts) > 1 else ""
            # Also extract documents header info
            if len(cell_texts) > 2 and "Number of documents" in cell_texts:
                result["documents"]["number_of_documents"] = {
                    "to": cell_texts[3] if len(cell_texts) > 3 else "",
                    "ship_with_dw": cell_texts[4] if len(cell_texts) > 4 else "",
                    "note": cell_texts[5] if len(cell_texts) > 5 else ""
                }
            continue
        
        # Meta information rows
        if "Work No." in cell_texts:
            result["meta"]["work_no"] = cell_texts[1] if len(cell_texts) > 1 else ""
        elif "Model" in cell_texts and "Work No." not in cell_texts:
            result["meta"]["model"] = cell_texts[1] if len(cell_texts) > 1 else ""
        elif "Controller" in cell_texts:
            result["meta"]["controller"] = cell_texts[1] if len(cell_texts) > 1 else ""
        elif "Subsidiary/ Agent" in cell_texts or "Subsidiary/Agent" in cell_texts:
            result["meta"]["subsidiary_agent"] = cell_texts[1] if len(cell_texts) > 1 else ""
        elif "End-user" in cell_texts and "country" not in cell_texts[0].lower():
            result["meta"]["end_user"] = cell_texts[1] if len(cell_texts) > 1 else ""
        elif "End-user country" in cell_texts:
            result["meta"]["end_user_country"] = cell_texts[1] if len(cell_texts) > 1 else ""
        elif "Destination port" in cell_texts:
            result["meta"]["destination_port"] = cell_texts[1] if len(cell_texts) > 1 else ""
        elif "Ex-factory date" in cell_texts:
            result["meta"]["ex_factory_date"] = cell_texts[1] if len(cell_texts) > 1 else ""
        
        # Documents information
        elif "Final drawing" in cell_texts:
            result["documents"]["final_drawing"] = {
                "required": cell_texts[2] if len(cell_texts) > 2 else "",
                "ship_with_dw": cell_texts[3] if len(cell_texts) > 3 else ""
            }
        elif "Parts (EN.)" in cell_texts:
            result["documents"]["parts_en"] = {
                "format": cell_texts[2] if len(cell_texts) > 2 else "",
                "delivery": cell_texts[3] if len(cell_texts) > 3 else ""
            }
        elif "Check data sheet" in cell_texts:
            result["documents"]["check_data_sheet"] = {
                "required": cell_texts[2] if len(cell_texts) > 2 else ""
            }
        elif "Installation (EN.)" in cell_texts:
            result["documents"]["installation_en"] = {
                "required": cell_texts[3] if len(cell_texts) > 3 else ""
            }
        elif "Setup/ Operation" in cell_texts or "Setup/Operation" in cell_texts:
            if "setup_operation" not in result["documents"]:
                result["documents"]["setup_operation"] = {
                    "required": cell_texts[3] if len(cell_texts) > 3 else ""
                }
        
        # Spec information (rows with numeric index or special keys)
        elif len(cell_texts) > 0 and cell_texts[0].isdigit():
            in_spec_section = True
            idx = cell_texts[0]
            key_name = cell_texts[1] if len(cell_texts) > 1 else ""
            key = f"{idx}_{_normalize_key(key_name)}"
            
            value_data = {"value": cell_texts[2] if len(cell_texts) > 2 else ""}
            
            # Add additional fields if present
            if len(cell_texts) > 3 and cell_texts[3]:
                if "↔" in cell_texts[3]:
                    value_data["alt"] = cell_texts[3]
                elif cell_texts[3].lower() not in ["", "no", "yes"]:
                    value_data["note"] = cell_texts[3]
                else:
                    value_data["note"] = cell_texts[3]
            if len(cell_texts) > 5 and cell_texts[5]:
                value_data["discharge"] = cell_texts[5]
            
            result["spec"][key] = value_data
        
        # Special spec keys without numeric index (e.g., "Degree", "C-C", "SN")
        elif in_spec_section and len(cell_texts) > 0 and cell_texts[0] == "" and len(cell_texts) > 1:
            key_name = cell_texts[1]
            if key_name and key_name not in ["Software", "Regulation", "Display language(s)"]:
                key = _normalize_key(key_name)
                value_data = {"value": cell_texts[2] if len(cell_texts) > 2 else ""}
                result["spec"][key] = value_data
        
        # Regulation
        elif "Regulation" in cell_texts:
            if len(cell_texts) > 2 and cell_texts[2] and not result["regulation"]:
                result["regulation"] = cell_texts[2]
        
        # Name plate
        elif "Name plate" in cell_texts:
            result["name_plate"]["code"] = cell_texts[2] if len(cell_texts) > 2 else ""
        
        # Optional spare parts
        elif "Optional spare parts" in cell_texts:
            result["optional_spare_parts"] = cell_texts[2] if len(cell_texts) > 2 else ""
        
        # Display language
        elif "Display language(s)" in cell_texts:
            if display_lang_count == 0:
                result["display_language"]["primary"] = cell_texts[2] if len(cell_texts) > 2 else ""
            elif display_lang_count == 1:
                result["display_language"]["secondary"] = cell_texts[2] if len(cell_texts) > 2 else ""
            display_lang_count += 1
        
        # Printer (used as name_plate whole field)
        elif "Printer" in cell_texts:
            result["name_plate"]["whole"] = cell_texts[2] if len(cell_texts) > 2 else ""
        
        # Operation (last row, might indicate secondary_required)
        elif "Operation" in cell_texts and len(cell_texts) > 2:
            result["display_language"]["secondary_required"] = cell_texts[2] if len(cell_texts) > 2 else "No"
    
    # Add language to name_plate (extract from display_language primary)
    if "primary" in result["display_language"]:
        result["name_plate"]["language"] = result["display_language"]["primary"]
    
    # Collect all non-table content as additional info
    for element in content:
        category = element.get("category")
        # Skip Table and Picture categories
        if category and category not in ["Table", "Picture"]:
            element_info = {
                "category": category,
                "bbox": element.get("bbox", [])
            }
            # Add text content if present
            if "text" in element and element["text"]:
                element_info["text"] = element["text"]
            
            # Only add if there's text content
            if "text" in element_info:
                result["additional_info"].append(element_info)
                
                # Also extract special keywords to remarks for backward compatibility
                text = element["text"]
                if any(keyword in text for keyword in ["同种规格做", "台", "WG", "规格"]):
                    if result["remarks"]:
                        result["remarks"] += " " + text
                    else:
                        result["remarks"] = text
    
    return result


def _normalize_key(text: str) -> str:
    """
    Normalize table key names to valid dictionary keys.
    
    Args:
        text: Original text from table
        
    Returns:
        Normalized key string
    """
    # Convert to lowercase and replace spaces/special chars with underscaces
    text = text.lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s-]+', '_', text)
    return text


def validate_extracted_info(info: Dict[str, Any]) -> tuple[bool, List[str]]:
    """
    Validate if extracted info has non-empty meta and spec sections.
    Only checks if the sections exist and are not empty dictionaries.
    Does not validate individual field values within meta or spec.
    
    Args:
        info: Extracted information dictionary
        
    Returns:
        Tuple of (is_valid, list of empty/missing sections)
    """
    empty_sections = []
    
    # Check if meta section exists and is not empty
    if "meta" not in info:
        empty_sections.append("meta (section missing)")
    elif not info["meta"] or not isinstance(info["meta"], dict):
        empty_sections.append("meta (section is empty or invalid)")
    
    # Check if spec section exists and is not empty
    if "spec" not in info:
        empty_sections.append("spec (section missing)")
    elif not info["spec"] or not isinstance(info["spec"], dict):
        empty_sections.append("spec (section is empty or invalid)")
    
    is_valid = len(empty_sections) == 0
    return is_valid, empty_sections


def extract_info_with_retry(image_url: str, api_url: str = "http://localhost:80/ocr/dotsocr/v1/chat/completions", max_retries: int = 3) -> Dict[str, Any]:
    """
    Extract information with retry mechanism.
    
    Args:
        image_url: URL of the image to be processed
        api_url: API endpoint URL
        max_retries: Maximum number of retry attempts (default: 3)
        
    Returns:
        Extracted and validated information dictionary
        
    Raises:
        ValueError: If extraction fails after max_retries attempts
        requests.exceptions.RequestException: If the API request fails
    """
    attempt = 0
    last_empty_sections = []
    
    while attempt < max_retries:
        # Add delay before retry (except for first attempt)
        if attempt > 0:
            time.sleep(3)
        
        attempt += 1
        
        try:
            # Extract layout info from OCR API
            content = extract_layout_info(image_url, api_url)
            
            # Extract structured info
            info = extract_info(content)
            
            # Validate extracted info
            is_valid, empty_sections = validate_extracted_info(info)
            
            if is_valid:
                return info
            else:
                last_empty_sections = empty_sections
                if attempt >= max_retries:
                    break
        
        except Exception as e:
            if attempt >= max_retries:
                raise
    
    # If we've exhausted all retries
    error_msg = f"无法提取完整内容，请重新上传重试。经过 {max_retries} 次尝试后仍有以下部分缺失或为空: {', '.join(last_empty_sections)}"
    raise ValueError(error_msg)

def main():
    """Test function for development"""
    image_url = "http://minio:9000/yamatodev/temp/61e64fdc2a464919805ff49d9ae108a8_2026-3-41111_page_001.jpg"
    
    try:
        info = extract_info_with_retry(image_url, max_retries=3)
        print(json.dumps(info, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"Error: {str(e)}")

if __name__ == "__main__":
    main()