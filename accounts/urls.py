from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('users/', views.user_management, name='user_management'),
    path('users/add/', views.user_add, name='user_add'),
    path('users/<int:user_id>/edit/', views.user_edit, name='user_edit'),
    path('users/<int:user_id>/delete/', views.user_delete, name='user_delete'),
    path('users/pending/', views.pending_requests, name='pending_requests'),
    path('roles/', views.role_matrix, name='role_matrix'),
    path('approval-flow/', views.approval_flow, name='approval_flow'),
    path('approval-flow/add/', views.workflow_step_add, name='workflow_step_add'),
    path('approval-flow/<int:step_id>/update/', views.workflow_step_update, name='workflow_step_update'),
    path('approval-flow/<int:step_id>/delete/', views.workflow_step_delete, name='workflow_step_delete'),
    path('approval-flow/<int:step_id>/move/<str:direction>/', views.workflow_step_move, name='workflow_step_move'),
]