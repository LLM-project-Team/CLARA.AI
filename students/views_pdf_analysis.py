"""
Views for PDF Analysis and RAG Document Processing in Academic Feature
"""

import json
import uuid
from datetime import datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, FileResponse
from django.views.decorators.http import require_http_methods
from django.core.files.storage import default_storage
from django.core.paginator import Paginator
from django.db.models import Q
from django.contrib import messages

from .models import (
    Department, ProgramSemester, Student, Subject, SubjectResult,
    AnalyzedDocument, DocumentAnalysisResult, RAGIndexMetadata
)
from utils.pdf_extraction import PDFExtractor, AcademicDataParser
try:
    from utils.chroma_rag import ChromaRAGDB
except ImportError:
    ChromaRAGDB = None
from users.models import UserProfile


@login_required
def pdf_analysis_home(request):
    """Home view for PDF analysis feature - select department"""
    departments = Department.objects.filter(is_active=True)
    
    context = {
        'departments': departments,
        'page_title': 'PDF Analysis - Select Department',
    }
    
    return render(request, 'students/pdf_analysis/analysis_home.html', context)


@login_required
def select_batch(request, department_id):
    """Select batch/year for the selected department"""
    department = get_object_or_404(Department, id=department_id, is_active=True)
    
    # Get all unique batch years for this department
    batches = ProgramSemester.objects.filter(
        department=department
    ).values_list('batch_year', flat=True).distinct().order_by('-batch_year')
    
    context = {
        'department': department,
        'batches': sorted(set(batches), reverse=True),
        'page_title': f'Select Batch - {department.name}',
    }
    
    return render(request, 'students/pdf_analysis/select_batch.html', context)


@login_required
def select_semester(request, department_id, batch_year):
    """Select semester for the selected batch"""
    department = get_object_or_404(Department, id=department_id, is_active=True)
    
    semesters = ProgramSemester.objects.filter(
        department=department,
        batch_year=batch_year
    ).order_by('number')
    
    if not semesters.exists():
        messages.error(request, "No semesters found for this batch.")
        return redirect('select_batch', department_id=department_id)
    
    context = {
        'department': department,
        'batch_year': batch_year,
        'semesters': semesters,
        'page_title': f'Select Semester - {batch_year}',
    }
    
    return render(request, 'students/pdf_analysis/select_semester.html', context)


@login_required
def upload_pdf(request, department_id, batch_year, semester_id):
    """Upload PDF for analysis"""
    department = get_object_or_404(Department, id=department_id, is_active=True)
    semester = get_object_or_404(ProgramSemester, id=semester_id, department=department)
    
    if request.method == 'POST':
        pdf_file = request.FILES.get('pdf_file')
        document_type = request.POST.get('document_type')
        
        if not pdf_file:
            messages.error(request, "Please select a PDF file.")
            return redirect('upload_pdf', department_id=department_id, 
                          batch_year=batch_year, semester_id=semester_id)
        
        if not pdf_file.name.endswith('.pdf'):
            messages.error(request, "Please upload a valid PDF file.")
            return redirect('upload_pdf', department_id=department_id, 
                          batch_year=batch_year, semester_id=semester_id)
        
        # Create unique document UUID
        doc_uuid = str(uuid.uuid4())
        
        try:
            # Save uploaded file
            file_path = f"pdfs/{doc_uuid}.pdf"
            saved_path = default_storage.save(file_path, pdf_file)
            file_size = pdf_file.size
            
            # Extract PDF content
            extractor = PDFExtractor(saved_path, doc_uuid)
            extractor.extract()
            json_path = extractor.save_json()
            
            # Create AnalyzedDocument record
            analyzed_doc = AnalyzedDocument.objects.create(
                document_uuid=doc_uuid,
                department=department,
                program_semester=semester,
                document_type=document_type,
                original_filename=pdf_file.name,
                file_size=file_size,
                total_pages=len(extractor.pdf),
                status='processing',
                uploaded_by=request.user.username if request.user else 'anonymous'
            )
            
            # Process document (synchronously for now, can be async with Celery)
            try:
                process_document_async(analyzed_doc.id)
            except Exception as e:
                analyzed_doc.status = 'failed'
                analyzed_doc.error_message = str(e)
                analyzed_doc.save()
                messages.error(request, f"Error processing document: {str(e)}")
                return redirect('analysis_results', analysis_id=analyzed_doc.id)
            
            messages.success(request, f"PDF uploaded and analyzed successfully!")
            return redirect('analysis_results', analysis_id=analyzed_doc.id)
        
        except Exception as e:
            messages.error(request, f"Error uploading PDF: {str(e)}")
            return redirect('upload_pdf', department_id=department_id, 
                          batch_year=batch_year, semester_id=semester_id)
    
    context = {
        'department': department,
        'batch_year': batch_year,
        'semester': semester,
        'document_types': AnalyzedDocument.DOCUMENT_TYPE_CHOICES,
        'page_title': f'Upload PDF - {semester}',
    }
    
    return render(request, 'students/pdf_analysis/upload_pdf.html', context)


