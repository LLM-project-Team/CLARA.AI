"""
Global PDF Extraction Service
Handles PDF extraction, parsing, and RAG-based analysis for academic documents
"""

import fitz  # PyMuPDF
import json
import io
import os
from PIL import Image
from typing import Dict, List, Tuple, Optional
import uuid


class PDFExtractor:
    """Extract text and images from PDF files"""
    
    def __init__(self, pdf_path_or_bytes, doc_uuid: str = None):
        """
        Initialize PDF extractor
        
        Args:
            pdf_path_or_bytes: Path to PDF file, or raw bytes of the PDF
            doc_uuid: Unique identifier for document
        """
        self.doc_uuid = doc_uuid or str(uuid.uuid4())
        if isinstance(pdf_path_or_bytes, (bytes, bytearray)):
            self.pdf_path = None
            self.pdf = fitz.open(stream=pdf_path_or_bytes, filetype="pdf")
        else:
            self.pdf_path = pdf_path_or_bytes
            self.pdf = fitz.open(pdf_path_or_bytes)
        self.pdf_json = {}
        self.image_store = {}
        self.image_id = 1
        self.image_index = 1
        
    def extract(self) -> Dict:
        """
        Extract text and images from PDF
        
        Returns:
            Dictionary with extracted content
        """
        for page_no, page in enumerate(self.pdf, start=1):
            page_key = f"page_{page_no}"
            self.pdf_json[page_key] = {
                "text": page.get_text(),
                "images": []
            }

            # Extract images from page
            for img in page.get_images(full=True):
                xref = img[0]
                img_data = self.pdf.extract_image(xref)
                image_bytes = img_data["image"]

                image_name = f"image{self.image_id}"
                self.image_store[image_name] = Image.open(
                    io.BytesIO(image_bytes)
                ).convert("RGB")

                self.pdf_json[page_key]["images"].append(image_name)
                self.image_id += 1
        
        return self.pdf_json
    
    def get_full_text(self) -> str:
        """Get all text from PDF as single string"""
        full_text = ""
        for page_key, content in self.pdf_json.items():
            full_text += content.get("text", "") + "\n"
        return full_text

    def close(self):
        """Explicitly close the fitz document and release the file lock."""
        try:
            self.pdf.close()
        except Exception:
            pass
    
    def save_json(self, output_dir: str = "langbase_json") -> str:
        """Save extracted JSON and images"""
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(f"{output_dir}/ExtractedImages/{self.doc_uuid}", exist_ok=True)
        
        # Save JSON
        json_path = f"{output_dir}/{self.doc_uuid}.json"
        with open(json_path, "w") as f:
            json.dump(self.pdf_json, f, indent=2)
        
        # Save images
        for image_name, image_obj in self.image_store.items():
            image_obj.save(
                f"{output_dir}/ExtractedImages/{self.doc_uuid}/{image_name}.png"
            )
        
        return json_path


class AcademicDataParser:
    """Parse academic data from extracted PDF text"""
    
    @staticmethod
    def extract_marks(text: str) -> Dict:
        """
        Extract marks/grades from PDF text using pattern matching
        
        Looks for common patterns:
        - Roll No / Registration No
        - Subject names and codes
        - Internal marks (T1, T2, T3, etc.)
        - End semester marks
        - Grades
        """
        import re
        
        data = {
            "students": {},
            "subjects": []
        }
        
        lines = text.split('\n')
        
        # Simple pattern matching for common academic formats
        for i, line in enumerate(lines):
            # Pattern: Roll No, Reg No
            roll_match = re.search(r'Roll\s*(?:No|Number|#)?[:\s]+(\d+[A-Za-z]*)', line)
            if roll_match:
                roll_no = roll_match.group(1)
                if roll_no not in data["students"]:
                    data["students"][roll_no] = {
                        "subjects": {}
                    }
            
            # Pattern: Subject Code and Name
            subject_match = re.search(
                r'([A-Z]{2}\d{3,4})\s*-?\s*([A-Za-z\s&()]+?)(?:\s+[\d.]+)?$', 
                line
            )
            if subject_match:
                code = subject_match.group(1)
                name = subject_match.group(2).strip()
                if code not in data["subjects"]:
                    data["subjects"].append({
                        "code": code,
                        "name": name
                    })
            
            # Pattern: Marks (Internal/External)
            marks_match = re.findall(r'(\d+\.?\d*)', line)
            if marks_match and len(marks_match) >= 2:
                # Assuming format: score/total
                try:
                    marks_list = [float(m) for m in marks_match]
                except:
                    pass
        
        return data
    
    @staticmethod
    def parse_table_data(text: str) -> List[Dict]:
        """
        Extract tabular data from text
        Useful for result tables with student marks
        """
        import re
        
        results = []
        lines = text.split('\n')
        
        for line in lines:
            # Look for lines with mixed text and numbers (typical table rows)
            if re.search(r'[A-Za-z]+.*\d+.*\d+', line):
                parts = re.split(r'\s{2,}|\t', line.strip())
                if len(parts) >= 3:  # At least name + 2 marks
                    results.append(parts)
        
        return results
