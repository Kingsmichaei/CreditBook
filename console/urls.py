from django.urls import path

from . import views

app_name = 'console'

urlpatterns = [
    path('', views.overview, name='overview'),
    path('businesses/', views.businesses, name='businesses'),
    path('businesses/<int:pk>/', views.business_detail, name='business_detail'),
    path('businesses/<int:pk>/<slug:action>/', views.business_action, name='business_action'),
    path('payments/', views.payments, name='payments'),
    path('activity/', views.activity, name='activity'),
]