@login_required
def analysis_results(request, analysis_id):
    """View analysis results from uploaded PDF"""
    analyzed_doc = get_object_or_404(AnalyzedDocument, id=analysis_id)
    
    # Check permission
    if not request.user.is_staff and request.user.username != analyzed_doc.uploaded_by:
        messages.error(request, "You don't have permission to view this analysis.")
        return redirect('pdf_analysis_home')
    
    # Get extracted results
    results = DocumentAnalysisResult.objects.filter(document=analyzed_doc)
    
    # Pagination
    paginator = Paginator(results, 20)
    page = request.GET.get('page', 1)
    results_page = paginator.get_page(page)
    
    # Statistics
    stats = {
        'total_records': results.count(),
        'verified_records': results.filter(is_verified=True).count(),
        'pending_verification': results.filter(is_verified=False).count(),
        'by_type': {}
    }
    
    for result_type, label in DocumentAnalysisResult.RESULT_TYPE_CHOICES:
        stats['by_type'][label] = results.filter(result_type=result_type).count()
    
    context = {
        'analyzed_doc': analyzed_doc,
        'results': results_page,
        'stats': stats,
        'page_title': f'Analysis Results - {analyzed_doc.original_filename}',
    }
    
    return render(request, 'students/pdf_analysis/analysis_results.html', context)


@login_required
def verify_result(request, result_id):
    """Verify and confirm extracted data"""
    result = get_object_or_404(DocumentAnalysisResult, id=result_id)
    
    # Check permission
    if not request.user.is_staff:
        messages.error(request, "Only staff can verify results.")
        return redirect('analysis_results', analysis_id=result.document.id)
    
    if request.method == 'POST':
        is_verified = request.POST.get('is_verified') == 'on'
        verification_notes = request.POST.get('verification_notes', '')
        
        result.is_verified = is_verified
        result.verification_notes = verification_notes
        result.save()
        
        # If verified, create/update SubjectResult
        if is_verified and result.student and result.subject:
            SubjectResult.objects.update_or_create(
                student=result.student,
                subject=result.subject,
                defaults={
                    'internal1': result.internal1,
                    'internal2': result.internal2,
                    'internal3': result.internal3,
                    'end_sem_marks': result.end_sem_marks,
                    'grade': result.grade,
                }
            )
            messages.success(request, "Result verified and saved to database!")
        else:
            messages.success(request, "Result marked as verified.")
        
        return redirect('analysis_results', analysis_id=result.document.id)
    
    context = {
        'result': result,
        'page_title': 'Verify Extracted Result',
    }
    
    return render(request, 'students/pdf_analysis/verify_result.html', context)


@login_required
def search_document(request):
    """Search analyzed documents"""
    query = request.GET.get('q', '')
    department_id = request.GET.get('department', '')
    status = request.GET.get('status', '')
    
    documents = AnalyzedDocument.objects.all()
    
    if query:
        documents = documents.filter(
            Q(original_filename__icontains=query) |
            Q(document_uuid__icontains=query)
        )
    
    if department_id:
        documents = documents.filter(department_id=department_id)
    
    if status:
        documents = documents.filter(status=status)
    
    # Pagination
    paginator = Paginator(documents, 20)
    page = request.GET.get('page', 1)
    documents_page = paginator.get_page(page)
    
    context = {
        'documents': documents_page,
        'departments': Department.objects.filter(is_active=True),
        'statuses': AnalyzedDocument.STATUS_CHOICES,
        'page_title': 'Search Analyzed Documents',
    }
    
    return render(request, 'students/pdf_analysis/search_documents.html', context)


