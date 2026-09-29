from django.urls import path
from . import views

urlpatterns = [
    path('payments/upload/', views.payment_upload, name='payment_upload'),
    path('payments/records/', views.payment_list, name='payment_list'),
    path('payments/<int:pk>/', views.payment_detail, name='payment_detail'),
    path('payments/<int:pk>/edit/', views.payment_edit, name='payment_edit'),
    path('payments/<int:pk>/delete/', views.payment_delete, name='payment_delete'),
    path('payments/approvals/', views.payment_approvals, name='payment_approvals'),
    path('payments/<int:pk>/review/', views.payment_review, name='payment_review'),
    path('payments/<int:pk>/approve/<str:action>/', views.payment_approve_action, name='payment_approve_action'),
]
