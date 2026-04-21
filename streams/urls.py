from django.urls import path

from . import views

app_name = "streams"

urlpatterns = [
    path('', views.index, name='index'),
    path('sls-stats/<str:player_key>/', views.sls_stats, name='sls_stats'),
    path('api/streams-status/', views.streams_status_json, name='streams_status_json'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('create-stream/', views.create_stream, name='create_stream'),
    path('add-player/', views.add_player, name='add_player'),
    path('delete-stream/<str:publisher_key>/', views.delete_stream, name='delete_stream'),
    path('delete-player/<str:player_key>/', views.delete_player, name='delete_player'),
    path('push-route/<str:publisher_key>/', views.update_push_route, name='update_push_route'),
    path('push-route/<str:publisher_key>/create-control-token/', views.create_control_token, name='create_control_token'),
    path('push-route/<str:publisher_key>/revoke-control-tokens/', views.revoke_control_tokens, name='revoke_control_tokens'),
    path('internal/push/routes', views.internal_push_routes, name='internal_push_routes'),
    path('internal/push/status', views.internal_push_status, name='internal_push_status'),
    path('api/push/control/<str:publisher_key>/enable', views.api_push_enable, name='api_push_enable'),
    path('api/push/control/<str:publisher_key>/disable', views.api_push_disable, name='api_push_disable'),
    path('api/push/control/<str:publisher_key>/status', views.api_push_status, name='api_push_status'),
]
