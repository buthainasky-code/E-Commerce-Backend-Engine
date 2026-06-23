from django.urls import path
from . import views

urlpatterns = [
    path('buy/unsafe/', views.buy_unsafe, name='buy-unsafe'),
    path('buy/', views.buy_safe, name='buy-safe'),  #async
     path('buy/sync/', views.buy_sync, name='buy-sync'),  # blocking 
    path('history/', views.order_history, name='order-history'),
    path('report/naive/', views.report_naive, name='report-naive'),
    path('report/chunked/', views.report_chunked, name='report-chunked'),
     path('buy/invalidate-cache/', views.buy_safe_invalidate_cache, name='buy-invalidate-cache'), #req 6
     path('coupons/claim/', views.claim_coupon, name='claim-coupon'),
     path('buy/non-atomic/', views.buy_non_atomic, name='buy-non-atomic'),
    path('buy/atomic/', views.buy_atomic, name='buy-atomic'),
    path('buy/optimized/', views.buy_optimized, name='buy-optimized'),
]