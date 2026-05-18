import logging
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from .models import Order
from accounts.models import Account
from products.models import Product
from .tasks import send_invoice
import time
from django.http import JsonResponse
from .tasks import generate_daily_sales_report_naive, generate_daily_sales_report_chunked


logger = logging.getLogger(__name__)

# ============================================================
# ❌ BEFORE FIX – UNSAFE PURCHASE (Race Condition)
# ============================================================
@csrf_exempt
@require_POST
def buy_unsafe(request):
    """
    Two simultaneous requests can both pass the stock check before
    either updates the stock → negative stock / overselling.
    """
    user_id = request.POST.get('user_id')
    product_id = request.POST.get('product_id')
    quantity = int(request.POST.get('quantity', 1))

    # Read product and user WITHOUT any locking
    product = Product.objects.get(id=product_id)
    user = Account.objects.get(id=user_id)
    total = product.price * quantity

    # --- Critical section (no synchronization) ---
    if user.balance < total:
        return JsonResponse({'error': 'Insufficient balance'}, status=400)
    if product.stock < quantity:
        return JsonResponse({'error': 'Not enough stock'}, status=400)

    # ❌ Gap between check and update: another request can also deduct
    product.stock -= quantity
    product.save()

    user.balance -= total
    user.save()
    # --- End critical section ---

    order = Order.objects.create(
        user=user, product=product, quantity=quantity,
        total_price=total, status='confirmed'
    )
    logger.info(f"UNSAFE Order {order.id}: {user.username} bought {quantity}x {product.name}")
    return JsonResponse({'order_id': order.id, 'status': 'confirmed'})


# ============================================================
# ✅ AFTER FIX – SAFE PURCHASE (Row‑Level Locking)
# ============================================================
@csrf_exempt
@require_POST
def buy_safe(request):
    """
    Uses SELECT … FOR UPDATE and transaction.atomic() to lock the
    product row. Only one request can hold the lock at a time.
    """
    user_id = request.POST.get('user_id')
    product_id = request.POST.get('product_id')
    quantity = int(request.POST.get('quantity', 1))

    with transaction.atomic():
        # Lock the product row NOW – all others wait until we commit/rollback
        product = Product.objects.select_for_update().get(id=product_id)
        user = Account.objects.get(id=user_id)
        total = product.price * quantity

        if user.balance < total:
            return JsonResponse({'error': 'Insufficient balance'}, status=400)
        if product.stock < quantity:
            return JsonResponse({'error': 'Not enough stock'}, status=400)

        # Now it's safe to deduct – no other request can modify this row
        product.stock -= quantity
        product.save()

        user.balance -= total
        user.save()

        order = Order.objects.create(
            user=user, product=product, quantity=quantity,
            total_price=total, status='confirmed'
        )

        # ✅ ASYNC: task is queued, response returns immediately
        send_invoice.delay(order.id)

    logger.info(f"SAFE Order {order.id}: {user.username} bought {quantity}x {product.name}")
    return JsonResponse({'order_id': order.id, 'status': 'confirmed'})


# ============================================================
# Simple read‑only endpoints
# ============================================================
def order_history(request):
    user_id = request.GET.get('user_id')
    orders = Order.objects.filter(user_id=user_id).values()
    return JsonResponse(list(orders), safe=False)

@csrf_exempt
@require_POST
def buy_sync(request):
    """
    ❌ BEFORE CELERY: invoice sending happens inside the request,
    blocking the user until the email simulation finishes.
    """
    user_id = request.POST.get('user_id')
    product_id = request.POST.get('product_id')
    quantity = int(request.POST.get('quantity', 1))

    with transaction.atomic():
        product = Product.objects.select_for_update().get(id=product_id)
        user = Account.objects.get(id=user_id)
        total = product.price * quantity

        if user.balance < total:
            return JsonResponse({'error': 'Insufficient balance'}, status=400)
        if product.stock < quantity:
            return JsonResponse({'error': 'Not enough stock'}, status=400)

        product.stock -= quantity
        product.save()
        user.balance -= total
        user.save()

        order = Order.objects.create(
            user=user, product=product, quantity=quantity,
            total_price=total, status='confirmed'
        )

        # ❌ SYNCHRONOUS call – blocks for 2 seconds
        send_invoice(order.id)

    logger.info(f"SAFE (sync) Order {order.id}: {user.username} bought {quantity}x {product.name}")
    return JsonResponse({'order_id': order.id, 'status': 'confirmed'})


def report_naive(request):
    """
    ❌ BEFORE: Runs the naive report SYNCHRONOUSLY.
    Returns the time it took + result.
    Use JMeter to measure response time under large data.
    """
    start = time.time()
    result = generate_daily_sales_report_naive()   # call the actual function, not .delay()
    elapsed = time.time() - start
    return JsonResponse({'method': 'naive', 'time_seconds': round(elapsed, 3), **result})

def report_chunked(request):
    """
    ✅ AFTER: Runs the chunked report SYNCHRONOUSLY.
    """
    start = time.time()
    result = generate_daily_sales_report_chunked()
    elapsed = time.time() - start
    return JsonResponse({'method': 'chunked', 'time_seconds': round(elapsed, 3), **result})