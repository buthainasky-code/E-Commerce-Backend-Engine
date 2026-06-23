from django.http import JsonResponse
from .models import Product
import time
from django.core.cache import cache

def product_detail(request, product_id):
    product = Product.objects.values('id', 'name', 'stock', 'price').get(id=product_id)
    return JsonResponse(product)

# NEW – cached version
def product_detail_cached(request, product_id):
    cache_key = f'product_detail:{product_id}'
    data = cache.get(cache_key)

    if data is not None:
        data['source'] = 'cache'
        return JsonResponse(data)

    start = time.perf_counter()
    product = Product.objects.values('id', 'name', 'stock', 'price').get(id=product_id)
    elapsed = time.perf_counter() - start
    response_data = {
        'source': 'database',
        'time_ms': round(elapsed * 1000, 2),
        **product
    }
    cache.set(cache_key, response_data, 60 * 5)  # 5 minutes
    return JsonResponse(response_data)