from django.db import models


class ServiceCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'service_categories'
        ordering = ['name']

    def __str__(self):
        return self.name


class Service(models.Model):
    category = models.ForeignKey(
        ServiceCategory,
        on_delete=models.DO_NOTHING,
        related_name='services'
    )
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, null=True)
    base_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    duration_minutes = models.IntegerField()
    unit = models.CharField(max_length=30, default='session')
    min_quantity = models.IntegerField(default=1)
    max_quantity = models.IntegerField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'services'
        constraints = [
            models.UniqueConstraint(fields=['category', 'name'], name='services_category_name_unique'),
            models.CheckConstraint(condition=models.Q(base_price__gte=0), name='services_base_price_check'),
            models.CheckConstraint(condition=models.Q(duration_minutes__gt=0), name='services_duration_minutes_check'),
            models.CheckConstraint(condition=models.Q(min_quantity__gt=0), name='services_min_quantity_check'),
            models.CheckConstraint(
                condition=models.Q(max_quantity__isnull=True) | models.Q(max_quantity__gte=models.F('min_quantity')),
                name='services_max_quantity_check'
            ),
        ]
        ordering = ['category__name', 'name']

    def __str__(self):
        return self.name


class ServicePackage(models.Model):
    class Frequency(models.TextChoices):
        DAILY = 'DAILY', 'Hằng ngày'
        WEEKLY = 'WEEKLY', 'Hằng tuần'
        MONTHLY = 'MONTHLY', 'Hằng tháng'
        CUSTOM = 'CUSTOM', 'Tùy chỉnh'

    service = models.ForeignKey(Service, on_delete=models.DO_NOTHING, related_name='packages')
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, null=True)
    frequency = models.CharField(max_length=20, choices=Frequency.choices)
    number_of_sessions = models.IntegerField()
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    package_price = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'service_packages'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(number_of_sessions__gt=0),
                name='service_packages_number_of_sessions_check'
            ),
            models.CheckConstraint(
                condition=models.Q(discount_percent__gte=0) & models.Q(discount_percent__lte=100),
                name='service_packages_discount_percent_check'
            ),
            models.CheckConstraint(
                condition=models.Q(package_price__isnull=True) | models.Q(package_price__gte=0),
                name='service_packages_package_price_check'
            ),
        ]
        ordering = ['service__name', 'name']

    def __str__(self):
        return f"{self.service} - {self.name}"
