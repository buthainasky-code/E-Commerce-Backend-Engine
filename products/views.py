from django.http import JsonResponse
from .models import Product

def product_detail(request, product_id):
    product = Product.objects.values('id', 'name', 'stock', 'price').get(id=product_id)
    return JsonResponse(product)