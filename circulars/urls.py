from django.urls import path
from . import views

urlpatterns = [
    path('', views.generator_view, name='circular_gen'),
    path('save/', views.save_circular, name='circular_save'),
    path('view/<int:circular_id>/', views.view_circular, name='circular_view'),
    path('delete/<int:circular_id>/', views.delete_circular, name='circular_delete'),
    path('generate-ai/', views.generate_ai_content, name='circular_ai_generate'),
]