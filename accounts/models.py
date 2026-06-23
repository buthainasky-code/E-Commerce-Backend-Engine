from django.db import models

class Account(models.Model):
    username = models.CharField(max_length=100, unique=True)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)

    def __str__(self):
        return f"{self.username} (${self.balance})"