from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('banners/', views.BannerListView.as_view(), name='banner_list'),
    path('banners/export/excel/', views.export_banners_excel, name='export_banners_excel'),
    path('banners/add/', views.BannerCreateView.as_view(), name='banner_add'),
    path('banners/<int:pk>/', views.BannerDetailView.as_view(), name='banner_detail'),
    path('banners/<int:pk>/edit/', views.banner_edit, name='banner_edit'),
    path('banners/<int:pk>/delete/', views.banner_delete, name='banner_delete'),
    path('banners/<int:banner_id>/add-placement/', views.add_placement, name='add_placement'),
    path('placements/<int:placement_id>/upload-photo/', views.upload_photo, name='upload_photo'),
    path('banners/<int:banner_id>/add-cost/', views.add_cost, name='add_cost'),
]