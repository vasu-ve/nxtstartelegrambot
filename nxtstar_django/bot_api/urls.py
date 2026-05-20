"""
URL configuration for bot_api app.
"""
from django.urls import path
from . import views

app_name = 'bot_api'

urlpatterns = [
    path('users/create/', views.create_or_get_user, name='create_or_get_user'),
    path('users/verify/', views.verify_user, name='verify_user'),
    path('invites/generate/', views.generate_invite_link, name='generate_invite_link'),
    path('invites/get/', views.get_invite_link, name='get_invite_link'),
    path('invites/mark-used/', views.mark_invite_used, name='mark_invite_used'),
    path('leaders/available/', views.get_available_leaders, name='get_available_leaders'),
    path('leaders/select-and-generate/', views.select_leader_and_generate_link, name='select_leader_and_generate_link'),
    path('groups/available/', views.get_available_groups, name='get_available_groups'),
    path('groups/select-and-generate/', views.select_group_and_generate_link, name='select_group_and_generate_link'),
    path('invites/validate-join/', views.validate_join),
    path('groups/user-left/',views.user_left_group),
    path('debug/invites/', views.debug_invites, name='debug_invites'),
]
