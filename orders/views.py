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
from django.core.cache import cache
import redis
from django.utils import timezone
from .models import CouponClaim
redis_stock_client = redis.Redis(host='localhost', port=6379, db=2, decode_responses=True)
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


@csrf_exempt
@require_POST
def buy_safe_invalidate_cache(request):
    """
    Same as buy_safe, but also deletes the product cache after purchase.
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

        # ✅ Invalidate the product cache
        cache.delete(f'product_detail:{product.id}')

        send_invoice.delay(order.id)

    logger.info(f"SAFE (invalidate cache) Order {order.id}: {user.username} bought {quantity}x {product.name}")
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


redis_lock_client = redis.Redis(host='localhost', port=6379, db=2, decode_responses=True)

@csrf_exempt
@require_POST
def claim_coupon(request):
    """
    Claim a coupon using a Redis distributed lock.
    No database row‑level lock is used.
    """
    user_id = request.POST.get('user_id')
    coupon_key = 'coupon:stock'
    lock_key = 'coupon:lock'

    # Acquire distributed lock (timeout = 5 seconds)
    lock = redis_lock_client.lock(lock_key, timeout=5)

    if not lock.acquire(blocking=True, blocking_timeout=3):
        return JsonResponse({'error': 'System busy, try again'}, status=503)

    try:
        # Critical section protected by Redis lock
        remaining = int(redis_lock_client.get(coupon_key) or 0)
        if remaining <= 0:
            return JsonResponse({'error': 'Coupons sold out'}, status=400)

        # Decrement the coupon count atomically
        new_remaining = redis_lock_client.decr(coupon_key)

        # Record the claim in database (no lock needed)
        CouponClaim.objects.create(user_id=user_id, claimed_at=timezone.now())

        return JsonResponse({
            'status': 'claimed',
            'remaining': new_remaining
        })
    finally:
        lock.release()
        
# @csrf_exempt
# @require_POST
# def buy_non_atomic(request):
#     """
#     ❌ BEFORE: No transaction, no row lock.
#     Failure after deduction leaves inconsistent data.
#     """
#     user_id = request.POST.get('user_id')
#     product_id = request.POST.get('product_id')
#     quantity = int(request.POST.get('quantity', 1))

#     try:
#         # Naive reads – no select_for_update()
#         user = Account.objects.get(id=user_id)
#         product = Product.objects.get(id=product_id)
#         total = product.price * quantity

#         if user.balance < total:
#             return JsonResponse({'error': 'Insufficient balance'}, status=400)
#         if product.stock < quantity:
#             return JsonResponse({'error': 'Not enough stock'}, status=400)

#         # Deduct without transaction protection
#         product.stock -= quantity
#         product.save()
#         user.balance -= total
#         user.save()

#         # Simulate a failure for quantity=999
#         if quantity == 999:
#             raise Exception("Simulated failure after deduction")

#         order = Order.objects.create(
#             user=user, product=product, quantity=quantity,
#             total_price=total, status='confirmed'
#         )
#         return JsonResponse({'order_id': order.id, 'status': 'confirmed'})

#     except Exception as e:
#         return JsonResponse({'error': f'Failure: {str(e)}'}, status=500)

@csrf_exempt
@require_POST
def buy_non_atomic(request):
    user_id = request.POST.get('user_id')
    product_id = request.POST.get('product_id')
    quantity = int(request.POST.get('quantity', 1))
    force_fail = request.POST.get('force_fail', 'false')

    try:
        user = Account.objects.get(id=user_id)
        product = Product.objects.get(id=product_id)
        total = product.price * quantity

        if user.balance < total:
            return JsonResponse({'error': 'Insufficient balance'}, status=400)
        if product.stock < quantity:
            return JsonResponse({'error': 'Not enough stock'}, status=400)

        product.stock -= quantity
        product.save()
        user.balance -= total
        user.save()

        if force_fail == 'true':
            raise Exception("Simulated failure after deduction")

        order = Order.objects.create(
            user=user, product=product, quantity=quantity,
            total_price=total, status='confirmed'
        )
        return JsonResponse({'order_id': order.id, 'status': 'confirmed'})

    except Exception as e:
        return JsonResponse({'error': f'Failure: {str(e)}'}, status=500)
@csrf_exempt
@require_POST
def buy_atomic(request):
    """
    ✅ AFTER: Wrapped in transaction.atomic().
    A failure rolls back everything – no partial updates.
    """
    user_id = request.POST.get('user_id')
    product_id = request.POST.get('product_id')
    quantity = int(request.POST.get('quantity', 1))

    try:
        with transaction.atomic():
            user = Account.objects.get(id=user_id)
            product = Product.objects.select_for_update().get(id=product_id)
            total = product.price * quantity

            if user.balance < total:
                return JsonResponse({'error': 'Insufficient balance'}, status=400)
            if product.stock < quantity:
                return JsonResponse({'error': 'Not enough stock'}, status=400)

            product.stock -= quantity
            product.save()
            user.balance -= total
            user.save()

            # Simulate failure for quantity=999
            if quantity == 999:
                raise Exception("Simulated failure after deduction")

            order = Order.objects.create(
                user=user, product=product, quantity=quantity,
                total_price=total, status='confirmed'
            )
            return JsonResponse({'order_id': order.id, 'status': 'confirmed'})

    except Exception as e:
        return JsonResponse({'error': f'Rolled back: {str(e)}'}, status=400)
    


@csrf_exempt
@require_POST
def buy_optimized(request):
    """
    ✅ AFTER: Redis stock pre‑check before acquiring DB lock.
    Requests that would fail due to insufficient stock are rejected early.
    """
    user_id = request.POST.get('user_id')
    product_id = request.POST.get('product_id')
    quantity = int(request.POST.get('quantity', 1))

    # Fast Redis pre‑check (no lock, just read)
    stock_key = f'product_stock:{product_id}'
    redis_stock = redis_stock_client.get(stock_key)

    if redis_stock is not None and int(redis_stock) < quantity:
        return JsonResponse({'error': 'Not enough stock'}, status=400)

    # Proceed with normal DB transaction
    with transaction.atomic():
        product = Product.objects.select_for_update().get(id=product_id)
        user = Account.objects.get(id=user_id)
        total = product.price * quantity

        if user.balance < total:
            return JsonResponse({'error': 'Insufficient balance'}, status=400)
        if product.stock < quantity:
            # Update Redis to reflect reality (stock already depleted)
            redis_stock_client.set(stock_key, product.stock)
            return JsonResponse({'error': 'Not enough stock'}, status=400)

        product.stock -= quantity
        product.save()
        user.balance -= total
        user.save()

        order = Order.objects.create(
            user=user, product=product, quantity=quantity,
            total_price=total, status='confirmed'
        )

        # Update Redis stock after successful purchase
        redis_stock_client.set(stock_key, product.stock)

        # Invalidate product cache
        cache.delete(f'product_detail:{product.id}')

        send_invoice.delay(order.id)

    logger.info(f"OPTIMIZED Order {order.id}: {user.username} bought {quantity}x {product.name}")
    return JsonResponse({'order_id': order.id, 'status': 'confirmed'})