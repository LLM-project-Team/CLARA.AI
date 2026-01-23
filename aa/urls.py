from django.contrib import admin
from django.urls import path,include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('',include('users.urls')),
    path('pages/',include('pages.urls')),
    path('circulars/',include('circulars.urls')),
    path('students/',include('students.urls')),
    path('staff/',include('staff.urls')),
]
