from django.contrib import admin
from django.urls import path,include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('',include('users.urls')),
    path('pages/',include('pages.urls')),
    path('circulars/',include('circulars.urls')),
    path('students/',include('students.urls')),
    path('staff/',include('staff.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
