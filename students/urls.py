from django.urls import path
from . import views
from . import views_pdf_analysis
from . import views_chat

app_name = 'students'

urlpatterns = [
    # Entry point: List of departments
    path('', views.department_list, name='department_list'),
    
    # PDF Analysis Routes
    path('pdf-analysis/', views_pdf_analysis.pdf_analysis_home, name='pdf_analysis_home'),
    path('pdf-analysis/dept/<uuid:department_id>/', views_pdf_analysis.select_batch, name='select_batch'),
    path('pdf-analysis/dept/<uuid:department_id>/batch/<str:batch_year>/', views_pdf_analysis.select_semester, name='select_semester'),
    path('pdf-analysis/dept/<uuid:department_id>/batch/<str:batch_year>/sem/<uuid:semester_id>/upload/', views_pdf_analysis.upload_pdf, name='upload_pdf'),
    path('pdf-analysis/results/<uuid:analysis_id>/', views_pdf_analysis.analysis_results, name='analysis_results'),
    path('pdf-analysis/verify/<uuid:result_id>/', views_pdf_analysis.verify_result, name='verify_result'),
    path('pdf-analysis/search/', views_pdf_analysis.search_document, name='search_documents'),
    path('pdf-analysis/api/query/<uuid:analysis_id>/', views_pdf_analysis.rag_query_api, name='rag_query_api'),
    
    # Academic Analytics
    path('analytics/', views.academic_analytics, name='academic_analytics'),
    path('analytics/<uuid:department_id>/', views.analytics_department_batches, name='analytics_department_batches'),
    path('analytics/<uuid:department_id>/batch/<str:batch_year>/', views.analytics_batch_semesters, name='analytics_batch_semesters'),
    path('analytics/<uuid:department_id>/batch/<str:batch_year>/sem/<int:semester_number>/', views.analytics_semester_details, name='analytics_semester_details'),

    # Subject Management API
    path('analytics/<uuid:department_id>/sem/<int:semester_number>/subjects/add/', views.subject_add, name='subject_add'),
    path('analytics/<uuid:department_id>/sem/<int:semester_number>/subjects/update/', views.subject_update, name='subject_update'),
    path('analytics/<uuid:department_id>/sem/<int:semester_number>/subjects/delete/', views.subject_delete, name='subject_delete'),

    # Analytics AI Chat API
    path('analytics/chat/', views_chat.analytics_chat_api, name='analytics_chat'),

    # Marks (SubjectResult) CRUD API
    path('analytics/<uuid:department_id>/batch/<str:batch_year>/sem/<int:semester_number>/marks/',
         views.marks_list_api,   name='marks_list'),
    path('analytics/marks/<uuid:result_id>/update/',
         views.marks_update_api, name='marks_update'),
    path('analytics/marks/<uuid:result_id>/delete/',
         views.marks_delete_api, name='marks_delete'),

    # End Semester Result CRUD API
    path('analytics/<uuid:department_id>/batch/<str:batch_year>/sem/<int:semester_number>/end-sem/',
         views.end_sem_list_api,   name='end_sem_list'),
    path('analytics/end-sem/<uuid:result_id>/update/',
         views.end_sem_update_api, name='end_sem_update'),
    path('analytics/end-sem/<uuid:result_id>/delete/',
         views.end_sem_delete_api, name='end_sem_delete'),

    # Bulk delete marks (all records for a subject/section)
    path('analytics/<uuid:department_id>/batch/<str:batch_year>/sem/<int:semester_number>/marks/bulk-delete/',
         views.marks_bulk_delete_api, name='marks_bulk_delete'),
    path('analytics/<uuid:department_id>/batch/<str:batch_year>/sem/<int:semester_number>/end-sem/bulk-delete/',
         views.end_sem_bulk_delete_api, name='end_sem_bulk_delete'),

    # Assign sections to a batch
    path('<uuid:department_id>/<str:batch_year>/assign-sections/', views.assign_sections_api, name='assign_sections'),
    
    # Add new student
    path('add/', views.student_add, name='student_add'),
    path('add/<uuid:department_id>/', views.student_add, name='student_add_dept'),
    path('add/<uuid:department_id>/<str:batch_year>/', views.student_add, name='student_add_batch'),
    
    # Batches for a department
    path('<uuid:department_id>/', views.batch_list, name='batch_list'),
    
    # Students for a department and batch
    path('<uuid:department_id>/<str:batch_year>/', views.student_list, name='student_list'),
    
    # Individual student detail and edit
    path('detail/<uuid:student_id>/', views.student_detail, name='student_detail'),
    path('edit/<uuid:student_id>/', views.student_edit, name='student_edit'),
]
