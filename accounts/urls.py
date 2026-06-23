from django.urls import path
from . import views

urlpatterns = [
    path('balance/', views.balance, name='balance'),
]