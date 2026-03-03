"""
Chroma RAG Database Service for semantic search on academic documents
"""

import os
import json
import re
import uuid
import torch
from PIL import Image
from typing import Dict, List, Optional
from sentence_transformers import SentenceTransformer
from transformers import CLIPProcessor, CLIPModel
import chromadb


# -----------------------------------------
# Hierarchical Smart Chunking
# -----------------------------------------

def split_paragraphs(text: str) -> List[str]:
    """Split text into paragraphs"""
    return [p.strip() for p in re.split(r"\n{2,}", text) if len(p.strip()) > 40]


def sentence_chunks(text: str) -> List[str]:
    """Split text into sentences"""
    return re.split(r"(?<=[.!?])\s+", text)


def sliding_chunks(tokens: List[str], size: int = 420, overlap: int = 120):
    """Generate sliding window chunks from tokens"""
    i = 0
    while i < len(tokens):
        yield tokens[i:i+size]
        i += size - overlap


# -----------------------------------------
# Chroma Multimodal RAG Database
# -----------------------------------------

class ChromaRAGDB:
    """
    Chroma-based vector database for RAG on academic documents
    Supports both text and image embeddings
    """
    
    def __init__(self, batch_id: str, semester_id: str = None, doc_uuid: str = None):
        """
        Initialize Chroma RAG DB
        
        Args:
            batch_id: Batch/year identifier
            semester_id: Semester identifier
            doc_uuid: Document UUID for extracted content
        """
        self.data = {}
        self.batch_id = batch_id
        self.semester_id = semester_id
        self.doc_uuid = doc_uuid
        
        # Collection name combines batch and semester for isolation
        self.collection_name = f"batch_{batch_id}_sem_{semester_id}"
        
        # Persistent storage
        self.client = chromadb.PersistentClient(path="./chroma_db_storage")
        self.collection = self.client.get_or_create_collection(
            self.collection_name,
            metadata={"description": f"Academic batch {batch_id} semester {semester_id}"}
        )
        
        # Initialize embedding models
        self._init_models()
        
        # Load extracted JSON if available
        if doc_uuid:
            self._load_document(doc_uuid)
    
    def _init_models(self):
        """Initialize embedding and vision models"""
        try:
            self.text_model = SentenceTransformer(
                "sentence-transformers/all-mpnet-base-v2"
            )
            self.clip_model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
            self.clip_processor = CLIPProcessor.from_pretrained(
                "openai/clip-vit-base-patch32"
            )
        except Exception as e:
            print(f"Error loading models: {e}")
            raise
    
    def _load_document(self, doc_uuid: str):
        """Load extracted JSON document"""
        json_path = f"langbase_json/{doc_uuid}.json"
        if os.path.exists(json_path):
            with open(json_path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
    
    # --------- TEXT INGEST ---------
    def ingest_text(self):
        """Ingest text from document with hierarchical chunking"""
        for page, content in self.data.items():
            raw_text = content.get("text", "")
            images = content.get("images", [])
            
            for p_id, para in enumerate(split_paragraphs(raw_text)):
                tokens = " ".join(sentence_chunks(para)).split()
                
                for w_id, token_chunk in enumerate(sliding_chunks(tokens)):
                    chunk_text = " ".join(token_chunk)
                    
                    try:
                        emb = self.text_model.encode(chunk_text).tolist()
                    except Exception as e:
                        print(f"Error encoding text: {e}")
                        continue
                    
                    cid = f"{self.batch_id}_{self.semester_id}_{uuid.uuid4()}"
                    
                    self.collection.add(
                        ids=[cid],
                        documents=[chunk_text],
                        embeddings=[emb],
                        metadatas=[{
                            "batch_id": self.batch_id,
                            "semester_id": self.semester_id,
                            "doc_uuid": self.doc_uuid,
                            "page": page,
                            "paragraph": p_id,
                            "window": w_id,
                            "associated_images": ",".join(images),
                            "type": "text"
                        }]
                    )
        
        print("✅ Text embeddings ingested")
    
    # --------- IMAGE INGEST ---------
    def ingest_images(self):
        """Ingest images with CLIP embeddings"""
        if not self.doc_uuid:
            return
        
        image_dir = f"langbase_json/ExtractedImages/{self.doc_uuid}/"
        
        if not os.path.exists(image_dir):
            print(f"Image directory not found: {image_dir}")
            return
        
        for fname in os.listdir(image_dir):
            if not fname.lower().endswith(('.png', '.jpg', '.jpeg')):
                continue
            
            path = os.path.join(image_dir, fname)
            image_id = os.path.splitext(fname)[0]
            
            try:
                img = Image.open(path).convert("RGB")
                inputs = self.clip_processor(images=img, return_tensors="pt")
                
                with torch.no_grad():
                    emb = self.clip_model.get_image_features(**inputs)[0].tolist()
                
                self.collection.add(
                    ids=[f"{self.batch_id}_{self.semester_id}_{image_id}"],
                    embeddings=[emb],
                    metadatas=[{
                        "batch_id": self.batch_id,
                        "semester_id": self.semester_id,
                        "doc_uuid": self.doc_uuid,
                        "type": "image",
                        "image_id": image_id
                    }]
                )
            except Exception as e:
                print(f"Skipping image {fname}: {e}")
        
        print("✅ Image embeddings ingested")
    
    def ingest_all(self):
        """Ingest both text and images"""
        self.ingest_text()
        self.ingest_images()
        print("🚀 Full multimodal ingestion complete")
    
    # --------- QUERY ---------
    def query_text(self, query: str, top_k: int = 10) -> List[str]:
        """
        Query text embeddings
        
        Args:
            query: Search query
            top_k: Number of results
        
        Returns:
            List of relevant text chunks
        """
        try:
            q_emb = self.text_model.encode(query).tolist()
            res = self.collection.query(
                query_embeddings=[q_emb],
                n_results=top_k,
                where={
                    "$and": [
                        {"batch_id": {"$eq": self.batch_id}},
                        {"type": {"$eq": "text"}}
                    ]
                }
            )
            return res["documents"][0] if res["documents"] else []
        except Exception as e:
            print(f"Query error: {e}")
            return []
    
    def query_grouped(self, question: str, top_k: int = 25) -> Dict[str, List[str]]:
        """
        Query and group results by page
        
        Args:
            question: Search query
            top_k: Number of results
        
        Returns:
            Dictionary grouped by page
        """
        try:
            q_emb = self.text_model.encode(question).tolist()
            
            res = self.collection.query(
                query_embeddings=[q_emb],
                n_results=top_k,
                where={
                    "$and": [
                        {"batch_id": {"$eq": self.batch_id}},
                        {"type": {"$eq": "text"}}
                    ]
                },
                include=["documents", "metadatas"]
            )
            
            grouped = {}
            if res["documents"]:
                for doc, meta in zip(res["documents"][0], res["metadatas"][0]):
                    page = meta.get("page", "unknown")
                    content = grouped.setdefault(page, [])
                    content.append(doc)
            
            return grouped
        except Exception as e:
            print(f"Query error: {e}")
            return {}
    
    def search_marks(self, query: str = "marks grades results") -> List[str]:
        """Specialized search for academic marks and grades"""
        return self.query_text(query, top_k=15)
    
    def search_by_subject(self, subject_code: str) -> List[str]:
        """Search for content related to a specific subject"""
        return self.query_text(f"{subject_code} marks grade score", top_k=20)
