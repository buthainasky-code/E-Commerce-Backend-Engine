from django.http import JsonResponse
from .models import Account

def balance(request):
    user_id = request.GET.get('user_id')
    user = Account.objects.values('id', 'username', 'balance').get(id=user_id)
    return JsonResponse(user)