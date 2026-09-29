from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('proposals/', views.BannerListView.as_view(), name='banner_list'),
    path('proposals/export/excel/', views.export_banners_excel, name='export_banners_excel'),
    path('proposals/add/', views.BannerCreateView.as_view(), name='banner_add'),
    path('proposals/<int:pk>/', views.BannerDetailView.as_view(), name='banner_detail'),
    path('proposals/<int:pk>/edit/', views.banner_edit, name='banner_edit'),
    path('proposals/<int:pk>/delete/', views.banner_delete, name='banner_delete'),
    path('proposals/approvals/', views.banner_approvals, name='banner_approvals'),
    path('proposals/<int:pk>/review/', views.proposal_review, name='proposal_review'),
    path('proposals/<int:pk>/approve/<str:action>/', views.banner_approve_action, name='banner_approve_action'),
    path('work-orders/', views.work_order_list, name='work_order_list'),
    path('work-orders/<int:pk>/', views.work_order_detail, name='work_order_detail'),
    path('work-orders/<int:pk>/download/', views.work_order_download, name='work_order_download'),
]