@login_required
@require_http_methods(["POST"])
def rag_query_api(request, analysis_id):
    """
    API endpoint for RAG-based queries on analyzed documents
    Returns relevant text chunks from the document
    """
    analyzed_doc = get_object_or_404(AnalyzedDocument, id=analysis_id)
    
    query = request.POST.get('query', '')
    if not query:
        return JsonResponse({'error': 'Query parameter required'}, status=400)
    
    try:
        # Get RAG metadata
        rag_meta = RAGIndexMetadata.objects.get(document=analyzed_doc)
        
        # Query Chroma
        rag_db = ChromaRAGDB(
            batch_id=rag_meta.batch_id,
            semester_id=rag_meta.semester_id,
            doc_uuid=analyzed_doc.document_uuid
        )
        
        results = rag_db.query_text(query, top_k=10)
        
        return JsonResponse({
            'success': True,
            'query': query,
            'results': results,
            'count': len(results)
        })
    
    except RAGIndexMetadata.DoesNotExist:
        return JsonResponse({'error': 'RAG index not found for this document'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# Async task for document processing (requires Celery or use signals)
def process_document_async(analysis_id):
    """
    Process PDF document: Extract data, parse academics, create results
    This can be converted to Celery task for async processing
    """
    try:
        analyzed_doc = AnalyzedDocument.objects.get(id=analysis_id)
        doc_uuid = analyzed_doc.document_uuid
        
        # Load extracted JSON
        json_path = f"langbase_json/{doc_uuid}.json"
        with open(json_path, 'r') as f:
            pdf_data = json.load(f)
        
        # Extract full text for analysis
        full_text = ""
        for page_data in pdf_data.values():
            full_text += page_data.get('text', '') + "\n"
        
        # Parse academic data
        parser = AcademicDataParser()
        marks_data = parser.extract_marks(full_text)
        
        # Index with RAG
        rag_db = ChromaRAGDB(
            batch_id=analyzed_doc.program_semester.batch_year,
            semester_id=str(analyzed_doc.program_semester.number),
            doc_uuid=doc_uuid
        )
        rag_db.ingest_all()
        
        # Create RAG metadata
        rag_meta = RAGIndexMetadata.objects.create(
            document=analyzed_doc,
            collection_name=rag_db.collection_name,
            batch_id=analyzed_doc.program_semester.batch_year,
            semester_id=str(analyzed_doc.program_semester.number),
        )
        
        # Create DocumentAnalysisResult entries from parsed data
        for roll_no, student_data in marks_data.get('students', {}).items():
            try:
                student = Student.objects.get(roll_number=roll_no)
                
                for subject_result in student_data.get('subjects', []):
                    subject_code = subject_result.get('code')
                    try:
                        subject = Subject.objects.get(code=subject_code)
                        
                        # Create analysis result
                        DocumentAnalysisResult.objects.create(
                            document=analyzed_doc,
                            student=student,
                            subject=subject,
                            result_type='marks',
                            internal1=subject_result.get('internal1'),
                            internal2=subject_result.get('internal2'),
                            internal3=subject_result.get('internal3'),
                            end_sem_marks=subject_result.get('end_sem'),
                            grade=subject_result.get('grade'),
                            raw_extracted_data=subject_result,
                        )
                    except Subject.DoesNotExist:
                        continue
            except Student.DoesNotExist:
                continue
        
        # Update document status
        analyzed_doc.status = 'completed'
        analyzed_doc.is_indexed = True
        analyzed_doc.total_records_extracted = DocumentAnalysisResult.objects.filter(
            document=analyzed_doc
        ).count()
        analyzed_doc.processed_date = datetime.now()
        analyzed_doc.save()
    
    except Exception as e:
        analyzed_doc.status = 'failed'
        analyzed_doc.error_message = str(e)
        analyzed_doc.save()
        raise
