"""
Utilities module for PDF analysis and RAG-based document processing
"""

from .pdf_extraction import PDFExtractor, AcademicDataParser

try:
    from .chroma_rag import ChromaRAGDB
except ImportError:
    ChromaRAGDB = None

__all__ = [
    'PDFExtractor',
    'AcademicDataParser',
    'ChromaRAGDB',
]
