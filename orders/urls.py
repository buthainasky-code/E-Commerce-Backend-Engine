from django.urls import path
from . import views

urlpatterns = [
    path('buy/unsafe/', views.buy_unsafe, name='buy-unsafe'),
    path('buy/', views.buy_safe, name='buy-safe'),  #async
     path('buy/sync/', views.buy_sync, name='buy-sync'),  # blocking 
    path('history/', views.order_history, name='order-history'),
    path('report/naive/', views.report_naive, name='report-naive'),
    path('report/chunked/', views.report_chunked, name='report-chunked'),
]