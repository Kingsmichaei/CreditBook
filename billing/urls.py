from django.urls import path

from . import views

urlpatterns = [
    path('', views.billing_dashboard_view, name='billing_dashboard'),
    path('subscribe/', views.subscribe_view, name='billing_subscribe'),
    path('payment/callback/', views.payment_callback_view, name='payment_callback'),
    path('webhook/nomba/', views.nomba_webhook_view, name='nomba_webhook'),
    path('suspended/', views.account_suspended_view, name='account_suspended'),
    path('paused/', views.account_paused_view, name='account_paused'),
    path('cancelled/', views.account_cancelled_view, name='account_cancelled'),
    path('disabled/', views.account_disabled_view, name='account_disabled'),
]
