from django.urls import path
from . import views

urlpatterns = [
    path('<int:product_id>/', views.product_detail, name='product-detail'), 
    path('<int:product_id>/cached/', views.product_detail_cached, name='product-cached'),  # NEW
]