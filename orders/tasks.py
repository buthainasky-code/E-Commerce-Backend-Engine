import time
import logging
from celery import shared_task
from django.utils import timezone
from .models import Order


logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_invoice(self, order_id):
    """
    Simulates sending an invoice email.
    This runs ASYNCHRONOUSLY in a Celery worker.
    """
    try:
        logger.info(f"[Task] Generating invoice for Order #{order_id}...")
        # Simulate a 2‑second I/O delay (email, PDF generation, etc.)
        time.sleep(2)
        logger.info(f"[Task] Invoice sent for Order #{order_id}")
        return f"Invoice for order #{order_id} sent"
    except Exception as exc:
        logger.error(f"[Task] Failed invoice #{order_id}: {exc}")
        raise self.retry(exc=exc)
    
@shared_task
def generate_daily_sales_report_naive():
    """
    ❌ BEFORE – loads ALL of today's orders into memory.
    If there are millions of orders, this can consume several GB of RAM.
    """
    today = timezone.now().date()
    orders = Order.objects.filter(created_at__date=today)   # ALL objects loaded
    order_count = orders.count()
    total_sales = sum(order.total_price for order in orders)  # iterates again
    logger.info(f"[Naive] Report: {order_count} orders, ${total_sales}")
    return {'orders': order_count, 'total_sales': float(total_sales)}


@shared_task
def generate_daily_sales_report_chunked(chunk_size=1000):
    """
    ✅ AFTER – uses iterator(chunk_size) to process rows in chunks.
    Only one chunk is held in memory at any time.
    """
    today = timezone.now().date()
    order_count = 0
    total_sales = 0

    # Fetch only the 'total_price' field, then iterate in chunks
    queryset = Order.objects.filter(created_at__date=today).only('total_price')
    for order in queryset.iterator(chunk_size=chunk_size):
        total_sales += order.total_price
        order_count += 1

    logger.info(f"[Chunked] Report: {order_count} orders, ${total_sales}")
    return {'orders': order_count, 'total_sales': float(total_sales)}